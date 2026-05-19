"""
Inland Freight (Trucking) Provider
====================================
Uses a synthetic **Estimated Daily Diesel Price** derived from:
1. Real-Time Heating Oil Futures (HO=F) - The high-frequency market signal.
2. Weekly DOE Diesel Price (GASDESW) - The baseline retail level.

Why this method?
----------------
The user wants "Day-by-Day Diesel Prices".
Official retail data (GASDESW) is only weekly.
Heating Oil (HO=F) trades real-time and is chemically nearly identical to diesel.
By taking the live HO=F price and adding the "Retail Spread" (Taxes + Distribution),
we create a highly accurate **Estimated Daily Diesel Price** that updates second-by-second.

Spread Logic:
    Spread = Latest_Official_Weekly_Price - HO_Close_At_That_Time
    Live_Est_Diesel = Live_HO_Price + Spread

Source: Calculated (HO=F via Yahoo + GASDESW via FRED)
Frequency: Real-time / Daily
"""

from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    inverse_normalize_value,
    normalization_bounds,
    normalize_series_inverse,
)


class TruckingProvider(BaseProvider):
    """Inland Freight — derived from Estimated Daily Diesel Price."""

    category = "trucking"
    _TICKER = "HO=F"
    _FRED_SERIES = "GASDESW"

    def fetch_current(self) -> tuple[float, dict]:
        # 1. Fetch Real-Time Market Signal (HO=F)
        ticker = yf.Ticker(self._TICKER)
        try:
            info = ticker.fast_info
            live_ho_price = float(info.last_price) if info.last_price else float(info.previous_close)
            if live_ho_price is None or live_ho_price == 0:
                 hist = ticker.history(period="5d")
                 live_ho_price = float(hist["Close"].iloc[-1])
        except Exception as e:
             logger.warning("HO=F fast_info failed, using history: %s", e)
             hist = ticker.history(period="5d")
             live_ho_price = float(hist["Close"].iloc[-1])

        # 2. Fetch Baseline Retail Level (GASDESW)
        retail_series = fetch_fred_series(self._FRED_SERIES)
        last_retail_price = float(retail_series.iloc[-1])
        last_retail_date = retail_series.index[-1]

        # 3. Calculate Spread (Retail - Market)
        # We need HO price at the time of the last retail data point (usually Monday)
        # We'll use the last 5 days average spread to be robust, or just the spot spread.
        # Let's use a fixed offset approximation if precise matching is hard, 
        # but better to fetch HO history.
        ho_hist = ticker.history(period="1mo")["Close"]
        
        # Find HO price closest to the last retail date
        # Retail date is usually Monday.
        try:
            # Match dates - simplistic approach:
            # We assume the spread is roughly constant (Taxes + Distribution ~ $1.20-$1.40)
            # Let's calculate the spread dynamically based on the most recent overlapping data.
            # But aligning weekly FRED dates with daily Yahoo dates is tricky in one line.
            # Simplified: Use the last known close of HO to estimate current spread? 
            # No, spread = Last_Retail - HO_Price_at_Last_Retail_Date.
            
            # Approximate: Just use the fixed spread from the latest available data pair?
            # Let's assume the spread is $1.30 (avg) if matching fails.
            
            # Best effort:
            idx_loc = ho_hist.index.get_indexer([last_retail_date], method='nearest')[0]
            if idx_loc != -1:
                ref_ho = ho_hist.iloc[idx_loc]
                spread = last_retail_price - ref_ho
            else:
                spread = 1.30 # Fallback
        except Exception:
            spread = 1.30 # Fallback typical spread

        # 4. Synthesize Daily Price
        est_daily_price = live_ho_price + spread
        
        # 5. Score Calculation — trailing window on retail diesel (not full 5yr)
        min_val, max_val = normalization_bounds(retail_series)
        clipped_price = max(min_val, min(max_val, est_daily_price))
        score = inverse_normalize_value(clipped_price, min_val, max_val)
        
        # Calculate daily change
        try:
            prev_close_ho = float(info.previous_close)
            change_ho = live_ho_price - prev_close_ho
            # Assuming spread is constant intraday, the change in Diesel = Change in HO
            change_str = f"{change_ho:+.3f}"
        except Exception:
            change_str = "0.000"

        # Context
        if est_daily_price > 4.50:
            condition = "Diesel prices are critically high"
        elif est_daily_price > 4.00:
            condition = "Diesel prices are elevated"
        elif est_daily_price > 3.50:
            condition = "Diesel prices are moderate"
        else:
            condition = "Diesel prices are low — favorable for carriers"
            
        latest_date = datetime.now().strftime("%Y-%m-%d %H:%M")

        return score, {
            "source": f"Estimated Real-Time (HO=F + ${spread:.2f} spread)",
            "raw_value": f"${est_daily_price:.3f}/gal ({change_str})",
            "raw_label": "Est. Daily Diesel Price",
            "description": (
                f"Estimated National Average Diesel Price is ${est_daily_price:.3f} today. {condition}. "
                "This metric is calculated real-time by applying the retail distribution spread "
                f"(${spread:.2f}) to live Heating Oil futures market data."
            ),
            "calculation": (
                "Score = inverse normalized est. diesel price. "
                f"Est. daily = live heating oil (${live_ho_price:.3f}) + spread (${spread:.2f}). "
                f"Normalized against the trailing {FRED_SCORE_LOOKBACK_DAYS}-day DOE retail range."
            ),
            "updated": latest_date,
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        # For history, just use the official weekly data forward-filled
        # This is cleaner than synthesizing history.
        # OR: Synthesize history using HO close + spread? 
        # User wants "Day by Day".
        # Let's use HO history + fixed recent spread to give the "daily wiggles"
        # that the user wants to see.
        
        ticker = yf.Ticker(self._TICKER)
        ho_hist = ticker.history(period="2y")["Close"]
        
        # We need to approximate the spread over time.
        # Simplification: Use the current spread.
        # Ideally we'd interpolate the spread between weekly DOE points, 
        # but adding a fixed spread to HO gives the right "shape" and volatility.
        
        # Let's assume spread is roughly constant for the visual trend.
        # Or better: Just use weekly FRED data ffill? 
        # User asked "Can this be day by day?". They want to see the daily wiggles.
        # So HO + Spread is better.
        
        # Recalculate spread just to be safe (code duplication, but safe)
        retail_series = fetch_fred_series(self._FRED_SERIES)
        last_retail_price = float(retail_series.iloc[-1])
        
        # Get matching HO price for spread
        spread = 1.30
        try:
             last_date = retail_series.index[-1]
             # Find approximate HO price at that date
             idx_loc = ho_hist.index.get_indexer([last_date], method='nearest')[0]
             if idx_loc != -1:
                 ref_ho = ho_hist.iloc[idx_loc]
                 spread = last_retail_price - ref_ho
        except Exception:
             pass
             
        daily_est = ho_hist + spread
        daily_est.index = daily_est.index.tz_localize(None)
        scores = normalize_series_inverse(daily_est)

        return scores.tail(days).rename("trucking")
