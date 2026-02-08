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


def normalize_series_inverse(series: pd.Series) -> pd.Series:
    """Normalize a series where LOWER raw values = HIGHER health score.

    Used for metrics where a lower value is better for the supply chain
    (e.g., oil prices, uncertainty indices, supply chain pressure).

    Maps the historical min → 100 (best) and historical max → 0 (worst).

    Parameters
    ----------
    series : pd.Series
        Raw FRED data.

    Returns
    -------
    pd.Series
        Scores in [0, 100], same index as input.
    """
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pd.Series(50.0, index=series.index)
    return ((1 - (series - min_val) / (max_val - min_val)) * 100).round(1)


def normalize_series_direct(series: pd.Series) -> pd.Series:
    """Normalize a series where HIGHER raw values = HIGHER health score.

    Used for metrics where a higher value is better for the supply chain
    (e.g., freight volume, manufacturing PMI).

    Maps the historical min → 0 (worst) and historical max → 100 (best).

    Parameters
    ----------
    series : pd.Series
        Raw FRED data.

    Returns
    -------
    pd.Series
        Scores in [0, 100], same index as input.
    """
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pd.Series(50.0, index=series.index)
    return (((series - min_val) / (max_val - min_val)) * 100).round(1)
