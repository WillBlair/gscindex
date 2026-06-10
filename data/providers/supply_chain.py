"""
Supply Chain Pressure Provider
================================
Scores the supply chain category from the NY Fed **GSCPI** (Global Supply
Chain Pressure Index): a monthly z-score built from transport costs and
PMI delivery-time/backlog components. 0 = average pressure, positive =
elevated pressure.

    score = 50 - GSCPI * 25, clipped to 0-100

The NY Fed **WEI** (Weekly Economic Index) is fetched for context only and
shown in the metadata. It does NOT contribute to the score: WEI is a
GDP-growth nowcast, and high growth historically coincides with supply
chain STRESS (2021: WEI ~+7 while GSCPI hit its all-time peak), so it has
no defensible sign in a linear health blend.
"""

from __future__ import annotations

import logging

import pandas as pd

from config import HISTORY_DAYS
from data.gscpi_client import (
    fetch_gscpi_series,
    gscpi_to_score,
    latest_published_gscpi,
)
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series

logger = logging.getLogger(__name__)


class SupplyChainProvider(BaseProvider):
    """Supply Chain Pressure — NY Fed GSCPI (monthly)."""

    category = "supply_chain"
    _WEI_SERIES_ID = "WEI"

    def fetch_current(self) -> tuple[float, dict]:
        # GSCPI is the score. If it fails, the provider fails and the
        # aggregator flags the category as a fallback — no silent stand-in.
        gscpi_series = fetch_gscpi_series()
        gscpi_value, gscpi_dt = latest_published_gscpi(gscpi_series)
        score = gscpi_to_score(gscpi_value)
        gscpi_date = str(gscpi_dt.date())

        if gscpi_value > 1.0:
            gscpi_condition = "supply chain pressures are well above normal"
        elif gscpi_value > 0.25:
            gscpi_condition = "pressures are elevated"
        elif gscpi_value > -0.25:
            gscpi_condition = "pressures are near historical average"
        else:
            gscpi_condition = "pressures are below average (favorable)"

        # WEI: context only, never part of the score.
        wei_context = ""
        raw_value = f"GSCPI {gscpi_value:+.2f}"
        try:
            wei_raw = fetch_fred_series(self._WEI_SERIES_ID)
            wei_value = float(wei_raw.iloc[-1])
            wei_context = (
                f" For context, the Weekly Economic Index is at {wei_value:+.2f} "
                "(macro activity, not scored)."
            )
            raw_value = f"GSCPI {gscpi_value:+.2f} | WEI {wei_value:+.2f} (context)"
        except Exception as exc:
            logger.warning("WEI context fetch failed (score unaffected): %s", exc)

        return score, {
            "source": "NY Fed GSCPI",
            "raw_value": raw_value,
            "raw_label": "Global Supply Chain Pressure",
            "description": (
                f"GSCPI at {gscpi_value:+.2f} standard deviations from its historical "
                f"average: {gscpi_condition}.{wei_context}"
            ),
            "calculation": (
                "Score = 50 - GSCPI × 25, clipped 0-100. GSCPI is a z-score "
                "(0 = average pressure), so 50 = normal, 0 = pressure at +2 sigma, "
                "100 = pressure at -2 sigma. Updated monthly by the NY Fed."
            ),
            "updated": f"GSCPI {gscpi_date}",
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        gscpi_raw = fetch_gscpi_series()
        scores = gscpi_raw.apply(gscpi_to_score)
        return scores.resample("D").ffill().tail(days).rename("supply_chain")
