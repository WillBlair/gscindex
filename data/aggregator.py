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


def _derive_regional_risk(
    composite_score: float,
    category_scores: dict[str, float],
) -> dict[str, float]:
    """Derive regional risk scores from category scores.

    This is an approximation. Different regions are weighted differently
    based on their primary supply chain role:
        - East Asia / SE Asia: heavily weighted by ports + shipping
        - Middle East: heavily weighted by energy + geopolitical
        - North America / Europe: balanced across all categories
        - etc.

    Parameters
    ----------
    composite_score : float
        Overall composite index.
    category_scores : dict[str, float]
        Current category scores.

    Returns
    -------
    dict[str, float]
        Risk score per region (0–100).
    """
    # Regional weighting adjustments — which categories matter most per region
    _REGIONAL_BIAS: dict[str, dict[str, float]] = {
        "North America":      {"weather": 0.2, "ports": 0.15, "energy": 0.15, "tariffs": 0.2, "shipping": 0.15, "geopolitical": 0.05, "demand": 0.1},
        "South America":      {"weather": 0.15, "ports": 0.2, "energy": 0.2, "tariffs": 0.15, "shipping": 0.15, "geopolitical": 0.1, "demand": 0.05},
        "Europe":             {"weather": 0.1, "ports": 0.15, "energy": 0.2, "tariffs": 0.2, "shipping": 0.15, "geopolitical": 0.15, "demand": 0.05},
        "East Asia":          {"weather": 0.1, "ports": 0.3, "energy": 0.1, "tariffs": 0.15, "shipping": 0.2, "geopolitical": 0.1, "demand": 0.05},
        "Southeast Asia":     {"weather": 0.15, "ports": 0.25, "energy": 0.1, "tariffs": 0.1, "shipping": 0.2, "geopolitical": 0.1, "demand": 0.1},
        "South Asia":         {"weather": 0.2, "ports": 0.15, "energy": 0.15, "tariffs": 0.15, "shipping": 0.15, "geopolitical": 0.15, "demand": 0.05},
        "Middle East":        {"weather": 0.05, "ports": 0.15, "energy": 0.3, "tariffs": 0.1, "shipping": 0.1, "geopolitical": 0.25, "demand": 0.05},
        "Sub-Saharan Africa": {"weather": 0.2, "ports": 0.15, "energy": 0.2, "tariffs": 0.1, "shipping": 0.1, "geopolitical": 0.2, "demand": 0.05},
        "Oceania":            {"weather": 0.15, "ports": 0.15, "energy": 0.15, "tariffs": 0.15, "shipping": 0.2, "geopolitical": 0.05, "demand": 0.15},
    }

    regional_risk: dict[str, float] = {}
    for region in REGIONS:
        bias = _REGIONAL_BIAS.get(region)
        if bias:
            score = sum(
                bias[cat] * category_scores.get(cat, 50.0)
                for cat in bias
            )
            regional_risk[region] = round(float(np.clip(score, 0, 100)), 1)
        else:
            regional_risk[region] = round(composite_score, 1)

    return regional_risk


def aggregate_data() -> dict:
    """Fetch data from all providers and assemble the dashboard data dict.

    Returns
    -------
    dict with keys:
        ``"dates"``            – pd.DatetimeIndex
        ``"category_history"`` – dict[str, pd.Series]
        ``"current_scores"``   – dict[str, float]
        ``"regional_risk"``    – dict[str, float]
        ``"alerts"``           – list[dict]
        ``"disruptions"``      – list[dict]
        ``"provider_errors"``  – dict[str, str] (category → error message)
    """
    current_scores: dict[str, float] = {}
    category_history: dict[str, pd.Series] = {}
    provider_errors: dict[str, str] = {}

    for provider in _PROVIDERS:
        cat = provider.category
        try:
            current_scores[cat] = provider.fetch_current()
            logger.info("Loaded %s: %.1f", cat, current_scores[cat])
        except Exception as exc:
            logger.error("Provider %s failed (current): %s", cat, exc)
            provider_errors[cat] = str(exc)
            current_scores[cat] = 50.0  # neutral fallback

        try:
            history = provider.fetch_history(HISTORY_DAYS)
            # Ensure the history has exactly HISTORY_DAYS entries
            # by reindexing to a daily range and forward-filling
            target_dates = pd.date_range(
                end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
                periods=HISTORY_DAYS,
                freq="D",
            )
            history = history.reindex(target_dates, method="ffill")
            # Fill any remaining NaN with the current score
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
        "regional_risk": _derive_regional_risk(composite, current_scores),
        "alerts": alerts,
        "disruptions": disruptions,
        "provider_errors": provider_errors,
    }
