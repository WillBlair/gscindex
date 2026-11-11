"""Shared builders for the history page tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import config

CATS = list(config.CATEGORY_WEIGHTS)
START = date(2019, 1, 11)


def rows(first, days, score=60.0, missing=None, overrides=None):
    """(date, category, score) for the eight global categories on `days` consecutive dates.
    missing: {date: {categories without a row}}; overrides: {(date, category): score}."""
    missing = missing or {}
    overrides = overrides or {}
    out = []
    for n in range(days):
        day = first + timedelta(days=n)
        for cat in CATS:
            if cat in missing.get(day, ()):
                continue
            out.append((day, cat, overrides.get((day, cat), score)))
    return out


def snapshot(today, score=50.0, excluded=(), fallback=()):
    """A minimal dashboard snapshot: last_updated_utc at 12:00 UTC on `today`, current_scores for the
    categories not excluded, composite = score, the excluded/fallback/stale lists, empty metadata per
    category, and an empty daily_history."""
    stamp = datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc)
    return {
        "last_updated_utc": stamp.isoformat().replace("+00:00", "Z"),
        "current_scores": {c: score for c in CATS if c not in excluded},
        "composite": score,
        "degraded": bool(excluded or fallback),
        "fallback_categories": list(fallback),
        "excluded_categories": list(excluded),
        "stale_categories": [],
        "category_metadata": {c: {} for c in CATS},
        "daily_history": {"dates": [], "scores": {}},
    }
