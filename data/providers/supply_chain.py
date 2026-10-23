"""
Supply Chain Pressure Provider
================================
Scores the supply chain category from the NY Fed **GSCPI** (Global Supply
Chain Pressure Index) alone: a monthly z-score built from transport costs and
supplier delivery times across major economies. 0 = historical average,
positive = elevated pressure.

    score = score_raw(GSCPI, anchor "gscpi")   # lower is better

The anchors are fixed: the healthiest 5% of pre-2020 months = 100, the pre-2020
median = 80, the worst month on record = 0.

The BDRY dry-bulk ETF is not scored: GSCPI already contains the Baltic Dry
Index, so blending BDRY in counted dry bulk twice. It, like the NY Fed **WEI**
(a GDP-growth nowcast that has no defensible sign in a health score, since
high growth coincided with the 2021 stress peak), is shown as hover context only.

GSCPI is published about five days after its month ends. The reading is dated
by that month's end, and in history each month starts on its publication date
and is carried forward until the next one, or until it is older than its
freshness drop window.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
from data.gscpi_client import fetch_gscpi_series
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.readings import (
    InputReading, blend_inputs, freshness_status, inputs_metadata, oldest_as_of, period_end)
from data.sources import markets
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_GSCPI = "gscpi"
_WEI_SERIES_ID = "WEI"
_BDRY = "BDRY"
_SOURCE = "NY Fed Global Supply Chain Pressure Index (GSCPI)"
_NOT_SCORED = "context, not scored"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _fetch_gscpi() -> pd.Series:
    """The NY Fed series; any failure to load it is a RuntimeError, so the category falls back."""
    try:
        return fetch_gscpi_series()
    except Exception as exc:
        raise RuntimeError(f"GSCPI unavailable: {exc}") from exc


def _gscpi_months(series: pd.Series) -> pd.Series:
    """Finite GSCPI values by data month, oldest first. A NaN or infinite month is dropped."""
    values = pd.to_numeric(series, errors="coerce")
    values = values[values.map(math.isfinite)]
    return values.sort_index()


def _latest_month(today: date) -> tuple[float, date]:
    """Newest finite GSCPI value and its data month's end. Raises if there is none."""
    values = _gscpi_months(_fetch_gscpi())
    # A month that has not started cannot have data; guards against a mis-dated row.
    values = values[[stamp.replace(day=1).date() <= today for stamp in values.index]]
    if values.empty:
        raise RuntimeError("GSCPI has no usable month")
    return float(values.iloc[-1]), period_end(values.index[-1].date(), "M")


def _wei_context() -> str | None:
    try:
        value = float(fetch_fred_series(_WEI_SERIES_ID).dropna().iloc[-1])
    except Exception as exc:
        logger.warning("WEI context unavailable (score unaffected): %s", exc)
        return None
    return f"WEI {value:+.2f} ({_NOT_SCORED})" if math.isfinite(value) else None


def _bdry_context() -> str | None:
    try:
        _, price = markets.last_quote(_BDRY)
    except Exception as exc:
        logger.warning("BDRY context unavailable (score unaffected): %s", exc)
        return None
    return f"BDRY ${price:.2f} ({_NOT_SCORED})" if math.isfinite(price) else None


def _condition(value: float) -> str:
    """Plain-words reading of a GSCPI z-score."""
    if value > 1.0:
        return "supply chain pressure is well above its historical average"
    if value > 0.25:
        return "pressure is above its historical average"
    if value > -0.25:
        return "pressure is near its historical average"
    return "pressure is below its historical average"


class SupplyChainProvider(BaseProvider):
    """Supply Chain Pressure - NY Fed GSCPI, mapped through fixed anchors."""

    category = "supply_chain"

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchor = get_anchor(_GSCPI)
        value, month_end = _latest_month(today)
        as_of = min(month_end, today)
        status = freshness_status(as_of, today, _GSCPI)
        reading = InputReading(
            _GSCPI, score_raw(value, anchor), as_of, _SOURCE,
            f"GSCPI {value:+.2f} ({month_end:%b %Y})", status)
        score, status = blend_inputs([reading], {_GSCPI: 1.0})
        if score is None:
            raise RuntimeError(f"GSCPI for {month_end:%B %Y} is past its freshness drop window")

        context = [c for c in (_wei_context(), _bdry_context()) if c]
        raw_value = " | ".join([reading.raw_value, *context])
        description = (
            f"The NY Fed's Global Supply Chain Pressure Index combines transport costs and supplier "
            f"delivery times across major economies into one z-score, where 0 is the historical "
            f"average. It stood at {value:+.2f} for {month_end:%B %Y}: {_condition(value)}. "
            "The score's normal (80) is the pre-2020 median. The index already includes the Baltic "
            "Dry Index, so the BDRY dry-bulk ETF and the Weekly Economic Index are shown for "
            "context and are not scored.")
        return score, {
            "source": _SOURCE,
            "raw_value": raw_value,
            "raw_label": "Global Supply Chain Pressure (z-score; 0 = historical average)",
            "description": description,
            "calculation": (
                "GSCPI is mapped through fixed anchors, lower being better: the healthiest 5% of "
                "pre-2020 months = 100, the pre-2020 median = 80, the worst month on record = 0. "
                f"The NY Fed publishes about {config.PUBLICATION_LAG_DAYS[_GSCPI]} days after the "
                "month ends. BDRY and WEI are not part of the score."),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of([reading]).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata([reading]),
        }

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchor = get_anchor(_GSCPI)
        values = pd.to_numeric(_fetch_gscpi(), errors="coerce").sort_index()
        if not values.map(math.isfinite).any():
            raise RuntimeError("no GSCPI history available")

        lag = timedelta(days=config.PUBLICATION_LAG_DAYS[_GSCPI])
        drop_after = config.FRESHNESS[_GSCPI][1]
        rows = []
        for stamp, value in values.items():
            end = period_end(stamp.date(), "M")
            score = score_raw(float(value), anchor) if math.isfinite(value) else float("nan")
            rows.append((pd.Timestamp(end + lag), pd.Timestamp(end), score))
        frame = pd.DataFrame(rows, columns=["available", "as_of", "score"]).set_index("available")
        frame = frame[~frame.index.duplicated(keep="last")]

        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        # reindex(method="ffill") takes the latest publication on or before each day and keeps
        # a NaN month as a gap, where ffill after reindexing would carry the month before it.
        daily = frame.reindex(window, method="ffill")
        age = (daily.index.to_series() - daily["as_of"]).dt.days
        out = daily["score"].where(age <= drop_after).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no GSCPI history inside the window")
        return out.rename("supply_chain")
