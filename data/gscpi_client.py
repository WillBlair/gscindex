"""
NY Fed Global Supply Chain Pressure Index (GSCPI)
==================================================
GSCPI is not on FRED; we load the official vintage matrix CSV published by
the New York Fed and extract the latest estimate for each calendar month.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime

import pandas as pd
import requests

from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_GSCPI_CSV_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/"
    "data/gscpi/gscpi_interactive_data.csv"
)
_CACHE_KEY = "nyfed_gscpi_monthly_v2"
_CACHE_TTL = 6 * 3600  # 6 hours — index updates monthly

# Excel serial day 0 (the NY Fed export switched column headers from
# "Jan-22" style strings to Excel serial dates like 44562 = 2022-01-01).
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _parse_month_column(col: str) -> pd.Timestamp | None:
    """Parse a vintage column header to a month-end Timestamp.

    Supports both header formats the NY Fed has used: "%b-%y" strings
    ("Jan-22") and Excel serial dates ("44562"). Returns None for headers
    that are neither (parsing must not crash on format drift).
    """
    text = str(col).strip()
    parsed: pd.Timestamp | None = None
    try:
        parsed = pd.to_datetime(text, format="%b-%y")
    except ValueError:
        try:
            parsed = _EXCEL_EPOCH + pd.Timedelta(days=float(text))
        except ValueError:
            return None
    month_end = (parsed + pd.offsets.MonthEnd(0)).normalize()
    # Sanity bounds: GSCPI vintages start in the 2020s and can't be future-dated
    # beyond next year. Anything else is a mis-parse.
    if not (pd.Timestamp("1995-01-01") <= month_end <= pd.Timestamp.now() + pd.DateOffset(years=1)):
        return None
    return month_end


def fetch_gscpi_series() -> pd.Series:
    """Return monthly GSCPI levels (z-score; higher = more pressure)."""
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached is not None:
        series = pd.Series(cached["values"], name="GSCPI")
        series.index = pd.DatetimeIndex(cached["dates"])
        return series.sort_index()

    resp = requests.get(_GSCPI_CSV_URL, timeout=30)
    resp.raise_for_status()

    df = pd.read_csv(
        io.BytesIO(resp.content),
        encoding="utf-8-sig",
        na_values=["#N/A"],
    )
    df.columns = ["Date"] + list(df.columns[1:])
    month_cols = list(df.columns[1:])

    by_month: dict[pd.Timestamp, float] = {}
    for col in month_cols:
        month_end = _parse_month_column(col)
        if month_end is None:
            logger.warning("GSCPI: skipping unparseable vintage column %r", col)
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        valid = numeric.dropna()
        if valid.empty:
            continue
        by_month[month_end] = float(valid.iloc[-1])

    if not by_month:
        raise ValueError("GSCPI CSV parsed empty — NY Fed format may have changed")

    series = pd.Series(by_month, name="GSCPI").sort_index()
    set_cached(
        _CACHE_KEY,
        {
            "dates": [d.strftime("%Y-%m-%d") for d in series.index],
            "values": series.tolist(),
        },
    )
    logger.info("Fetched GSCPI: %d monthly points, latest=%.2f", len(series), series.iloc[-1])
    return series


def latest_published_gscpi(series: pd.Series) -> tuple[float, pd.Timestamp]:
    """Return the newest month that should be treated as published (lag 1 month)."""
    if series.empty:
        raise ValueError("GSCPI series is empty")
    now = pd.Timestamp(datetime.now().date())
    prev_month_end = (now.replace(day=1) - pd.Timedelta(days=1)).normalize()
    eligible = series[series.index <= prev_month_end]
    if eligible.empty:
        eligible = series
    date = eligible.index[-1]
    return float(eligible.iloc[-1]), date


def gscpi_to_score(value: float) -> float:
    """Map GSCPI z-score to 0–100 health (lower pressure → higher score)."""
    return float(max(0.0, min(100.0, 50.0 - value * 25.0)))
