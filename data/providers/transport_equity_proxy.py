"""
Daily Freight/Transportation Sector Proxy (IYT)
=================================================
The Freight Flow category (freight.py) is scored from the BTS Freight
Transportation Services Index (FRED TSIFRGHT), which is monthly with a
1-2 month publication lag. That's the longest lag of any category in the
dashboard, so freight can sit flat for 8-12 weeks between usable prints.

Uses IYT (iShares U.S. Transportation ETF), a free/no-key yfinance
ticker tracking an index of US transportation-sector equities (rail,
trucking, airlines, freight/delivery, marine). Equity prices are a
forward-looking market read on transportation-sector health: they move
daily on freight demand expectations, fuel costs, capacity, and
earnings — well before BTS's throughput data is published.

Score Logic
-----------
Unlike the cost-pressure gauges (energy, tariffs) where higher raw value
is worse, a stronger transportation-sector price level reflects a
healthier/more in-demand freight network (more like the freight.py YoY
logic: growth reads healthy). So this uses a DIRECT (not inverse)
percentile rank:

    score = 100 * percentile_rank(latest_price, trailing_2yr_window)

This is a PROXY, not a replacement for TSIFRGHT. See freight.py for how
it's blended into the final category score.
"""

from __future__ import annotations

import logging

import pandas as pd

from config import FRED_SCORE_LOOKBACK_DAYS
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_TICKER = "IYT"
_CACHE_KEY = "iyt_daily_v1"
_CACHE_TTL = 3600  # 1 hour — daily-close data, no need to hammer yfinance


def _fetch_iyt_history() -> pd.Series:
    """Fetch IYT daily close history via yfinance, with caching."""
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached is not None:
        s = pd.Series(cached["values"], name=_TICKER)
        s.index = pd.DatetimeIndex(cached["dates"])
        return s

    import yfinance as yf

    hist = yf.Ticker(_TICKER).history(period="2y")
    if hist.empty:
        raise ValueError(f"yfinance returned no data for {_TICKER}")

    closes = hist["Close"].astype(float)
    closes.index = pd.DatetimeIndex(closes.index.date)
    closes = closes.sort_index()

    set_cached(
        _CACHE_KEY,
        {
            "dates": [d.strftime("%Y-%m-%d") for d in closes.index],
            "values": closes.tolist(),
        },
    )
    return closes.rename(_TICKER)


def _direct_percentile_score(series: pd.Series, lookback_days: int | None = None) -> pd.Series:
    """Higher raw value -> higher score (growth/strength reads healthy)."""
    if series.empty:
        return series
    days = lookback_days if lookback_days is not None else FRED_SCORE_LOOKBACK_DAYS
    pct = series.rolling(f"{days}D", min_periods=10).rank(pct=True)
    return (pct * 100).round(1).clip(0.0, 100.0)


def fetch_transport_equity_score() -> tuple[float, float, str]:
    """Return (score_0_100, latest_price, latest_date_str) for the IYT daily
    proxy. Raises on failure — caller decides how to fall back (e.g. 100%
    TSIFRGHT).
    """
    series = _fetch_iyt_history()
    scores = _direct_percentile_score(series)
    scores = scores.dropna()
    if scores.empty:
        raise ValueError("IYT score series empty after percentile ranking")

    latest_score = float(scores.iloc[-1])
    latest_price = float(series.iloc[-1])
    latest_date = str(series.index[-1])
    return latest_score, latest_price, latest_date


def fetch_transport_equity_score_history(days: int) -> pd.Series:
    """Return the daily IYT-derived score series for charting/blending."""
    series = _fetch_iyt_history()
    scores = _direct_percentile_score(series)
    return scores.dropna().tail(days).rename("transport_equity_proxy")
