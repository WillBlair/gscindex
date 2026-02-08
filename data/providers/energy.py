"""
Energy & Fuel Provider
=======================
Uses FRED series ``DCOILWTICO`` (WTI Crude Oil Price, daily) to score
the energy category.

Score Logic
-----------
Lower oil prices = healthier supply chain. The raw price is normalized
against its 5-year historical range:
    - At the 5-year LOW  → score = 100 (cheapest energy in 5 years)
    - At the 5-year HIGH → score = 0   (most expensive in 5 years)
"""

from __future__ import annotations

import pandas as pd

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    normalize_series_inverse,
)


class EnergyProvider(BaseProvider):
    """Energy & Fuel — derived from WTI crude oil price."""

    category = "energy"
    _SERIES_ID = "DCOILWTICO"

    def fetch_current(self) -> float:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return float(scores.iloc[-1])

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return scores.tail(days).rename("energy")
