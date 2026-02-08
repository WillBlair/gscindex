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
from datetime import datetime

import numpy as np
import pandas as pd

from config import CATEGORY_LABELS, CATEGORY_WEIGHTS, HISTORY_DAYS, REGIONS
from data.providers.demand import DemandProvider
from data.providers.energy import EnergyProvider
from data.providers.geopolitical import GeopoliticalProvider, fetch_supply_chain_news
from data.providers.ports import PortsProvider
from data.providers.shipping import ShippingProvider
from data.providers.tariffs import TariffsProvider
from data.providers.weather import WeatherProvider
from scoring import get_health_tier

logger = logging.getLogger(__name__)

# All providers, instantiated once
_PROVIDERS = [
    WeatherProvider(),
    PortsProvider(),
    EnergyProvider(),
    TariffsProvider(),
    ShippingProvider(),
    GeopoliticalProvider(),
    DemandProvider(),
]


def _make_fallback_series(days: int, name: str, value: float = 50.0) -> pd.Series:
    """Create a flat series at a neutral value for categories that failed to load."""
    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=days,
        freq="D",
    )
    return pd.Series(value, index=dates, name=name)


# ---------------------------------------------------------------------------
# Major Ports — coordinates + news keywords + risk profiles
# ---------------------------------------------------------------------------
# Each entry: (name, lat, lon, direct_keywords, regional_keywords)
#
#   direct_keywords  — port name, infrastructure, chokepoints → full penalty.
#   regional_keywords — country, region, waterway → half penalty.
# ---------------------------------------------------------------------------

_MAJOR_PORTS: list[tuple[str, float, float, list[str], list[str]]] = [
    # ── North America ───────────────────────────────────────
    ("Houston",       29.76,  -95.37,
     ["houston", "gulf coast port"],
     ["united states", "u.s.", "american port"]),
    ("New York",      40.68,  -74.04,
     ["new york port", "newark port", "port authority"],
     ["united states", "u.s.", "american port", "east coast"]),
    ("Los Angeles",   33.75, -118.27,
     ["los angeles", "long beach", "san pedro"],
     ["united states", "u.s.", "american port", "west coast"]),
    ("Savannah",      32.08,  -81.09,
     ["savannah port"],
     ["united states", "u.s.", "american port"]),
    ("Vancouver",     49.29, -123.11,
     ["vancouver port"],
     ["canada", "canadian"]),
    # ── Central & South America ─────────────────────────────
    ("Colon",          9.36,  -79.90,
     ["panama canal", "colon port"],
     ["panama", "central america", "latin america"]),
    ("Manzanillo",    19.05, -104.32,
     ["manzanillo"],
     ["mexico", "mexican", "latin america"]),
    ("Santos",       -23.96,  -46.33,
     ["santos port"],
     ["brazil", "brazilian", "south america", "latin america"]),
    ("Buenos Aires", -34.60,  -58.38,
     ["buenos aires"],
     ["argentina", "south america", "latin america"]),
    # ── Europe ──────────────────────────────────────────────
    ("Rotterdam",     51.92,    4.48,
     ["rotterdam", "europoort"],
     ["netherlands", "dutch", "eu ", "european", "europe "]),
    ("Hamburg",       53.55,    9.99,
     ["hamburg"],
     ["germany", "german", "eu ", "european", "europe "]),
    ("Antwerp",       51.27,    4.39,
     ["antwerp"],
     ["belgium", "eu ", "european", "europe "]),
    ("Felixstowe",    51.96,    1.35,
     ["felixstowe"],
     ["uk ", "u.k.", "britain", "british"]),
    ("Piraeus",       37.94,   23.65,
     ["piraeus"],
     ["greece", "greek", "eu ", "european", "mediterranean"]),
    ("Algeciras",     36.13,   -5.45,
     ["algeciras", "strait of gibraltar"],
     ["spain", "spanish", "eu ", "european", "mediterranean"]),
    ("Gdansk",        54.35,   18.65,
     ["gdansk", "baltic port"],
     ["poland", "eu ", "european", "europe ", "russia", "ukraine"]),
    # ── East Asia ───────────────────────────────────────────
    ("Shanghai",      31.23,  121.47,
     ["shanghai", "yangshan"],
     ["china", "chinese", "beijing"]),
    ("Hong Kong",     22.29,  114.17,
     ["hong kong"],
     ["china", "chinese"]),
    ("Busan",         35.10,  129.03,
     ["busan"],
     ["south korea", "korean", "korea "]),
    ("Qingdao",       36.07,  120.38,
     ["qingdao"],
     ["china", "chinese"]),
    ("Tokyo",         35.65,  139.84,
     ["tokyo"],
     ["japan", "japanese"]),
    ("Kaohsiung",     22.62,  120.31,
     ["kaohsiung"],
     ["taiwan", "taiwanese"]),
    # ── Southeast Asia ──────────────────────────────────────
    ("Singapore",      1.35,  103.82,
     ["singapore", "malacca strait", "strait of malacca"],
     ["southeast asia", "asean"]),
    ("Laem Chabang",  13.08,  100.88,
     ["laem chabang"],
     ["thailand", "thai", "southeast asia"]),
    ("Port Klang",     3.00,  101.39,
     ["port klang"],
     ["malaysia", "malaysian", "southeast asia"]),
    # ── South Asia ──────────────────────────────────────────
    ("Mumbai",        19.08,   72.88,
     ["mumbai", "nhava sheva", "jnpt"],
     ["india", "indian"]),
    ("Chennai",       13.08,   80.29,
     ["chennai"],
     ["india", "indian"]),
    ("Colombo",        6.93,   79.84,
     ["colombo"],
     ["sri lanka", "india", "indian ocean"]),
    # ── Middle East ─────────────────────────────────────────
    ("Dubai",         25.28,   55.30,
     ["dubai", "jebel ali"],
     ["uae", "emirates", "middle east", "iran", "persian gulf", "gulf state"]),
    ("Jeddah",        21.49,   39.19,
     ["jeddah", "red sea"],
     ["saudi", "middle east", "iran", "persian gulf"]),
    # ── Africa ──────────────────────────────────────────────
    ("Durban",       -29.86,   31.02,
     ["durban"],
     ["south africa", "african port"]),
    ("Mombasa",       -4.04,   39.67,
     ["mombasa"],
     ["kenya", "east africa"]),
    ("Djibouti",      11.59,   43.15,
     ["djibouti"],
     ["horn of africa", "red sea", "east africa"]),
    ("Lagos",          6.45,    3.39,
     ["lagos", "apapa"],
     ["nigeria", "west africa"]),
    ("Port Said",     31.26,   32.30,
     ["port said", "suez canal", "suez"],
     ["egypt", "red sea", "middle east"]),
    # ── Oceania ─────────────────────────────────────────────
    ("Sydney",       -33.86,  151.20,
     ["sydney port"],
     ["australia", "australian"]),
    ("Melbourne",    -37.81,  144.96,
     ["melbourne port"],
     ["australia", "australian"]),
]




