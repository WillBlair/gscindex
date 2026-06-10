"""
Trade & Tariffs Provider
=========================
Uses FRED series ``EPUTRADE`` (Economic Policy Uncertainty: Categorical
Index, Trade Policy) as the trade and tariff disruption signal. Unlike
the general EPU index (which spikes on fiscal, monetary, and electoral
news), this categorical index counts only trade-policy coverage.

Score Logic
-----------
Higher trade policy uncertainty = worse for supply chains. Score is the
inverse percentile of the latest value within a trailing 2-year window:
    - Calm end of the window      → score near 100
    - Most uncertain end          → score near 0

The series is monthly, so this category moves slowly by design.

Source: https://fred.stlouisfed.org/series/EPUTRADE
Based on: Baker, Bloom, and Davis categorical EPU data
"""

from __future__ import annotations

import pandas as pd

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    normalize_series_inverse,
)


class TariffsProvider(BaseProvider):
    """Trade & Tariffs — derived from the Trade Policy Uncertainty categorical index."""

    category = "tariffs"
    _SERIES_ID = "EPUTRADE"

    def fetch_current(self) -> tuple[float, dict]:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        score = float(scores.iloc[-1])
        val = float(raw.iloc[-1])

        return score, {
            "source": "FRED Series EPUTRADE",
            "raw_value": f"{val:.1f}",
            "raw_label": "Trade Policy Uncertainty",
            "description": (
                f"Trade Policy Uncertainty (categorical EPU) is at {val:.1f}. "
                "This index counts newspaper coverage of trade policy uncertainty "
                "specifically — tariffs, trade wars, import/export policy — rather "
                "than general economic policy noise. Updated monthly."
            ),
            "calculation": (
                "Score = inverse percentile of the latest value within the trailing "
                f"{FRED_SCORE_LOOKBACK_DAYS}-day range. Higher trade policy "
                "uncertainty = lower score."
            ),
            "updated": str(raw.index[-1].date())
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return scores.resample("D").ffill().tail(days).rename("tariffs")
