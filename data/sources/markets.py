"""Guarded Yahoo Finance helpers: latest close, close on a date, and live scaling.

Official series (FRED, EIA) lag by days; ``scale_live`` carries the latest official
value forward by the Yahoo price move since the official date. Any doubt about the
Yahoo data (stale quote, missing close, a ratio that looks like a unit change, a
yfinance error) falls back to the official value.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta

from config import LIVE_SCALE_RATIO_BOUNDS

logger = logging.getLogger(__name__)

CLOSE_LOOKBACK_DAYS = 5          # close_on looks back at most this far


def _ticker(symbol: str):
    import yfinance as yf

    return yf.Ticker(symbol)


def last_quote(symbol: str) -> tuple[date, float]:
    """Latest daily close and its date (yfinance ``history(period="10d")``)."""
    closes = _ticker(symbol).history(period="10d")["Close"].dropna()
    if closes.empty:
        raise ValueError(f"yfinance returned no data for {symbol}")
    return closes.index[-1].date(), float(closes.iloc[-1])


def close_on(symbol: str, day: date) -> float | None:
    """Close on or before ``day``, looking back up to 5 days; None if there is none."""
    frame = _ticker(symbol).history(
        start=(day - timedelta(days=CLOSE_LOOKBACK_DAYS)).isoformat(),
        end=(day + timedelta(days=1)).isoformat(),
    )
    closes = frame["Close"].dropna() if "Close" in frame else frame
    closes = closes[[d.date() <= day for d in closes.index]]
    return float(closes.iloc[-1]) if len(closes) else None


def scale_live(official_value: float, official_date: date, symbol: str,
               unit_factor: float = 1.0) -> tuple[float, date, str]:
    """Return ``(value, as_of, mode)``, ``mode`` being ``"live"`` or ``"official"``."""
    official = (official_value, official_date, "official")
    try:
        quote_date, last = last_quote(symbol)
        close = close_on(symbol, official_date)
        if quote_date < official_date or close is None:
            return official
        last, close = last * unit_factor, close * unit_factor
        if not (math.isfinite(last) and math.isfinite(close) and last > 0 and close > 0):
            return official
        ratio = last / close
        if not LIVE_SCALE_RATIO_BOUNDS[0] <= ratio <= LIVE_SCALE_RATIO_BOUNDS[1]:
            logger.warning("Yahoo %s ratio %.2f outside bounds; using official value", symbol, ratio)
            return official
        return official_value * ratio, quote_date, "live"
    except Exception as exc:
        logger.warning("Yahoo live scaling for %s failed (%s); using official value", symbol, exc)
        return official
