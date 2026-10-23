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


def cpi_reference() -> float:
    """The anchors' CPI reference value; a missing one is a RuntimeError, not a KeyError."""
    try:
        return float(config.SCORE_ANCHORS["cpi_reference"]["value"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("no anchor for cpi_reference") from None


def cpi_ratios(fetch: Callable[[str], pd.Series], cpi_ref: float) -> pd.Series:
    """CPI_ref / CPI_t, dated by CPI observation month. ``fetch(series_id)`` returns the series."""
    try:
        cpi = clean_prices(fetch(CPI_SERIES))
    except Exception as exc:
        raise RuntimeError(f"{CPI_SERIES} unavailable: {exc}") from exc
    if cpi.empty:
        raise RuntimeError(f"{CPI_SERIES} unavailable: no observations")
    return cpi_ref / cpi
