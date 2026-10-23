"""Bank of Japan Time-Series Data Search API: monthly Corporate Goods Price Index series.

Used for the Semis memory and logic chip price categories. Free, no key. BOJ asks API users
to keep access light, so each series is fetched in one request and cached for 24 hours.
Terms: https://www.stat-search.boj.or.jp/info/api_notice_en.pdf (credit line in
``config.BOJ_CREDIT``).

Request shape (checked 2026-10-23, one call per series):

    GET {API_URL}?format=json&lang=en&db=PR01&startDate=200001&code=PRCG20_2500850005

The reply is JSON with ``STATUS`` (200 on success), ``RESULTSET`` (one object per code) and
``NEXTPOSITION``. Each result carries ``SERIES_CODE``, ``FREQUENCY`` and
``VALUES = {"SURVEY_DATES": [YYYYMM, ...], "VALUES": [float | null, ...]}``.
"""
from __future__ import annotations

import logging
import math

import pandas as pd
import requests

from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

API_URL = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
DB = "PR01"
START_DATE = "200001"
_TIMEOUT = 30
_CACHE_TTL = 24 * 3600
_USER_AGENT = "gscindex (supply chain index dashboard)"


def _cache_key(code: str) -> str:
    return f"boj_{code}_v1"


def parse_series(payload: dict, code: str) -> pd.Series:
    """Monthly series for ``code`` indexed by month start, finite values only.

    A reply that is HTTP 200 but not the series asked for (an error body, a reshaped result,
    another code, no values) raises ``ValueError``, so the caller counts the input as missing.
    """
    if not isinstance(payload, dict):
        raise ValueError("BOJ reply is not a JSON object")
    status = payload.get("STATUS")
    if status != 200:
        raise ValueError(f"BOJ status {status!r}: {payload.get('MESSAGE', 'no message')}")
    results = payload.get("RESULTSET")
    if not isinstance(results, list) or not results:
        raise ValueError(f"BOJ reply has no series for {code}")
    match = [r for r in results if isinstance(r, dict) and r.get("SERIES_CODE") == code]
    if not match:
        raise ValueError(f"BOJ reply does not contain series {code}")
    result = match[0]
    if result.get("FREQUENCY") != "MONTHLY":
        raise ValueError(f"BOJ series {code} is not monthly ({result.get('FREQUENCY')!r})")
    values = result.get("VALUES")
    if not isinstance(values, dict):
        raise ValueError(f"BOJ series {code} has no VALUES")
    dates, numbers = values.get("SURVEY_DATES"), values.get("VALUES")
    if not isinstance(dates, list) or not isinstance(numbers, list) or len(dates) != len(numbers):
        raise ValueError(f"BOJ series {code} has mismatched dates and values")

    index, data = [], []
    for stamp, value in zip(dates, numbers):
        try:
            month = pd.Timestamp(year=int(stamp) // 100, month=int(stamp) % 100, day=1)
            number = float(value)
        except (TypeError, ValueError):
            continue    # a null or non-numeric observation is a gap
        if math.isfinite(number):
            index.append(month)
            data.append(number)
    if not data:
        raise ValueError(f"BOJ series {code} has no usable values")
    series = pd.Series(data, index=pd.DatetimeIndex(index), name=code, dtype=float).sort_index()
    return series[~series.index.duplicated(keep="last")]


def fetch_series(code: str) -> pd.Series:
    """Download and parse one series; cached 24 hours under ``boj_<code>_v1``.

    A reply that fails ``parse_series`` raises ``ValueError`` and is not cached.
    """
    cached = get_cached(_cache_key(code), ttl=_CACHE_TTL)
    if cached is not None:
        return pd.Series(cached["values"], index=pd.DatetimeIndex(cached["dates"]), name=code, dtype=float)
    resp = requests.get(
        API_URL,
        params={"format": "json", "lang": "en", "db": DB, "startDate": START_DATE, "code": code},
        headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
    resp.raise_for_status()
    series = parse_series(resp.json(), code)
    set_cached(_cache_key(code), {"dates": series.index.strftime("%Y-%m-%d").tolist(),
                                  "values": series.tolist()})
    return series
