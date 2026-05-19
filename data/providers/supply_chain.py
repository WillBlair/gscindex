"""
Supply Chain Pressure Provider
================================
Blends two NY Fed indicators:

* **WEI** (Weekly Economic Index, FRED) — high-frequency macro activity
  (rail, fuel, steel, electricity, staffing).
* **GSCPI** (Global Supply Chain Pressure Index) — monthly supply-chain-specific
  pressure index (transport costs + PMI delivery/backlog components).

Score Logic
-----------
Each series is mapped to 0–100 (100 = healthiest), then combined:

    score = WEI_WEIGHT × wei_score + GSCPI_WEIGHT × gscpi_score

WEI uses a fixed scale (robust to COVID outliers). GSCPI is inverted from its
z-score (0 = average pressure; positive = elevated pressure).
"""

from __future__ import annotations

import logging

import pandas as pd

from config import (
    HISTORY_DAYS,
    SUPPLY_CHAIN_GSCPI_WEIGHT,
    SUPPLY_CHAIN_WEI_WEIGHT,
)
from data.gscpi_client import (
    fetch_gscpi_series,
    gscpi_to_score,
    latest_published_gscpi,
)
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series

logger = logging.getLogger(__name__)


def _wei_to_score(wei: float) -> float:
    """Fixed calibration: WEI ≈ +2 healthy, 0 stagnant, -2 contracting."""
    return float(max(0.0, min(100.0, 50.0 + wei * 12.5)))


def _blend_scores(wei_score: float, gscpi_score: float) -> float:
    w_wei = SUPPLY_CHAIN_WEI_WEIGHT
    w_gscpi = SUPPLY_CHAIN_GSCPI_WEIGHT
    total = w_wei + w_gscpi
    if total <= 0:
        return wei_score
    return float(max(0.0, min(100.0, (w_wei * wei_score + w_gscpi * gscpi_score) / total)))


class SupplyChainProvider(BaseProvider):
    """Supply Chain Activity — WEI (weekly) + GSCPI (monthly) blend."""

    category = "supply_chain"
    _WEI_SERIES_ID = "WEI"

    def fetch_current(self) -> tuple[float, dict]:
        wei_raw = fetch_fred_series(self._WEI_SERIES_ID)
        wei_value = float(wei_raw.iloc[-1])
        wei_date = str(wei_raw.index[-1].date())
        wei_score = _wei_to_score(wei_value)

        gscpi_score = 50.0
        gscpi_value = 0.0
        gscpi_date = "unavailable"
        try:
            gscpi_series = fetch_gscpi_series()
            gscpi_value, gscpi_dt = latest_published_gscpi(gscpi_series)
            gscpi_score = gscpi_to_score(gscpi_value)
            gscpi_date = str(gscpi_dt.date())
        except Exception as exc:
            logger.warning("GSCPI fetch failed, using WEI only: %s", exc)
            gscpi_score = wei_score

        score = _blend_scores(wei_score, gscpi_score)

        if wei_value > 3.0:
            wei_condition = "economic activity is surging"
        elif wei_value > 1.5:
            wei_condition = "activity is solid"
        elif wei_value > 0.0:
            wei_condition = "activity is positive but slow"
        elif wei_value > -2.0:
            wei_condition = "activity is contracting slightly"
        else:
            wei_condition = "deep contraction in physical activity"

        if gscpi_value > 1.0:
            gscpi_condition = "supply chain pressures are well above normal"
        elif gscpi_value > 0.25:
            gscpi_condition = "pressures are elevated"
        elif gscpi_value > -0.25:
            gscpi_condition = "pressures are near historical average"
        else:
            gscpi_condition = "pressures are below average (favorable)"

        return score, {
            "source": "NY Fed WEI (FRED) + GSCPI",
            "raw_value": f"WEI {wei_value:+.2f} | GSCPI {gscpi_value:+.2f}",
            "raw_label": "Weekly Activity + Supply Chain Pressure",
            "description": (
                f"WEI at {wei_value:+.2f} ({wei_condition}); "
                f"GSCPI at {gscpi_value:+.2f} ({gscpi_condition}). "
                f"Blended score weights throughput ({int(SUPPLY_CHAIN_WEI_WEIGHT * 100)}%) "
                f"and supply-chain-specific pressure ({int(SUPPLY_CHAIN_GSCPI_WEIGHT * 100)}%)."
            ),
            "calculation": (
                f"Score = {SUPPLY_CHAIN_WEI_WEIGHT:.0%} × (50 + WEI×12.5) + "
                f"{SUPPLY_CHAIN_GSCPI_WEIGHT:.0%} × (50 − GSCPI×25), clipped 0–100."
            ),
            "updated": f"WEI {wei_date}, GSCPI {gscpi_date}",
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        wei_raw = fetch_fred_series(self._WEI_SERIES_ID)
        wei_scores = (50 + wei_raw * 12.5).clip(0.0, 100.0)
        wei_daily = wei_scores.resample("D").interpolate(method="linear")

        try:
            gscpi_raw = fetch_gscpi_series()
            gscpi_scores = gscpi_raw.apply(gscpi_to_score)
            gscpi_daily = gscpi_scores.resample("D").ffill()
        except Exception as exc:
            logger.warning("GSCPI history unavailable: %s", exc)
            gscpi_daily = wei_daily.copy()

        combined = pd.DataFrame({"wei": wei_daily, "gscpi": gscpi_daily}).sort_index()
        combined = combined.ffill().bfill()
        blended = combined["wei"] * SUPPLY_CHAIN_WEI_WEIGHT + combined["gscpi"] * SUPPLY_CHAIN_GSCPI_WEIGHT
        total = SUPPLY_CHAIN_WEI_WEIGHT + SUPPLY_CHAIN_GSCPI_WEIGHT
        if total > 0:
            blended = blended / total
        return blended.clip(0.0, 100.0).tail(days).rename("supply_chain")
