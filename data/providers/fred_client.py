"""
FRED API Client
================
Shared helper for all providers that pull data from the Federal Reserve
Economic Data (FRED) API. Five of the seven dashboard categories use FRED.

FRED API docs: https://fred.stlouisfed.org/docs/api/fred/

Setup
-----
1. Create a free account at https://fred.stlouisfed.org
2. Request an API key at https://fred.stlouisfed.org/docs/api/api_key.html
3. Add ``FRED_API_KEY=your_key_here`` to your ``.env`` file
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import pandas as pd
import requests

from config import FRED_SCORE_LOOKBACK_DAYS
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def _get_api_key() -> str:
    """Read the FRED API key from environment, or raise a clear error."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "FRED_API_KEY is not set.\n"
            "  1. Sign up free at https://fred.stlouisfed.org\n"
            "  2. Get a key at https://fred.stlouisfed.org/docs/api/api_key.html\n"
            "  3. Add FRED_API_KEY=your_key to your .env file"
        )
    return key


def fetch_fred_series(
    series_id: str,
    lookback_days: int = 365 * 5,
    cache_ttl: int = 3600,
) -> pd.Series:
    """Fetch a FRED time series, with caching.

    Parameters
    ----------
    series_id : str
        FRED series identifier (e.g., ``"DCOILWTICO"`` for WTI crude oil).
    lookback_days : int
        How many days of history to request. Default is 5 years.
    cache_ttl : int
        Cache lifetime in seconds. Default 1 hour.

    Returns
    -------
    pd.Series
        Float values indexed by ``pd.DatetimeIndex``, sorted chronologically.
        Missing observations (FRED uses ``"."`` for these) are dropped.

    Raises
    ------
    EnvironmentError
        If ``FRED_API_KEY`` is not set.
    requests.HTTPError
        If the FRED API returns a non-200 status code.
    """
    cache_key = f"fred_{series_id}"
    cached = get_cached(cache_key, ttl=cache_ttl)
    if cached is not None:
        # Rebuild Series from cached dict
        s = pd.Series(cached["values"], name=series_id)
        s.index = pd.DatetimeIndex(cached["dates"])
        return s

    api_key = _get_api_key()
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    logger.info("Fetching FRED series %s (from %s)", series_id, start_date)

    resp = requests.get(
        _BASE_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start_date,
            "sort_order": "asc",
        },
        timeout=15,
    )
    resp.raise_for_status()

    observations = resp.json().get("observations", [])

    dates: list[str] = []
    values: list[float] = []
    for obs in observations:
        # FRED uses "." for missing values — skip them
        if obs["value"] == ".":
            continue
        dates.append(obs["date"])
        values.append(float(obs["value"]))

    series = pd.Series(values, index=pd.DatetimeIndex(dates), name=series_id)

    # Cache the result
    set_cached(cache_key, {"dates": dates, "values": values})

    return series


def _score_window(series: pd.Series, lookback_days: int | None = None) -> pd.Series:
    """Return the trailing slice used for min/max scoring bounds."""
    if series.empty:
        return series
    days = lookback_days if lookback_days is not None else FRED_SCORE_LOOKBACK_DAYS
    end = series.index.max()
    start = end - pd.Timedelta(days=days)
    windowed = series[series.index >= start]
    return windowed if len(windowed) >= 2 else series


def normalization_bounds(
    series: pd.Series,
    lookback_days: int | None = None,
) -> tuple[float, float]:
    """Min/max over the trailing lookback window (default: 2 years)."""
    window = _score_window(series, lookback_days)
    return float(window.min()), float(window.max())


def inverse_normalize_value(value: float, min_val: float, max_val: float) -> float:
    """Map a raw value to a 0–100 score (lower raw → higher score)."""
    if max_val == min_val:
        return 50.0
    return float(max(0.0, min(100.0, 100 * (1 - (value - min_val) / (max_val - min_val)))))


def normalize_series_inverse(
    series: pd.Series,
    lookback_days: int | None = None,
) -> pd.Series:
    """Normalize a series where LOWER raw values = HIGHER health score.

    Uses a trailing time window at each date (default 2 years) so COVID-era
    spikes do not dominate the scale.

    Parameters
    ----------
    series : pd.Series
        Raw FRED data with a DatetimeIndex.
    lookback_days : int | None
        Trailing window in days. Defaults to ``FRED_SCORE_LOOKBACK_DAYS``.

    Returns
    -------
    pd.Series
        Scores in [0, 100], same index as input.
    """
    if series.empty:
        return series
    days = lookback_days if lookback_days is not None else FRED_SCORE_LOOKBACK_DAYS
    roll_min = series.rolling(f"{days}D", min_periods=30).min()
    roll_max = series.rolling(f"{days}D", min_periods=30).max()
    span = roll_max - roll_min
    scores = (1 - (series - roll_min) / span) * 100
    scores = scores.where(span > 0, 50.0)
    return scores.round(1).clip(0.0, 100.0)


def normalize_series_direct(
    series: pd.Series,
    lookback_days: int | None = None,
) -> pd.Series:
    """Normalize a series where HIGHER raw values = HIGHER health score.

    Uses a trailing time window at each date (default 2 years).

    Parameters
    ----------
    series : pd.Series
        Raw FRED data with a DatetimeIndex.
    lookback_days : int | None
        Trailing window in days. Defaults to ``FRED_SCORE_LOOKBACK_DAYS``.

    Returns
    -------
    pd.Series
        Scores in [0, 100], same index as input.
    """
    if series.empty:
        return series
    days = lookback_days if lookback_days is not None else FRED_SCORE_LOOKBACK_DAYS
    roll_min = series.rolling(f"{days}D", min_periods=30).min()
    roll_max = series.rolling(f"{days}D", min_periods=30).max()
    span = roll_max - roll_min
    scores = ((series - roll_min) / span) * 100
    scores = scores.where(span > 0, 50.0)
    return scores.round(1).clip(0.0, 100.0)
