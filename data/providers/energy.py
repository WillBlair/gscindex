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


from datetime import datetime
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
            print(f"[EnergyProvider] yfinance failed: {e}, falling back to FRED.")
            raw = fetch_fred_series(self._SERIES_ID)
            price = float(raw.iloc[-1])
            change_str = ""

        # 2. Normalize against FRED History (to keep baseline consistent)
        # We still use the FRED 5-year history to define what is "High" vs "Low"
        fred_hist = fetch_fred_series(self._SERIES_ID)
        min_val = fred_hist.min()
        max_val = fred_hist.max()
        
        # Inverse Normalization: Lower Price = Higher Score
        # 100 at min, 0 at max
        norm_score = 100 * (1 - (price - min_val) / (max_val - min_val))
        score = max(0.0, min(100.0, norm_score))

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
                "We baseline the LIVE price against the 5-year historical range. "
                "Current price is positioned within the 5-year min-max range, "
                "then inverted (Higher Price = Lower Score)."
            ),
            "updated": datetime.now().strftime("%H:%M:%S Live")
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        return scores.tail(days).rename("energy")
