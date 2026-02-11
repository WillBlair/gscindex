"""
Supply Chain Pressure Provider
================================
Uses the NY Fed Weekly Economic Index (FRED: ``WEI``) as a high-frequency
measure of real economic activity and supply chain throughput.

The WEI is a composite of 10 daily and weekly indicators, including:
    - Railroad traffic (AAR)
    - Staffing index (ASA)
    - Fuel sales (Booth Financial)
    - Steel production (AISI)
    - Electricity output (EEI)

Unlike monthly indices (like PMI or TSI), the WEI provides a real-time
signal of the physical economy. A rising WEI indicates expanding economic
activity, implying robust supply chain volume.

Score Logic
-----------
Higher WEI = More activity = Healthier flow of goods (Higher Score).
Lower WEI = Contracting activity = Supply chain slowdown (Lower Score).

The raw index is normalized directly against its 5-year historical range.

Source: https://fred.stlouisfed.org/series/WEI
Published by: Federal Reserve Bank of New York based on data from multiple sources.
Frequency: Weekly (Thursdays/Saturdays)
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series, normalize_series_direct


class SupplyChainProvider(BaseProvider):
    """Supply Chain Activity — derived from NY Fed Weekly Economic Index (WEI)."""

    category = "supply_chain"
    _SERIES_ID = "WEI"

    def fetch_current(self) -> tuple[float, dict]:
        raw = fetch_fred_series(self._SERIES_ID)
        latest_value = float(raw.iloc[-1])
        latest_date = str(raw.index[-1].date())

        # Calibrated scoring: WEI is scaled to GDP growth.
        # Normal range is roughly -2.0 to +4.0.
        # Outliers in 2020/2021 skewed min/max normalization (-11 to +12).
        # We use a fixed scale to ensure recent data is scored meaningfully:
        #   WEI = 4.0  -> Score 100
        #   WEI = 2.0  -> Score 75
        #   WEI = 0.0  -> Score 50 (Stagnation)
        #   WEI = -2.0 -> Score 25 (Contraction)
        #   WEI = -4.0 -> Score 0
        
        # Formula: Score = 50 + (WEI * 12.5)
        score = 50 + (latest_value * 12.5)
        score = max(0.0, min(100.0, score))

        # Context
        if latest_value > 3.0:
            condition = "Economic activity is surging — high supply chain throughput"
        elif latest_value > 1.5:
            condition = "Economic activity is solid — healthy flow of goods"
        elif latest_value > 0.0:
            condition = "Economic activity is strictly positive but slow"
        elif latest_value > -2.0:
            condition = "Economic activity is contracting slightly"
        else:
            condition = "Deep contraction in physical economic activity"

        return score, {
            "source": "NY Fed via FRED (WEI - Weekly)",
            "raw_value": f"{latest_value:+.2f}",
            "raw_label": "Weekly Economic Index",
            "description": (
                f"The Weekly Economic Index is at {latest_value:+.2f}. {condition}. "
                "The WEI aggregates 10 high-frequency indicators including rail traffic, "
                "fuel sales, and steel production to measure real-time supply chain velocity."
            ),
            "calculation": (
                "Score = 50 + (WEI * 12.5). "
                "We use a fixed scale where WEI > 2.0 is Healthy (75+) and "
                "WEI < 0 is Slow (50-). Outliers from 2020-2021 are clipped."
            ),
            "updated": latest_date,
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        # Apply the same fixed scaling to history
        scores = 50 + (raw * 12.5)
        scores = scores.clip(lower=0.0, upper=100.0)
        
        # Weekly data — forward-fill to daily for smooth charts
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("supply_chain")