# ---------------------------------------------------------------------------
# News penalty tables + helpers
# ---------------------------------------------------------------------------

_DIRECT_PENALTY:   dict[str, float] = {"high": 15, "medium": 8, "low": 3}
_REGIONAL_PENALTY: dict[str, float] = {"high": 8,  "medium": 4, "low": 2}


def _sentiment_label(compound: float) -> str:
    """Human-readable description of VADER compound sentiment."""
    if compound <= -0.75:
        return "Very negative"
    if compound <= -0.5:
        return "Strongly negative"
    if compound <= -0.25:
        return "Negative"
    return "Slightly negative"


# Terms that indicate an article is clearly NOT about supply chains.
# If any of these appear in the title or body, the article is skipped
# before it ever matches to a port.  Keeps garbage out of scores.
_IRRELEVANT_TERMS: set[str] = {
    "fantasy", "baseball", "football", "basketball", "hockey", "nfl",
    "nba", "nhl", "mlb", "premier league", "world cup", "olympics",
    "vacation", "hotel", "resort", "airbnb", "tourism", "travel deal",
    "gaming", "playstation", "xbox", "nintendo", "handheld",
    "upsc", "exam prep", "exam result", "board exam", "college admission",
    "recipe", "cookbook", "celebrity", "red carpet", "box office",
    "movie review", "album review", "concert", "streaming service",
    "cryptocurrency", "bitcoin", "ethereum", "nft", "meme coin",
    "horoscope", "zodiac", "astrology", "lottery", "powerball",
}


def _is_irrelevant_article(text: str) -> bool:
    """Return True if the article text contains clearly off-topic terms."""
    return any(term in text for term in _IRRELEVANT_TERMS)


