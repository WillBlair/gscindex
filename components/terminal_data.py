"""Pure math behind the Terminal view: category rows, index summary, index history.

No Dash imports. All dates are UTC: "today" is the UTC date of the snapshot's
``last_updated_utc``; "yesterday" is the stored value at exactly today minus
one day, otherwise ``None``. Today's value always comes from ``current_scores``
(the stored daily history is read before today's hourly write, so its last
slot can be empty).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from config import CATEGORY_LABELS, DEFAULT_PROFILE, HEALTH_TIERS, INDUSTRY_PROFILES

# UI-only palette. config.HEALTH_TIERS keeps the newsletter/stored-metadata colors.
TIER_COLORS: dict[str, str] = {
    "Healthy": "#35D07F",
    "Stable": "#F5C542",
    "Stressed": "#FF8A3D",
    "Critical": "#FF4D5E",
}

ROW_HISTORY_DAYS = 30


def tier_for(score: float) -> dict:
    """Tier label and UI color for a score, using HEALTH_TIERS thresholds."""
    tier = HEALTH_TIERS[-1]
    for candidate in HEALTH_TIERS:
        if score >= candidate["min"]:
            tier = candidate
            break
    return {"label": tier["label"], "color": TIER_COLORS[tier["label"]]}


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _weights(profile_key: str) -> dict[str, float]:
    return INDUSTRY_PROFILES.get(profile_key, INDUSTRY_PROFILES[DEFAULT_PROFILE])["weights"]


def _today_utc(data: dict) -> date:
    raw = data.get("last_updated_utc")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).date()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _stored(data: dict, cat: str, day: date) -> float | None:
    """Stored daily score for ``cat`` on ``day`` (None if absent or not finite)."""
    history = data.get("daily_history") or {}
    dates = history.get("dates") or []
    series = (history.get("scores") or {}).get(cat)
    if not series:
        return None
    try:
        idx = dates.index(day.isoformat())
    except ValueError:
        return None
    return _finite(series[idx]) if idx < len(series) else None


def _window(today: date, days: int) -> list[date]:
    return [today - timedelta(days=n) for n in range(days - 1, -1, -1)]


def _weighted(values: list[float | None], weights: list[float]) -> float | None:
    if any(v is None for v in values):
        return None
    return sum(w * v for w, v in zip(weights, values))


def category_rows(data: dict, profile_key: str) -> list[dict]:
    """One row per profile category, heaviest weight first."""
    weights = _weights(profile_key)
    today_date = _today_utc(data)
    yesterday = today_date - timedelta(days=1)
    scores = data.get("current_scores") or {}
    metadata = data.get("category_metadata") or {}
    fallbacks = set(data.get("fallback_categories") or [])
    window = _window(today_date, ROW_HISTORY_DAYS)

    rows = []
    for cat, weight in weights.items():
        today = _finite(scores.get(cat))
        yday = _stored(data, cat, yesterday)
        change = today - yday if today is not None and yday is not None else None
        history = [_stored(data, cat, d) for d in window[:-1]] + [today]
        meta = metadata.get(cat) or {}
        rows.append({
            "cat": cat,
            "label": CATEGORY_LABELS.get(cat, cat),
            "weight": weight,
            "today": today,
            "yday": yday,
            "change": change,
            "effect": change * weight if change is not None else None,
            "history": history,
            "is_fallback": cat in fallbacks,
            "source": meta.get("source"),
            "raw_value": meta.get("raw_value"),
            "raw_label": meta.get("raw_label"),
            "updated": meta.get("updated"),
            "description": meta.get("description"),
            "calculation": meta.get("calculation"),
        })
    rows.sort(key=lambda r: r["weight"], reverse=True)
    return rows


def index_summary(data: dict, profile_key: str) -> dict:
    """Weighted index today and yesterday. Any missing category blanks that side.

    ``today`` and ``tier`` are None only if a profile category has no live score.
    """
    rows = category_rows(data, profile_key)
    weights = [r["weight"] for r in rows]
    today = _weighted([r["today"] for r in rows], weights)
    yday = _weighted([r["yday"] for r in rows], weights)
    change = today - yday if today is not None and yday is not None else None
    return {
        "today": today,
        "yday": yday,
        "change": change,
        "tier": tier_for(today) if today is not None else None,
    }


def index_history(data: dict, profile_key: str, days: int) -> list[float | None]:
    """Weighted index per day over the last ``days`` days; last point is the live index.

    A past day is None unless every profile category has a stored score for it.
    """
    weights = _weights(profile_key)
    today_date = _today_utc(data)
    cats = list(weights)
    wts = [weights[c] for c in cats]
    out = [
        _weighted([_stored(data, c, d) for c in cats], wts)
        for d in _window(today_date, days)[:-1]
    ]
    out.append(index_summary(data, profile_key)["today"])
    return out
