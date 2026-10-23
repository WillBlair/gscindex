"""
Geopolitical Risk Provider
==========================
The Geopolitical category is the Caldara-Iacoviello daily Geopolitical Risk (GPR) index:
the 30-day mean, mapped on a log scale through its anchors (see ``GeopoliticalProvider``).
A stored Claude disruption register can be blended in through ``config.GEO_REGISTER_WEIGHT``
(0 for now).

Headlines are display-only and live in ``data/news_alerts.py``; they feed no score.
"""

from datetime import date, datetime, timezone
import logging
import math

import pandas as pd

import config
from data.database import get_last_category_score
from data.providers.base import BaseProvider
from data.providers.readings import (
    InputReading, no_inputs_error, blend_inputs, freshness_status, inputs_metadata, oldest_as_of)
from data.sources import gpr
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)


_GPR, _REGISTER = "gpr", "geo_register"
_GPR_SOURCE = "Caldara\u2013Iacoviello GPR (daily)"
_REGISTER_SOURCE = "Claude disruption register (stored score)"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _gpr_mean() -> tuple[pd.Series, date]:
    """Rolling 30-row mean of the daily index and the file's last date.

    Days without enough observations behind them stay NaN; the file is the publication,
    so the mean is dated by the day it covers.
    """
    daily = gpr.fetch_gpr_daily()
    mean = daily.rolling(config.GPR_MEAN_DAYS, min_periods=config.GPR_MIN_PERIODS).mean()
    return mean, daily.index[-1].date()


def _safe_score(value: float, anchor: dict) -> float:
    if not (math.isfinite(value) and (anchor["transform"] != "log" or value > 0)):
        return float("nan")
    return score_raw(value, anchor)


class GeopoliticalProvider(BaseProvider):
    """Geopolitical Risk - the Caldara-Iacoviello daily GPR index (30-day mean), with a hook
    for the stored Claude disruption register (``config.GEO_REGISTER_WEIGHT``, 0 for now)."""

    category = "geopolitical"

    # ------------------------------------------------------------------ current

    @staticmethod
    def _gpr_reading(today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            mean, as_of = _gpr_mean()
            value = float(mean.iloc[-1])
            score = _safe_score(value, anchor)
            if not math.isfinite(score):
                raise ValueError(f"no usable 30-day mean ({value})")
            reading = InputReading(
                _GPR, score, as_of, _GPR_SOURCE, f"GPR {config.GPR_MEAN_DAYS}-day mean {value:.0f}",
                freshness_status(as_of, today, _GPR))
            return reading, value
        except Exception as exc:
            logger.warning("GPR unavailable: %s", exc)
            return InputReading(_GPR, None, None, _GPR_SOURCE, status="missing"), None

    @staticmethod
    def _register_reading(today: date) -> InputReading:
        try:
            row = get_last_category_score(_REGISTER)
        except Exception as exc:
            logger.warning("Disruption register unavailable: %s", exc)
            row = None
        if row is None:
            return InputReading(_REGISTER, None, None, _REGISTER_SOURCE, status="missing")
        as_of, score = row
        return InputReading(_REGISTER, score, as_of, _REGISTER_SOURCE, f"register score {score:.0f}",
                            freshness_status(as_of, today, _REGISTER))

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchor = get_anchor(_GPR)
        register_weight = config.GEO_REGISTER_WEIGHT
        weights = {_GPR: 1.0 - register_weight, _REGISTER: register_weight}

        reading, gpr_value = self._gpr_reading(today, anchor)
        readings = [reading]
        if register_weight > 0:
            readings.append(self._register_reading(today))

        score, status = blend_inputs(readings, weights)
        if score is None:
            raise no_inputs_error(readings, "no geopolitical input available: " + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        sentences = []
        if reading in used:
            sentences.append(
                "The Geopolitical Risk index counts newspaper coverage of geopolitical tensions, "
                "both threats and acts, across major newspapers each day. Its "
                f"{config.GPR_MEAN_DAYS}-day average was {gpr_value:.0f}, against a normal level "
                "set at the pre-2020 median.")
        if len(used) > 1:
            sentences.append(
                f"Blended with the stored disruption register score at {register_weight:.0%} weight.")
        metadata = {
            "source": "; ".join(r.source for r in used),
            "raw_value": " / ".join(r.raw_value for r in used),
            "raw_label": f"Geopolitical Risk index ({config.GPR_MEAN_DAYS}-day mean)",
            "description": " ".join(sentences),
            "calculation": (
                f"The {config.GPR_MEAN_DAYS}-day mean of the daily index is mapped on a log scale "
                "through its anchors (healthiest 5% of pre-2020 history = 100, pre-2020 median = 80, "
                "the record monthly GPR, October 2001 = 0)."
                + (f" Weights: GPR {weights[_GPR]:.0%}, disruption register {register_weight:.0%},"
                   " renormalized over the inputs available." if register_weight > 0 else "")),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    def fetch_history(self, days: int) -> pd.Series:
        """Daily GPR scores for the last ``days`` calendar days ending today.

        Days inside the file keep their own values (the file is the publication, so nothing
        is shifted by a lag). After the file's last date the last value is carried forward
        day by day while its age is within ``FRESHNESS["gpr"]`` drop_after_days, which is
        what the live score shows, and is NaN after that. Days before the first usable
        30-day mean stay NaN. The register has no history source, so it is not blended in.
        """
        anchor = get_anchor(_GPR)
        try:
            mean, last = _gpr_mean()
        except Exception as exc:
            raise RuntimeError(f"no GPR history available: {exc}") from exc
        scores = pd.Series([_safe_score(v, anchor) for v in mean], index=mean.index)
        today = _today()
        window = pd.date_range(end=pd.Timestamp(max(today, last)), periods=days, freq="D")
        out = scores.reindex(window)
        last_score = scores.get(pd.Timestamp(last), float("nan"))
        if math.isfinite(last_score):
            drop_after = config.FRESHNESS[_GPR][1]
            age = (window - pd.Timestamp(last)).days
            tail = (age > 0) & (age <= drop_after)
            out[tail] = last_score
        out = out.clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no GPR history available")
        return out.rename("geopolitical")
