"""
Input Costs Provider
====================
What manufacturers pay for their inputs, from three inputs (weights in
``config.INPUT_WEIGHTS``, renormalized over the inputs available):

    1. Regional Fed prices paid (50%) - Philadelphia, Empire State and Dallas manufacturing
       surveys (FRED, see ``data/sources/fed_surveys.py``). Each survey is z-scored against its
       own 2004-2019 mean and sd (``SCORE_ANCHORS["prices_paid_stats"]``), the available z values
       are averaged per month, and the composite is mapped through its anchors.
    2. Copper (25%)   - IMF monthly price, FRED ``PCOPPUSDM`` ($/mt), live ``HG=F`` ($/lb).
    3. Aluminum (25%) - IMF monthly price, FRED ``PALUMUSDM`` ($/mt), live ``ALI=F`` ($/mt).

Metals are deflated to the CPI reference month (``CPIAUCSL``), logged and mapped through their
anchors; the live quote carries the latest monthly price forward by the Yahoo move since that
month ended (``markets.scale_live``). Supplier delivery times from the Philadelphia and Empire
State surveys are shown in the hover text only and never scored.

This is a COST gauge. Lower prices read as healthier; whether low prices come from weak demand
is not measured here.

History dates each monthly value by its publication lag and carries it forward until it is
older than its drop window.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.prices import clean_prices, cpi_ratios, cpi_reference, cpi_reference_date
from data.providers.readings import (
    InputReading, no_inputs_error, blend_inputs, freshness_status, inputs_metadata, oldest_as_of, period_end)
from data.sources import fed_surveys, markets
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_PP = "prices_paid"
_METALS = {
    # leg: (label, FRED series, live symbol, unit factor from the live quote to the FRED unit)
    "copper": ("Copper", "PCOPPUSDM", "HG=F", config.COPPER_USD_PER_LB_TO_USD_PER_MT),
    "aluminum": ("Aluminum", "PALUMUSDM", "ALI=F", config.ALUMINUM_LIVE_UNIT_FACTOR),
}
_SURVEY_LABELS = {"philly": "Philadelphia", "empire": "Empire State", "dallas": "Dallas"}
_ANCHOR_KEYS = (_PP, "copper", "copper_monthly", "aluminum", "aluminum_monthly")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _fred(series_id: str) -> pd.Series:
    return fetch_fred_series(series_id, lookback_days=config.INPUTS_FRED_LOOKBACK_DAYS)


def _stats() -> dict[str, tuple[float, float]]:
    """Per-survey (mean, sd) from the anchors file; absent or malformed is a RuntimeError."""
    try:
        raw = config.SCORE_ANCHORS["prices_paid_stats"]
        stats = {survey: (float(v[0]), float(v[1])) for survey, v in raw.items()}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise RuntimeError("no anchor for prices_paid_stats") from None
    if not stats:
        raise RuntimeError("no anchor for prices_paid_stats")
    return stats


def _anchors() -> tuple[dict, dict, float]:
    """Input anchors, the survey stats and the CPI reference; a missing one is a RuntimeError."""
    anchors = {key: get_anchor(key) for key in _ANCHOR_KEYS}
    return anchors, _stats(), cpi_reference()


def _safe_score(value: float, anchor: dict, ratio: float | None = None) -> float:
    if not (math.isfinite(value) and (ratio is None or math.isfinite(ratio))):
        return float("nan")
    return score_raw(value, anchor, ratio)


def _monthly_daily(scores: pd.Series, lag_days: int, drop_after: int, today: date) -> pd.Series:
    """Monthly scores on a daily index: each public ``lag_days`` after its month ends, carried
    forward until it is ``drop_after`` days past the period end."""
    scores = scores.dropna()
    dated = scores.copy()
    dated.index = pd.DatetimeIndex([pd.Timestamp(period_end(d.date(), "M")) + pd.Timedelta(days=lag_days)
                                    for d in scores.index])
    dated = dated[~dated.index.duplicated(keep="last")]
    full = pd.date_range(dated.index.min().normalize(), pd.Timestamp(today), freq="D")
    return dated.reindex(full).ffill(limit=max(drop_after - lag_days, 0))


class InputsProvider(BaseProvider):
    """Input Costs - Fed prices paid, copper and aluminum."""

    category = "inputs"

    # ------------------------------------------------------------------ current

    @staticmethod
    def _missing(name: str, source: str) -> InputReading:
        return InputReading(name, None, None, source, status="missing")

    def _prices_paid_reading(self, today: date, anchor: dict,
                             stats: dict) -> tuple[InputReading, list[str]]:
        """The composite reading and the surveys behind the latest month."""
        try:
            surveys = fed_surveys.fetch_prices_paid()
            composite = fed_surveys.prices_paid_composite(surveys, stats)
            if composite.empty:
                raise ValueError("no survey has a usable value")
            month, z = composite.index[-1], float(composite.iloc[-1])
            as_of = min(period_end(month.date(), "M"), today)    # a month still in progress is as of today
            latest = {name: float(s[month]) for name, s in surveys.items()
                      if name in stats and month in s.index and math.isfinite(s[month])}
            ids = ", ".join(f"{_SURVEY_LABELS.get(n, n)} {fed_surveys.PRICES_PAID_SERIES[n]}" for n in latest)
            raw = f"composite z {z:+.2f} in {month:%b %Y}: " + ", ".join(
                f"{_SURVEY_LABELS.get(n, n)} {v:.1f}" for n, v in latest.items())
            reading = InputReading(
                _PP, score_raw(z, anchor), as_of, f"Fed prices paid (FRED: {ids})", raw,
                freshness_status(as_of, today, _PP))
            return reading, [_SURVEY_LABELS.get(n, n) for n in latest]
        except Exception as exc:
            logger.warning("Fed prices paid unavailable: %s", exc)
            return self._missing(_PP, "Fed prices paid: unavailable"), []

    def _metal_reading(self, leg: str, today: date, anchors: dict,
                       ratio_now: float | None) -> tuple[InputReading, float | None]:
        label, series_id, symbol, factor = _METALS[leg]
        missing = self._missing(f"{leg}_monthly", f"{label}: FRED {series_id} unavailable")
        try:
            if ratio_now is None:
                raise ValueError("no CPI deflator")
            monthly = clean_prices(_fred(series_id))
            if monthly.empty:
                raise ValueError("no observations")
            official, month = float(monthly.iloc[-1]), monthly.index[-1].date()
            official_date = period_end(month, "M")
            value, as_of, mode = markets.scale_live(official, official_date, symbol, unit_factor=factor)
            as_of = min(as_of, today)
            name = leg if mode == "live" else f"{leg}_monthly"
            if mode == "live":
                source = f"{label} ({series_id}, {symbol}: live, scaled from the {official_date:%b %Y} average)"
            else:
                source = f"{label} ({series_id}, {symbol}: official monthly average, {official_date:%b %Y})"
            reading = InputReading(name, score_raw(value, anchors[name], ratio_now), as_of, source,
                                   f"${value:,.0f}/mt", freshness_status(as_of, today, name))
            return reading, value
        except Exception as exc:
            logger.warning("Input Costs %s unavailable: %s", label, exc)
            return missing, None

    @staticmethod
    def _delivery_context() -> str:
        """Supplier delivery times sentence for the hover; empty on any failure."""
        try:
            parts = []
            for survey, series in fed_surveys.fetch_delivery_times().items():
                parts.append(f"{_SURVEY_LABELS.get(survey, survey)} {float(series.iloc[-1]):.1f} "
                             f"({series.index[-1]:%b %Y})")
            return ("Supplier delivery times, context only and not scored (above 0 means slower "
                    "deliveries): " + ", ".join(parts) + ".") if parts else ""
        except Exception as exc:
            logger.info("Fed delivery times unavailable: %s", exc)
            return ""

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchors, stats, cpi_ref = _anchors()
        try:
            ratio_now = float(cpi_ratios(_fred, cpi_ref).iloc[-1])
        except RuntimeError as exc:
            logger.warning("Input Costs metals skipped: %s", exc)
            ratio_now = None

        pp, survey_names = self._prices_paid_reading(today, anchors[_PP], stats)
        metals = {leg: self._metal_reading(leg, today, anchors, ratio_now) for leg in _METALS}
        readings = [pp] + [metals[leg][0] for leg in _METALS]

        weights = {**config.INPUT_WEIGHTS,
                   **{f"{leg}_monthly": config.INPUT_WEIGHTS[leg] for leg in _METALS}}
        score, status = blend_inputs(readings, weights)
        if score is None:
            raise no_inputs_error(readings, "no input cost input available: " + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        sentences = [
            "Cost pressure on manufacturers' inputs, not a demand gauge: lower prices read as healthier "
            "whatever their cause."]
        if pp in used:
            names = " and ".join(survey_names) if len(survey_names) < 3 else (
                ", ".join(survey_names[:-1]) + ", and " + survey_names[-1])
            sentences.append(
                f"The {names} Fed manufacturing {'surveys report' if len(survey_names) > 1 else 'survey reports'} "
                "the share of firms paying higher prices; each is compared with its own 2004-2019 range and the "
                f"results are averaged ({pp.raw_value.split(':')[0]}).")
        for leg in _METALS:
            reading, value = metals[leg]
            if reading in used:
                sentences.append(f"{_METALS[leg][0]} is ${value:,.0f} per metric tonne "
                                 f"({'live quote' if reading.name == leg else 'monthly average'}).")
        delivery = self._delivery_context()
        if delivery:
            sentences.append(delivery)

        weight_text = ", ".join(f"{label} {config.INPUT_WEIGHTS[key]:.0%}" for key, label in
                                ((_PP, "prices paid"), ("copper", "copper"), ("aluminum", "aluminum")))
        metadata = {
            "source": "; ".join(r.source for r in readings),
            "raw_value": " / ".join(r.raw_value for r in used),
            "raw_label": "Fed prices-paid composite (z); copper $/mt; aluminum $/mt",
            "description": " ".join(sentences),
            "calculation": (
                "Prices paid: each survey's value minus its 2004-2019 mean, over its sd, averaged over the "
                "surveys reporting that month, then mapped through anchors (healthiest 5% of pre-2020 history "
                "= 100, pre-2020 median = 80, worst monthly average on record = 0). Copper and aluminum: price "
                f"x CPI ratio (to {cpi_reference_date()} dollars), log, same anchors. "
                f"Weights {weight_text}, renormalized over available inputs."),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return round(score, 1), metadata

    # ------------------------------------------------------------------ history

    @staticmethod
    def _prices_paid_history(today: date, anchor: dict, stats: dict) -> pd.Series:
        composite = fed_surveys.prices_paid_composite(fed_surveys.fetch_prices_paid(), stats)
        if composite.empty:
            raise ValueError("no survey has a usable value")
        scores = pd.Series([_safe_score(float(z), anchor) for z in composite], index=composite.index)
        return _monthly_daily(scores, config.PUBLICATION_LAG_DAYS[_PP], config.FRESHNESS[_PP][1], today)

    @staticmethod
    def _metal_history(leg: str, today: date, anchor: dict, ratios: pd.Series) -> pd.Series:
        monthly = clean_prices(_fred(_METALS[leg][1]))
        if monthly.empty:
            raise ValueError("no observations")
        ratio = ratios.reindex(ratios.index.union(monthly.index)).ffill().reindex(monthly.index)
        scores = pd.Series([_safe_score(float(p), anchor, float(r)) for p, r in zip(monthly, ratio)],
                           index=monthly.index)
        return _monthly_daily(scores, config.PUBLICATION_LAG_DAYS["imf_monthly"],
                              config.FRESHNESS[f"{leg}_monthly"][1], today)

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchors, stats, cpi_ref = _anchors()
        try:
            ratios = cpi_ratios(_fred, cpi_ref)
        except RuntimeError as exc:
            logger.warning("Input Costs metal history skipped: %s", exc)
            ratios = None

        builders = {_PP: lambda: self._prices_paid_history(today, anchors[_PP], stats)}
        if ratios is not None:
            for leg in _METALS:
                builders[leg] = (lambda leg=leg: self._metal_history(leg, today, anchors[f"{leg}_monthly"], ratios))
        scores = {}
        for key, build in builders.items():
            try:
                scores[key] = build()
            except Exception as exc:
                logger.warning("Input Costs %s history unavailable: %s", key, exc)
        if not scores:
            raise RuntimeError("no input costs history available")

        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        frame = pd.DataFrame({k: v.reindex(window) for k, v in scores.items()})
        w = pd.Series({k: config.INPUT_WEIGHTS[k] for k in frame.columns})
        weight_sum = frame.notna().mul(w, axis=1).sum(axis=1)
        blend = frame.mul(w, axis=1).sum(axis=1, skipna=True) / weight_sum
        out = blend.where(weight_sum > 0).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no input costs history available")
        return out.rename("inputs")
