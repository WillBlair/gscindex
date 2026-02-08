"""
Port Congestion Provider
=========================
Uses FRED series ``TSIFRGHT`` (Transportation Services Index: Freight, monthly)
as a proxy for port and freight throughput.

The TSI Freight index measures the volume of freight carried by for-hire
transportation companies. When freight volume drops, it often signals
congestion, capacity issues, or demand shocks.

Score Logic
-----------
Higher freight volume = supply chain is flowing = healthy. Direct normalization:
    - At the 5-year HIGH → score = 100 (freight moving freely)
    - At the 5-year LOW  → score = 0   (freight stalled)

Note: This is a proxy. For real port congestion data, you'd need a
paid API like MarineTraffic, VesselFinder, or project44.

Source: https://fred.stlouisfed.org/series/TSIFRGHT
"""

from __future__ import annotations

import pandas as pd

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    normalize_series_direct,
)


class PortsProvider(BaseProvider):
    """Port Congestion — derived from TSI Freight Index."""

    category = "ports"
    _SERIES_ID = "TSIFRGHT"

    def fetch_current(self) -> float:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_direct(raw)
        return float(scores.iloc[-1])

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_direct(raw)
        # TSI is monthly — forward-fill to daily for dashboard charts
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("ports")
