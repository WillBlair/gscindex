"""Anchored 0-100 mapping shared by every input of the score rebuild (methodology v2).

Each input is mapped piecewise-linearly through three anchors: ``best`` -> 100,
``normal`` -> 80, ``worst`` -> 0, then clipped to [0, 100]. Anchor values come
from ``data/score_anchors.json`` (config.SCORE_ANCHORS) and are in transformed units.
"""
from __future__ import annotations

import calendar
import math
import re

import config


def transform_value(raw: float, transform: str, cpi_ratio: float | None = None) -> float:
    """Put a raw reading on the scale its anchors were fitted in.

    ``log_real`` deflates to reference-year dollars first: ``cpi_ratio`` is CPI_ref / CPI_t.
    """
    if transform == "identity":
        return float(raw)
    if transform == "log":
        return math.log(raw)
    if transform == "log_real":
        if cpi_ratio is None:
            raise ValueError("log_real needs a cpi_ratio")
        return math.log(raw * cpi_ratio)
    raise ValueError(f"unknown transform {transform!r}")


def anchored_score(x: float, anchor: dict) -> float:
    """Map a transformed value to 0-100 through the anchor's best/normal/worst."""
    if not math.isfinite(x):
        raise ValueError(f"cannot score non-finite value {x!r}")
    direction = anchor["direction"]
    best, normal, worst = anchor["best"], anchor["normal"], anchor["worst"]
    if direction == "lower_better":
        sign = 1.0
    elif direction == "higher_better":
        sign = -1.0
    else:
        raise ValueError(f"unknown direction {direction!r}")
    # Flip a higher-is-better anchor so one lower-is-better walk handles both.
    x, best, normal, worst = sign * x, sign * best, sign * normal, sign * worst
    if not best < normal < worst:
        raise ValueError(
            f"anchors not monotone for {direction}: best={anchor['best']}, "
            f"normal={anchor['normal']}, worst={anchor['worst']}"
        )
    if x <= best:
        return 100.0
    if x >= worst:
        return 0.0
    if x <= normal:
        return 100.0 - 20.0 * (x - best) / (normal - best)
    return 80.0 * (worst - x) / (worst - normal)


def score_raw(raw: float, anchor: dict, cpi_ratio: float | None = None) -> float:
    return anchored_score(transform_value(raw, anchor["transform"], cpi_ratio), anchor)


def get_anchor(key: str) -> dict:
    """Look up an input's anchor at call time; a missing one is a clear RuntimeError."""
    try:
        return config.SCORE_ANCHORS["inputs"][key]
    except KeyError:
        raise RuntimeError(f"no anchor for {key}") from None


def past_record(name: str, score: float | None) -> dict | None:
    """Record details for an input scoring 0, i.e. at or past its worst month on record.

    The score cannot go below 0, so the UI uses this to show the reading against the
    record instead. Returns {"record": text, "when": "Dec 2025"} or None (not at the floor,
    or no anchor). Nothing here changes a score.
    """
    if score is None or score > 0:
        return None
    anchor = ((config.SCORE_ANCHORS or {}).get("inputs") or {}).get(name)
    if not anchor or "worst" not in anchor:
        return None
    worst = float(anchor["worst"])
    if anchor.get("transform") in ("log", "log_real"):
        worst = math.exp(worst)
    record = config.RECORD_FORMATS.get(name, "{:g}").format(worst)
    basis = str(anchor.get("worst_basis") or "")
    months = re.findall(r"(\d{4})-(\d{2})", basis)
    if months:
        year, month = months[-1]
        when = f"{calendar.month_abbr[int(month)]} {year}"
    else:
        year = re.search(r"\bin (\d{4})\b", basis)
        when = year.group(1) if year else None
    return {"record": record, "when": when}
