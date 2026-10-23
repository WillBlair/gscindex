"""
Physical Disruption Provider
============================
Physical events that stop ships, from three inputs (weights in ``config.PHYSICAL_WEIGHTS``,
renormalized over the inputs available):

    1. Natural hazards near ports (50%) - GDACS Orange and Red alerts for tropical cyclones,
       floods, earthquakes and volcanoes. An event within its type's radius of a port costs
       throughput share x level points (see ``data/sources/gdacs.py``).
    2. Gatun Lake (25%)   - Panama Canal Authority daily lake level. 100 at or above 85 ft (the
       full 50 ft draft level), 0 at the record low.
    3. Mississippi (25%)  - USGS daily gauge height at St. Louis. 100 at or above the low-water
       threshold, 0 at the record low.

The Rhine at Kaub is stored in ``gauge_readings`` each cycle and never scored.

Thresholds come from ``config`` and ``SCORE_ANCHORS["waterways"]``; port throughput shares from
``SCORE_ANCHORS["port_throughput_share"]``. A missing anchor is a RuntimeError at fetch time.

Replaces weather in the composite; ``weather.py`` stays for the map.

History scores each day from the events active that day and the gauge value of that day
(carried forward at most to the input's drop window); days before a gauge's first reading
leave that input out.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
from data import database
from data.ports_data import MAJOR_PORTS
from data.providers.base import BaseProvider
from data.providers.readings import (
    InputReading, blend_inputs, freshness_status, inputs_metadata, oldest_as_of)
from data.sources import gdacs, waterways

logger = logging.getLogger(__name__)

_HAZARDS, _GATUN, _MISSISSIPPI = "hazards", "gatun", "mississippi"
_SOURCES = {
    _HAZARDS: "GDACS Orange and Red alerts near ports",
    _GATUN: "Panama Canal Authority Gatun Lake level",
    _MISSISSIPPI: "USGS 07010000 Mississippi River at St. Louis",
}
_RAW_LABELS = {_HAZARDS: "Active hazard alerts", _GATUN: "Gatun Lake level (ft)",
               _MISSISSIPPI: "St. Louis stage (ft)"}
_WATERWAY_KEYS = ("gatun_record_low", "mississippi_record_low", "mississippi_threshold")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _ports() -> list[dict]:
    return [{"name": name, "lat": lat, "lon": lon} for name, lat, lon, _ in MAJOR_PORTS]


def _anchors() -> tuple[dict[str, float], dict[str, float]]:
    """Port throughput shares and the waterway anchors; anything missing is a RuntimeError."""
    shares = config.SCORE_ANCHORS.get("port_throughput_share")
    if not isinstance(shares, dict) or not shares:
        raise RuntimeError("no anchor for port_throughput_share")
    waterway = config.SCORE_ANCHORS.get("waterways")
    try:
        anchors = {key: float(waterway[key]) for key in _WATERWAY_KEYS}
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("no anchor for waterways (needs " + ", ".join(_WATERWAY_KEYS) + ")") from None
    if not all(math.isfinite(v) for v in anchors.values()):
        raise RuntimeError("no anchor for waterways (non-finite value)")
    if anchors["gatun_record_low"] >= config.GATUN_FULL_DRAFT_FT or \
            anchors["mississippi_record_low"] >= anchors["mississippi_threshold"]:
        raise RuntimeError("no anchor for waterways (a record low is not below its full level)")
    return {str(k): float(v) for k, v in shares.items()}, anchors


def _latest(series: pd.Series) -> tuple[date, float]:
    clean = series.dropna()
    if clean.empty:
        raise ValueError("no finite reading")
    return clean.index[-1].date(), float(clean.iloc[-1])


def _daily_scores(series: pd.Series, score_fn, window: pd.DatetimeIndex, drop_after: int) -> pd.Series:
    """Score each value, carry it forward up to ``drop_after`` days, and cut to ``window``."""
    scores = series.dropna().map(score_fn)
    full = pd.date_range(scores.index.min(), max(window[-1], scores.index.max()), freq="D")
    return scores.reindex(full).ffill(limit=drop_after).reindex(window)


class PhysicalProvider(BaseProvider):
    """Physical Disruption - port hazards, Gatun Lake and the Mississippi at St. Louis."""

    category = "physical"

    # ------------------------------------------------------------------ current

    @staticmethod
    def _missing(name: str) -> InputReading:
        return InputReading(name, None, None, f"{_SOURCES[name]}: unavailable", status="missing")

    def _hazards_reading(self, today: date, shares: dict) -> tuple[InputReading, list[dict]]:
        try:
            events = gdacs.fetch_events(today - timedelta(days=config.HAZARD_LOOKBACK_DAYS), today, today=today)
            active = gdacs.active_on(events, today)
            score = gdacs.hazard_score(active, _ports(), shares, config.HAZARD_RADIUS_KM)
            raw = f"{len(active)} active Orange or Red alert{'' if len(active) == 1 else 's'}"
            return InputReading(_HAZARDS, score, today, _SOURCES[_HAZARDS], raw,
                                freshness_status(today, today, _HAZARDS)), active
        except Exception as exc:
            logger.warning("GDACS hazards unavailable: %s", exc)
            return self._missing(_HAZARDS), []

    def _gauge_reading(self, name: str, today: date, fetch, score_fn) -> InputReading:
        try:
            as_of, value = _latest(fetch())
            as_of = min(as_of, today)
            return InputReading(name, score_fn(value), as_of, _SOURCES[name], f"{value:.2f} ft",
                                freshness_status(as_of, today, name))
        except Exception as exc:
            logger.warning("Physical %s unavailable: %s", name, exc)
            return self._missing(name)

    @staticmethod
    def _store_kaub() -> None:
        """Keep the latest Rhine level at Kaub for later study; it never affects the score."""
        try:
            day, level_cm = waterways.fetch_kaub_latest()
            database.upsert_gauge_reading(day, "kaub", level_cm)
        except Exception as exc:
            logger.info("Kaub reading not stored: %s", exc)

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        shares, anchors = _anchors()
        hazards, active = self._hazards_reading(today, shares)
        gatun = self._gauge_reading(
            _GATUN, today, waterways.fetch_gatun,
            lambda v: waterways.gatun_score(v, anchors["gatun_record_low"]))
        river = self._gauge_reading(
            _MISSISSIPPI, today,
            lambda: waterways.fetch_mississippi_stl(
                today - timedelta(days=config.PHYSICAL_GAUGE_LOOKBACK_DAYS)),
            lambda v: waterways.river_score(v, anchors["mississippi_threshold"],
                                            anchors["mississippi_record_low"]))
        readings = [hazards, gatun, river]
        self._store_kaub()

        score, status = blend_inputs(readings, config.PHYSICAL_WEIGHTS)
        if score is None:
            raise RuntimeError("no physical disruption input available: "
                               + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        sentences = []
        if hazards in used:
            ports = _ports()
            near = [e for e in active
                    if gdacs.hazard_score([e], ports, shares, config.HAZARD_RADIUS_KM) < 100.0]
            sentences.append(
                f"{len(active)} Orange or Red natural-hazard alert{' is' if len(active) == 1 else 's are'} "
                f"active worldwide today; {len(near)} {'is' if len(near) == 1 else 'are'} close enough to "
                "affect a major port (cyclones within 300 km, floods 100 km, earthquakes 150 km, "
                "volcanoes 50 km), weighted by the port's share of world container throughput.")
        if gatun in used:
            sentences.append(
                f"Gatun Lake is {gatun.raw_value}; the Panama Canal allows the full 50 ft draft only at "
                f"{config.GATUN_FULL_DRAFT_FT:.0f} ft or above.")
        if river in used:
            sentences.append(
                f"The Mississippi at St. Louis reads {river.raw_value}; low stages cut barge drafts and "
                "tow sizes.")
        weight_text = ", ".join(f"{label} {config.PHYSICAL_WEIGHTS[key]:.0%}" for key, label in
                                ((_HAZARDS, "hazards"), (_GATUN, "Gatun Lake"), (_MISSISSIPPI, "Mississippi")))
        metadata = {
            "source": "; ".join(r.source for r in readings),
            "raw_value": " / ".join(r.raw_value for r in used),
            "raw_label": "; ".join(_RAW_LABELS[r.name] for r in used),
            "description": " ".join(sentences),
            "calculation": (
                "Hazards: 100 minus 1000 x the sum, over affected ports, of throughput share x level "
                "points (Orange 0.5, Red 1.0), clipped to 0-100. Gatun Lake: 100 at or above "
                f"{config.GATUN_FULL_DRAFT_FT:.0f} ft, 0 at the record low, linear between. Mississippi: "
                "100 at or above the low-water stage (the gauge's 10th-percentile stage), 0 at its record "
                f"low, linear between. Weights {weight_text}, renormalized over available inputs."),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return round(score, 1), metadata

    # ------------------------------------------------------------------ history

    @staticmethod
    def _hazard_history(window: pd.DatetimeIndex, shares: dict) -> pd.Series:
        events = gdacs.fetch_events(window[0].date(), window[-1].date(), today=window[-1].date())
        ports = _ports()
        return pd.Series(
            [gdacs.hazard_score(gdacs.active_on(events, d.date()), ports, shares, config.HAZARD_RADIUS_KM)
             for d in window], index=window)

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        shares, anchors = _anchors()
        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        gatun_drop = config.FRESHNESS[_GATUN][1]
        river_drop = config.FRESHNESS[_MISSISSIPPI][1]
        builders = {
            _HAZARDS: lambda: self._hazard_history(window, shares),
            _GATUN: lambda: _daily_scores(
                waterways.fetch_gatun(), lambda v: waterways.gatun_score(v, anchors["gatun_record_low"]),
                window, gatun_drop),
            _MISSISSIPPI: lambda: _daily_scores(
                waterways.fetch_mississippi_stl(window[0].date() - timedelta(days=river_drop)),
                lambda v: waterways.river_score(v, anchors["mississippi_threshold"],
                                                anchors["mississippi_record_low"]),
                window, river_drop),
        }
        scores = {}
        for key, build in builders.items():
            try:
                scores[key] = build()
            except Exception as exc:
                logger.warning("Physical %s history unavailable: %s", key, exc)
        if not scores:
            raise RuntimeError("no physical disruption history available")

        frame = pd.DataFrame(scores)
        w = pd.Series({k: config.PHYSICAL_WEIGHTS[k] for k in frame.columns})
        weight_sum = frame.notna().mul(w, axis=1).sum(axis=1)
        blend = frame.mul(w, axis=1).sum(axis=1, skipna=True) / weight_sum
        out = blend.where(weight_sum > 0).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no physical disruption history available")
        return out.rename("physical")
