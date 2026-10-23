"""
Aerospace sector categories
===========================
Four categories that make up the Aero index (``config.SECTORS["aerospace"]``). All data is FRED:

    aero_throughput   - Fed G.17 capacity utilization, aerospace and miscellaneous transportation
                        equipment (CAPUTLG3364T9S), level in percent. Higher is healthier.
    aero_flow         - Census M3 nondefense aircraft and parts: inventories (ANAPTI) divided by the
                        3-month mean of shipments (ANAPVS), in months, log scale. Lower is healthier.
    aero_mill_prices  - BLS PPI mill shapes, year over year: titanium and titanium-base alloy
                        (WPU102505) and nickel and nickel-base alloy (WPU102504). Lower is healthier.
    aero_forge_cast   - BLS PPI, year over year: titanium forgings (PCU33211233211242), nonferrous
                        forging (PCU332112332112) and steel investment castings (PCU3315123315120).
                        Lower is healthier.

Series titles were confirmed on FRED on 2026-10-23. Each input is mapped through
``get_anchor(<input key>)`` (healthiest 5% of pre-2020 history = 100, pre-2020 median = 80, worst
month through 2025 = 0). A missing anchor is a RuntimeError. A category with several inputs is the
equal-weight mean of the inputs that are present.

The latest month of an input must be measurable: a non-finite value, a year-earlier base that is
not positive, or a 3-month mean of shipments at or below zero makes that input missing for now. It
never falls back to an older month and never becomes an extreme score. A category with no usable
input raises; a neutral constant is never returned. When the only readings are past their drop
window the provider raises ``InputsExpired``.

History dates each month by its period end plus the source's publication lag
(``PUBLICATION_LAG_DAYS``: G.17 16, M3 35, PPI 15 days) and carries it forward until it is older
than the drop window. Months before the first measurable value stay gaps.

Sector categories are not part of the global composite; the aggregator runs them separately.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import numpy as np
import pandas as pd

import config
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.readings import (
    InputReading, blend_inputs, finite_series, freshness_status, inputs_metadata, monthly_daily, no_inputs_error,
    oldest_as_of, period_end, safe_score, yoy_percent)
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_SHIPMENT_MONTHS = 3


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ------------------------------------------------------------------ measures
# Each takes the finite monthly FRED series by id and returns the measure the anchor was fitted
# on, indexed by month start. NaN marks a month that cannot be measured; it is never dropped here
# so the latest month is judged as it is.

def _level(series_id: str) -> Callable[[dict[str, pd.Series]], pd.Series]:
    return lambda data: data[series_id]


def _yoy(series_id: str) -> Callable[[dict[str, pd.Series]], pd.Series]:
    def measure(data: dict[str, pd.Series]) -> pd.Series:
        levels = data[series_id]
        return yoy_percent(levels).reindex(levels.index)
    return measure


def _flow(data: dict[str, pd.Series]) -> pd.Series:
    """Inventories over the mean of the month's and the two earlier months' shipments, in months.
    A month missing from any of the three, or a mean that is not positive, has no value."""
    inventories, shipments = data["ANAPTI"], data["ANAPVS"]
    months = inventories.index.intersection(shipments.index)
    mean = sum(shipments.reindex(months - pd.DateOffset(months=k)).to_numpy()
               for k in range(_SHIPMENT_MONTHS)) / _SHIPMENT_MONTHS
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(np.isfinite(mean) & (mean > 0), inventories.reindex(months).to_numpy() / mean, np.nan)
    ratio = np.where(np.isfinite(ratio) & (ratio > 0), ratio, np.nan)
    return pd.Series(ratio, index=months, dtype=float)


def _pct_text(value: float, month: pd.Timestamp) -> str:
    return f"{value:+.1f}% YoY ({month:%b %Y})"


def _level_text(value: float, month: pd.Timestamp) -> str:
    return f"{value:.1f}% ({month:%b %Y})"


def _flow_text(value: float, month: pd.Timestamp) -> str:
    return f"{value:.1f} months of shipments ({month:%b %Y})"


@dataclass(frozen=True)
class _Input:
    key: str                       # anchor and FRESHNESS key
    short: str                     # name used in a category's raw_value when it has several inputs
    lag_key: str                   # PUBLICATION_LAG_DAYS key
    source: str
    series_ids: tuple[str, ...]
    measure: Callable[[dict[str, pd.Series]], pd.Series]
    text: Callable[[float, pd.Timestamp], str]

    def monthly(self) -> pd.Series:
        """The anchored measure by month, sorted, with NaN for unmeasurable months."""
        data = {sid: finite_series(fetch_fred_series(sid, lookback_days=config.AERO_FRED_LOOKBACK_DAYS)).sort_index()
                for sid in self.series_ids}
        monthly = self.measure(data).sort_index()
        if monthly.empty:
            raise ValueError("no observations")
        return monthly


def _ppi(key: str, short: str, series_id: str, name: str) -> _Input:
    return _Input(key, short, "bls_ppi", f"BLS Producer Price Index, {name} (FRED {series_id})",
                  (series_id,), _yoy(series_id), _pct_text)


_CAPUTL = _Input(
    "aero_caputl", "Utilization", "g17",
    "Federal Reserve G.17 capacity utilization, aerospace and miscellaneous transportation equipment "
    "(FRED CAPUTLG3364T9S)",
    ("CAPUTLG3364T9S",), _level("CAPUTLG3364T9S"), _level_text)

_FLOW = _Input(
    "aero_inv_ship", "Inventory to shipments", "census_m3",
    "Census M3 nondefense aircraft and parts: inventories (FRED ANAPTI) over a 3-month mean of "
    "shipments (FRED ANAPVS)",
    ("ANAPTI", "ANAPVS"), _flow, _flow_text)

_TI_MILL = _ppi("ppi_ti_mill", "Titanium", "WPU102505", "titanium and titanium-base alloy mill shapes")
_NI_MILL = _ppi("ppi_ni_mill", "Nickel alloy", "WPU102504", "nickel and nickel-base alloy mill shapes")
_TI_FORGE = _ppi("ppi_ti_forge", "Titanium forgings", "PCU33211233211242", "titanium and titanium alloy forgings")
_NF_FORGE = _ppi("ppi_nonferrous_forge", "Nonferrous forgings", "PCU332112332112", "nonferrous forging")
_CAST = _ppi("ppi_steel_invest_cast", "Steel castings", "PCU3315123315120", "steel investment castings")

_PRICE_CALCULATION = (
    "Each input is the year-over-year % change of a monthly index, mapped through anchors (healthiest "
    "5% of pre-2020 history = 100, pre-2020 median = 80, worst month on record through 2025 = 0). "
    "Lower growth scores higher. The category is the equal-weight mean of the inputs that are "
    "available.")


class _AeroProvider(BaseProvider):
    """Equal-weight mean of one or more anchored monthly inputs becomes one sector category."""

    inputs: tuple[_Input, ...] = ()
    raw_label: str = ""
    description: str = ""
    calculation: str = ""

    # ------------------------------------------------------------------ current

    def _reading(self, spec: _Input, today: date, anchor: dict) -> InputReading:
        try:
            monthly = spec.monthly()
            month, value = monthly.index[-1], float(monthly.iloc[-1])
            if not math.isfinite(value):
                raise ValueError(f"{month:%Y-%m} cannot be measured")
            as_of = min(period_end(month.date(), "M"), today)    # a month still in progress is as of today
            return InputReading(spec.key, score_raw(value, anchor), as_of, spec.source, spec.text(value, month),
                                freshness_status(as_of, today, spec.key))
        except Exception as exc:
            logger.warning("%s input %s unavailable: %s", self.category, spec.key, exc)
            return InputReading(spec.key, None, None, f"{spec.source}: unavailable", status="missing")

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchors = {spec.key: get_anchor(spec.key) for spec in self.inputs}
        readings = [self._reading(spec, today, anchors[spec.key]) for spec in self.inputs]
        score, status = blend_inputs(readings, {spec.key: 1.0 for spec in self.inputs})
        if score is None:
            raise no_inputs_error(readings, f"no {self.category} input available: "
                                            + "; ".join(r.source for r in readings))
        used = [(spec, r) for spec, r in zip(self.inputs, readings) if r.status != "missing"]
        single = len(self.inputs) == 1
        metadata = {
            "source": "; ".join(r.source for _, r in used),
            "raw_value": "; ".join(r.raw_value if single else f"{spec.short} {r.raw_value}" for spec, r in used),
            "raw_label": self.raw_label,
            "description": self.description,
            "calculation": self.calculation,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    def _input_history(self, spec: _Input, anchor: dict, today: date) -> pd.Series:
        monthly = spec.monthly()
        scores = pd.Series([safe_score(float(v), anchor) for v in monthly], index=monthly.index, dtype=float)
        return monthly_daily(scores, config.PUBLICATION_LAG_DAYS[spec.lag_key], config.FRESHNESS[spec.key][1], today)

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchors = {spec.key: get_anchor(spec.key) for spec in self.inputs}
        daily = []
        for spec in self.inputs:
            try:
                daily.append(self._input_history(spec, anchors[spec.key], today))
            except Exception as exc:
                logger.warning("%s history input %s unavailable: %s", self.category, spec.key, exc)
        if not daily:
            raise RuntimeError(f"no {self.category} history available")
        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        combined = pd.concat([d.reindex(window) for d in daily], axis=1).mean(axis=1, skipna=True)
        out = combined.clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError(f"no {self.category} history available")
        return out.rename(self.category)


class ThroughputProvider(_AeroProvider):
    """Aero Throughput: share of US aerospace manufacturing capacity in use."""

    category = "aero_throughput"
    inputs = (_CAPUTL,)
    raw_label = "Capacity utilization, %"
    description = (
        "Share of US aerospace and miscellaneous transportation equipment manufacturing capacity in use, "
        "from the Federal Reserve's industrial production report. Plants running near their normal rate "
        "are turning out aircraft and parts at a steady pace, so higher utilization reads as healthier. "
        "Low utilization caused by weak orders rather than supply trouble is not separated out.")
    calculation = (
        "Utilization level in percent, mapped through anchors (healthiest 5% of pre-2020 history = 100, "
        "pre-2020 median = 80, worst month on record through 2025 = 0). Higher utilization scores higher.")


class FlowProvider(_AeroProvider):
    """Delivery Flow: months of shipments sitting in aircraft and parts inventory."""

    category = "aero_flow"
    inputs = (_FLOW,)
    raw_label = "Inventories over 3-month mean shipments, months"
    description = (
        "Months of current shipments sitting in inventory at US nondefense aircraft and parts makers: "
        "inventories divided by the average of the last three months of shipments. Work piling up "
        "unshipped points to a blockage somewhere in the line, so a lower ratio reads as healthier.")
    calculation = (
        "Inventories divided by the 3-month mean of shipments, put on a log scale and mapped through "
        "anchors (healthiest 5% of pre-2020 history = 100, pre-2020 median = 80, worst month on record "
        "through 2025 = 0). A month with no positive 3-month mean of shipments is not scored. A lower "
        "ratio scores higher.")


class MillPricesProvider(_AeroProvider):
    """Mill Prices: producer prices for titanium and nickel-alloy mill shapes, year over year."""

    category = "aero_mill_prices"
    inputs = (_TI_MILL, _NI_MILL)
    raw_label = "Mill shape producer prices, YoY %"
    description = (
        "Year-over-year change in producer prices for titanium and nickel-alloy mill shapes, the metal "
        "that aircraft and engine makers buy before forging or machining it. Fast price growth signals "
        "tight supply and rising input costs. Lower growth reads as healthier, though a price drop from "
        "weak demand is not separated out.")
    calculation = _PRICE_CALCULATION


class ForgeCastProvider(_AeroProvider):
    """Forgings and Castings: producer prices for forged and cast aircraft parts, year over year."""

    category = "aero_forge_cast"
    inputs = (_TI_FORGE, _NF_FORGE, _CAST)
    raw_label = "Forging and casting producer prices, YoY %"
    description = (
        "Year-over-year change in producer prices for titanium forgings, nonferrous forgings and steel "
        "investment castings, the shaped parts that go into engines and airframes. Fast price growth "
        "signals tight capacity at the few shops that make them. Lower growth reads as healthier, though "
        "a price drop from weak demand is not separated out.")
    calculation = _PRICE_CALCULATION
