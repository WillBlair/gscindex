"""
Data Aggregator
================
Orchestrates all data providers and assembles the single ``dict`` that the
dashboard layout consumes.

This is the main entry point for data. It:
    1. Instantiates every provider
    2. Calls ``fetch_current()`` and ``fetch_history()`` on each, with a per-category timeout
    3. Handles provider failures explicitly: the last stored score while it is younger than
       ``CATEGORY_DROP_AFTER_DAYS`` (flagged fallback and stale), otherwise the category is
       excluded and the remaining weights are renormalized
    4. Computes and stores the composite (``result["composite"]``)
    5. Assembles alerts from the RSS news pipeline and the port map
    6. Returns everything in the shape the layout expects
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

import config
from config import (
    CATEGORY_LABELS,
    CATEGORY_WEIGHTS,
    DISRUPTION_SCORE_THRESHOLD,
    HISTORY_DAYS,
)
from data import database
from data.ports_data import MAJOR_PORTS

from data.providers.chokepoints import ChokepointsProvider
from data.providers.energy import EnergyProvider
from data.providers.freight import FreightProvider
from data.providers.geopolitical import GeopoliticalProvider
from data.providers.inputs import InputsProvider
from data.providers.physical import PhysicalProvider
from data.providers.supply_chain import SupplyChainProvider
from data.providers.tariffs import TariffsProvider
from data.providers.weather import WeatherProvider
from data.providers.aerospace import AeroMetalsProvider
from data.providers.silicon_analysts import ChipFabUtilProvider
from data.news_alerts import _is_irrelevant_article, fetch_supply_chain_news, scoring_label
from data.port_analyst import generate_port_summaries
from data.portwatch import fetch_chokepoint_traffic
from data.register import run_register_cycle
from scoring import get_health_tier
from scoring.engine import compute_composite_index, renormalized_weights
from data.runtime import RefreshTasks

logger = logging.getLogger(__name__)
_FETCH_TASKS = RefreshTasks(max_workers=3)

# The eight weighted categories plus the two industry adapters, instantiated once. The
# slow ones (freight, physical) go last so the fast providers finish inside their 45 s
# before those two take workers; their own timeouts are longer (PROVIDER_TIMEOUT_OVERRIDES).
_PROVIDERS = [
    SupplyChainProvider(),
    ChokepointsProvider(),
    EnergyProvider(),
    TariffsProvider(),
    GeopoliticalProvider(),
    InputsProvider(),
    ChipFabUtilProvider(),
    AeroMetalsProvider(),
    FreightProvider(),
    PhysicalProvider(),
]

# Port weather for the map only; weather is not a composite category.
_WEATHER = WeatherProvider()

def _fetch_market_data() -> dict:
    """Fetch key market indicators (Oil, Gas, Shipping Stocks)."""
    import yfinance as yf
    from data.cache import get_cached, set_cached
    
    # (label, symbol, group). Order is the display order in the Markets pane.
    tickers = [
        ("WTI crude", "CL=F", "Energy"),
        ("Brent crude", "BZ=F", "Energy"),
        ("Diesel (ULSD)", "HO=F", "Energy"),
        ("Natural gas", "NG=F", "Energy"),
        ("Dry bulk (BDRY)", "BDRY", "Shipping"),
        ("Shipping stocks (BOAT)", "BOAT", "Shipping"),
        ("Transports (IYT)", "IYT", "Shipping"),
        ("Copper", "HG=F", "Materials"),
        ("Aluminum", "ALI=F", "Materials"),
        ("Steel (SLX)", "SLX", "Materials"),
        ("Gold", "GC=F", "Materials"),
        ("US dollar index", "DX-Y.NYB", "Macro"),
        ("Volatility (VIX)", "^VIX", "Macro"),
    ]

    cache_key = "raw_market_data_v2"
    cached = get_cached(cache_key, ttl=3600)
    if cached: 
        return cached
    
    data = {}
    for name, sym, group in tickers:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if not hist.empty:
                # Use scalar float() conversion to avoid numpy types
                current = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
                
                data[name] = {
                    "price": current,
                    "prev": prev,
                    "symbol": sym,
                    "group": group,
                    "change_pct": ((current - prev) / prev) * 100 if prev else 0.0
                }
        except Exception as e:
            logger.warning(f"Market data fetch failed for {sym}: {e}")
            
    if data: 
        set_cached(cache_key, data)
        
    return data



def _as_naive_daily_index(index: pd.Index) -> pd.DatetimeIndex:
    """Normalize a history index to naive UTC calendar dates.

    Providers mix tz-aware stamps (yfinance, ``Timestamp.now(tz='UTC')``)
    with naive FRED dates. ``reindex`` against the aggregator's naive
    ``dates`` range raises if those dtypes are mixed.
    """
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize()


def _align_history_to_dates(
    hist_series: pd.Series | None,
    dates: pd.DatetimeIndex,
    score: float,
) -> pd.Series:
    """Forward-fill a provider series onto the dashboard date index.

    Dates before the first real observation stay NaN. Points dated after the last
    dashboard date (history dated by publication lag can run past today) never fill
    anything. Today's point is forced to the live score so sparklines do not show
    yesterday's close; with no history at all, today's point is the only value.
    """
    if hist_series is None or hist_series.empty:
        aligned = pd.Series(float("nan"), index=dates)
    else:
        hist = hist_series.copy()
        hist.index = _as_naive_daily_index(hist.index)
        hist = hist[~hist.index.duplicated(keep="last")].sort_index()
        hist = hist[hist.index <= dates[-1]]
        aligned = hist.reindex(dates, method="ffill")
    aligned.iloc[-1] = score
    return aligned


def _empty_history(dates: pd.DatetimeIndex, name: str) -> pd.Series:
    """History for a category that was not measured this cycle: every point NaN."""
    return pd.Series(float("nan"), index=dates, name=name)


# ---------------------------------------------------------------------------
# News penalty tables + helpers
# ---------------------------------------------------------------------------

_DIRECT_PENALTY: dict[str, float] = {"high": 30, "medium": 15, "low": 5}

# ---------------------------------------------------------------------------
# Regional risk profiles — per-port macro sensitivity
# ---------------------------------------------------------------------------
# Each region overrides the default equal-weight macro blend with weights that
# reflect real-world exposure.  This means a tariff spike hurts Chinese ports
# far more than it hurts Rotterdam, creating genuine per-port differentiation.
#
# Keys are category names; values are relative weights (normalised at runtime).
# "vulnerability" is a fixed 0–15 pt structural penalty for ports in
# chronically disrupted areas (piracy corridors, congestion, conflict zones).

_REGION_PROFILES: dict[str, dict] = {
    "us_gulf": {
        "weights": {"energy": 0.35, "trucking": 0.30, "supply_chain": 0.15, "tariffs": 0.10, "geopolitical": 0.10},
        "vulnerability": 0,
    },
    "us_east": {
        "weights": {"supply_chain": 0.25, "trucking": 0.25, "energy": 0.20, "tariffs": 0.15, "geopolitical": 0.15},
        "vulnerability": 0,
    },
    "us_west": {
        "weights": {"tariffs": 0.30, "supply_chain": 0.25, "trucking": 0.20, "energy": 0.15, "geopolitical": 0.10},
        "vulnerability": 2,  # chronic congestion
    },
    "canada": {
        "weights": {"supply_chain": 0.25, "energy": 0.25, "trucking": 0.20, "tariffs": 0.15, "geopolitical": 0.15},
        "vulnerability": 0,
    },
    "latin_america": {
        "weights": {"geopolitical": 0.25, "supply_chain": 0.25, "energy": 0.20, "tariffs": 0.15, "trucking": 0.15},
        "vulnerability": 3,
    },
    "panama": {
        "weights": {"supply_chain": 0.30, "geopolitical": 0.25, "energy": 0.20, "tariffs": 0.15, "trucking": 0.10},
        "vulnerability": 5,  # drought / capacity constraints
    },
    "north_europe": {
        "weights": {"energy": 0.35, "supply_chain": 0.25, "geopolitical": 0.20, "tariffs": 0.10, "trucking": 0.10},
        "vulnerability": 0,
    },
    "med_europe": {
        "weights": {"geopolitical": 0.30, "energy": 0.25, "supply_chain": 0.20, "tariffs": 0.15, "trucking": 0.10},
        "vulnerability": 2,
    },
    "uk": {
        "weights": {"energy": 0.25, "supply_chain": 0.25, "tariffs": 0.20, "geopolitical": 0.15, "trucking": 0.15},
        "vulnerability": 1,
    },
    "east_europe": {
        "weights": {"geopolitical": 0.40, "energy": 0.25, "supply_chain": 0.15, "tariffs": 0.10, "trucking": 0.10},
        "vulnerability": 5,  # conflict proximity
    },
    "china": {
        "weights": {"tariffs": 0.35, "geopolitical": 0.25, "supply_chain": 0.20, "energy": 0.10, "trucking": 0.10},
        "vulnerability": 4,  # tariff / decoupling risk
    },
    "taiwan": {
        "weights": {"geopolitical": 0.40, "tariffs": 0.25, "supply_chain": 0.20, "energy": 0.10, "trucking": 0.05},
        "vulnerability": 8,  # cross-strait tension
    },
    "japan_korea": {
        "weights": {"supply_chain": 0.25, "tariffs": 0.25, "energy": 0.20, "geopolitical": 0.20, "trucking": 0.10},
        "vulnerability": 1,
    },
    "southeast_asia": {
        "weights": {"supply_chain": 0.25, "geopolitical": 0.25, "tariffs": 0.20, "energy": 0.15, "trucking": 0.15},
        "vulnerability": 2,
    },
    "south_asia": {
        "weights": {"geopolitical": 0.25, "supply_chain": 0.25, "energy": 0.20, "tariffs": 0.15, "trucking": 0.15},
        "vulnerability": 3,
    },
    "persian_gulf": {
        "weights": {"geopolitical": 0.35, "energy": 0.30, "supply_chain": 0.15, "tariffs": 0.10, "trucking": 0.10},
        "vulnerability": 5,  # strait of Hormuz risk
    },
    "red_sea": {
        "weights": {"geopolitical": 0.45, "energy": 0.20, "supply_chain": 0.15, "tariffs": 0.10, "trucking": 0.10},
        "vulnerability": 10,  # Houthi attacks / active conflict zone
    },
    "east_africa": {
        "weights": {"geopolitical": 0.35, "supply_chain": 0.25, "energy": 0.15, "tariffs": 0.15, "trucking": 0.10},
        "vulnerability": 6,  # piracy corridor
    },
    "west_africa": {
        "weights": {"geopolitical": 0.30, "energy": 0.25, "supply_chain": 0.20, "tariffs": 0.15, "trucking": 0.10},
        "vulnerability": 5,
    },
    "south_africa": {
        "weights": {"supply_chain": 0.25, "energy": 0.25, "geopolitical": 0.20, "tariffs": 0.15, "trucking": 0.15},
        "vulnerability": 3,
    },
    "oceania": {
        "weights": {"supply_chain": 0.25, "tariffs": 0.20, "energy": 0.20, "geopolitical": 0.15, "trucking": 0.20},
        "vulnerability": 0,
    },
}

# Energy and Inland Freight (diesel) were merged into a single "energy" fuel-cost
# category. The per-region profiles above still list a legacy "trucking" weight;
# fold it into "energy" once at import so the macro blend keeps summing to 1.0
# and never references a category that no longer exists.
for _profile in _REGION_PROFILES.values():
    _weights = _profile["weights"]
    if "trucking" in _weights:
        _weights["energy"] = _weights.get("energy", 0.0) + _weights.pop("trucking")

# Port name → region key
_PORT_REGION: dict[str, str] = {
    "Houston":       "us_gulf",
    "New York":      "us_east",
    "Los Angeles":   "us_west",
    "Savannah":      "us_east",
    "Vancouver":     "canada",
    "Colon":         "panama",
    "Manzanillo":    "latin_america",
    "Santos":        "latin_america",
    "Buenos Aires":  "latin_america",
    "Rotterdam":     "north_europe",
    "Hamburg":       "north_europe",
    "Antwerp":       "north_europe",
    "Felixstowe":    "uk",
    "Piraeus":       "med_europe",
    "Algeciras":     "med_europe",
    "Gdansk":        "east_europe",
    "Shanghai":      "china",
    "Hong Kong":     "china",
    "Qingdao":       "china",
    "Busan":         "japan_korea",
    "Tokyo":         "japan_korea",
    "Kaohsiung":     "taiwan",
    "Singapore":     "southeast_asia",
    "Laem Chabang":  "southeast_asia",
    "Port Klang":    "southeast_asia",
    "Mumbai":        "south_asia",
    "Chennai":       "south_asia",
    "Colombo":       "south_asia",
    "Dubai":         "persian_gulf",
    "Jeddah":        "red_sea",
    "Durban":        "south_africa",
    "Mombasa":       "east_africa",
    "Djibouti":      "red_sea",
    "Lagos":         "west_africa",
    "Port Said":     "red_sea",
    "Sydney":        "oceania",
    "Melbourne":     "oceania",
}


def _severity_label(severity: float) -> str:
    """Human-readable label for an alert severity score.

    Alert ``sentiment`` values are Claude severity scores (-10..+10).
    Thresholds match ``_score_to_severity`` in ``data.news_alerts``.
    """
    if severity <= -4.0:
        return "Severe"
    if severity <= -1.5:
        return "Significant"
    return "Minor"


def _wrap_text(text: str, max_chars: int = 40) -> str:
    """Wrap text with <br> tags to prevent Plotly tooltips from overflowing mobile screens."""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 <= max_chars:
            current_line = f"{current_line} {word}".strip()
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return "<br>".join(lines)


def _match_news_to_ports(
    alerts: list[dict],
) -> dict[str, list[dict]]:
    """Match negative news alerts to ports via keyword scanning.

    Articles that are clearly irrelevant (sports, lifestyle, exam prep,
    crypto, entertainment) are filtered out before matching, preventing
    garbage from polluting port scores.

    Returns
    -------
    dict[str, list[dict]]
        port name → [alert, ...]
    """
    port_news: dict[str, list[dict]] = {}

    for alert in alerts:
        # For Port Risk Scoring, ONLY consider negative news.
        # Neutral/Positive news is fine for the feed, but shouldn't penalize port scores.
        # Unscored headlines (no Claude severity) never penalize a port.
        sentiment = alert.get("sentiment")
        if not isinstance(sentiment, (int, float)) or sentiment >= -0.05:
            continue

        text = f"{alert.get('title', '')} {alert.get('body', '')}".lower()

        if _is_irrelevant_article(text):
            logger.debug("Skipping irrelevant article: %s", alert.get("title", ""))
            continue

        for name, _lat, _lon, direct_kw in MAJOR_PORTS:
            if any(kw in text for kw in direct_kw):
                port_news.setdefault(name, []).append(alert)

    return port_news


def _derive_map_markers(
    current_scores: dict[str, float],
    alerts: list[dict],
    weather_provider: WeatherProvider,
    port_summaries: dict[str, str] | None = None,
) -> list[dict]:
    """Build a map marker for every major shipping port.

    Each port's score is computed from **real data only** with four components:

        1. **Local weather** (40%) — real-time conditions at the port's
           exact lat/lon, fetched in one batched Open-Meteo call.
        2. **Regional macro** (60%) — weighted average of non-weather
           categories, with weights tuned per-region (e.g. Chinese ports
           weight tariffs heavily, Red Sea ports weight geopolitical risk).
        3. **Structural vulnerability** (0–10 pts) — fixed penalty for
           ports in chronically disrupted zones (piracy, conflict, drought).
        4. **News penalty** (0–60 pts) — Claude-scored articles matched
           via two-tier keywords with garbage pre-filtered.
    """
    markers: list[dict] = []

    # ── Batch-fetch real weather for all 37 ports (1 HTTP call) ──
    port_coords = [(name, lat, lon) for name, lat, lon, _ in MAJOR_PORTS]
    batch_weather = weather_provider.fetch_batch_port_weather(port_coords)

    # ── Default macro weights (fallback for unmapped ports) ──────
    non_weather_cats = ["energy", "supply_chain", "tariffs", "geopolitical"]
    default_weights = {cat: 0.25 for cat in non_weather_cats}

    # ── Match news to ports ──────────────────────────────────────
    port_news = _match_news_to_ports(alerts)

    for name, lat, lon, _direct_kw in MAJOR_PORTS:
        # ── Local weather score (real, unique per port) ──────────
        wx = batch_weather.get(name, {})
        local_weather = wx.get("score")
        weather_summary = wx.get("summary", "Weather data unavailable")

        # ── Per-port macro score (region-specific weighting) ─────
        region = _PORT_REGION.get(name)
        profile = _REGION_PROFILES.get(region, {}) if region else {}
        macro_weights = profile.get("weights", default_weights)
        vulnerability = profile.get("vulnerability", 0)

        regional_macro = sum(
            current_scores.get(cat, 50) * w
            for cat, w in macro_weights.items()
        )

        # ── Composite: 40% local weather + 60% regional macro ───
        # Without a weather reading the port scores on regional macro alone.
        if local_weather is None:
            composite = regional_macro
        else:
            composite = local_weather * 0.40 + regional_macro * 0.60

        # ── Structural vulnerability penalty ─────────────────────
        composite -= vulnerability

        # ── News penalty ─────────────────────────────────────────
        matched = port_news.get(name, [])
        
        raw_penalties = []
        news_lines: list[str] = []

        for article in matched:
            severity = article.get("severity", "low")
            sentiment = article.get("sentiment", 0)
            title = article.get("title", "Unknown event")
            description = article.get("body", "")
            
            wrapped_title = _wrap_text(title, max_chars=40)
            
            # Show a brief snippet of the description so users see WHY it's red
            short_desc = description[:100] + "..." if len(description) > 100 else description
            wrapped_desc = _wrap_text(short_desc, max_chars=45) if short_desc else ""
            
            label = _severity_label(sentiment)

            penalty = _DIRECT_PENALTY.get(severity, 2)
            raw_penalties.append(penalty)

            sev_tag = severity.upper()
            
            if wrapped_desc:
                news_lines.append(
                    f"<b>[{sev_tag}]</b> {wrapped_title}<br>"
                    f"<i>{wrapped_desc}</i><br>"
                    f"   {label} severity ({sentiment:+.1f}) · Direct impact"
                )
            else:
                news_lines.append(
                    f"<b>[{sev_tag}]</b> {wrapped_title}<br>"
                    f"   {label} severity ({sentiment:+.1f}) · Direct impact"
                )

        # Diminishing returns penalty calculation to prevent excessive stacking
        if raw_penalties:
            raw_penalties.sort(reverse=True)
            max_penalty = raw_penalties[0]
            additional_penalty = sum(raw_penalties[1:]) * 0.20
            news_penalty = max_penalty + additional_penalty
        else:
            news_penalty = 0.0

        news_penalty = min(news_penalty, 50.0)

        # ── AI-generated port summary & dynamic penalty ────────────────
        ai_data = port_summaries.get(name, {}) if port_summaries else {}
        if isinstance(ai_data, str):
            ai_data = {"summary": ai_data, "disruption_penalty": 0.0}
        elif not isinstance(ai_data, dict):
            ai_data = {}
        ai_summary = ai_data.get("summary", "")
        ai_penalty = float(ai_data.get("disruption_penalty", 0.0))
        
        # Override the news penalty if the AI analyst gives a specific high penalty
        final_penalty = max(news_penalty, ai_penalty)

        # ── Final score ──────────────────────────────────────────
        score = round(max(0.0, min(100.0, composite - final_penalty)), 1)
        tier = get_health_tier(score)

        # ── Build hover tooltip (transparent about data sources) ─
        region_label = (region or "global").replace("_", " ").title()

        lines: list[str] = [
            f"Score: {score:.0f}/100 — <b>{tier['label']}</b>",
            "────────────",
            f"<b>Region:</b> {region_label} (macro: {regional_macro:.0f})",
        ]
        if vulnerability > 0:
            lines.append(f"<b>Structural risk:</b> -{vulnerability} pts (zone vulnerability)")
        # Why this port scores what it does, from measured data only: the two
        # regional categories that pull its score down the most (weight x
        # shortfall from 100), plus today's weather reading at the port.
        drags = sorted(
            ((w * (100 - current_scores.get(c, 50)), c) for c, w in macro_weights.items()),
            reverse=True,
        )[:2]
        drag_text = ", ".join(
            f"{CATEGORY_LABELS.get(c, c.title())} ({current_scores.get(c, 50):.0f})"
            for d, c in drags if d > 0
        )
        if drag_text:
            lines.append(f"<b>Main drags:</b> {drag_text}")
        if local_weather is not None:
            lines.append(f"<b>Weather:</b> {weather_summary} ({local_weather:.0f})")

        if ai_summary:
            wrapped_summary = _wrap_text(ai_summary, max_chars=45)
            lines.append(f"<b>AI Status:</b> <i>{wrapped_summary}</i>")
            if ai_penalty > 0:
                lines.append(f"<b>AI Penalty:</b> -{ai_penalty:.1f} pts")
        else:
            # Fallback to global context if no AI summary (baseline categories only;
            # chip and aero signals say nothing about a port)
            critical = [k for k in CATEGORY_WEIGHTS if k != "weather" and current_scores.get(k, 100) < 40]
            stressed = [k for k in CATEGORY_WEIGHTS if k != "weather" and 40 <= current_scores.get(k, 100) < 60]
            if critical:
                names = ", ".join(CATEGORY_LABELS[c] for c in critical)
                lines.append(f"<b>Global alert:</b> {names} at critical levels")
            elif stressed:
                names = ", ".join(CATEGORY_LABELS[s] for s in stressed[:3])
                lines.append(f"<b>Global:</b> {names} slightly elevated")
            else:
                lines.append("<b>Global:</b> All macro indicators healthy")

        if news_lines:
            lines.append("────────────")
            for nl in news_lines[:3]:
                lines.append(nl)

        markers.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "score": score,
            "description": "<br>".join(lines),
        })

    return markers


def _provider_timeout(category: str) -> float:
    """Seconds to wait for one provider, counted from the start of the cycle."""
    return float(config.PROVIDER_TIMEOUT_OVERRIDES.get(category, config.PROVIDER_TIMEOUT_SECONDS))


def _recent_stored_score(category: str, today: date) -> tuple[date, float] | None:
    """The category's last stored daily score while it is younger than its drop limit.

    Categories without a ``CATEGORY_DROP_AFTER_DAYS`` entry (the industry ones) never
    fall back to a stored score.
    """
    limit = config.CATEGORY_DROP_AFTER_DAYS.get(category)
    if limit is None:
        return None
    try:
        row = database.get_last_category_score(category)
    except Exception as exc:
        logger.warning("Stored score lookup failed for %s: %s", category, exc)
        return None
    if not row:
        return None
    day, score = row
    if not math.isfinite(score) or (today - day).days >= limit:
        return None
    return day, float(score)


def _stored_fallback_metadata(category: str, reason: str, day: date, score: float) -> dict:
    """Metadata for a category served from its last stored score (fallback and stale)."""
    limit = config.CATEGORY_DROP_AFTER_DAYS[category]
    return {
        "source": "Last stored reading (live source unavailable)",
        "raw_value": f"{score:.1f}",
        "raw_label": "Last stored daily score",
        "description": (
            f"Last stored reading from {day.isoformat()}. The live source failed this "
            f"cycle: {reason}"
        ),
        "calculation": (
            f"Not measured this cycle. The last stored daily score is used until it is "
            f"{limit} days old; after that the category is left out of the composite and "
            "the other weights are renormalized."
        ),
        "updated": day.isoformat(),
        "as_of": day.isoformat(),
        "is_stale": True,
        "is_fallback": True,
        "inputs": [],
        "error": reason,
    }


def _unavailable_metadata(category: str, reason: str) -> dict:
    """Metadata for a category with no live score and no usable stored score."""
    limit = config.CATEGORY_DROP_AFTER_DAYS.get(category)
    stored = f"no stored score younger than {limit} days" if limit else "no stored fallback"
    return {
        "source": "Unavailable (provider failed)",
        "raw_value": "—",
        "raw_label": "No data",
        "description": (
            f"The live source failed and there is {stored}, so this category is left out "
            f"of the composite. Error: {reason}"
        ),
        "calculation": "Not scored this cycle; the other weights are renormalized.",
        "updated": "Unavailable",
        "as_of": None,
        "is_stale": False,
        "is_fallback": False,
        "inputs": [],
        "error": reason,
    }


def _fetch_provider_data(provider) -> tuple[str, float | None, pd.Series | None, dict, str | None]:
    """Fetch one provider safely. A failed provider returns score None and its error."""
    cat = provider.category
    try:
        # Support both tuple (new) and float (legacy) returns
        result = provider.fetch_current()
        if isinstance(result, tuple):
            current_score, metadata = result
        else:
            current_score = float(result)
            metadata = {
                "source": "Unknown",
                "description": "Provider returned simplistic data format."
            }
        # NaN/Inf would propagate through the composite; it counts as a failure.
        if not math.isfinite(current_score):
            raise RuntimeError("provider returned a non-finite score")
        metadata.setdefault("is_fallback", False)
        metadata["is_stale"] = bool(metadata.get("is_stale", False))
        logger.info("Loaded %s: %.1f", cat, current_score)
    except Exception as exc:
        logger.error("Provider %s failed (current): %s", cat, exc)
        return cat, None, None, {}, str(exc)

    error_msg = None
    try:
        history_series = provider.fetch_history(HISTORY_DAYS)
    except Exception as exc:
        logger.error("Provider %s failed (history): %s", cat, exc)
        error_msg = str(exc)
        history_series = None

    return cat, float(current_score), history_series, metadata, error_msg


def _collect_provider_results(future_to_provider: dict, started: float) -> tuple[list, dict]:
    """Wait for each provider until its own deadline (cycle start + its timeout).

    Returns (results, timed_out) where ``timed_out`` maps category -> reason. A timed-out
    job keeps running in the pool and is reused by the next cycle.
    """
    import concurrent.futures

    pending = dict(future_to_provider)
    results: list = []
    timed_out: dict[str, str] = {}
    while pending:
        now = time.monotonic()
        deadlines = {f: started + _provider_timeout(p.category) for f, p in pending.items()}
        for future in [f for f, d in deadlines.items() if d <= now and not f.done()]:
            provider = pending.pop(future)
            logger.warning("Provider %s timed out", provider.category)
            timed_out[provider.category] = "Provider timed out"
        if not pending:
            break
        wait_for = max(0.0, min(deadlines[f] for f in pending) - now)
        done, _ = concurrent.futures.wait(
            list(pending), timeout=wait_for, return_when=concurrent.futures.FIRST_COMPLETED
        )
        for future in done:
            provider = pending.pop(future)
            try:
                results.append(future.result())
            except Exception as exc:  # the wrapper itself crashed
                logger.error("Provider task %s failed unexpectedly: %s", provider.category, exc)
                results.append((provider.category, None, None, {}, str(exc)))
    return results, timed_out


def aggregate_data(status_callback=None) -> dict:
    """Fetch data from all providers and assemble the dashboard data dict.

    Fetches run in parallel. Each provider has its own timeout
    (``config.PROVIDER_TIMEOUT_SECONDS`` / ``PROVIDER_TIMEOUT_OVERRIDES``); a provider
    that fails or times out uses its last stored score while that is younger than
    ``CATEGORY_DROP_AFTER_DAYS``, otherwise it is excluded from the composite.

    Returns
    -------
    dict with keys:
        ``"dates"``               – pd.DatetimeIndex
        ``"category_history"``    – dict[str, pd.Series]
        ``"current_scores"``      – dict[str, float] (excluded categories are absent)
        ``"composite"``           – float | None, renormalized over present weighted categories
        ``"excluded_categories"`` – weighted categories left out of the composite
        ``"stale_categories"``    – categories whose metadata says ``is_stale``
        ``"fallback_categories"`` – categories serving a stored or fallback value
        ``"map_markers"``         – list[dict]
        ``"alerts"``              – list[dict] (severity None when unscored)
        ``"news_scoring"``        – "Claude", "Claude (stale)", "Unscored" or "" (news failed)
        ``"disruptions"``         – list[dict]
        ``"briefing"``            – str
        ``"provider_errors"``     – dict[str, str]
        ``"market_data"``         – dict
    """
    start_time = datetime.now()
    logger.info("Starting parallel data fetch...")
    if status_callback: status_callback("Starting parallel data fetch...")

    current_scores: dict[str, float] = {}
    category_history: dict[str, pd.Series] = {}
    category_metadata: dict[str, dict] = {}
    provider_errors: dict[str, str] = {}
    failed: dict[str, str] = {}  # category -> reason, for providers with no live score

    # Prepare the target date range for history alignment
    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=HISTORY_DAYS,
        freq="D",
    )

    executor = _FETCH_TASKS
    try:
        # -- Submit Provider Tasks --
        providers_started = time.monotonic()
        future_to_provider = {
            executor.submit_once(p.category, _fetch_provider_data, p): p
            for p in _PROVIDERS
        }

        # -- Submit News/Market/Port Tasks --
        future_news = executor.submit_once("news", fetch_supply_chain_news)
        future_market = executor.submit_once("market", _fetch_market_data)
        future_port_summaries = executor.submit_once("port_summaries", generate_port_summaries)
        future_chokepoints = executor.submit_once("chokepoint_traffic", fetch_chokepoint_traffic)
        future_register = executor.submit_once("register", run_register_cycle)

        # -------------------------------------------------------------------
        # 2. Collect Results (each provider until its own deadline)
        # -------------------------------------------------------------------
        # A. Process Providers
        if status_callback:
            status_callback("Waiting for data providers...")
        results, timed_out = _collect_provider_results(future_to_provider, providers_started)
        failed.update(timed_out)
        provider_errors.update(timed_out)

        for cat, score, hist_series, meta, err in results:
            if err:
                provider_errors[cat] = err
            if score is None:
                failed[cat] = err or "Provider failed"
                continue

            current_scores[cat] = score
            meta["score"] = round(score, 1)
            meta["tier"] = get_health_tier(score)
            category_metadata[cat] = meta

            # Industry adapters (SiliconAnalysts / Aerospace) return 4 categories under
            # one primary key. Pop so the packed Series/tuples never leak into card
            # modals or cache.
            additional_scores = meta.pop("additional_scores", None)
            additional_history = meta.pop("additional_history", None)
            if additional_scores:
                for add_cat, (add_score, add_meta) in additional_scores.items():
                    if not math.isfinite(add_score):
                        continue
                    current_scores[add_cat] = float(add_score)
                    add_meta = dict(add_meta or {})
                    add_meta["score"] = round(add_score, 1)
                    add_meta["tier"] = get_health_tier(add_score)
                    add_meta["is_stale"] = bool(add_meta.get("is_stale", False))
                    category_metadata[add_cat] = add_meta
                    add_hist = additional_history.get(add_cat) if additional_history else None
                    category_history[add_cat] = _align_history_to_dates(add_hist, dates, add_score)
                    logger.info("Loaded %s (via %s): %.1f", add_cat, cat, add_score)

            # Reindex fills gaps by ffill. Dates BEFORE the first real observation stay
            # NaN; with no history only today's live point is set.
            category_history[cat] = _align_history_to_dates(hist_series, dates, score)

        # B. Process News (AI analysis takes 20-40s — old 5s timeout killed it every time).
        # News is display-only; it never reaches a category.
        alerts = []
        briefing = ""
        full_report = ""
        news_scoring = ""
        try:
            if status_callback:
                status_callback("Analyzing news feeds (AI)...")
            alerts, briefing, full_report = future_news.result(timeout=240)
            news_scoring = scoring_label()
        except Exception as e:
            logger.warning("News fetch timed out or failed: %s", e)

        # C. Process Market Data (yfinance is slow on cold start)
        market_data = {}
        try:
            market_data = future_market.result(timeout=30) or {}
        except Exception as e:
            logger.warning("Market data fetch timed out or failed: %s", e)

        # C2. Chokepoint traffic (IMF PortWatch, measured ship transits)
        chokepoints = None
        try:
            chokepoints = future_chokepoints.result(timeout=30)
        except Exception as e:
            logger.warning("Chokepoint traffic fetch timed out or failed: %s", e)

        # D. Process Port Summaries (Claude generation)
        port_summaries = {}
        try:
            if status_callback:
                status_callback("Generating port summaries...")
            port_summaries = future_port_summaries.result(timeout=240) or {}
        except Exception as e:
            logger.warning("Port summaries fetch timed out or failed: %s", e)
    finally:
        # Do not block forever on a hung upstream call.
        # Running jobs remain tracked and are reused on the next refresh.
        # Never create replacement pools for calls that are still running.
        # The shadow register stays queued: it is collected after the composite.
        executor.cancel_pending(keep=("register",))


    # -----------------------------------------------------------------------
    # 3. Failed providers: last stored score while recent, otherwise excluded
    # -----------------------------------------------------------------------
    today = datetime.now(timezone.utc).date()
    excluded_categories: list[str] = []
    for cat in sorted(failed):
        reason = failed[cat]
        category_history[cat] = _empty_history(dates, cat)  # never filled for a failure
        stored = _recent_stored_score(cat, today)
        if stored is not None:
            day, score = stored
            current_scores[cat] = score
            meta = _stored_fallback_metadata(cat, reason, day, score)
            meta["score"] = round(score, 1)
            meta["tier"] = get_health_tier(score)
            category_metadata[cat] = meta
            logger.warning("%s: using last stored score %.1f from %s", cat, score, day)
        else:
            category_metadata[cat] = _unavailable_metadata(cat, reason)
            if cat in CATEGORY_WEIGHTS:
                excluded_categories.append(cat)
            logger.warning("%s: no live or recent stored score; left out", cat)

    # A weighted category with no result at all (should not happen) is excluded too.
    for cat in CATEGORY_WEIGHTS:
        if cat not in current_scores and cat not in excluded_categories:
            excluded_categories.append(cat)
            category_history.setdefault(cat, _empty_history(dates, cat))
            category_metadata.setdefault(cat, _unavailable_metadata(cat, "No provider result"))
    excluded_categories.sort()

    # Composite over the weighted categories present, weights renormalized explicitly.
    present = {cat for cat in CATEGORY_WEIGHTS if cat in current_scores}
    composite: float | None = None
    try:
        weights = renormalized_weights(CATEGORY_WEIGHTS, present)
        composite = compute_composite_index({c: current_scores[c] for c in present}, weights)
    except ValueError as exc:
        logger.error("Composite unavailable: %s", exc)

    # Degradation flags, exposed via the snapshot, API, and /health.
    fallback_categories = sorted(
        cat for cat, meta in category_metadata.items() if meta.get("is_fallback")
    )
    stale_categories = sorted(
        cat for cat, meta in category_metadata.items()
        if meta.get("is_stale") and cat in current_scores
    )

    # Map markers (port weather is fetched here, for the map only)
    try:
        map_markers = _derive_map_markers(current_scores, alerts, _WEATHER, port_summaries)
    except Exception as e:
        logger.error("Map marker generation failed: %s", e)
        map_markers = []

    # Disruptions aggregation, on one 0-100 impact scale.
    disruptions: list[dict] = []

    # Source 1: Low-scoring categories, impact = 100 - score (measured values only — a
    # category serving a stored fallback is an outage, not a supply chain event)
    for cat, score in current_scores.items():
        if cat in fallback_categories:
            continue
        if score < DISRUPTION_SCORE_THRESHOLD:
            severity = "Critical" if score < 40 else "Stressed"
            disruptions.append({
                "event": f"{CATEGORY_LABELS.get(cat, cat.title())} — {severity}",
                "region": "Global",
                "impact_score": round(100 - score, 1),
                "categories": [cat],
                "started": "Ongoing",
                "status": "Active" if score < 50 else "Monitoring",
            })

    # Source 2: High-severity news alerts, impact = |severity| x 10
    for alert in alerts:
        if alert.get("severity") == "high":
            cat = alert.get("category", "geopolitical")
            title = alert.get("title", "Unknown event")
            short_title = title[:60] + "..." if len(title) > 60 else title
            disruptions.append({
                "event": short_title,
                "region": "Global",
                "impact_score": round(abs(alert.get("sentiment", -0.5)) * 10, 1),
                "categories": [cat],
                "started": "Recent",
                "status": "Active",
            })

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Data aggregation complete in %.2fs", elapsed)

    try:
        daily_history = database.get_daily_category_scores(91)
    except Exception as e:
        logger.warning("Failed to load daily history: %s", e)
        daily_history = {"dates": [], "scores": {}}

    result = {
        "last_updated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dates": dates,
        "category_history": category_history,
        "current_scores": current_scores,
        "composite": composite,
        "map_markers": map_markers,
        "alerts": alerts,
        "news_scoring": news_scoring,
        "briefing": briefing,
        "full_report": full_report,
        "disruptions": disruptions,
        "provider_errors": provider_errors,
        "category_metadata": category_metadata,
        "market_data": market_data,
        "chokepoints": chokepoints,
        "degraded": bool(fallback_categories or excluded_categories),
        "fallback_categories": fallback_categories,
        "excluded_categories": excluded_categories,
        "stale_categories": stale_categories,
        "daily_history": daily_history,
    }

    # E. Claude disruption register (shadow: stored as geo_register, not weighted).
    # Collected only if it has already finished, so a slow register never delays the
    # composite; an unfinished run stays queued and is picked up by a later cycle.
    register_score = None
    if future_register.done() and not future_register.cancelled():
        try:
            register_score = future_register.result(timeout=0)
        except Exception as e:
            logger.warning("Disruption register failed: %s", e)
    else:
        logger.info("Disruption register still running; not recorded this cycle.")

    # Persist the full dashboard state to disk for instant startup
    from data.cache import set_cached_dashboard
    from data.status import set_status
    import json as _json
    try:
        # Only persist measured values — stored fallback scores must not be written
        # back as if measured today. The composite is stored only when no weighted
        # category is excluded (history keeps a gap on degraded days).
        measured_scores = {
            cat: score for cat, score in current_scores.items()
            if cat not in fallback_categories
        }
        if isinstance(register_score, float) and math.isfinite(register_score):
            measured_scores["geo_register"] = register_score
        database.record_daily_scores(
            composite if not excluded_categories else None, measured_scores
        )
        set_cached_dashboard(result)
        logger.info("Dashboard state persisted to disk (JSON/Safe).")

        # Persist the latest good snapshot to the database so a fresh deploy
        # (empty disk) starts from data at most an hour old. Skipped when a
        # weighted category is excluded or serving a fallback, so outages aren't saved.
        if not excluded_categories and not any(cat in CATEGORY_WEIGHTS for cat in fallback_categories):
            from data.cache import dashboard_to_safe_dict

            database.save_dashboard_snapshot(_json.dumps(dashboard_to_safe_dict(result), default=str))

        if status_callback: status_callback("Data ready! Launching...")
        set_status("Data ready!")
    except Exception as e:
        logger.warning("Failed to persist dashboard state: %s", e)

    return result