def _match_news_to_ports(
    alerts: list[dict],
) -> dict[str, list[tuple[dict, str]]]:
    """Match negative news alerts to ports via two-tier keyword scanning.

    Articles that are clearly irrelevant (sports, lifestyle, exam prep,
    crypto, entertainment) are filtered out before matching, preventing
    garbage from polluting port scores.

    Returns
    -------
    dict[str, list[tuple[dict, str]]]
        port name → [(alert, "direct" | "regional"), ...]
    """
    port_news: dict[str, list[tuple[dict, str]]] = {}

    for alert in alerts:
        if alert.get("sentiment", 0) >= -0.05:
            continue

        text = f"{alert.get('title', '')} {alert.get('body', '')}".lower()

        if _is_irrelevant_article(text):
            logger.debug("Skipping irrelevant article: %s", alert.get("title", ""))
            continue

        for name, _lat, _lon, direct_kw, regional_kw in _MAJOR_PORTS:
            if any(kw in text for kw in direct_kw):
                port_news.setdefault(name, []).append((alert, "direct"))
            elif any(kw in text for kw in regional_kw):
                port_news.setdefault(name, []).append((alert, "regional"))

    return port_news


def _derive_map_markers(
    current_scores: dict[str, float],
    alerts: list[dict],
    weather_provider: WeatherProvider,
) -> list[dict]:
    """Build a map marker for every major shipping port.

    Each port's score is computed from **real data only** — no fabricated
    jitter, no made-up risk profiles.  The three score components:

        1. **Local weather** (60% weight) — real-time conditions at the
           port's exact lat/lon, fetched in one batched Open-Meteo call.
           This is the primary source of genuine per-port variation.
        2. **Global macro factors** (40% weight) — weighted average of all
           non-weather FRED categories (energy, ports, tariffs, shipping,
           geopolitical, demand).  Same for all ports, and the tooltip is
           honest about that.
        3. **News penalty** (0–40 pts deducted) — VADER-scored articles
           matched via two-tier keywords with garbage pre-filtered.
    """
    markers: list[dict] = []

    # ── Batch-fetch real weather for all 37 ports (1 HTTP call) ──
    port_coords = [(name, lat, lon) for name, lat, lon, _, _ in _MAJOR_PORTS]
    batch_weather = weather_provider.fetch_batch_port_weather(port_coords)

    # ── Global macro baseline (non-weather categories) ───────────
    non_weather_cats = ["energy", "ports", "tariffs", "shipping", "geopolitical", "demand"]
    non_weather_weights = {
        cat: CATEGORY_WEIGHTS.get(cat, 0)
        for cat in non_weather_cats
        if cat in CATEGORY_WEIGHTS
    }
    weight_sum = sum(non_weather_weights.values()) or 1.0
    # Normalize so these 6 categories' weights sum to 1.0
    normalized_weights = {
        cat: w / weight_sum for cat, w in non_weather_weights.items()
    }
    global_macro = sum(
        current_scores.get(cat, 50) * w
        for cat, w in normalized_weights.items()
    )

    # ── Match news to ports ──────────────────────────────────────
    port_news = _match_news_to_ports(alerts)

    for name, lat, lon, _direct_kw, _regional_kw in _MAJOR_PORTS:
        # ── Local weather score (real, unique per port) ──────────
        wx = batch_weather.get(name, {})
        local_weather = wx.get("score", 75.0)
        weather_summary = wx.get("summary", "Weather data unavailable")

        # ── Composite: 60% local weather + 40% global macro ─────
        composite = local_weather * 0.60 + global_macro * 0.40

        # ── News penalty ─────────────────────────────────────────
        matched = port_news.get(name, [])
        news_penalty = 0.0
        news_lines: list[str] = []

        for article, match_type in matched:
            severity = article.get("severity", "low")
            sentiment = article.get("sentiment", 0)
            title = article.get("title", "Unknown event")
            short_title = (title[:58] + "...") if len(title) > 58 else title
            label = _sentiment_label(sentiment)

            penalty_table = (
                _DIRECT_PENALTY if match_type == "direct"
                else _REGIONAL_PENALTY
            )
            news_penalty += penalty_table.get(severity, 2)

            scope = "Direct" if match_type == "direct" else "Regional"
            sev_tag = severity.upper()
            news_lines.append(
                f"<b>[{sev_tag}]</b> {short_title}<br>"
                f"   {label} ({sentiment:+.2f}) · {scope} impact"
            )

        news_penalty = min(news_penalty, 40)

        # ── Final score ──────────────────────────────────────────
        score = round(max(0.0, min(100.0, composite - news_penalty)), 1)
        tier = get_health_tier(score)

        # ── Build hover tooltip (transparent about data sources) ─
        lines: list[str] = [
            f"Score: {score:.0f}/100 — <b>{tier['label']}</b>",
            "────────────",
            f"<b>Weather:</b> {weather_summary} (score: {local_weather:.0f})",
        ]

        # Show global macro context — only mention stressed or critical
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
        elif not critical and not stressed:
            lines.append("No active disruptions for this port.")

        markers.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "score": score,
            "description": "<br>".join(lines),
        })

    return markers


