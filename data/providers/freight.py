"""
Freight Volume Provider
========================
How much freight is physically moving, from two year-over-year inputs (weights in
``config.FREIGHT_WEIGHTS``, renormalized over the inputs available):

    1. BTS Freight Transportation Services Index (50%) - FRED ``TSIFRGHT``, the monthly volume
       of for-hire freight across trucking, rail, inland waterways, pipelines and air.
    2. Weekly rail volume (50%) - STB originated carloads plus intermodal units, the 4-week
       mean against the 4-week mean 52 weeks earlier.

Each growth rate is mapped through its anchors (healthiest 5% of pre-2020 history = 100,
pre-2020 median = 80, worst on record = 0). This is a demand gauge: a contraction is bad.
It is not a congestion or cost gauge; the Supply Chain category covers delivery pressure.

TSIFRGHT is published about 80 days after its month ends, so the weekly rail data (about five
days after the week ends) carries the category between prints. In history each reading is
dated by its publication lag and carried forward until it is older than its drop window.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.readings import (
    InputReading, no_inputs_error, blend_inputs, freshness_status, inputs_metadata, oldest_as_of, period_end,
    safe_score)
from data.sources import rail
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_TSI, _RAIL = "tsifrght", "rail_volume"
_TSI_SERIES = "TSIFRGHT"
_SOURCES = {
    _TSI: "BTS Freight Transportation Services Index (FRED TSIFRGHT)",
    _RAIL: "STB weekly rail carloads plus intermodal units (USDA AgTransport)",
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _anchors() -> dict[str, dict]:
    """Both anchors; a missing one is a RuntimeError, not a KeyError."""
    return {key: get_anchor(key) for key in config.FREIGHT_WEIGHTS}


def _missing(name: str) -> InputReading:
    return InputReading(name, None, None, _SOURCES[name], status="missing")


def _finite(series: pd.Series) -> pd.Series:
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def _tsifrght_yoy() -> pd.Series:
    """TSIFRGHT year-over-year in %, indexed by observation month (first of month on FRED).

    Each month is compared with the same month a year earlier by date, not by position, so a
    missing month cannot shift the comparison.
    """
    raw = fetch_fred_series(_TSI_SERIES, lookback_days=config.FREIGHT_FRED_LOOKBACK_DAYS)
    raw = _finite(raw).sort_index()
    base = raw.reindex(raw.index - pd.DateOffset(months=config.TSIFRGHT_YOY_MONTHS))
    yoy = _finite((raw / base.to_numpy() - 1.0) * 100.0)
    if yoy.empty:
        raise ValueError("TSIFRGHT has no month with a year-earlier value")
    return yoy


def _rail_series() -> tuple[pd.Series, pd.Series]:
    """``(weekly totals, year-over-year %)``; the YoY has at least one measurable week."""
    weekly = rail.fetch_rail_weekly()
    yoy = _finite(rail.rail_yoy(weekly))
    if yoy.empty:
        raise ValueError("rail history too short for a year-over-year read")
    return weekly, yoy


def _carry(yoy: pd.Series, anchor: dict, key: str, as_of_of, today: date) -> pd.Series:
    """Daily scores of one input: each reading public ``PUBLICATION_LAG_DAYS[key]`` days after
    its period ends, carried forward, and dropped once older than the freshness drop window."""
    lag = timedelta(days=config.PUBLICATION_LAG_DAYS[key])
    rows = []
    for stamp, value in yoy.items():
        as_of = as_of_of(stamp.date())
        rows.append((pd.Timestamp(as_of + lag), pd.Timestamp(as_of), safe_score(float(value), anchor)))
    frame = pd.DataFrame(rows, columns=["available", "as_of", "score"]).dropna()
    frame = frame.drop_duplicates("available", keep="last").set_index("available")
    full = pd.date_range(frame.index.min().normalize(), pd.Timestamp(today), freq="D")
    daily = frame.reindex(full).ffill()
    age = (daily.index.to_series() - daily["as_of"]).dt.days
    return daily["score"].where(age <= config.FRESHNESS[key][1])


class FreightProvider(BaseProvider):
    """Freight Volume - BTS Freight TSI and weekly STB rail volume, year over year."""

    category = "freight"

    # ------------------------------------------------------------------ current

    def _tsifrght_reading(self, today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            yoy = _tsifrght_yoy()
            value = float(yoy.iloc[-1])
            as_of = period_end(yoy.index[-1].date(), "M")
            reading = InputReading(
                _TSI, score_raw(value, anchor), as_of, _SOURCES[_TSI],
                f"{value:+.1f}% YoY ({as_of:%b %Y})", freshness_status(as_of, today, _TSI))
            return reading, value
        except Exception as exc:
            logger.warning("TSIFRGHT unavailable: %s", exc)
            return _missing(_TSI), None

    def _rail_reading(self, today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            weekly, yoy = _rail_series()
            value = float(yoy.iloc[-1])
            as_of = yoy.index[-1].date()
            units = float(weekly.loc[yoy.index[-1]])
            reading = InputReading(
                _RAIL, score_raw(value, anchor), as_of, _SOURCES[_RAIL],
                f"{value:+.1f}% YoY (4 weeks to {as_of:%b %d}; {units:,.0f} carloads and intermodal "
                "units that week)", freshness_status(as_of, today, _RAIL))
            return reading, value
        except Exception as exc:
            logger.warning("Rail volume unavailable: %s", exc)
            return _missing(_RAIL), None

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchors = _anchors()
        tsi, tsi_value = self._tsifrght_reading(today, anchors[_TSI])
        rail_reading, rail_value = self._rail_reading(today, anchors[_RAIL])
        readings = [tsi, rail_reading]

        score, status = blend_inputs(readings, config.FREIGHT_WEIGHTS)
        if score is None:
            raise no_inputs_error(readings, "no freight input available: " + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        sentences = ["This category measures goods moving, the demand side of freight: a contraction "
                     "in volume is bad. It is not a congestion or cost gauge."]
        if tsi in used:
            sentences.append(
                f"The BTS Freight Transportation Services Index, the volume of for-hire freight moved "
                f"by trucks, rail, barges, pipelines and air, was {'up' if tsi_value >= 0 else 'down'} "
                f"{abs(tsi_value):.1f}% in {tsi.as_of:%B %Y} from a year earlier.")
        if rail_reading in used:
            sentences.append(
                f"US railroads originated {abs(rail_value):.1f}% {'more' if rail_value >= 0 else 'fewer'} "
                f"carloads and intermodal units over the four weeks to {rail_reading.as_of:%B %d} than "
                "in the same four weeks a year earlier.")
        weights = ", ".join(f"{label} {config.FREIGHT_WEIGHTS[key]:.0%}" for key, label in
                            ((_TSI, "BTS Freight TSI"), (_RAIL, "rail volume")))
        metadata = {
            "source": "; ".join(r.source for r in used),
            "raw_value": " / ".join(r.raw_value for r in used),
            "raw_label": "Freight volume growth, year over year: BTS Freight TSI; rail carloads plus "
                         "intermodal units (4-week mean)",
            "description": " ".join(sentences),
            "calculation": (
                "Each year-over-year growth rate is mapped through its anchors (healthiest 5% of "
                "pre-2020 history = 100, pre-2020 median = 80, worst on record = 0). TSIFRGHT is "
                f"compared with the same month a year earlier; rail is the {config.RAIL_MEAN_WEEKS}-week "
                f"mean of originated carloads plus intermodal units against the same mean "
                f"{config.RAIL_YOY_LAG_WEEKS} weeks earlier. Weights {weights}, renormalized over the "
                "inputs available. TSIFRGHT is published about 80 days after its month ends, rail "
                "about 5 days after its week ends."),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    @staticmethod
    def _tsifrght_history(today: date, anchor: dict) -> pd.Series:
        return _carry(_tsifrght_yoy(), anchor, _TSI, lambda d: period_end(d, "M"), today)

    @staticmethod
    def _rail_history(today: date, anchor: dict) -> pd.Series:
        return _carry(_rail_series()[1], anchor, _RAIL, lambda d: d, today)

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchors = _anchors()
        builders = {_TSI: self._tsifrght_history, _RAIL: self._rail_history}
        scores = {}
        for key, build in builders.items():
            try:
                scores[key] = build(today, anchors[key])
            except Exception as exc:
                logger.warning("Freight %s history unavailable: %s", key, exc)
        if not scores:
            raise RuntimeError("no freight history available")

        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        frame = pd.DataFrame({k: v.reindex(window) for k, v in scores.items()})
        w = pd.Series({k: config.FREIGHT_WEIGHTS[k] for k in frame.columns})
        weight_sum = frame.notna().mul(w, axis=1).sum(axis=1)
        blend = frame.mul(w, axis=1).sum(axis=1, skipna=True) / weight_sum
        out = blend.where(weight_sum > 0).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no freight history available")
        return out.rename("freight")
