"""Geopolitical Risk (GPR) index, Caldara and Iacoviello.

A newspaper-based count of articles on geopolitical tensions (threats and acts), published as
a daily file and a monthly file in Stata format (free, no key). Each file is the publication:
a value is dated by the day or month it covers.
https://www.matteoiacoviello.com/gpr.htm
"""
from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd
import requests

from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

DAILY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.dta"
MONTHLY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.dta"
_DAILY_COLUMNS = ("date", "GPRD")
_MONTHLY_COLUMNS = ("month", "GPR")
_TIMEOUT = 60
_DAILY_CACHE_KEY = "gpr_daily_v1"
_MONTHLY_CACHE_KEY = "gpr_monthly_v1"
_CACHE_TTL = 12 * 3600


def _parse(frame: pd.DataFrame, date_column: str, value_column: str, label: str) -> pd.Series:
    for needed in (date_column, value_column):
        if needed not in frame.columns:
            raise ValueError(f"GPR {label} file has no column {needed!r}")
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[value_column], errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(dates), name=value_column)
    series = series[series.index.notna() & np.isfinite(series)].sort_index()
    series = series[~series.index.duplicated(keep="last")]
    if series.empty:
        raise ValueError(f"GPR {label} file has no usable {value_column!r} values")
    return series


def parse_gpr_daily(df: pd.DataFrame) -> pd.Series:
    """Daily ``GPRD`` indexed by ``date``; ``ValueError`` if either column is missing."""
    return _parse(df, *_DAILY_COLUMNS, "daily")


def parse_gpr_monthly(df: pd.DataFrame) -> pd.Series:
    """Monthly ``GPR`` indexed by ``month``; ``ValueError`` if either column is missing."""
    return _parse(df, *_MONTHLY_COLUMNS, "monthly")


def _pack(series: pd.Series) -> dict:
    return {"dates": series.index.strftime("%Y-%m-%d").tolist(), "values": series.tolist()}


def _unpack(packed: dict, name: str) -> pd.Series:
    return pd.Series(packed["values"], index=pd.DatetimeIndex(packed["dates"]), name=name, dtype=float)


def _fetch(url: str, key: str, parse, name: str) -> pd.Series:
    cached = get_cached(key, ttl=_CACHE_TTL)
    if cached is not None:
        return _unpack(cached, name)
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    try:
        frame = pd.read_stata(io.BytesIO(resp.content))
    except Exception as exc:
        raise ValueError(f"GPR file at {url} is not readable Stata data: {exc}") from exc
    series = parse(frame)
    set_cached(key, _pack(series))
    return series


def fetch_gpr_daily() -> pd.Series:
    """Daily GPR, cached 12 hours under ``gpr_daily_v1``.

    A 200 response that is not the expected file raises ``ValueError`` and is not cached.
    """
    return _fetch(DAILY_URL, _DAILY_CACHE_KEY, parse_gpr_daily, "GPRD")


def fetch_gpr_monthly() -> pd.Series:
    """Monthly GPR, cached 12 hours under ``gpr_monthly_v1``."""
    return _fetch(MONTHLY_URL, _MONTHLY_CACHE_KEY, parse_gpr_monthly, "GPR")
