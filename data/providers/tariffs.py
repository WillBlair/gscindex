"""
Trade & Tariffs Provider
=========================
Uses FRED series ``USEPUINDXD`` (US Economic Policy Uncertainty Index, daily)
as a proxy for trade and tariff disruption risk.

Score Logic
-----------
Higher policy uncertainty = worse for supply chains. Inverted normalization:
    - At the 5-year LOW  → score = 100 (stable policy environment)
    - At the 5-year HIGH → score = 0   (maximum uncertainty)

Source: https://fred.stlouisfed.org/series/USEPUINDXD
Based on: Baker, Bloom, and Davis Economic Policy Uncertainty Index
"""

from __future__ import annotations

import pandas as pd

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    normalize_series_inverse,
)


class TariffsProvider(BaseProvider):
    """Trade & Tariffs — derived from Economic Policy Uncertainty Index."""

    category = "tariffs"
    _SERIES_ID = "USEPUINDXD"

    def fetch_current(self) -> tuple[float, dict]:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        score = float(scores.iloc[-1])
        val = float(raw.iloc[-1])

        return score, {
            "source": "FRED Series USEPUINDXD",
            "raw_value": f"{val:.1f}",
            "raw_label": "Policy Uncertainty Index",
            "description": (
                f"Economic Policy Uncertainty Index is at {val:.1f}. "
                "Higher uncertainty often correlates with tariff volatility and trade barriers."
            ),
            "calculation": (
                "Score = 100 - (Normalized Uncertainty). "
                "We track the Economic Policy Uncertainty Index. "
                "We normalize the current value against its 5-year range. "
                "Higher uncertainty = Lower Supply Chain Health Score."
            ),
            "updated": str(raw.index[-1].date())
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return scores.tail(days).rename("tariffs")
