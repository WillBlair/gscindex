"""Waterway levels that gate bulk shipping: the Mississippi River (scored) and the Rhine at Kaub (stored).

- Mississippi River at St. Louis: USGS site 07010000, parameter 00065 (gauge height, ft), daily
  values from ``waterservices.usgs.gov/nwis/dv``. St. Louis publishes this daily series under
  its own statistic code (30800), so a request that names ``statCd=00003`` (the daily mean)
  returns no series. Today's value is a provisional partial day.
- Kaub on the Rhine (PEGELONLINE station KAUB, water level W in cm): stored for later study,
  never scored.

A 200 response that is empty, reshaped or outside a plausible range raises ``ValueError``.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime

import pandas as pd
import requests

import config
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

USGS_DV_URL = "https://waterservices.usgs.gov/nwis/dv/"
STL_SITE = "07010000"
STL_PARAMETER = "00065"
KAUB_URL = "https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/KAUB/W.json"
_TIMEOUT = 60


def _within(series: pd.Series, bounds: tuple[float, float], label: str) -> pd.Series:
    """Raise unless the latest value lies inside the plausible range (a unit or datum change)."""
    low, high = bounds
    if not (low <= float(series.iloc[-1]) <= high):
        raise ValueError(f"{label} latest value {series.iloc[-1]} is outside {low} to {high} ft")
    return series


# ------------------------------------------------------------------------------ scores

def _linear_score(level: float, full: float, record_low: float, label: str) -> float:
    if not (math.isfinite(level) and math.isfinite(full) and math.isfinite(record_low)):
        raise ValueError(f"{label}: non-finite input")
    if record_low >= full:
        raise ValueError(f"{label}: record low {record_low} is not below the full level {full}")
    return float(min(100.0, max(0.0, 100.0 * (level - record_low) / (full - record_low))))


def river_score(stage: float, threshold: float, record_low: float) -> float:
    """100 at or above the low-water ``threshold``, 0 at ``record_low``, linear in between."""
    return _linear_score(stage, threshold, record_low, "river stage")


# ------------------------------------------------------------------------------ Mississippi

def parse_usgs_daily(payload) -> pd.Series:
    """Daily gauge height (ft) by date from a USGS ``dv`` JSON response. Raises ``ValueError`` on
    no series, a series for another parameter, no usable values, or an implausible latest value."""
    try:
        timeseries = payload["value"]["timeSeries"]
    except (KeyError, TypeError):
        raise ValueError("USGS payload has no timeSeries") from None
    if not isinstance(timeseries, list) or not timeseries:
        raise ValueError("USGS payload has no series")
    for ts in timeseries:
        try:
            code = ts["variable"]["variableCode"][0]["value"]
            if code != STL_PARAMETER:
                continue
            no_data = ts["variable"].get("noDataValue")
            rows = ts["values"][0]["value"]
        except (KeyError, IndexError, TypeError):
            continue
        days, values = [], []
        for row in rows:
            try:
                value = float(row["value"])
                day = pd.Timestamp(str(row["dateTime"])[:10])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(value) or (no_data is not None and value == float(no_data)):
                continue
            days.append(day)
            values.append(value)
        if not values:
            raise ValueError("USGS gauge height series has no usable values")
        series = pd.Series(values, index=pd.DatetimeIndex(days), name="stl_ft").sort_index()
        series = series[~series.index.duplicated(keep="last")]
        return _within(series, config.MISSISSIPPI_STL_PLAUSIBLE_FT, "St. Louis stage")
    raise ValueError(f"USGS payload has no parameter {STL_PARAMETER} series")


def fetch_mississippi_stl(start: date | None = None) -> pd.Series:
    """Daily St. Louis gauge height (ft) from ``start`` (default: the whole record, from 1982).

    Cached 6 hours per start date under ``stl_stage_v1_<start>``. No statistic code is sent;
    see the module docstring.
    """
    key = f"stl_stage_v1_{start.isoformat() if start else 'all'}"
    cached = get_cached(key, ttl=6 * 3600)
    if cached is not None:
        return pd.Series(cached["values"], index=pd.DatetimeIndex(cached["dates"]), name="stl_ft",
                         dtype=float)
    params = {"format": "json", "sites": STL_SITE, "parameterCd": STL_PARAMETER,
              "startDT": (start or date(1900, 1, 1)).isoformat()}
    resp = requests.get(USGS_DV_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    series = parse_usgs_daily(resp.json())
    set_cached(key, {"dates": series.index.strftime("%Y-%m-%d").tolist(), "values": series.tolist()})
    return series


# ------------------------------------------------------------------------------ Kaub

def parse_kaub(payload) -> tuple[date, float]:
    """(date, water level in cm) of the current Kaub measurement. Raises ``ValueError`` if the
    measurement is absent, not numeric, or the unit is not centimetres."""
    if not isinstance(payload, dict):
        raise ValueError("PEGELONLINE payload is not an object")
    if payload.get("unit") != "cm":
        raise ValueError(f"PEGELONLINE unit is {payload.get('unit')!r}, expected cm")
    current = payload.get("currentMeasurement")
    if not isinstance(current, dict):
        raise ValueError("PEGELONLINE payload has no currentMeasurement")
    value = current.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("PEGELONLINE measurement value is not a number")
    try:
        stamp = datetime.fromisoformat(str(current.get("timestamp")))
    except ValueError:
        raise ValueError("PEGELONLINE measurement has no valid timestamp") from None
    return stamp.date(), float(value)


def fetch_kaub_latest() -> tuple[date, float]:
    """Latest Kaub water level (date, cm)."""
    resp = requests.get(KAUB_URL, params={"includeCurrentMeasurement": "true"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return parse_kaub(resp.json())
