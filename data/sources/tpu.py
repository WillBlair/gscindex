"""Trade Policy Uncertainty (TPU) index, Caldara, Iacoviello, Molligo, Prestipino and Raffo.

A newspaper-based count of articles on trade policy uncertainty, published as a daily and
a monthly index in one workbook (free, no key). The workbook is the publication: each day's
value is dated by the day it covers.
https://www.matteoiacoviello.com/tpu.htm
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

URL = "https://www.matteoiacoviello.com/tpu_files/tpu_web_latest.xlsx"
_DAILY_SHEET, _DAILY_COLUMN = "TPU_DAILY", "TPUD_index"
_MONTHLY_SHEET, _MONTHLY_COLUMN = "TPU_MONTHLY", "TPU"
_TIMEOUT = 60
_CACHE_KEY = "tpu_v1"
_CACHE_TTL = 12 * 3600


def _read_sheet(source, sheet: str, column: str) -> pd.Series:
    try:
        frame = pd.read_excel(source, sheet_name=sheet)
    except Exception as exc:
        raise ValueError(f"TPU workbook has no readable sheet {sheet!r}: {exc}") from exc
    for needed in ("DATE", column):
        if needed not in frame.columns:
            raise ValueError(f"TPU sheet {sheet!r} has no column {needed!r}")
    dates = pd.to_datetime(frame["DATE"], errors="coerce")
    values = pd.to_numeric(frame[column], errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(dates), name=column)
    series = series[series.index.notna() & np.isfinite(series)].sort_index()
    series = series[~series.index.duplicated(keep="last")]
    if series.empty:
        raise ValueError(f"TPU sheet {sheet!r} has no usable {column!r} values")
    return series


def parse_tpu_xlsx(path_or_bytes) -> tuple[pd.Series, pd.Series]:
    """Return ``(daily TPUD_index, monthly TPU)``; ``ValueError`` if a sheet or column is missing."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
        return (_read_sheet(io.BytesIO(data), _DAILY_SHEET, _DAILY_COLUMN),
                _read_sheet(io.BytesIO(data), _MONTHLY_SHEET, _MONTHLY_COLUMN))
    source = Path(path_or_bytes)
    return (_read_sheet(source, _DAILY_SHEET, _DAILY_COLUMN),
            _read_sheet(source, _MONTHLY_SHEET, _MONTHLY_COLUMN))


def _pack(series: pd.Series) -> dict:
    return {"dates": series.index.strftime("%Y-%m-%d").tolist(), "values": series.tolist()}


def _unpack(packed: dict, name: str) -> pd.Series:
    return pd.Series(packed["values"], index=pd.DatetimeIndex(packed["dates"]), name=name, dtype=float)


def fetch_tpu() -> tuple[pd.Series, pd.Series]:
    """Download and parse the workbook; cached 12 hours under ``tpu_v1``.

    A 200 response that is not the expected workbook raises ``ValueError`` and is not cached.
    """
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached is not None:
        return _unpack(cached["daily"], _DAILY_COLUMN), _unpack(cached["monthly"], _MONTHLY_COLUMN)
    resp = requests.get(URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    daily, monthly = parse_tpu_xlsx(resp.content)
    set_cached(_CACHE_KEY, {"daily": _pack(daily), "monthly": _pack(monthly)})
    return daily, monthly
