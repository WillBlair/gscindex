"""
Commodities Provider
====================
Uses yfinance to fetch real-time futures prices for key supply chain inputs:
Energy (Oil, Gas) and Metals (Copper).

Rising commodity prices = Higher input costs = Supply Chain Stress.
Falling commodity prices = Lower input costs = Relief (but potential demand signal).

Score Logic
-----------
We compare the current price to its 50-day moving average (MA50).
- Price significantly ABOVE MA50 (>20%) → High Stress (Inflationary) → Low Score
- Price significantly BELOW MA50 (>20%) → Low Demand signal? or Low Cost? 
  For this index, LOW COST is GOOD for the supply chain operator, so we treat 
  lower prices as a higher score (easier to operate).

Source: Yahoo Finance (yfinance)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import HISTORY_DAYS
from data.cache import get_cached, set_cached
from data.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Tickers to track
# CL=F: Crude Oil (WTI)
# NG=F: Natural Gas
# HG=F: Copper (Manufacturing proxy)
_TICKERS = {
    "oil": "CL=F",
    "gas": "NG=F",
    "copper": "HG=F",
}


def _fetch_history_yf(ticker: str, period: str = "1y") -> pd.Series:
    """Fetch historical closing data from yfinance."""
    try:
        data = yf.Ticker(ticker).history(period=period)
        if data.empty:
            return pd.Series(dtype=float)
        return data["Close"]
    except Exception as e:
        logger.error("Failed to fetch %s: %s", ticker, e)
        return pd.Series(dtype=float)


def _score_market_trend(series: pd.Series) -> pd.Series:
    """
    Score based on price relative to 50-day Moving Average (MA50).
    LOWER price (relative to trend) = HIGHER score (Better/Cheaper for supply chain).
    
    Ratio = Price / MA50
    Ratio 1.0 = Price is at average = Score 75 (Normal)
    Ratio 1.2 = Price is +20% (Expensive) = Score 50
    Ratio 0.8 = Price is -20% (Cheap) = Score 100
    """
    ma50 = series.rolling(window=50).mean()
    
    # Avoid division by zero
    if ma50.empty:
        return pd.Series(75.0, index=series.index)

    ratio = series / ma50
    
    # Invert: Higher ratio (expensive) -> Lower score
    # Baseline: Ratio 1.0 -> 75
    # Sensitivity: Each 10% move changes score by 15 points
    scores = 75 - (ratio - 1.0) * 150
    
    return scores.clip(0, 100).fillna(75.0)


class CommoditiesProvider(BaseProvider):
    """Commodities Cost Stress — derived from Oil, Gas, and Copper prices."""

    category = "commodities"

    def fetch_current(self) -> float:
        # We'll use the history fetch to get the latest valid data point
        hist = self.fetch_history(days=5)
        if hist.empty:
            return 75.0
        return float(hist.iloc[-1])

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        cache_key = f"commodities_history_{days}"
        cached = get_cached(cache_key, ttl=3600)  # 1 hour cache
        if cached:
            s = pd.Series(cached["values"])
            s.index = pd.DatetimeIndex(cached["dates"])
            return s

        # Fetch all tickers
        series_list = []
        for name, ticker in _TICKERS.items():
            hist = _fetch_history_yf(ticker, period="2y") # Get enough for MA50
            if not hist.empty:
                score_series = _score_market_trend(hist)
                series_list.append(score_series.rename(name))

        if not series_list:
            # Fallback
            dates = pd.date_range(end=datetime.now(), periods=days, freq="D")
            return pd.Series(75.0, index=dates, name="commodities")

        # Average the scores of all commodities
        df = pd.concat(series_list, axis=1)
        avg_score = df.mean(axis=1).ffill().tail(days)
        
        # Ensure it has a name
        avg_score.name = "commodities"

        set_cached(cache_key, {
            "dates": [d.isoformat() for d in avg_score.index],
            "values": avg_score.tolist()
        })
        
        return avg_score
