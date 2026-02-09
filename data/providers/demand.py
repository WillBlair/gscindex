"""
Industrial Demand Stress Provider
==================================
Uses Live Copper Prices (HG=F) and Volatility to measure upstream industrial demand pressure.

Copper is "Dr. Copper" — the leading indicator of global economic health.
High copper prices usually signal strong manufacturing demand.

Score Logic
-----------
We calculate an "Industrial Demand Stress Index" (0-100).
A LOW score means HIGH stress (prices are high/volatile).

Formula:
    Score = 100 - (Price_Factor * 60) - (Volatility_Factor * 40)

    1. Price_Factor (0.0 - 1.0):
       - Measures how expensive input materials are.
       - Normalized against 5-year range.
       - High Price = High Factor.

    2. Volatility_Factor (0.0 - 1.0):
       - Measures how unstable the price is (uncertainty).
       - Based on 30-day annualized volatility.
       - High Volatility (>30%) = High Factor.

Interpretation:
    - High Demand + Stable Prices (Score ~40): "Elevated Risk" (Input costs are high, but predictable).
    - High Demand + Volatile Prices (Score ~0): "Critical" (High costs + uncertainty).
    - Low Demand (Score ~100): "Healthy" (Low input costs, easy availability).

Source: Yahoo Finance (HG=F)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series


class DemandProvider(BaseProvider):
    """Industrial Demand Stress — derived from Copper Price & Volatility."""

    category = "demand"
    _SERIES_ID = "ISRATIO" # Kept for legacy history if needed, but not used for current.

    def fetch_current(self) -> tuple[float, dict]:
        # -------------------------------------------------------------------
        # STRATEGY: Industrial Demand Stress Index
        # -------------------------------------------------------------------
        # Inputs:
        # 1. Copper Price (HG=F) - Real-time
        # 2. Copper Volatility (30-day std dev)
        #
        # Formula: Score = 100 - (Price * 60%) - (Vol * 40%)
        # -------------------------------------------------------------------
        
        try:
            ticker = yf.Ticker("HG=F")
            
            # --- 1. Fetch Price & History ---
            # We need history for both Range (5y) and Volatility (30d)
            hist = ticker.history(period="5y")
            
            if hist.empty:
                raise ValueError("No copper data available")
                
            current_price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            
            # --- 2. Calculate Volatility (30-day Annualized) ---
            # Log returns
            hist["Log_Ret"] = np.log(hist["Close"] / hist["Close"].shift(1))
            # 30-day rolling std dev, annualized (assuming 252 trading days)
            vol_30d = hist["Log_Ret"].tail(30).std() * np.sqrt(252) * 100
            
            # --- 3. Normalization Factors ---
            
            # A. Price Factor (Range-based)
            # Min/Max from last 5 years
            min_price = float(hist["Close"].min())
            # Add 50% buffer to max to allow for "high but not crisis" scoring
            max_price = float(hist["Close"].max()) * 1.50
            
            print(f"DEBUG: Demand - Price {current_price:.2f} | Range {min_price:.2f}-{max_price:.2f} | Vol {vol_30d:.1f}%")

            # Normalize Current Price (0.0 to 1.0)
            if max_price > min_price:
                price_factor = (current_price - min_price) / (max_price - min_price)
            else:
                price_factor = 0.5
            price_factor = max(0.0, min(1.0, price_factor))
            
            # B. Volatility Factor (Threshold-based)
            # Normal Volatility for Copper is ~15-20%. Crisis is >30%.
            # Map 20% (Stable) to 50% (Chaos) -> 0.0 to 1.0
            min_vol = 20.0
            max_vol = 50.0
            vol_factor = (vol_30d - min_vol) / (max_vol - min_vol)
            vol_factor = max(0.0, min(1.0, vol_factor))
            
            # --- 4. Composite Scoring ---
            # Score = 100 - (Price Impact) - (Volatility Impact)
            # 60% Weight to Price, 40% Weight to Volatility
            
            price_penalty = price_factor * 60.0
            vol_penalty = vol_factor * 40.0
            
            final_score = 100.0 - price_penalty - vol_penalty
            final_score = round(max(0.0, min(100.0, final_score)), 1)
            
            # --- 5. Formatting ---
            change_pct = ((current_price - prev_close) / prev_close) * 100
            change_str = f"({change_pct:+.2f}%)"
            
            return final_score, {
                "source": "Live Futures (HG=F)",
                "raw_value": f"${current_price:.2f}/lb",
                "raw_label": f"Copper Price {change_str}",
                "description": (
                    f"Copper is trading at ${current_price:.2f}/lb with {vol_30d:.1f}% annualized volatility. "
                    "Elevated copper prices indicate strong global industrial demand relative to available supply, "
                    "increasing upstream input costs."
                ),
                "calculation": (
                    f"Score = 100 - (PriceFactor {price_factor:.2f} × 60) - (VolFactor {vol_factor:.2f} × 40). "
                    "Reflects demand-side pressure; does not account for speculative pricing or short-term supply disruptions."
                ),
                "updated": datetime.now().strftime("%H:%M UTC")
            }
            
        except Exception as e:
            print(f"Demand Index Error: {e}")
            return 50.0, {
                "source": "System Error",
                "description": "Live copper data unavailable.",
                "raw_label": "Error"
            }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        # For history, we can still use the FRED inventory ratio as a 
        # long-term structural baseline, OR we could try to fetch Copper history.
        # Let's stick to FRED for the *chart* because it's smoother and 
        # represents "Inventory Health" over time, while the *Score* is 
        # the "Live Demand Stress".
        
        # Actually, to avoid confusion, let's use the FRED series but 
        # maybe inverted/scaled to match the "Stress" concept?
        # Implementing simple ISRATIO fetch for now.
        
        raw = fetch_fred_series(self._SERIES_ID)
        # Normalize: Median = 100. Deviation = lower score.
        median = raw.median()
        deviation = (raw - median).abs()
        max_dev = deviation.max()
        scores = ((1 - (deviation / max_dev)) * 100).clip(0, 100)
        
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("demand")
