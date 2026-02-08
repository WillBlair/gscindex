"""
Shipping Rates Provider
========================
Uses FRED series ``PCU483483`` (Producer Price Index: Water Transportation,
monthly) to score the shipping rates category.

Score Logic
-----------
Instead of normalizing the raw PPI level (which trends upward with inflation),
we measure the YEAR-OVER-YEAR percent change. This isolates the supply chain
signal from the inflation trend:
    - Shipping costs falling YoY     → high score (supply chain improving)
    - Shipping costs stable           → moderate score
    - Shipping costs surging YoY      → low score (supply chain stress)

The YoY change is then inverted-normalized against its own 5-year range.

Source: https://fred.stlouisfed.org/series/PCU483483
"""

from __future__ import annotations

import pandas as pd

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series, normalize_series_inverse


class ShippingProvider(BaseProvider):
    """Shipping Rates — derived from YoY change in PPI: Water Transportation."""

    category = "shipping"
    _SERIES_ID = "PCU483483"

    def _get_yoy_change(self) -> pd.Series:
        """Fetch raw PPI and compute year-over-year percent change.

        Returns
        -------
        pd.Series
            YoY percent change (positive = prices rising = bad for supply chain).
        """
        raw = fetch_fred_series(self._SERIES_ID, lookback_days=365 * 6)
        # Compute YoY change: compare each month to 12 months ago
        yoy = raw.pct_change(periods=12) * 100
        # Drop the first 12 months of NaN values
        return yoy.dropna()

    def fetch_current(self) -> float:
        yoy = self._get_yoy_change()
        # Normalize: high YoY increase → low score, YoY decrease → high score
        scores = normalize_series_inverse(yoy)
        return float(scores.iloc[-1])

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        yoy = self._get_yoy_change()
        scores = normalize_series_inverse(yoy)
        # Monthly data — forward-fill to daily for the dashboard charts
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("shipping")
