"""Weekly US rail volume from the STB's EP 724 carload reports, via USDA AgTransport.

Socrata dataset ``tb7q-kn5i`` holds one row per railroad, week, commodity and direction
(free, no key). Originated carloads of every commodity plus the two intermodal commodities,
``Containers`` and ``Trailers`` (intermodal units), add up to the week's total rail volume.
The week is dated by its Saturday ending date. History starts 2017-03-25.
https://agtransport.usda.gov/Rail/STB-Weekly-Rail-Carloads/tb7q-kn5i
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import requests

import config
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

URL = "https://agtransport.usda.gov/resource/tb7q-kn5i.json"
INTERMODAL_COMMODITIES = frozenset({"Containers", "Trailers"})
_TIMEOUT = 120
_CACHE_KEY = "stb_rail_weekly_v1"
_CACHE_TTL = 12 * 3600
_PARAMS = {
    "$select": "date,commodity,sum(carloads) as carloads",
    "$where": "type='Originated'",
    "$group": "date,commodity",
    "$order": "date",
    "$limit": 100000,
}


def parse_rail_rows(rows) -> pd.Series:
    """Weekly total (carloads plus intermodal units) by week-ending date.

    Raises ``ValueError`` for anything that is not the expected shape: not a list of rows, no
    usable rows, or no intermodal commodity (a renamed commodity would silently drop about
    half the volume and step the series down).
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("STB rail payload is empty or not a list of rows")
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError("STB rail payload rows are not objects")
    frame = pd.DataFrame(rows)
    for needed in ("date", "commodity", "carloads"):
        if needed not in frame.columns:
            raise ValueError(f"STB rail payload has no column {needed!r}")
    frame["day"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["units"] = pd.to_numeric(frame["carloads"], errors="coerce")
    frame = frame[frame["day"].notna() & np.isfinite(frame["units"])]
    if frame.empty:
        raise ValueError("STB rail payload has no usable rows")
    if not frame["commodity"].isin(INTERMODAL_COMMODITIES).any():
        raise ValueError("STB rail payload has no intermodal commodity (Containers, Trailers)")
    series = frame.groupby("day")["units"].sum().sort_index()
    series.name = "rail_units"
    return series


def _pack(series: pd.Series) -> dict:
    return {"dates": series.index.strftime("%Y-%m-%d").tolist(), "values": series.tolist()}


def _unpack(packed: dict) -> pd.Series:
    return pd.Series(packed["values"], index=pd.DatetimeIndex(packed["dates"]), name="rail_units",
                     dtype=float)


def fetch_rail_weekly() -> pd.Series:
    """Weekly originated carloads plus intermodal units; cached 12 hours under ``stb_rail_weekly_v1``.

    A 200 response that is empty or reshaped raises ``ValueError`` and is not cached.
    """
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached is not None:
        return _unpack(cached)
    resp = requests.get(URL, params=_PARAMS, timeout=_TIMEOUT)
    resp.raise_for_status()
    series = parse_rail_rows(resp.json())
    set_cached(_CACHE_KEY, _pack(series))
    return series


def rail_yoy(weekly: pd.Series) -> pd.Series:
    """Year-over-year change in %: the 4-week mean over the 4-week mean 52 weeks earlier.

    Weeks are counted on a regular 7-day grid, so a missing week leaves a gap rather than
    shifting the comparison. A week is measurable only when both means are complete.
    """
    grid = weekly.sort_index().asfreq("7D")
    mean = grid.rolling(config.RAIL_MEAN_WEEKS).mean()
    base = mean.shift(config.RAIL_YOY_LAG_WEEKS)
    return ((mean / base - 1.0) * 100.0).replace([np.inf, -np.inf], np.nan)
