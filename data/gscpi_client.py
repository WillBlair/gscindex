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
_CACHE_KEY = "nyfed_gscpi_monthly_v3"
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


# Stale-cache fallback TTL: if the live CSV fetch fails, reuse the last good
# GSCPI for up to 60 days rather than letting the provider drop to a neutral
# fallback. GSCPI moves monthly, so a slightly stale real reading beats a
# fabricated 50.0 that hides the actual pressure level.
_STALE_FALLBACK_TTL = 60 * 86400


def _series_from_cache(cached: dict) -> pd.Series:
    """Rebuild the GSCPI Series from a cached payload."""
    series = pd.Series(cached["values"], name="GSCPI")
    series.index = pd.DatetimeIndex(cached["dates"])
    return series.sort_index()


def fetch_gscpi_series() -> pd.Series:
    """Return monthly GSCPI levels (z-score; higher = more pressure)."""
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached is not None:
        return _series_from_cache(cached)

    try:
        resp = requests.get(_GSCPI_CSV_URL, timeout=30)
        resp.raise_for_status()

        df = pd.read_csv(
            io.BytesIO(resp.content),
            encoding="utf-8-sig",
            na_values=["#N/A"],
        )
        df.columns = ["Date"] + list(df.columns[1:])
        # The CSV is a vintage matrix: each row is a data month ("Date"),
        # each column is a release (vintage). A vintage's last value is the
        # PREVIOUS month's reading, so keying values by the vintage header
        # shifted everything a month late. Key by the row's data month and
        # take the newest vintage that has a value for it.
        vintage_cols = [c for c in df.columns[1:] if _parse_month_column(c) is not None]
        skipped = [c for c in df.columns[1:] if c not in vintage_cols]
        if skipped:
            logger.warning("GSCPI: skipping unparseable vintage columns %r", skipped)
        vintage_cols.sort(key=_parse_month_column)
        values = df[vintage_cols].apply(pd.to_numeric, errors="coerce")
        latest = values.ffill(axis=1).iloc[:, -1] if vintage_cols else pd.Series(dtype=float)
        dates = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce")

        by_month: dict[pd.Timestamp, float] = {}
        for date, value in zip(dates, latest):
            if pd.isna(date) or pd.isna(value):
                continue
            by_month[(date + pd.offsets.MonthEnd(0)).normalize()] = float(value)

        if not by_month:
            raise ValueError("GSCPI CSV parsed empty — NY Fed format may have changed")
    except Exception as exc:
        # Network blip / format drift: fall back to the last good reading
        # (up to 60 days old) instead of failing the provider entirely.
        stale = get_cached(_CACHE_KEY, ttl=_STALE_FALLBACK_TTL)
        if stale is not None:
            logger.warning("GSCPI live fetch failed (%s); serving stale cached series", exc)
            return _series_from_cache(stale)
        raise

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
