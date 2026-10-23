"""Per-input readings and the freshness-aware blend used by the rebuilt providers."""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date

import config


@dataclass
class InputReading:
    name: str
    score: float | None
    as_of: date | None
    source: str
    raw_value: str = ""
    status: str = "live"  # live | stale | missing

    def __post_init__(self) -> None:
        # A NaN or infinite score is a missing reading, so metadata never carries NaN.
        if self.score is not None and not math.isfinite(self.score):
            self.score = None
            self.status = "missing"


def period_end(obs: date, freq: str) -> date:
    """Date a period's data is complete: month end for monthly series, else unchanged."""
    if freq == "M":
        return date(obs.year, obs.month, calendar.monthrange(obs.year, obs.month)[1])
    if freq in ("D", "W"):
        return obs
    raise ValueError(f"unknown freq {freq!r}")


def freshness_status(as_of: date | None, today: date, key: str) -> str:
    """live, stale or missing from the age of ``as_of`` against config.FRESHNESS[key]."""
    if as_of is None:
        return "missing"
    stale_after, drop_after = config.FRESHNESS[key]
    age = (today - as_of).days
    if age > drop_after:
        return "missing"
    if age > stale_after:
        return "stale"
    return "live"


def _used(readings: list[InputReading]) -> list[InputReading]:
    return [r for r in readings
            if r.status != "missing" and r.score is not None and math.isfinite(r.score)]


def blend_inputs(readings: list[InputReading], weights: dict[str, float]) -> tuple[float | None, str]:
    """Weighted mean of the usable readings, weights renormalized over what is left."""
    used = _used(readings)
    total = sum(weights[r.name] for r in used)
    if not used or total <= 0:
        return None, "missing"
    score = sum(weights[r.name] * r.score for r in used) / total
    status = "stale" if any(r.status == "stale" for r in used) else "live"
    return round(score, 1), status


def inputs_metadata(readings: list[InputReading]) -> list[dict]:
    return [
        {
            "name": r.name,
            "score": r.score,
            "as_of": r.as_of.isoformat() if r.as_of else None,
            "status": r.status,
            "source": r.source,
            "raw_value": r.raw_value,
        }
        for r in readings
    ]


def oldest_as_of(readings: list[InputReading]) -> date | None:
    dates = [r.as_of for r in _used(readings) if r.as_of is not None]
    return min(dates) if dates else None
