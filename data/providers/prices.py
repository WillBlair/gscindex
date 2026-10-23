"""Price-series helpers shared by the providers that score real (CPI-deflated) prices."""
from __future__ import annotations

import math
from typing import Callable

import pandas as pd

import config

CPI_SERIES = "CPIAUCSL"


def clean_prices(series: pd.Series) -> pd.Series:
    """Finite, positive prices only, sorted, one value per date."""
    series = pd.to_numeric(series, errors="coerce").dropna()
    series = series[(series > 0) & series.map(math.isfinite)].sort_index()
    return series[~series.index.duplicated(keep="last")]


def _cpi_entry() -> tuple[float, str]:
    """(value, date) of the anchors' CPI reference; either one missing or malformed is a RuntimeError."""
    try:
        entry = config.SCORE_ANCHORS["cpi_reference"]
        value, day = float(entry["value"]), str(entry["date"]).strip()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("no anchor for cpi_reference") from None
    if not (math.isfinite(value) and value > 0 and day):
        raise RuntimeError("no anchor for cpi_reference")
    return value, day


def cpi_reference() -> float:
    """The anchors' CPI reference value."""
    return _cpi_entry()[0]


def cpi_reference_date() -> str:
    """The anchors' CPI reference month, for the calculation text."""
    return _cpi_entry()[1]


def cpi_ratios(fetch: Callable[[str], pd.Series], cpi_ref: float) -> pd.Series:
    """CPI_ref / CPI_t, dated by CPI observation month. ``fetch(series_id)`` returns the series."""
    try:
        cpi = clean_prices(fetch(CPI_SERIES))
    except Exception as exc:
        raise RuntimeError(f"{CPI_SERIES} unavailable: {exc}") from exc
    if cpi.empty:
        raise RuntimeError(f"{CPI_SERIES} unavailable: no observations")
    return cpi_ref / cpi
