"""
Shipping Financials Provider
============================
Uses yfinance to fetch stock performance of major shipping lines and ETFs.
This serves as a high-frequency PROXY for freight rates and industry health.

Logic:
- Shipping stocks (ZIM, Maersk) correlate with Freight Rates.
- High stock price = High Rates = High Demand (but High Cost for shippers).
- For a Supply Chain Health Index, we view "Healthy" as a balance.
  - Too Low = Recession/Collapse
  - Too High = Capacity Crunch/Inflation
  
  However, usually "Strong Shipping Stocks" = "Moving Goods", so we treat
  uptrends as generally positive (activity is happening), but dampen it 
  if it goes parabolic (cost crisis).

Source: Yahoo Finance (yfinance)
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from config import HISTORY_DAYS
from data.cache import get_cached, set_cached
from data.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Tickers to track
# ZIM: Integrated Shipping (High Beta)
# BOAT: SonicShares Global Shipping ETF
# GSL: Global Ship Lease (Container Leasing)
_TICKERS = {
    "ZIM": "ZIM",
    "ETF": "BOAT",
    "Leasing": "GSL",
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


def _score_shipping_health(series: pd.Series) -> pd.Series:
    """
    Score based on trend (MA50).
    Uptrend = Strong Demand = Good score (up to a point).
    Downtrend = Weak Demand = Low score.
    """
    ma50 = series.rolling(window=50).mean()
    
    if ma50.empty:
        return pd.Series(50.0, index=series.index)

    ratio = series / ma50
    
    # Baseline: Ratio 1.0 (Flat) -> Score 60 (Healthy Neutral)
    # Strong Uptrend: Ratio 1.2 -> Score 80
    # Weak Downtrend: Ratio 0.8 -> Score 40
    scores = 60 + (ratio - 1.0) * 100
    
    return scores.clip(0, 100).fillna(60.0)


class ShippingFinancialsProvider(BaseProvider):
    """Shipping Health — derived from Shipping Industry Stocks/ETFs."""

    category = "shipping_financials"

    def fetch_current(self) -> float:
        hist = self.fetch_history(days=5)
        if hist.empty:
            return 60.0
        return float(hist.iloc[-1])

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        cache_key = f"shipping_fin_history_{days}"
        cached = get_cached(cache_key, ttl=3600)  # 1 hour cache, stocks don't change THAT fast
        if cached:
            s = pd.Series(cached["values"])
            s.index = pd.DatetimeIndex(cached["dates"])
            return s

        series_list = []
        for name, ticker in _TICKERS.items():
            hist = _fetch_history_yf(ticker, period="2y")
            if not hist.empty:
                score_series = _score_shipping_health(hist)
                series_list.append(score_series.rename(name))

        if not series_list:
            dates = pd.date_range(end=datetime.now(), periods=days, freq="D")
            return pd.Series(60.0, index=dates, name="shipping_financials")

        # Average the scores
        df = pd.concat(series_list, axis=1)
        avg_score = df.mean(axis=1).ffill().tail(days)
        
        avg_score.name = "shipping_financials"

        set_cached(cache_key, {
            "dates": [d.isoformat() for d in avg_score.index],
            "values": avg_score.tolist()
        })
        
        return avg_score
