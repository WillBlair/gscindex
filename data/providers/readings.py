"""Per-input readings and the freshness-aware blend used by the rebuilt providers."""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

import config
from scoring.anchors import score_raw


class InputsExpired(RuntimeError):
    """Every input that returned data is past its drop window, so the category is excluded
    at once; the aggregator does not serve a stored score, which would only be older data."""


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


def no_inputs_error(readings: list[InputReading], message: str) -> RuntimeError:
    """The error for a category with no usable input.

    ``InputsExpired`` when at least one input returned data and every such input was dropped
    for age (a dated, scored reading whose freshness status is missing); a plain
    ``RuntimeError`` when every input failed to fetch or parse.
    """
    aged = [r for r in readings if r.as_of is not None and r.score is not None and r.status == "missing"]
    return InputsExpired(message) if aged else RuntimeError(message)


def safe_score(value: float, anchor: dict, ratio: float | None = None) -> float:
    """Anchored score of a reading, or NaN when the value (or the CPI ratio, if given) is not finite."""
    if not (math.isfinite(value) and (ratio is None or math.isfinite(ratio))):
        return float("nan")
    return score_raw(value, anchor, ratio)


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


def finite_series(series: pd.Series) -> pd.Series:
    """The series' finite numeric values only (NaN, inf and non-numbers dropped)."""
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


_YOY_MONTHS = 12


def yoy_percent(levels: pd.Series) -> pd.Series:
    """Year-over-year % of a monthly index, comparing each month with the same month a year
    earlier by date (a missing month cannot shift the comparison). A month whose base is
    missing or not positive has no value."""
    levels = finite_series(levels).sort_index()
    base = levels.reindex(levels.index - pd.DateOffset(months=_YOY_MONTHS)).to_numpy()
    base = np.where(base > 0, base, np.nan)
    return finite_series(pd.Series((levels.to_numpy() / base - 1.0) * 100.0, index=levels.index))
