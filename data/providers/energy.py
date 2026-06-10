"""
Energy & Fuel Provider
=======================
Scores energy COST PRESSURE on supply chains from the WTI crude oil price
(live CL=F futures, with FRED ``DCOILWTICO`` as history and fallback).

Score Logic
-----------
The score is the inverse percentile of the current price within its
trailing 2-year distribution:
    - Cheapest end of the window  → score near 100 (low cost pressure)
    - Most expensive end          → score near 0   (high cost pressure)

This is explicitly a COST gauge, not a demand gauge: a price collapse
driven by falling demand will read as low cost pressure even though the
demand picture may be bad. Demand-side health is not measured here.
"""

from __future__ import annotations

import logging
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    inverse_percentile_value,
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

        # 2. Score by percentile within the trailing FRED window (2yr default).
        # Note: CL=F is the front-month future and DCOILWTICO is spot; the
        # basis between them is small relative to the scoring window.
        fred_hist = fetch_fred_series(self._SERIES_ID)
        score = inverse_percentile_value(float(price), fred_hist)

        return score, {
            "source": "Live Futures (CL=F)",
            "raw_value": f"${price:.2f}",
            "raw_label": f"WTI Crude Oil{change_str}",
            "description": (
                f"Crude oil is trading at ${price:.2f}/barrel{change_str}. "
                "Real-time pricing from futures markets. This score measures energy "
                "cost pressure on supply chains, not demand-side health."
            ),
            "calculation": (
                "Score = inverse percentile of the live price within the trailing "
                f"{FRED_SCORE_LOOKBACK_DAYS}-day FRED price distribution. "
                "Cheaper than most of the window = high score (low cost pressure)."
            ),
            "updated": datetime.now().strftime("%H:%M:%S Live")
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return scores.tail(days).rename("energy")
