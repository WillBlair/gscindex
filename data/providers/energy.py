"""
Energy & Fuel Provider
=======================
Uses FRED series ``DCOILWTICO`` (WTI Crude Oil Price, daily) to score
the energy category.

Score Logic
-----------
Lower oil prices = healthier supply chain. The raw price is normalized
against its trailing 2-year historical range:
    - At the 2-year LOW  → score = 100 (cheapest energy in that window)
    - At the 2-year HIGH → score = 0   (most expensive in that window)
"""

from __future__ import annotations

import logging
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from config import FRED_SCORE_LOOKBACK_DAYS
from data.providers.fred_client import (
    fetch_fred_series,
    inverse_normalize_value,
    normalization_bounds,
    normalize_series_inverse,
)


class EnergyProvider(BaseProvider):
    """Energy & Fuel — derived from WTI crude oil price."""

    category = "energy"
    _SERIES_ID = "DCOILWTICO"

    def fetch_current(self) -> tuple[float, dict]:
        import yfinance as yf
        
        # 1. Fetch Live Data from Yahoo Finance
        ticker = yf.Ticker("CL=F")
        try:
            # Try to get the absolute latest real-time price
            price = ticker.fast_info.get("last_price")
            if not price:
                # Fallback to recent history if market is closed/fast_info empty
                hist = ticker.history(period="1d")
                price = float(hist["Close"].iloc[-1])
            
            # Get previous close for "Change" calculation
            prev_close = ticker.fast_info.get("previous_close")
            change_str = ""
            if prev_close:
                pct_change = ((price - prev_close) / prev_close) * 100
                change_str = f" ({pct_change:+.2f}%)"

        except Exception as e:
            # Fallback to FRED if Yahoo fails
            logger.warning("yfinance failed, falling back to FRED: %s", e)
            raw = fetch_fred_series(self._SERIES_ID)
            price = float(raw.iloc[-1])
            change_str = ""

        # 2. Normalize against trailing FRED window (2yr default, not full 5yr)
        fred_hist = fetch_fred_series(self._SERIES_ID)
        min_val, max_val = normalization_bounds(fred_hist)
        score = inverse_normalize_value(float(price), min_val, max_val)

        return score, {
            "source": "Live Futures (CL=F)",
            "raw_value": f"${price:.2f}",
            "raw_label": f"WTI Crude Oil{change_str}",
            "description": (
                f"Crude oil is trading at ${price:.2f}/barrel{change_str}. "
                "Real-time pricing from futures markets."
            ),
            "calculation": (
                "Score = 100 - (Normalized Price). "
                f"We baseline the LIVE price against the trailing {FRED_SCORE_LOOKBACK_DAYS}-day "
                "FRED range, then invert (higher price = lower score)."
            ),
            "updated": datetime.now().strftime("%H:%M:%S Live")
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return scores.tail(days).rename("energy")
