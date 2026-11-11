"""Pure math for the /history page: stored category rows in, index series, episodes and CSV out.

No Flask, Dash or database import. A day counts only when all eight global category rows
exist for it; a missing day stays None and is never filled. Sector keys never pass through.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import date, timedelta

import config
from components import terminal_data
from data.providers import chokepoints
from scoring import snapshot_composite


def _cats() -> list[str]:
    return list(config.CATEGORY_WEIGHTS)


def build_history(rows: list[tuple[date, str, float]], start: date, loaded_on: date) -> dict:
    """Aligned daily history of the eight global categories from ``start`` to the last row date."""
    cats = _cats()
    kept: dict[tuple[date, str], float] = {}
    for day, cat, score in rows:
        value = terminal_data._finite(score)
        if cat in cats and day >= start and value is not None:
            kept[(day, cat)] = value
    last = max((day for day, _ in kept), default=None)
    if last is None:
        return {"loaded_on": loaded_on.isoformat(), "start": start.isoformat(), "dates": [],
                "scores": {c: [] for c in cats}}
    days = [start + timedelta(days=n) for n in range((last - start).days + 1)]
    return {
        "loaded_on": loaded_on.isoformat(),
        "start": start.isoformat(),
        "dates": [d.isoformat() for d in days],
        "scores": {c: [kept.get((d, c)) for d in days] for c in cats},
    }


def _weighted_day(history: dict, i: int) -> float | None:
    total = 0.0
    for cat, weight in config.CATEGORY_WEIGHTS.items():
        series = history["scores"].get(cat) or []
        value = terminal_data._finite(series[i]) if i < len(series) else None
        if value is None:
            return None
        total += weight * value
    return total


def daily_index(history: dict) -> list[float | None]:
    """One weighted index per date, None unless all eight scores are present."""
    return [_weighted_day(history, i) for i in range(len(history["dates"]))]


def _live_point(snapshot: dict | None) -> tuple[date, float] | None:
    if not snapshot or snapshot.get("excluded_categories"):
        return None
    value = terminal_data._finite(snapshot_composite(snapshot))
    if value is None:
        return None
    return terminal_data._today_utc(snapshot), value


def series(history: dict, snapshot: dict | None) -> list[tuple[date, float | None]]:
    """Stored days, plus (with a snapshot) None for missing days up to yesterday and one live point.

    A snapshot dated before the last stored day is stale: every stored day is kept, no live point."""
    points = [(date.fromisoformat(d), v) for d, v in zip(history["dates"], daily_index(history))]
    if snapshot is None:
        return points
    today = terminal_data._today_utc(snapshot)
    if points and points[-1][0] > today:
        return points  # the snapshot is older than the stored days: keep them all, add no live point
    points = [(d, v) for d, v in points if d < today]
    if points:
        day = points[-1][0] + timedelta(days=1)
        while day < today:
            points.append((day, None))
            day += timedelta(days=1)
    live = _live_point(snapshot)
    if live is not None:
        points.append(live)
    return points


def extremes(points) -> dict:
    """Lowest and highest non-None point as (date, value), or None when there are none."""
    known = [(d, v) for d, v in points if v is not None]
    if not known:
        return {"low": None, "high": None}
    return {"low": min(known, key=lambda p: p[1]), "high": max(known, key=lambda p: p[1])}


def _date_map(history: dict) -> dict[str, int]:
    return {d: i for i, d in enumerate(history["dates"])}


def _lookup(history: dict, day: date, dates: dict[str, int] | None = None) -> int | None:
    return (dates if dates is not None else _date_map(history)).get(day.isoformat())


def _score_at(history: dict, cat: str, day: date, dates: dict[str, int] | None = None) -> float | None:
    i = _lookup(history, day, dates)
    series_ = history["scores"].get(cat) or []
    if i is None or i >= len(series_):
        return None
    return terminal_data._finite(series_[i])


def _index_at(history: dict, day: date, dates: dict[str, int] | None = None) -> float | None:
    i = _lookup(history, day, dates)
    return None if i is None else _weighted_day(history, i)


def _diff(now: float | None, before: float | None) -> float | None:
    return None if now is None or before is None else now - before


def episode_rows(history: dict, episodes: list[dict], change_days: int) -> list[dict]:
    """One row per episode from stored days only (never the live point)."""
    out = []
    dates = _date_map(history)
    for n, episode in enumerate(episodes, start=1):
        day = date.fromisoformat(episode["date"])
        earlier = day - timedelta(days=change_days)
        index = _index_at(history, day, dates)
        out.append({
            "n": n,
            "date": day,
            "label": episode["label"],
            "text": episode["text"],
            "source_url": episode["source_url"],
            "index": index,
            "tier": None if index is None else terminal_data.tier_for(index),
            "change": _diff(index, _index_at(history, earlier, dates)),
            "categories": [
                {
                    "cat": cat,
                    "label": config.CATEGORY_LABELS.get(cat, cat),
                    "score": (score := _score_at(history, cat, day, dates)),
                    "change": _diff(score, _score_at(history, cat, earlier, dates)),
                }
                for cat in config.CATEGORY_WEIGHTS
            ],
        })
    return out


def _cell(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.2f}"


def history_csv(history: dict, snapshot: dict | None) -> str:
    """Header, then one row per ``series`` day. Today's category cells come from the snapshot."""
    cats = _cats()
    dates = _date_map(history)
    live = _live_point(snapshot)
    if live is not None and history["dates"] and date.fromisoformat(history["dates"][-1]) > live[0]:
        live = None
    current = (snapshot or {}).get("current_scores") or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["date", "index", *cats, "credit"])
    for day, value in series(history, snapshot):
        if live is not None and day == live[0]:
            cells = [terminal_data._finite(current.get(c)) for c in cats]
        else:
            cells = [_score_at(history, c, day, dates) for c in cats]
        writer.writerow([day.isoformat(), _cell(value), *(_cell(c) for c in cells), chokepoints.CREDIT])
    return buffer.getvalue()
