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

from config import CATEGORY_WEIGHTS, HISTORY_DAYS, REGIONS
from data.providers.demand import DemandProvider
from data.providers.energy import EnergyProvider
from data.providers.geopolitical import GeopoliticalProvider, fetch_supply_chain_news
from data.providers.ports import PortsProvider
from data.providers.shipping import ShippingProvider
from data.providers.tariffs import TariffsProvider
from data.providers.weather import WeatherProvider

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


def _derive_map_markers(
    current_scores: dict[str, float],
    weather_provider: WeatherProvider,
) -> list[dict]:
    """Derive specific map markers (cities/hubs) with detailed tooltips.
    
    Instead of generic regions, we now plot specific major shipping hubs.
    The score for each hub is a mix of its specific LOCAL weather score
    and the GLOBAL category scores (shipping, energy, etc.).
    """
    markers = []
    
    # Get specific hub weather data
    hub_data = weather_provider.fetch_current_hub_data()
    
    # Global factors that affect everyone (weighted sum)
    # We exclude 'weather' because we use local weather.
    # We exclude 'ports' because we don't have local port data yet, so we treat it as global tax.
    global_factors = {
        "energy": 0.25,
        "tariffs": 0.25,
        "shipping": 0.25, 
        "geopolitical": 0.25,
    }
    
    # Calculate a "Global Baseline" score from non-weather categories
    global_score_sum = sum(
        current_scores.get(cat, 50) * weight 
        for cat, weight in global_factors.items()
    )
    
    for hub in hub_data:
        # Composite: 80% local weather, 20% global baseline
        # We heavily bias towards local weather to ensure the map dots
        # turn yellow/red when local conditions are bad.
        local_weather_score = hub["score"]
        composite = (local_weather_score * 0.8) + (global_score_sum * 0.2)
        
        # Build the "Why" description string
        reasons = []
        
        # 1. Weather Reason (if significant deduction)
        if local_weather_score < 80:
            reasons.append(f"Weather: {hub['weather_summary']}")
            
        # 2. Global Reasons (if low scores)
        if current_scores.get("geopolitical", 100) < 60:
            reasons.append("Geopolitics: High Risk")
        if current_scores.get("energy", 100) < 60:
            reasons.append("Energy: High Cost")
        if current_scores.get("shipping", 100) < 60:
            reasons.append("Shipping: Rate Spike")
            
        # Fallback if everything is fine
        if not reasons:
            reasons.append("Status: Nominal")
            
        reason_html = "<br>• " + "<br>• ".join(reasons)
        
        markers.append({
            "name": hub["name"],
            "lat": hub["lat"],
            "lon": hub["lon"],
            "score": round(composite, 1),
            "description": reason_html
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

    # Compute composite for regional derivation
    from scoring.engine import compute_composite_index
    composite = compute_composite_index(current_scores)
    
    # Generate Map Markers (City/Hub based)
    # We grab the WeatherProvider instance specifically to access hub data
    weather_provider = providers_map["weather"]
    map_markers = _derive_map_markers(current_scores, weather_provider)

    # Alerts from NewsAPI
    alerts: list[dict] = []
    try:
        _, news_alerts = fetch_supply_chain_news()
        alerts = news_alerts
    except Exception as exc:
        logger.warning("Could not load alerts: %s", exc)

    # Disruptions — derived from TWO sources:
    #   1. Categories scoring below 70 (stressed or worse)
    #   2. High-severity news alerts (real events from the news feed)
    from config import CATEGORY_LABELS

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
