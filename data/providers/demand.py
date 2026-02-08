"""
Demand & Inventory Provider
============================
Uses FRED series ``ISRATIO`` (Total Business Inventory-to-Sales Ratio, monthly)
to assess demand-side supply chain health.

The inventory-to-sales ratio measures how many months of inventory businesses
are holding. Too high = oversupply / weak demand. Too low = stockouts / can't
keep up with demand. The sweet spot is around the historical median.

Score Logic
-----------
Score is based on distance from the 5-year median:
    - At the median → score = 100 (perfect balance)
    - At the 5-year extremes → score approaches 0

Source: https://fred.stlouisfed.org/series/ISRATIO
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series


def _normalize_around_median(series: pd.Series) -> pd.Series:
    """Score based on distance from median — extremes in either direction are bad.

    Parameters
    ----------
    series : pd.Series
        Raw FRED data.

    Returns
    -------
    pd.Series
        Scores in [0, 100].
    """
    median = series.median()
    max_deviation = max(abs(series.max() - median), abs(series.min() - median))
    if max_deviation == 0:
        return pd.Series(100.0, index=series.index)
    deviation = (series - median).abs() / max_deviation
    return ((1 - deviation) * 100).clip(0, 100).round(1)


class DemandProvider(BaseProvider):
    """Demand & Inventory — derived from Inventory-to-Sales Ratio."""

    category = "demand"
    _SERIES_ID = "ISRATIO"

    def fetch_current(self) -> float:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = _normalize_around_median(raw)
        return float(scores.iloc[-1])

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = _normalize_around_median(raw)
        # Monthly data — forward-fill to daily
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("demand")
