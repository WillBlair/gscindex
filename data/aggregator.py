"""
Data Aggregator
================
Orchestrates all data providers and assembles the single ``dict`` that the
dashboard layout consumes.

This is the main entry point for data. It:
    1. Instantiates every provider
    2. Calls ``fetch_current()`` and ``fetch_history()`` on each
    3. Handles provider failures gracefully (logs error, continues)
    4. Assembles alerts from the NewsAPI provider
    5. Computes regional risk scores (derived from category scores)
    6. Returns everything in the shape the layout expects
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import CATEGORY_LABELS, CATEGORY_WEIGHTS, HISTORY_DAYS
from data.ports_data import MAJOR_PORTS

from data.providers.energy import EnergyProvider
from data.providers.freight import FreightProvider
from data.providers.geopolitical import GeopoliticalProvider, fetch_supply_chain_news, _is_irrelevant_article
from data.providers.supply_chain import SupplyChainProvider
from data.providers.tariffs import TariffsProvider
from data.providers.weather import WeatherProvider
from data.port_analyst import generate_port_summaries
from scoring import get_health_tier

logger = logging.getLogger(__name__)

# All providers, instantiated once
_PROVIDERS = [
    WeatherProvider(),
    SupplyChainProvider(),
    FreightProvider(),
    EnergyProvider(),
    TariffsProvider(),
    GeopoliticalProvider(),
]

def _fetch_market_data() -> dict:
    """Fetch key market indicators (Oil, Gas, Shipping Stocks)."""
    import yfinance as yf
    from data.cache import get_cached, set_cached
    
    tickers = {
        "Crude Oil": "CL=F", 
        "Natural Gas": "NG=F", 
        "Copper": "HG=F",
        "Gold": "GC=F",
        "Volatility (VIX)": "^VIX",
    }
    
    cache_key = "raw_market_data"
    cached = get_cached(cache_key, ttl=3600)
    if cached: 
        return cached
    
    data = {}
    for name, sym in tickers.items():
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
                    "change_pct": ((current - prev) / prev) * 100 if prev else 0.0
                }
        except Exception as e:
            logger.warning(f"Market data fetch failed for {sym}: {e}")
            
    if data: 
        set_cached(cache_key, data)
        
    return data



def _make_fallback_series(days: int, name: str, value: float = 50.0) -> pd.Series:
    """Series with only TODAY's point set; the rest is NaN.

    A flat line at the fallback value would fabricate 90 days of history
    that was never measured. Charts render the single point and leave the
    rest of the window honestly empty.
    """
    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=days,
        freq="D",
    )
    series = pd.Series(float("nan"), index=dates, name=name)
    series.iloc[-1] = value
    return series


def get_safe_fallback_data() -> dict:
    """Return a completely safe, neutral dataset to ensure dashboard starts."""
    current_scores = {cat: 50.0 for cat in CATEGORY_WEIGHTS}
    
    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=HISTORY_DAYS,
        freq="D",
    )
    
    category_history = {
        cat: _make_fallback_series(HISTORY_DAYS, cat, 50.0)
        for cat in CATEGORY_WEIGHTS
    }
    
    return {
        "dates": dates,
        "category_history": category_history,
        "current_scores": current_scores,
        "map_markers": [],
        "alerts": [],
        "briefing": "System recovering... Data will update shortly.",
        "full_report": "",
        "disruptions": [],
        "provider_errors": {"System": "Using fallback data while background fetch initializes."},
        "category_metadata": {},
        "market_data": {},
        "degraded": True,
        "fallback_categories": sorted(CATEGORY_WEIGHTS),
    }



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

    Alert ``sentiment`` values are on the severity scale (roughly -6..0,
    VADER compound x 6 or Gemini severity_score) — NOT raw VADER compound.
    Thresholds match ``_score_to_severity`` in the geopolitical provider.
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
        if alert.get("sentiment", 0) >= -0.05:
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
        4. **News penalty** (0–60 pts) — VADER-scored articles matched
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
        local_weather = wx.get("score", 75.0)
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
        # Find the worst-performing category relevant to this port's region.
        # Only consider categories with meaningful weight (>10%) for this region.
        relevant_cats = [c for c, w in macro_weights.items() if w >= 0.10]
        top_risk_cat = min(relevant_cats, key=lambda c: current_scores.get(c, 50))
        top_risk_label = CATEGORY_LABELS.get(top_risk_cat, top_risk_cat.title())
        top_risk_score = current_scores.get(top_risk_cat, 50)

        region_label = (region or "global").replace("_", " ").title()

        lines: list[str] = [
            f"Score: {score:.0f}/100 — <b>{tier['label']}</b>",
            "────────────",
            f"<b>Region:</b> {region_label} (macro: {regional_macro:.0f})",
        ]
        if vulnerability > 0:
            lines.append(f"<b>Structural risk:</b> -{vulnerability} pts (zone vulnerability)")
        if top_risk_score < 60:
            lines.append(f"<b>Top risk:</b> {top_risk_label} ({top_risk_score:.0f})")

        if ai_summary:
            wrapped_summary = _wrap_text(ai_summary, max_chars=45)
            lines.append(f"<b>AI Status:</b> <i>{wrapped_summary}</i>")
            if ai_penalty > 0:
                lines.append(f"<b>AI Penalty:</b> -{ai_penalty:.1f} pts")
        else:
            # Fallback to old global context if no AI summary
            critical = [k for k, v in current_scores.items() if k != "weather" and v < 40]
            stressed = [k for k, v in current_scores.items() if k != "weather" and 40 <= v < 60]
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


def _fallback_metadata(reason: str) -> dict:
    """Full required-key metadata for a failed provider, flagged as fallback.

    Keeps the detail modal renderable and lets the UI/API distinguish a
    measured score from an injected neutral default.
    """
    return {
        "source": "Unavailable (provider failed)",
        "raw_value": "—",
        "raw_label": "No data",
        "description": f"Data fetch failed; showing a neutral fallback score. Error: {reason}",
        "calculation": "Neutral fallback of 50.0 — not a measured value.",
        "updated": "Unavailable",
        "error": reason,
        "is_fallback": True,
    }


def _fetch_provider_data(provider) -> tuple[str, float, pd.Series | None, dict, str | None]:
    """Helper to fetch data for a single provider safely."""
    cat = provider.category
    current_score = 50.0
    history_series = None
    metadata = {}
    error_msg = None

    try:
        # 1. Fetch current score + metadata
        # Support both tuple (new) and float (legacy/fallback) returns
        result = provider.fetch_current()
        if isinstance(result, tuple):
            current_score, metadata = result
        else:
            current_score = float(result)
            metadata = {
                "source": "Unknown", 
                "description": "Provider returned simplistic data format."
            }
            
        # Guard against NaN/Inf from providers (e.g. division by zero in normalization).
        # NaN would propagate through the composite calculation and break the gauge.
        if not math.isfinite(current_score):
            logger.warning("Provider %s returned non-finite score; using neutral fallback", cat)
            current_score = 50.0
            metadata["is_fallback"] = True

        metadata.setdefault("is_fallback", False)
        logger.info("Loaded %s: %.1f", cat, current_score)
    except Exception as exc:
        logger.error("Provider %s failed (current): %s", cat, exc)
        error_msg = str(exc)
        current_score = 50.0
        metadata = _fallback_metadata(str(exc))

    try:
        # 2. Fetch history
        history_series = provider.fetch_history(HISTORY_DAYS)
    except Exception as exc:
        logger.error("Provider %s failed (history): %s", cat, exc)
        if not error_msg: 
            error_msg = str(exc)
        history_series = None

    return cat, current_score, history_series, metadata, error_msg

def aggregate_data(status_callback=None) -> dict:
    """Fetch data from all providers and assemble the dashboard data dict.

    Fetches are performed in PARALLEL to ensure fast startup.
    A timeout ensures no single provider hangs the entire app.

    Returns
    -------
    dict with keys:
        ``"dates"``            – pd.DatetimeIndex
        ``"category_history"`` – dict[str, pd.Series]
        ``"current_scores"``   – dict[str, float]
        ``"map_markers"``      – list[dict]
        ``"alerts"``           – list[dict]
        ``"disruptions"``      – list[dict]
        ``"briefing"``         – str
        ``"provider_errors"``  – dict[str, str]
        ``"market_data"``      – dict
    """
    import concurrent.futures
    
    start_time = datetime.now()
    logger.info("Starting parallel data fetch...")
    if status_callback: status_callback("Starting parallel data fetch...")

    current_scores: dict[str, float] = {}
    category_history: dict[str, pd.Series] = {}
    category_metadata: dict[str, dict] = {}
    provider_errors: dict[str, str] = {}
    
    # Prepare the target date range for history alignment
    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=HISTORY_DAYS,
        freq="D",
    )

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    try:
        # -- Submit Provider Tasks --
        future_to_provider = {
            executor.submit(_fetch_provider_data, p): p
            for p in _PROVIDERS
        }

        # -- Submit News/Market/Port Tasks --
        future_news = executor.submit(fetch_supply_chain_news)
        future_market = executor.submit(_fetch_market_data)
        future_port_summaries = executor.submit(generate_port_summaries)

        # -------------------------------------------------------------------
        # 2. Collect Results (with Timeout)
        # -------------------------------------------------------------------
        # A. Process Providers
        try:
            if status_callback:
                status_callback("Waiting for data providers...")
            for future in concurrent.futures.as_completed(future_to_provider, timeout=45):
                try:
                    # Unpack 5 values now
                    cat, score, hist_series, meta, err = future.result()
                    current_scores[cat] = score

                    # Enrich metadata with calculated score and tier
                    if meta:
                        meta["score"] = round(score, 1)
                        meta["tier"] = get_health_tier(score)
                    else:
                        meta = {"score": round(score, 1), "tier": get_health_tier(score)}

                    category_metadata[cat] = meta

                    if err:
                        provider_errors[cat] = err

                    # Align history series
                    if hist_series is not None and not hist_series.empty:
                        # Reindex fills gaps by ffill. Dates BEFORE the first real
                        # observation stay NaN — backfilling them with today's
                        # score would paint history that was never measured.
                        aligned = hist_series.reindex(dates, method="ffill")

                        # CRITICAL FIX: Overwrite the last data point (today) with the LIVE score.
                        # This ensures the sparkline/delta calculation uses the real current value,
                        # not yesterday's close (which ffill would do).
                        aligned.iloc[-1] = score

                        category_history[cat] = aligned
                    else:
                        # Fallback if history fetch failed: today's point only
                        category_history[cat] = _make_fallback_series(HISTORY_DAYS, cat, score)

                except Exception as e:
                    # This catches timeouts or crashes in the wrapper
                    logger.error("A provider task failed unexpectedly: %s", e)
        except concurrent.futures.TimeoutError:
            logger.warning("Data fetch timed out. Some providers may be missing.")

        # B. Process News (AI analysis takes 20-40s — old 5s timeout killed it every time)
        alerts = []
        briefing = ""
        full_report = ""
        news_score: float | None = None
        try:
            if status_callback:
                status_callback("Analyzing news feeds (AI)...")
            news_score, alerts, briefing, full_report = future_news.result(timeout=120)
        except Exception as e:
            logger.warning("News fetch timed out or failed: %s", e)

        # C. Process Market Data (yfinance is slow on cold start)
        market_data = {}
        try:
            market_data = future_market.result(timeout=30) or {}
        except Exception as e:
            logger.warning("Market data fetch timed out or failed: %s", e)

        # D. Process Port Summaries (Gemini AI generation)
        port_summaries = {}
        try:
            if status_callback:
                status_callback("Generating port summaries...")
            port_summaries = future_port_summaries.result(timeout=60) or {}
        except Exception as e:
            logger.warning("Port summaries fetch timed out or failed: %s", e)
    finally:
        # Do not block forever on a hung upstream call.
        # Stuck futures are abandoned so the main update loop can keep running.
        executor.shutdown(wait=False, cancel_futures=True)


    # -----------------------------------------------------------------------
    # 3. Post-Processing (Scoring & Markers)
    # -----------------------------------------------------------------------
    # Ensure complete datasets (fill missing providers with neutral, flagged)
    for p in _PROVIDERS:
        if p.category not in current_scores:
            current_scores[p.category] = 50.0
            category_history[p.category] = _make_fallback_series(HISTORY_DAYS, p.category, 50.0)
            provider_errors[p.category] = "Provider timed out"
            meta = _fallback_metadata("Provider timed out")
            meta["score"] = 50.0
            meta["tier"] = get_health_tier(50.0)
            category_metadata[p.category] = meta

    # Compute composite
    from scoring.engine import compute_composite_index

    # Use fresh news result as the source of truth for geopolitical current score.
    # This avoids stale provider snapshots and keeps alerts/score aligned.
    if news_score is not None:
        current_scores["geopolitical"] = float(news_score)
        geo_meta = category_metadata.get("geopolitical", {})
        high_sev = sum(1 for a in alerts if a.get("severity") == "high")
        med_sev = sum(1 for a in alerts if a.get("severity") == "medium")
        geo_meta.update(
            {
                "source": "RSS + Gemini AI",
                "raw_value": f"{len(alerts)} articles",
                "raw_label": "Analyzed News Volume",
                "description": (
                    f"Analyzed recent supply chain news. Found {high_sev} high-severity "
                    f"and {med_sev} medium-severity risk events affecting the score."
                ),
                "updated": "Live",
                "score": round(float(news_score), 1),
                "tier": get_health_tier(float(news_score)),
                "is_fallback": False,
            }
        )
        category_metadata["geopolitical"] = geo_meta
        geo_hist = category_history.get("geopolitical")
        if geo_hist is not None and not geo_hist.empty:
            geo_hist.iloc[-1] = float(news_score)

    composite = compute_composite_index(current_scores)

    # Degradation flags: which categories are serving a fallback value
    # instead of a measurement. Exposed via the snapshot, API, and /health.
    fallback_categories = sorted(
        cat for cat, meta in category_metadata.items() if meta.get("is_fallback")
    )

    # Map markers — requires WeatherProvider specifically
    # We need to find the WeatherProvider instance from our list
    weather_provider = next((p for p in _PROVIDERS if isinstance(p, WeatherProvider)), None)
    
    if weather_provider:
        try:
            map_markers = _derive_map_markers(current_scores, alerts, weather_provider, port_summaries)
        except Exception as e:
            logger.error("Map marker generation failed: %s", e)
            map_markers = []
    else:
        map_markers = []

    # Disruptions aggregation
    disruptions: list[dict] = []

    # Source 1: Low-scoring categories
    for cat, score in current_scores.items():
        if score < 70:
            severity = "Critical" if score < 40 else "Stressed"
            impact = round((100 - score) / 10, 1)
            disruptions.append({
                "event": f"{CATEGORY_LABELS.get(cat, cat.title())} — {severity}",
                "region": "Global",
                "impact_score": impact,
                "categories": [cat],
                "started": "Ongoing",
                "status": "Active" if score < 50 else "Monitoring",
            })

    # Source 2: High-severity news alerts
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

    result = {
        "last_updated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dates": dates,
        "category_history": category_history,
        "current_scores": current_scores,
        "map_markers": map_markers,
        "alerts": alerts,
        "briefing": briefing,
        "full_report": full_report,
        "disruptions": disruptions,
        "provider_errors": provider_errors,
        "category_metadata": category_metadata,
        "market_data": market_data,
        "degraded": bool(fallback_categories),
        "fallback_categories": fallback_categories,
    }

    # Persist the full dashboard state to disk for instant startup
    from data.cache import set_cached_dashboard, _write_text_atomic
    from data.status import set_status
    from data.database import record_daily_scores
    import json as _json
    from pathlib import Path as _Path
    try:
        # Only persist measured values — fallback scores must not pollute
        # the real daily history that trend charts are built from.
        measured_scores = {
            cat: score for cat, score in current_scores.items()
            if cat not in fallback_categories
        }
        record_daily_scores(composite, measured_scores)
        set_cached_dashboard(result)
        logger.info("Dashboard state persisted to disk (JSON/Safe).")

        # Auto-refresh the committed fallback snapshot if it's older than 7 days.
        # This keeps cold-start users from seeing weeks-old data.
        _fallback_path = _Path(__file__).parent / "fallback_snapshot_safe.json"
        _fallback_age = (
            datetime.now(timezone.utc).timestamp() - _fallback_path.stat().st_mtime
            if _fallback_path.exists() else float("inf")
        )
        if _fallback_age > 7 * 86400:
            # Re-use the same safe serialisation logic that set_cached_dashboard uses
            import copy as _copy
            safe = _copy.deepcopy(result)
            if "dates" in safe and hasattr(safe["dates"], "strftime"):
                safe["dates"] = safe["dates"].strftime("%Y-%m-%d").tolist()
            if "category_history" in safe:
                safe["category_history"] = {
                    cat: (s.replace({np.nan: None}).tolist() if hasattr(s, "tolist") else s)
                    for cat, s in safe["category_history"].items()
                }
            _write_text_atomic(_fallback_path, _json.dumps(safe, default=str))
            logger.info("Refreshed fallback_snapshot_safe.json (was %.1f days old).", _fallback_age / 86400)

        if status_callback: status_callback("Data ready! Launching...")
        set_status("Data ready!")
    except Exception as e:
        logger.warning("Failed to persist dashboard state: %s", e)

    return result