def aggregate_data() -> dict:
    """Fetch data from all providers and assemble the dashboard data dict.

    Returns
    -------
    dict with keys:
        ``"dates"``            – pd.DatetimeIndex
        ``"category_history"`` – dict[str, pd.Series]
        ``"current_scores"``   – dict[str, float]
        ``"map_markers"``      – list[dict] (REPLACES regional_risk)
        ``"alerts"``           – list[dict]
        ``"disruptions"``      – list[dict]
        ``"provider_errors"``  – dict[str, str] (category → error message)
    """
    current_scores: dict[str, float] = {}
    category_history: dict[str, pd.Series] = {}
    provider_errors: dict[str, str] = {}
    
    # Instantiate providers map for easy access
    providers_map = {}

    for provider in _PROVIDERS:
        cat = provider.category
        providers_map[cat] = provider
        try:
            current_scores[cat] = provider.fetch_current()
            logger.info("Loaded %s: %.1f", cat, current_scores[cat])
        except Exception as exc:
            logger.error("Provider %s failed (current): %s", cat, exc)
            provider_errors[cat] = str(exc)
            current_scores[cat] = 50.0  # neutral fallback

        try:
            history = provider.fetch_history(HISTORY_DAYS)
            target_dates = pd.date_range(
                end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
                periods=HISTORY_DAYS,
                freq="D",
            )
            history = history.reindex(target_dates, method="ffill")
            history = history.fillna(current_scores[cat])
            category_history[cat] = history
        except Exception as exc:
            logger.error("Provider %s failed (history): %s", cat, exc)
            category_history[cat] = _make_fallback_series(
                HISTORY_DAYS, cat, current_scores[cat]
            )

    # Compute composite
    from scoring.engine import compute_composite_index
    composite = compute_composite_index(current_scores)

    # Alerts from NewsAPI — fetched BEFORE map markers so news intelligence
    # can influence per-port scores (turning dots yellow / red).
    alerts: list[dict] = []
    try:
        _, news_alerts = fetch_supply_chain_news()
        alerts = news_alerts
    except Exception as exc:
        logger.warning("Could not load alerts: %s", exc)

    # Map markers — real local weather (1 batched call) + global macro + news.
    weather_provider = providers_map.get("weather")
    map_markers = _derive_map_markers(current_scores, alerts, weather_provider)

    # Disruptions — derived from TWO sources:
    #   1. Categories scoring below 70 (stressed or worse)
    #   2. High-severity news alerts (real events from the news feed)

    disruptions: list[dict] = []

    # Source 1: Low-scoring categories
    for cat, score in current_scores.items():
        if score < 70:
            severity = "Critical" if score < 40 else "Stressed"
            impact = round((100 - score) / 10, 1)
            disruptions.append({
                "event": f"{CATEGORY_LABELS[cat]} — {severity}",
                "region": "Global",
                "impact_score": impact,
                "categories": [cat],
                "started": "Ongoing",
                "status": "Active" if score < 50 else "Monitoring",
            })

    # Source 2: High-severity news alerts become disruption events
    for alert in alerts:
        if alert.get("severity") == "high":
            cat = alert.get("category", "geopolitical")
            title = alert.get("title", "Unknown event")
            # Truncate long titles for the table
            short_title = title[:60] + "..." if len(title) > 60 else title
            disruptions.append({
                "event": short_title,
                "region": "Global",
                "impact_score": round(abs(alert.get("sentiment", -0.5)) * 10, 1),
                "categories": [cat],
                "started": "Recent",
                "status": "Active",
            })

    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=HISTORY_DAYS,
        freq="D",
    )

    return {
        "dates": dates,
        "category_history": category_history,
        "current_scores": current_scores,
        "map_markers": map_markers,
        "alerts": alerts,
        "disruptions": disruptions,
        "provider_errors": provider_errors,
    }
