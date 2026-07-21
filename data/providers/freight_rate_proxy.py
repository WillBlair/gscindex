"""
Daily Freight Rate Proxy (BDRY)
================================
GSCPI (the core supply_chain signal) is monthly — it goes weeks between
prints. This module supplies a genuinely DAILY proxy so the supply_chain
category can move between GSCPI releases instead of sitting flat.

Uses BDRY (Breakwave Dry Bulk Shipping ETF), a free/no-key yfinance ticker
that tracks near-term dry bulk freight futures (Capesize/Panamax/Supramax
TCE rates). Dry bulk rates are a real-time read on global shipping demand
and vessel capacity tightness — when rates spike, ships are scarce
relative to cargo, which is a genuine supply-chain-stress signal, not a
cosmetic one.

Score Logic
-----------
Higher freight rates = tighter capacity = more supply chain stress, so
this is scored like the other cost-pressure gauges (energy, tariffs):
inverse percentile within a trailing 2-year window.

    score = 100 * (1 - percentile_rank(latest_price, trailing_2yr_window))

This is a PROXY, not a replacement for GSCPI. See supply_chain.py for how
it's blended into the final category score.
"""

from __future__ import annotations

import logging

import pandas as pd

from config import FRED_SCORE_LOOKBACK_DAYS
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_TICKER = "BDRY"
_CACHE_KEY = "bdry_daily_v1"
_CACHE_TTL = 3600  # 1 hour — daily-close data, no need to hammer yfinance


def _fetch_bdry_history() -> pd.Series:
    """Fetch BDRY daily close history via yfinance, with caching."""
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


def _inverse_percentile_score(series: pd.Series, lookback_days: int | None = None) -> pd.Series:
    """Higher raw value -> lower score (same convention as fred_client.normalize_series_inverse)."""
    if series.empty:
        return series
    days = lookback_days if lookback_days is not None else FRED_SCORE_LOOKBACK_DAYS
    pct = series.rolling(f"{days}D", min_periods=10).rank(pct=True)
    return ((1 - pct) * 100).round(1).clip(0.0, 100.0)


def fetch_freight_rate_score() -> tuple[float, float, str]:
    """Return (score_0_100, latest_price, latest_date_str) for the BDRY daily proxy.

    Raises on failure — caller decides how to fall back (e.g. 100% GSCPI).
    """
    series = _fetch_bdry_history()
    scores = _inverse_percentile_score(series)
    scores = scores.dropna()
    if scores.empty:
        raise ValueError("BDRY score series empty after percentile ranking")

    latest_score = float(scores.iloc[-1])
    latest_price = float(series.iloc[-1])
    latest_date = str(series.index[-1])
    return latest_score, latest_price, latest_date


def fetch_freight_rate_score_history(days: int) -> pd.Series:
    """Return the daily BDRY-derived score series for charting/blending."""
    series = _fetch_bdry_history()
    scores = _inverse_percentile_score(series)
    return scores.dropna().tail(days).rename("freight_rate_proxy")
