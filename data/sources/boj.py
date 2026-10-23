"""Bank of Japan Time-Series Data Search API: monthly Corporate Goods Price Index series.

Used for the Semis memory and logic chip price categories. Free, no key. BOJ asks API users
to keep access light, so each series is fetched in one request and a good reply is reused for
``config.BOJ_CACHE_SECONDS`` (24 hours). A failed or unusable reply is remembered too: the series
is not requested again for ``config.BOJ_FAILURE_RETRY_SECONDS`` (6 hours), so an outage does not
turn into a request every 5-minute cycle. Both results are kept in memory (so ``fetch_history``
reuses what ``fetch_current`` just fetched, even if the disk cache cannot be written) and on disk
(so a restart keeps them while the cache directory survives; a cold deploy starts empty).
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
import threading
import time

import pandas as pd
import requests

import config
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

API_URL = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
DB = "PR01"
START_DATE = "200001"
_TIMEOUT = 30
_USER_AGENT = "gscindex (supply chain index dashboard)"


def _cache_key(code: str) -> str:
    return f"boj_{code}_v1"


def _failed_key(code: str) -> str:
    return f"boj_{code}_failed_v1"


# code -> (time of the result, series or None for a failure, failure message)
_MEMORY: dict[str, tuple[float, pd.Series | None, str]] = {}
_MEMORY_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def _remember(code: str, series: pd.Series | None, error: str = "") -> None:
    with _MEMORY_LOCK:
        _MEMORY[code] = (_now(), series, error)


def _write_cache(key: str, data: dict) -> None:
    """Disk cache write; a failure is logged, never raised (the memory copy still holds)."""
    try:
        set_cached(key, data)
    except Exception as exc:
        logger.warning("BOJ cache write failed for %s: %s", key, exc)


def _not_retried(code: str, error: str) -> RuntimeError:
    hours = config.BOJ_FAILURE_RETRY_SECONDS / 3600
    return RuntimeError(f"BOJ series {code} failed recently and is not retried for {hours:g} h: {error}")


def parse_series(payload: dict, code: str) -> pd.Series:
    """Monthly series for ``code`` indexed by month start, finite values only.

    A reply that is HTTP 200 but not the whole series asked for (an error body, a reshaped result,
    another code, no values, a page with more to fetch) raises ``ValueError``, so the caller counts the input as missing.
    """
    if not isinstance(payload, dict):
        raise ValueError("BOJ reply is not a JSON object")
    status = payload.get("STATUS")
    if status != 200:
        raise ValueError(f"BOJ status {status!r}: {payload.get('MESSAGE', 'no message')}")
    if payload.get("NEXTPOSITION") is not None:
        raise ValueError(f"BOJ reply for {code} is truncated (NEXTPOSITION {payload['NEXTPOSITION']!r})")
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
    """Download and parse one series, at most once per ``BOJ_CACHE_SECONDS`` after a good reply and
    once per ``BOJ_FAILURE_RETRY_SECONDS`` after a failure.

    A good reply is cached under ``boj_<code>_v1``. A request error or a reply that fails
    ``parse_series`` is re-raised and recorded under ``boj_<code>_failed_v1``; until that marker
    expires every call raises ``RuntimeError`` without contacting BOJ.
    """
    now = _now()
    with _MEMORY_LOCK:
        remembered = _MEMORY.get(code)
    if remembered is not None:
        at, series, error = remembered
        if series is not None and now - at <= config.BOJ_CACHE_SECONDS:
            return series.copy()
        if series is None and now - at <= config.BOJ_FAILURE_RETRY_SECONDS:
            raise _not_retried(code, error)

    cached = get_cached(_cache_key(code), ttl=config.BOJ_CACHE_SECONDS)
    if cached is not None:
        series = pd.Series(cached["values"], index=pd.DatetimeIndex(cached["dates"]), name=code, dtype=float)
        _remember(code, series)
        return series.copy()
    failed = get_cached(_failed_key(code), ttl=config.BOJ_FAILURE_RETRY_SECONDS)
    if failed is not None:
        raise _not_retried(code, str(failed.get("error", "")) if isinstance(failed, dict) else "")

    try:
        resp = requests.get(
            API_URL,
            params={"format": "json", "lang": "en", "db": DB, "startDate": START_DATE, "code": code},
            headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        series = parse_series(resp.json(), code)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        _remember(code, None, error)
        _write_cache(_failed_key(code), {"error": error})
        raise
    _remember(code, series)
    _write_cache(_cache_key(code), {"dates": series.index.strftime("%Y-%m-%d").tolist(),
                                    "values": series.tolist()})
    return series.copy()
