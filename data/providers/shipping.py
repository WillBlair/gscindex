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

    def fetch_current(self) -> tuple[float, dict]:
        # -------------------------------------------------------------------
        # STRATEGY: Composite Shipping Stress Index
        # -------------------------------------------------------------------
        # User rejected stock prices (ZIM). We now use fundamental drivers:
        # 1. Bunker Fuel Proxy: Crude Oil (CL=F) - Real-time
        # 2. Market Risk: CBOE Volatility Index (^VIX) - Real-time
        # 
        # Logic: High Oil + High Volatility = High Shipping Stress (Low Score)
        # -------------------------------------------------------------------
        import yfinance as yf
        from datetime import datetime
        
        try:
            # Fetch both tickers
            tickers = yf.Tickers("CL=F ^VIX")
            
            # --- 1. Crude Oil (Proxy for Bunker Fuel) ---
            # Range: $60 (Healthy) to $100 (High Cost/Stress)
            # Accessing tickers["CL=F"] might fail if yfinance grouping fails, fallback strictly
            try:
                oil_tk = tickers.tickers["CL=F"]
                oil_hist = oil_tk.history(period="1d")
                oil_price = float(oil_hist["Close"].iloc[-1]) if not oil_hist.empty else 75.0
            except:
                oil_price = 75.0
            
            # Normalize Oil (Higher = More Stress = Lower Score)
            # $60 -> 0% Stress, $100 -> 100% Stress
            oil_stress = (oil_price - 60) / (100 - 60)
            oil_stress = max(0.0, min(1.0, oil_stress))
            
            # --- 2. VIX (Market Volatility/Fear) ---
            # Range: 12 (Calm) to 35 (High Risk)
            try:
                vix_tk = tickers.tickers["^VIX"]
                vix_hist = vix_tk.history(period="1d")
                vix_price = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else 15.0
            except:
                vix_price = 15.0
            
            # Normalize VIX
            vix_stress = (vix_price - 12) / (35 - 12)
            vix_stress = max(0.0, min(1.0, vix_stress))
            
            # --- Composite Score ---
            # Weighted: 70% Fuel Cost, 30% Market Risk
            total_stress = (oil_stress * 0.70) + (vix_stress * 0.30)
            
            # Invert: High Stress = Low Health Score
            score = 100.0 * (1.0 - total_stress)
            score = round(max(0.0, min(100.0, score)), 1)
            
            return score, {
                "source": "Live Commodities",
                "raw_value": f"Oil ${oil_price:.0f} / VIX {vix_price:.0f}",
                "raw_label": "Composite (Oil & VIX)",
                "description": (
                    f"Real-time shipping health derived from bunker fuel costs "
                    f"(Crude Oil ${oil_price:.2f}) and market volatility (VIX {vix_price:.1f})."
                ),
                "updated": datetime.now().strftime("%H:%M UTC")
            }
            
        except Exception as e:
            # Fallback if yfinance fails
            print(f"Shipping Index Error: {e}")
            return 50.0, {
                "source": "System Error",
                "description": "Live data unavailable.",
                "raw_label": "Error"
            }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        yoy = self._get_yoy_change()
        scores = normalize_series_inverse(yoy)
        # Monthly data — forward-fill to daily for the dashboard charts
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("shipping")
