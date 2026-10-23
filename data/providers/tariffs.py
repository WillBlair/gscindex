"""
Trade & Tariffs Provider
=========================
How much trade policy is costing supply chains, from two inputs (weights in
``config.TARIFF_WEIGHTS``, renormalized over the inputs available):

    1. Tariff burden (60%) - customs deposits in the Daily Treasury Statement as a share of
       goods imports (FRED ``BOPGIMP``), both summed over three months. Duties arrive mostly
       the month after goods are imported, so deposits of month m+1 pair with imports of
       month m. Deposits are gross of IEEPA refunds.
    2. Trade Policy Uncertainty (40%) - the 30-day mean of the daily Caldara et al. index.

Each input is mapped through its anchors (healthiest 5% of pre-2020 history = 100, pre-2020
median = 80, worst on record = 0). FRED ``EPUTRADE`` is shown on hover as context only.

The burden is monthly: month m is scored once deposits for m+1 are complete and BOPGIMP is
published for m. In history it is available from the later of period end of m+1 plus the DTS
lag and period end of m plus the BOPGIMP lag.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.readings import (
    InputReading, freshness_status, inputs_metadata, oldest_as_of, period_end, blend_inputs)
from data.sources import tpu, treasury
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_BURDEN, _TPU = "tariff_burden", "tpu"
_IMPORTS_SERIES = "BOPGIMP"
_CONTEXT_SERIES = "EPUTRADE"
_SOURCES = {
    _BURDEN: "Treasury Daily Treasury Statement customs deposits / goods imports (FRED BOPGIMP)",
    _TPU: "Trade Policy Uncertainty index (Caldara et al.), 30-day mean",
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _anchors() -> dict[str, dict]:
    """Both anchors; a missing one is a RuntimeError, not a KeyError."""
    return {key: get_anchor(key) for key in config.TARIFF_WEIGHTS}


def _missing(name: str) -> InputReading:
    return InputReading(name, None, None, _SOURCES[name], status="missing")


def _burden_series() -> pd.Series:
    """Burden in percent, indexed by the last month of each 3-month window."""
    customs = treasury.fetch_customs_monthly()
    imports = fetch_fred_series(_IMPORTS_SERIES, lookback_days=config.TARIFFS_FRED_LOOKBACK_DAYS)
    burden = treasury.tariff_burden_series(customs, imports)
    if burden.empty:
        raise ValueError("no month has both 3-month customs and goods imports sums")
    return burden


def _tpu_mean_series() -> pd.Series:
    """30-day mean of the daily index; days without enough observations are dropped."""
    daily, _ = tpu.fetch_tpu()
    mean = daily.rolling(config.TPU_MEAN_DAYS, min_periods=config.TPU_MIN_PERIODS).mean().dropna()
    if mean.empty:
        raise ValueError("not enough daily TPU observations for a 30-day mean")
    return mean


def _safe_score(value: float, anchor: dict) -> float:
    if not (math.isfinite(value) and (anchor["transform"] != "log" or value > 0)):
        return float("nan")
    return score_raw(value, anchor)


class TariffsProvider(BaseProvider):
    """Trade & Tariffs - customs burden and daily trade policy uncertainty."""

    category = "tariffs"

    # ------------------------------------------------------------------ current

    def _burden_reading(self, today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            burden = _burden_series()
            value = float(burden.iloc[-1])
            as_of = period_end(burden.index[-1].date(), "M")
            reading = InputReading(
                _BURDEN, score_raw(value, anchor), as_of, _SOURCES[_BURDEN],
                f"{value:.2f}% of goods imports (3 months to {as_of:%b %Y})",
                freshness_status(as_of, today, _BURDEN))
            return reading, value
        except Exception as exc:
            logger.warning("Tariff burden unavailable: %s", exc)
            return _missing(_BURDEN), None

    def _tpu_reading(self, today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            mean = _tpu_mean_series()
            value = float(mean.iloc[-1])
            as_of = mean.index[-1].date()
            reading = InputReading(
                _TPU, score_raw(value, anchor), as_of, _SOURCES[_TPU],
                f"{value:.1f} (30-day mean of the daily index)",
                freshness_status(as_of, today, _TPU))
            return reading, value
        except Exception as exc:
            logger.warning("Trade policy uncertainty unavailable: %s", exc)
            return _missing(_TPU), None

    @staticmethod
    def _context() -> str:
        """Latest EPUTRADE print as a hover line; never raises."""
        try:
            raw = fetch_fred_series(_CONTEXT_SERIES, lookback_days=config.TARIFFS_FRED_LOOKBACK_DAYS)
            raw = raw.dropna()
            if raw.empty:
                return ""
            return (f"For context, the newspaper-based trade policy uncertainty index on FRED "
                    f"({_CONTEXT_SERIES}) was {float(raw.iloc[-1]):.1f} in "
                    f"{raw.index[-1]:%b %Y}; it is not scored.")
        except Exception as exc:
            logger.info("EPUTRADE context unavailable: %s", exc)
            return ""

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchors = _anchors()
        burden, burden_value = self._burden_reading(today, anchors[_BURDEN])
        uncertainty, tpu_value = self._tpu_reading(today, anchors[_TPU])
        readings = [burden, uncertainty]

        score, status = blend_inputs(readings, config.TARIFF_WEIGHTS)
        if score is None:
            raise RuntimeError("no tariff input available: " + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        sentences = []
        if burden in used:
            sentences.append(
                f"Customs duties deposited to the US Treasury, paid mostly the month after goods are "
                f"imported, were {burden_value:.2f}% of goods imports over the three months to "
                f"{burden.as_of:%B %Y}. Deposits are gross of IEEPA refunds, so the burden can "
                "overstate what importers end up paying.")
        if uncertainty in used:
            sentences.append(
                f"Trade Policy Uncertainty, a daily index built from newspaper coverage, averaged "
                f"{tpu_value:.1f} over the last 30 days.")
        sentences.append(self._context())
        weights = ", ".join(f"{label} {config.TARIFF_WEIGHTS[key]:.0%}" for key, label in
                            ((_BURDEN, "tariff burden"), (_TPU, "trade policy uncertainty")))
        metadata = {
            "source": "; ".join(r.source for r in used),
            "raw_value": " / ".join(r.raw_value for r in used),
            "raw_label": "Customs duties as % of goods imports; Trade Policy Uncertainty (30-day mean)",
            "description": " ".join(s for s in sentences if s),
            "calculation": (
                "Each input is mapped through its anchors (healthiest 5% of pre-2020 history = 100, "
                "pre-2020 median = 80, worst on record = 0): the burden as customs deposits over "
                f"goods imports, {config.TARIFF_BURDEN_MONTHS}-month sums with deposits shifted back one month "
                "(month m+1 deposits against month m imports), and the TPU 30-day mean on a log "
                f"scale. Weights {weights}, renormalized over the inputs available."),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    @staticmethod
    def _burden_history(today: date, anchor: dict) -> pd.Series:
        """Monthly burden scores, available once both inputs are public, carried forward.

        Month m is public at the later of period end of m+1 plus the DTS lag (its deposits)
        and period end of m plus the BOPGIMP lag (its imports). A value is dropped once the
        month is older than the freshness drop window.
        """
        burden = _burden_series()
        lags = config.PUBLICATION_LAG_DAYS
        rows = []
        for month, value in burden.items():
            end = period_end(month.date(), "M")
            nxt = period_end((month + pd.DateOffset(months=1)).date(), "M")
            available = max(nxt + timedelta(days=lags["dts"]), end + timedelta(days=lags["bopgimp"]))
            rows.append((pd.Timestamp(available), pd.Timestamp(end), _safe_score(value, anchor)))
        frame = pd.DataFrame(rows, columns=["available", "as_of", "score"]).dropna()
        frame = frame.drop_duplicates("available", keep="last").set_index("available")
        full = pd.date_range(frame.index.min().normalize(), pd.Timestamp(today), freq="D")
        daily = frame.reindex(full).ffill()
        age = (daily.index.to_series() - daily["as_of"]).dt.days
        return daily["score"].where(age <= config.FRESHNESS[_BURDEN][1])

    @staticmethod
    def _tpu_history(today: date, anchor: dict) -> pd.Series:
        """Daily 30-day-mean scores, dated by the day they cover and carried to today.

        The workbook is the publication, so nothing is shifted forward by a lag.
        """
        mean = _tpu_mean_series()
        scores = pd.Series([_safe_score(v, anchor) for v in mean], index=mean.index).dropna()
        full = pd.date_range(scores.index.min().normalize(), pd.Timestamp(today), freq="D")
        return scores.reindex(full).ffill(limit=config.FRESHNESS[_TPU][1])

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchors = _anchors()
        builders = {_BURDEN: self._burden_history, _TPU: self._tpu_history}
        scores = {}
        for key, build in builders.items():
            try:
                scores[key] = build(today, anchors[key])
            except Exception as exc:
                logger.warning("Tariffs %s history unavailable: %s", key, exc)
        if not scores:
            raise RuntimeError("no tariff history available")

        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        frame = pd.DataFrame({k: v.reindex(window) for k, v in scores.items()})
        w = pd.Series({k: config.TARIFF_WEIGHTS[k] for k in frame.columns})
        weight_sum = frame.notna().mul(w, axis=1).sum(axis=1)
        blend = frame.mul(w, axis=1).sum(axis=1, skipna=True) / weight_sum
        out = blend.where(weight_sum > 0).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no tariff history available")
        return out.rename("tariffs")
