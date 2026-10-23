"""
Semiconductor sector categories
===============================
Three one-input categories that make up the Semis index (``config.SECTORS["semiconductor"]``):

    semis_memory_prices    - Bank of Japan import price index for MOS memory integrated circuits
                             (contract-currency basis, series PRCG20_2500850005), year over year.
    semis_logic_prices     - Bank of Japan import price index for MOS logic integrated circuits
                             (contract-currency basis, series PRCG20_2500850004), year over year.
    semis_fab_utilization  - Fed G.17 capacity utilization, semiconductors and other electronic
                             components (FRED CAPUTLG3344S), level in percent.

Every input is mapped through ``get_anchor(<input key>)`` (healthiest 5% of pre-2020 history = 100,
pre-2020 median = 80, worst month through 2025 = 0). All three are cost or tightness gauges:
lower price growth and lower utilization read as healthier. A missing anchor is a RuntimeError.

An input that cannot be fetched or parsed, has no finite value, or whose year-earlier base is
not positive counts as missing and the category raises; a neutral constant is never returned.
When the only reading is past its drop window the provider raises ``InputsExpired``.

History dates each month by its period end plus the source's publication lag
(``PUBLICATION_LAG_DAYS``) and carries it forward until it is older than its drop window.
Months before the first measurable value stay gaps.

Sector categories are not part of the global composite; the aggregator runs them separately.
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
    InputReading, blend_inputs, freshness_status, inputs_metadata, no_inputs_error, oldest_as_of,
    period_end)
from data.sources import boj
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_YOY_MONTHS = 12
_BOJ_CATEGORY = "Corporate Goods Price Index (2020 base), import price index, contract-currency basis"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _finite(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _yoy_percent(levels: pd.Series) -> pd.Series:
    """Year-over-year % of a monthly index, comparing each month with the same month a year
    earlier by date (a missing month cannot shift the comparison). A month whose base is
    missing or not positive has no value."""
    levels = _finite(levels).sort_index()
    base = levels.reindex(levels.index - pd.DateOffset(months=_YOY_MONTHS)).to_numpy()
    base = np.where(base > 0, base, np.nan)
    return _finite(pd.Series((levels.to_numpy() / base - 1.0) * 100.0, index=levels.index))


def _safe_score(value: float, anchor: dict) -> float:
    return score_raw(value, anchor) if math.isfinite(value) else float("nan")


def monthly_daily(scores: pd.Series, lag_days: int, drop_after: int, today: date) -> pd.Series:
    """Monthly scores on a daily index: each public ``lag_days`` after its month ends, carried
    forward until it is ``drop_after`` days past the period end. Empty input gives an empty series."""
    scores = scores.dropna()
    if scores.empty:
        return scores.astype(float)
    dated = scores.copy()
    dated.index = pd.DatetimeIndex([pd.Timestamp(period_end(d.date(), "M")) + pd.Timedelta(days=lag_days)
                                    for d in scores.index])
    dated = dated[~dated.index.duplicated(keep="last")]
    full = pd.date_range(dated.index.min().normalize(), pd.Timestamp(today), freq="D")
    return dated.reindex(full).ffill(limit=max(drop_after - lag_days, 0))


class _SemisProvider(BaseProvider):
    """One anchored monthly input becomes one sector category."""

    input_key: str = ""         # anchor and FRESHNESS key
    lag_key: str = ""           # PUBLICATION_LAG_DAYS key
    source: str = ""            # reading source text
    raw_label: str = ""
    description: str = ""
    calculation: str = ""
    credits_boj: bool = False

    def _monthly(self) -> pd.Series:
        """Finite monthly measure (what the anchor is fitted on), indexed by month start."""
        raise NotImplementedError

    @staticmethod
    def _raw_text(value: float, month: pd.Timestamp) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------------ current

    def _reading(self, today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            monthly = self._monthly()
            if monthly.empty:
                raise ValueError("no measurable month")
            month, value = monthly.index[-1], float(monthly.iloc[-1])
            as_of = min(period_end(month.date(), "M"), today)   # a month still in progress is as of today
            reading = InputReading(
                self.input_key, score_raw(value, anchor), as_of, self.source, self._raw_text(value, month),
                freshness_status(as_of, today, self.input_key))
            return reading, value
        except Exception as exc:
            logger.warning("%s unavailable: %s", self.category, exc)
            return InputReading(self.input_key, None, None, f"{self.source}: unavailable",
                                status="missing"), None

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchor = get_anchor(self.input_key)
        reading, _ = self._reading(today, anchor)
        score, status = blend_inputs([reading], {self.input_key: 1.0})
        if score is None:
            raise no_inputs_error([reading], f"no {self.category} input available: {reading.source}")
        description = f"{self.description} {config.BOJ_CREDIT}" if self.credits_boj else self.description
        metadata = {
            "source": reading.source,
            "raw_value": reading.raw_value,
            "raw_label": self.raw_label,
            "description": description,
            "calculation": self.calculation,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of([reading]).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata([reading]),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchor = get_anchor(self.input_key)
        monthly = self._monthly()
        scores = pd.Series([_safe_score(float(v), anchor) for v in monthly], index=monthly.index, dtype=float)
        daily = monthly_daily(scores, config.PUBLICATION_LAG_DAYS[self.lag_key],
                              config.FRESHNESS[self.input_key][1], today)
        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        out = daily.reindex(window).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError(f"no {self.category} history available")
        return out.rename(self.category)


class _BojProvider(_SemisProvider):
    lag_key = "boj_cgpi"
    credits_boj = True
    code: str = ""

    def _monthly(self) -> pd.Series:
        return _yoy_percent(boj.fetch_series(self.code))

    @staticmethod
    def _raw_text(value: float, month: pd.Timestamp) -> str:
        return f"{value:+.1f}% YoY ({month:%b %Y})"


class MemoryPricesProvider(_BojProvider):
    """Memory Prices: Japan's import prices for memory chips, year over year."""

    category = "semis_memory_prices"
    input_key = "boj_memory"
    code = "PRCG20_2500850005"
    source = f"Bank of Japan {_BOJ_CATEGORY}: MOS memory integrated circuits ({code})"
    raw_label = "Memory chip import price index, YoY %"
    description = (
        "Year-over-year change in what Japan pays for imported memory chips, measured in the currency of "
        "the contract so yen swings do not move it. Fast price growth signals tight memory supply and "
        "rising costs for chip buyers. Falling prices read as healthier for buyers, though a price drop "
        "from weak demand is not measured here.")
    calculation = (
        "Year-over-year % change of the monthly index, mapped through anchors (healthiest 5% of pre-2020 "
        "history = 100, pre-2020 median = 80, worst month on record through 2025 = 0). Lower growth scores "
        "higher.")


