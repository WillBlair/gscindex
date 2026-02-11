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
from data.ports_data import MAJOR_PORTS

from data.providers.energy import EnergyProvider
from data.providers.geopolitical import GeopoliticalProvider, fetch_supply_chain_news, _is_irrelevant_article
from data.providers.supply_chain import SupplyChainProvider
from data.providers.trucking import TruckingProvider
from data.providers.tariffs import TariffsProvider
from data.providers.weather import WeatherProvider
from data.port_analyst import generate_port_summaries
from scoring import get_health_tier

logger = logging.getLogger(__name__)

# All providers, instantiated once
_PROVIDERS = [
    WeatherProvider(),
    SupplyChainProvider(),
    EnergyProvider(),
    TariffsProvider(),
    TruckingProvider(),
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
    """Create a flat series at a neutral value for categories that failed to load."""
    dates = pd.date_range(
        end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        periods=days,
        freq="D",
    )
    return pd.Series(value, index=dates, name=name)



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
        # For Port Risk Scoring, ONLY consider negative news.
        # Neutral/Positive news is fine for the feed, but shouldn't penalize port scores.
        if alert.get("sentiment", 0) >= -0.05:
            continue

        text = f"{alert.get('title', '')} {alert.get('body', '')}".lower()

        if _is_irrelevant_article(text):
            logger.debug("Skipping irrelevant article: %s", alert.get("title", ""))
            continue

        for name, _lat, _lon, direct_kw, regional_kw in MAJOR_PORTS:
            if any(kw in text for kw in direct_kw):
                port_news.setdefault(name, []).append((alert, "direct"))
            elif any(kw in text for kw in regional_kw):
                port_news.setdefault(name, []).append((alert, "regional"))

    return port_news


def _derive_map_markers(
    current_scores: dict[str, float],
    alerts: list[dict],
    weather_provider: WeatherProvider,
    port_summaries: dict[str, str] | None = None,
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
    port_coords = [(name, lat, lon) for name, lat, lon, _, _ in MAJOR_PORTS]
    batch_weather = weather_provider.fetch_batch_port_weather(port_coords)

    # ── Global macro baseline (non-weather categories) ───────────
    non_weather_cats = ["energy", "supply_chain", "tariffs", "trucking", "geopolitical"]
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

    for name, lat, lon, _direct_kw, _regional_kw in MAJOR_PORTS:
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

        # ── AI-generated port summary ─────────────────────────────
        ai_summary = ""
        if port_summaries:
            ai_summary = port_summaries.get(name, "")
        
        if ai_summary:
            # Wrap long summaries to ~60 chars per line for tooltip readability
            words = ai_summary.split()
            wrapped_lines = []
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 <= 60:
                    current_line = f"{current_line} {word}".strip()
                else:
                    if current_line:
                        wrapped_lines.append(current_line)
                    current_line = word
            if current_line:
                wrapped_lines.append(current_line)
            wrapped_summary = "<br>".join(wrapped_lines)
            lines.append(f"<b>Status:</b> {wrapped_summary}")
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
            
        logger.info("Loaded %s: %.1f", cat, current_score)
    except Exception as exc:
        logger.error("Provider %s failed (current): %s", cat, exc)
        error_msg = str(exc)
        current_score = 50.0
        metadata = {"error": str(exc), "description": "Data fetch failed."}

    try:
        # 2. Fetch history
        history_series = provider.fetch_history(HISTORY_DAYS)
    except Exception as exc:
        logger.error("Provider %s failed (history): %s", cat, exc)
        if not error_msg: 
            error_msg = str(exc)
        history_series = None

    return cat, current_score, history_series, metadata, error_msg

def aggregate_data() -> dict:
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # -- Submit Provider Tasks --
        future_to_provider = {
            executor.submit(_fetch_provider_data, p): p 
            for p in _PROVIDERS
        }
        
        # -- Submit News Task --
        future_news = executor.submit(fetch_supply_chain_news)
        
        # -- Submit Market Data Task --
        future_market = executor.submit(_fetch_market_data)
        
        # -- Submit AI Port Summaries Task --
        future_port_summaries = executor.submit(generate_port_summaries)

        # -------------------------------------------------------------------
        # 2. Collect Results (with Timeout)
        # -------------------------------------------------------------------
        # We give the whole batch a timeout (e.g. 15 seconds)
        # If it takes longer, we'll proceed with whatever we have.

        # A. Process Providers
        try:
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
                        # Reindex handles filling missing dates with NaNs, then we ffill/bfill
                        aligned = hist_series.reindex(dates, method="ffill")
                        # Fill any remaining NaNs (e.g. at start) with current score
                        aligned = aligned.fillna(score)
                        
                        # CRITICAL FIX: Overwrite the last data point (today) with the LIVE score.
                        # This ensures the sparking/delta calculation uses the real current value,
                        # not yesterday's close (which ffill would do).
                        aligned.iloc[-1] = score
                        
                        category_history[cat] = aligned
                    else:
                        # Fallback if history fetch failed
                        category_history[cat] = _make_fallback_series(HISTORY_DAYS, cat, score)
                        
                except Exception as e:
                    # This catches timeouts or crashes in the wrapper
                    logger.error("A provider task failed unexpectedly: %s", e)
        except concurrent.futures.TimeoutError:
            logger.warning("Data fetch timed out. Some providers may be missing.")

        # B. Process News
        alerts = []
        briefing = ""
        full_report = ""
        try:
             # Wait specifically for news
            _, alerts, briefing, full_report = future_news.result(timeout=5) 
        except Exception as e:
            logger.warning("News fetch timed out or failed: %s", e)

        # C. Process Market Data
        market_data = {}
        try:
            market_data = future_market.result(timeout=5) or {}
        except Exception as e:
            logger.warning("Market data fetch timed out or failed: %s", e)
        
        # D. Process Port Summaries
        port_summaries = {}
        try:
            port_summaries = future_port_summaries.result(timeout=10) or {}
        except Exception as e:
            logger.warning("Port summaries fetch timed out or failed: %s", e)


    # -----------------------------------------------------------------------
    # 3. Post-Processing (Scoring & Markers)
    # -----------------------------------------------------------------------
    # Ensure complete datasets (fill missing providers with neutral)
    for p in _PROVIDERS:
        if p.category not in current_scores:
            current_scores[p.category] = 50.0
            category_history[p.category] = _make_fallback_series(HISTORY_DAYS, p.category, 50.0)
            provider_errors[p.category] = "Provider timed out"

    # Compute composite
    from scoring.engine import compute_composite_index
    composite = compute_composite_index(current_scores)

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
    }

    # Persist the full dashboard state to disk for instant startup
    # Persist the full dashboard state to disk for instant startup
    from data.cache import set_cached_dashboard
    try:
        set_cached_dashboard(result)
        logger.info("Dashboard state persisted to disk (JSON/Safe).")
    except Exception as e:
        logger.warning("Failed to persist dashboard state: %s", e)

    return result

