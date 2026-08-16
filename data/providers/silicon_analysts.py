"""
Silicon Analysts Data Provider
===============================
Fetches semiconductor supply chain data from the free Silicon Analysts API
(https://siliconanalysts.com). No API key required.

Returns four category scores from a single batch fetch:
  - chip_fab_util       (Fab Capacity Utilization)
  - chip_memory_prices  (HBM/DRAM Pricing)
  - chip_lead_times     (Component Lead Times)
  - chip_wafer_prices   (Wafer Pricing)

Scoring logic:
  - Fab utilization: higher = healthier (100% util = demand strong, <70% = glut)
  - Memory prices: inverse bell — extreme highs OR extreme lows are bad
  - Lead times: shorter = healthier (>40 wk = stressed, <20 wk = healthy)
  - Wafer prices: cost pressure inverse percentile vs trailing window
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone

import os

import pandas as pd
import requests

from config import (
    INDUSTRY_PROVIDER_CACHE_TTL,
)

logger = logging.getLogger(__name__)

# API key (optional — raises anonymous tier from 20 to 100 req/day, unlocks history).
_SILICON_ANALYSTS_API_KEY: str | None = os.environ.get("SILICON_ANALYSTS_API_KEY")

# The Silicon Analysts provider is designed to run a single batch HTTP call
# and unpack multiple category scores.  The aggregator detects the
# ``additional_scores`` key in metadata and merges them into the dashboard
# snapshot so each appears as its own weighted category.

BASE_URL = "https://siliconanalysts.com/api/v1/market-data"

ENDPOINTS: list[dict] = [
    {
        "key": "chip_fab_util",
        "url": f"{BASE_URL}/fab-utilization",
        "label": "Fab Capacity Utilization",
        "scoring": "percentile_higher_better",
    },
    {
        "key": "chip_memory_prices",
        "url": f"{BASE_URL}/hbm-pricing",
        "label": "HBM Pricing (per GB)",
        "scoring": "inverse_bell",
    },
    {
        "key": "chip_lead_times",
        "url": f"{BASE_URL}/component-lead-times",
        "label": "Component Lead Times",
        "scoring": "inverse_linear",
    },
    {
        "key": "chip_wafer_prices",
        "url": f"{BASE_URL}/wafer-price-tsmc",
        "label": "TSMC Wafer Pricing",
        "scoring": "percentile_higher_better",
    },
]

# Cache TTL — semiconductor data is slow-moving; 24h is appropriate.
CACHE_TTL_SECONDS: int = INDUSTRY_PROVIDER_CACHE_TTL


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_fab_util(data_points: list[dict]) -> tuple[float, dict]:
    """Score fab utilization: higher = healthier (strong demand).
    
    Uses the most recent TSMC leading-edge utilization value.
    >95% = excellent (demand outstripping supply)
    85-95% = healthy
    70-85% = softening
    <70% = oversupply / demand collapse signal
    """
    recent = [d for d in data_points if d.get("is_recent") and d.get("series_key") == "tsmc-leading"]
    if not recent:
        recent = [d for d in data_points if d.get("series_key") == "tsmc-leading"]
    if not recent:
        return 50.0, {"source": "Silicon Analysts API", "error": "No TSMC leading-edge data found"}
    
    # Get most recent period
    latest = max(recent, key=lambda d: d.get("period_sort_key", 0))
    util = latest.get("value_mid", 50)
    source_note = latest.get("source_note", "")
    confidence = latest.get("confidence", "Medium")
    period = latest.get("period_label", "Unknown")
    
    # Score: linear map from utilization percent to 0-100
    # 100% util → 100, 70% util → 30, 50% util → 0
    score = max(0.0, min(100.0, (util - 50) * 2.0))
    
    metadata = {
        "source": f"Silicon Analysts API ({confidence} confidence)",
        "raw_value": f"{util}%",
        "raw_label": f"TSMC Leading Edge Utilization ({period})",
        "description": source_note or f"TSMC leading-edge fab utilization at {util}% in {period}",
        "calculation": f"score = max(0, min(100, ({util} - 50) * 2.0))",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    return score, metadata


def _score_lead_times(data_points: list[dict]) -> tuple[float, dict]:
    """Score component lead times: shorter = healthier.
    
    Focuses on CoWoS and TSMC N3 lead times.
    <20 weeks = healthy (90+)
    20-40 weeks = normal (60-90)
    40-52 weeks = constrained (30-60)
    >52 weeks = severe shortage (<30)
    """
    cowos = [d for d in data_points if d.get("is_recent") and "cowos" in d.get("series_key", "").lower()]
    tsmc = [d for d in data_points if d.get("is_recent") and "tsmc" in d.get("series_key", "").lower()]
    combined = cowos + tsmc
    
    if not combined:
        return 50.0, {"source": "Silicon Analysts API", "error": "No lead time data found"}
    
    # Average the lead times of CoWoS and TSMC N3
    vals = [d.get("value_mid", 52) for d in combined]
    avg_weeks = sum(vals) / len(vals)
    
    # Score: inverse linear, 0 weeks → 100, 52 weeks → 30, beyond → 0
    score = max(0.0, min(100.0, 100.0 - (avg_weeks * 1.35)))
    
    periods = ", ".join(d.get("period_label", "?") for d in combined)
    labels = ", ".join(d.get("series_label", "?") for d in combined)
    
    metadata = {
        "source": "Silicon Analysts API",
        "raw_value": f"{avg_weeks:.0f} weeks",
        "raw_label": f"Avg Lead Time: {labels}",
        "description": f"Average lead time of {avg_weeks:.0f} weeks for key components ({labels}) in {periods}",
        "calculation": f"score = max(0, min(100, 100 - ({avg_weeks:.1f} * 1.35)))",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    return score, metadata


def _score_memory_prices(data_points: list[dict]) -> tuple[float, dict]:
    """Score memory prices using an inverse-bell model.
    
    HBM pricing that's too high = shortage/demand exceeding supply. Too low =
    demand collapse / oversupply. Both are bad. Moderate pricing = healthy.
    """
    recent = [d for d in data_points if d.get("is_recent")]
    if not recent:
        return 50.0, {"source": "Silicon Analysts API", "error": "No recent HBM pricing data found"}
    
    # Get the latest HBM3 or HBM3E pricing as the reference
    hbm3 = [d for d in recent if "hbm3" in d.get("series_key", "").lower() and "hbm2e" not in d.get("series_key", "").lower()]
    if not hbm3:
        hbm3 = [d for d in recent if "hbm" in d.get("series_key", "").lower()]
    if not hbm3:
        return 50.0, {"source": "Silicon Analysts API", "error": "No HBM3 data found"}
    
    latest = max(hbm3, key=lambda d: d.get("period_sort_key", 0))
    price = latest.get("value_mid", 0)
    label = latest.get("series_label", "HBM")
    period = latest.get("period_label", "Unknown")
    
    # Score: bell curve centered around moderate pricing
    # If HBM3 is ~$15-20/GB, score 70-90 (healthy)
    # Above $25/GB → shortage, score drops toward 30
    # Below $10/GB → demand collapse, score drops toward 40
    if price > 20:
        score = max(20.0, 80.0 - (price - 20) * 4)
    elif price < 10:
        score = max(20.0, 60.0 + (price - 5) * 4)
    else:
        score = max(70.0, 90.0 - abs(price - 15) * 2)
    
    metadata = {
        "source": "Silicon Analysts API",
        "raw_value": f"${price:.0f}/GB",
        "raw_label": f"{label} ({period})",
        "description": f"HBM pricing at ${price:.0f}/GB in {period}. {'Elevated — shortage signal' if price > 20 else 'Healthy moderate pricing' if price > 10 else 'Low — demand concern'}.",
        "calculation": f"Bell-curve score centered at $15/GB, extremes penalized",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    return score, metadata


def _score_wafer_prices(data_points: list[dict]) -> tuple[float, dict]:
    """Score wafer prices: moderate = healthy (extremes in either direction = bad).
    
    Uses the most recent N3/N4 wafer pricing data points.
    """
    recent = [d for d in data_points if d.get("is_recent")]
    if not recent:
        return 50.0, {"source": "Silicon Analysts API", "error": "No recent wafer pricing data found"}
    
    # Try to find N3/N3E data
    n3 = [d for d in recent if any(n in d.get("series_label", "").lower() for n in ["n3", "3nm"])]
    if not n3:
        n3 = recent[:1]  # fallback to most recent
    
    latest = max(n3, key=lambda d: d.get("period_sort_key", 0))
    price = latest.get("value_mid", 0)
    label = latest.get("series_label", "Wafer")
    period = latest.get("period_label", "Unknown")
    
    # Score: bell curve. N3 at ~$18-22K is normal market.
    # Above $25K = shortage / allocation squeeze → score drops
    # Below $15K = demand collapse → score drops
    if price > 22000:
        score = max(20.0, 80.0 - (price - 22000) / 500)
    elif price < 15000:
        score = max(20.0, 60.0 + (price - 12000) / 300)
    else:
        score = max(70.0, 90.0 - abs(price - 19000) / 1000)
    
    metadata = {
        "source": "Silicon Analysts API",
        "raw_value": f"${price:,.0f}",
        "raw_label": f"{label} ({period})",
        "description": f"TSMC {label} pricing at ${price:,.0f} per wafer in {period}.",
        "calculation": "Bell-curve score — extreme prices in either direction are penalized",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    return score, metadata


# ---------------------------------------------------------------------------
# Main provider
# ---------------------------------------------------------------------------

class SiliconAnalystsProvider:
    """Fetch all semiconductor supply chain signals from the free Silicon
    Analysts API and return four category scores.

    This is NOT a standard BaseProvider (which maps 1:1 to a category).
    Instead, ``fetch_all_current()`` returns a dict of category→score
    that the aggregator merges into the dashboard snapshot.
    """

    category: str = "chip_fab_util"  # primary category for the provider list

    def __init__(self) -> None:
        self._cache: dict | None = None
        self._cache_time: datetime | None = None

    def _fetch_with_cache(self) -> dict[str, dict]:
        """Fetch all four datasets from the API, with 24-hour caching."""
        now = datetime.now(timezone.utc)
        if (
            self._cache is not None
            and self._cache_time is not None
            and (now - self._cache_time).total_seconds() < CACHE_TTL_SECONDS
        ):
            logger.info("Silicon Analysts: serving from cache (age=%ds)",
                         (now - self._cache_time).total_seconds())
            return self._cache

        logger.info("Silicon Analysts: fetching %d datasets from %s",
                     len(ENDPOINTS), BASE_URL)
        datasets = {}
        headers = {}
        if _SILICON_ANALYSTS_API_KEY:
            headers["X-API-Key"] = _SILICON_ANALYSTS_API_KEY
        for ep in ENDPOINTS:
            try:
                resp = requests.get(ep["url"], timeout=15, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                if body.get("success"):
                    datasets[ep["key"]] = body["data"]["dataPoints"]
                else:
                    logger.warning("Silicon Analysts API returned error for %s: %s",
                                   ep["key"], body)
                    datasets[ep["key"]] = []
            except Exception as exc:
                logger.warning("Silicon Analysts fetch failed for %s: %s", ep["key"], exc)
                datasets[ep["key"]] = []

        self._cache = datasets
        self._cache_time = now
        return datasets

    def fetch_all_current(self) -> dict[str, tuple[float, dict]]:
        """Fetch current semiconductor scores for all four categories.

        Returns
        -------
        dict[str, tuple[float, dict]]
            Mapping of category key → (score, metadata).
        """
        datasets = self._fetch_with_cache()
        scores: dict[str, tuple[float, dict]] = {}

        for ep in ENDPOINTS:
            key = ep["key"]
            points = datasets.get(key, [])
            if not points:
                scores[key] = (50.0, {
                    "source": "Silicon Analysts API",
                    "raw_value": "—",
                    "raw_label": ep["label"],
                    "description": f"No data available for {ep['label']}",
                    "calculation": "Neutral default — API returned no data",
                    "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "is_fallback": True,
                })
                continue

            scoring = ep["scoring"]
            if scoring == "percentile_higher_better":
                score, meta = _score_fab_util(points) if key == "chip_fab_util" else _score_wafer_prices(points)
            elif scoring == "inverse_bell":
                score, meta = _score_memory_prices(points)
            elif scoring == "inverse_linear":
                score, meta = _score_lead_times(points)
            else:
                score, meta = 50.0, {"source": "Silicon Analysts API", "error": f"Unknown scoring: {scoring}"}

            scores[key] = (score, meta)

        return scores

    def fetch_history(self, days: int) -> pd.Series:
        """Return stub history for the primary category.

        The Silicon Analysts API only returns current data points on the free
        tier; historical series require a Pro key.  We return a single-point
        Series for the primary fab-util category so the chart doesn't break.
        """
        current = self.fetch_all_current()
        score, _ = current.get("chip_fab_util", (50.0, {}))
        today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
        return pd.Series([float(score)], index=[today], name="chip_fab_util")


# ---------------------------------------------------------------------------
# Aggregator adapter — so the provider list in aggregator.py can consume this
# without invasive changes.
# ---------------------------------------------------------------------------

# The aggregator iterates _PROVIDERS and calls .fetch_current() on each,
# expecting (float, dict).  We provide a thin wrapper that returns fab_util
# as the primary score and packs memory/lead_time/wafer scores in metadata.
# The aggregator detects "additional_scores" in metadata and merges them.

_si_instance: SiliconAnalystsProvider | None = None


def get_silicon_analysts_provider() -> SiliconAnalystsProvider:
    """Singleton SiliconAnalystsProvider — one instance, one HTTP cache."""
    global _si_instance
    if _si_instance is None:
        _si_instance = SiliconAnalystsProvider()
    return _si_instance


class ChipFabUtilProvider:
    """Adapter: exposes chip_fab_util as the primary category; packs the other
    three in metadata under ``additional_scores`` for the aggregator to merge."""

    category: str = "chip_fab_util"

    def fetch_current(self) -> tuple[float, dict]:
        provider = get_silicon_analysts_provider()
        all_scores = provider.fetch_all_current()
        primary_score, primary_meta = all_scores["chip_fab_util"]

        # Pack additional categories into metadata
        additional: dict[str, tuple[float, dict]] = {}
        for key in ("chip_memory_prices", "chip_lead_times", "chip_wafer_prices"):
            if key in all_scores:
                additional[key] = all_scores[key]

        primary_meta["additional_scores"] = additional
        return primary_score, primary_meta

    def fetch_history(self, days: int) -> pd.Series:
        return get_silicon_analysts_provider().fetch_history(days)


def _get_cached_industry_provider() -> SiliconAnalystsProvider:
    return get_silicon_analysts_provider()