class LogicPricesProvider(_BojProvider):
    """Logic Chip Prices: Japan's import prices for logic chips, year over year."""

    category = "semis_logic_prices"
    input_key = "boj_logic"
    code = "PRCG20_2500850004"
    source = f"Bank of Japan {_BOJ_CATEGORY}: MOS logic integrated circuits ({code})"
    raw_label = "Logic chip import price index, YoY %"
    description = (
        "Year-over-year change in what Japan pays for imported logic chips (processors and other "
        "non-memory chips), measured in the currency of the contract. Fast price growth signals tight "
        "supply and rising costs for chip buyers. Falling prices read as healthier for buyers, though a "
        "price drop from weak demand is not measured here.")
    calculation = MemoryPricesProvider.calculation


class FabUtilizationProvider(_SemisProvider):
    """Fab Utilization: share of US semiconductor and electronic component capacity in use."""

    category = "semis_fab_utilization"
    input_key = "fab_util_3344"
    lag_key = "g17"
    series_id = "CAPUTLG3344S"
    source = f"Federal Reserve G.17 capacity utilization, semiconductors and other electronic components (FRED {series_id})"
    raw_label = "Capacity utilization, %"
    description = (
        "Share of US semiconductor and electronic component manufacturing capacity in use, from the "
        "Federal Reserve's industrial production report. Utilization near the top of its range leaves "
        "little spare capacity to absorb a demand jump, so lower utilization reads as healthier on this "
        "index.")
    calculation = (
        "Utilization level in percent, mapped through anchors (healthiest 5% of pre-2020 history = 100, "
        "pre-2020 median = 80, worst month on record through 2025 = 0). Lower utilization scores higher.")

    def _monthly(self) -> pd.Series:
        raw = fetch_fred_series(self.series_id, lookback_days=config.SEMIS_FRED_LOOKBACK_DAYS)
        return _finite(raw).sort_index()

    @staticmethod
    def _raw_text(value: float, month: pd.Timestamp) -> str:
        return f"{value:.1f}% ({month:%b %Y})"
