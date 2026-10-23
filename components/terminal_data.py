"""Pure math behind the Terminal view: category rows, index summary, index history.

No Dash imports. All dates are UTC: "today" is the UTC date of the snapshot's
``last_updated_utc``; "yesterday" is the stored value at exactly today minus
one day, otherwise ``None``. Today's value always comes from ``current_scores``
(the stored daily history is read before today's hourly write, so its last
slot can be empty).

Tabs (``config.TABS``): "global" is the composite over ``CATEGORY_WEIGHTS``. A sector
tab (``config.SECTORS``) shows only its own categories: today's index is the
aggregator's ``data["sectors"][key]["index"]``, and a past day is the equal-weight
mean of the sector categories stored that day, or None below ``min_categories``.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from config import CATEGORY_LABELS, CATEGORY_WEIGHTS, DEFAULT_TAB, HEALTH_TIERS, SECTORS, TABS

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


def tab_key(key) -> str:
    """A known tab key; anything else (an old session value such as "baseline") is Global."""
    return key if key in TABS else DEFAULT_TAB


def tab_weights(key) -> dict[str, float]:
    key = tab_key(key)
    return CATEGORY_WEIGHTS if key == DEFAULT_TAB else SECTORS[key]["weights"]


def sector_block(data: dict, key: str) -> dict:
    """The snapshot's block for one sector ({} for Global or a snapshot saved before sectors)."""
    block = (data.get("sectors") or {}).get(key)
    return block if isinstance(block, dict) else {}


def _sector_day(data: dict, key: str, day: date) -> float | None:
    """Equal-weight mean of the sector categories stored on ``day``; None below coverage."""
    spec = SECTORS[key]
    stored = {c: _stored(data, c, day) for c in spec["weights"]}
    present = {c: v for c, v in stored.items() if v is not None}
    if not present or len(present) < spec["min_categories"]:
        return None
    total = sum(spec["weights"][c] for c in present)
    return sum(spec["weights"][c] / total * v for c, v in present.items())


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
    """One row per tab category, heaviest weight first.

    Status flags come from the tab's own lists: the global lists for Global, the sector
    block plus each category's metadata for a sector (a sector category with no score is
    excluded, as the aggregator counts it).
    """
    key = tab_key(profile_key)
    weights = tab_weights(key)
    today_date = _today_utc(data)
    yesterday = today_date - timedelta(days=1)
    scores = data.get("current_scores") or {}
    metadata = data.get("category_metadata") or {}
    flags = data if key == DEFAULT_TAB else sector_block(data, key)
    fallbacks = set(flags.get("fallback_categories") or [])
    stale = set(flags.get("stale_categories") or [])
    excluded = set(flags.get("excluded_categories") or [])
    if key != DEFAULT_TAB:
        fallbacks |= {c for c in weights if (metadata.get(c) or {}).get("is_fallback")}
        excluded |= {c for c in weights if _finite(scores.get(c)) is None}
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
            "is_stale": cat in stale or bool(meta.get("is_stale")),
            "is_excluded": cat in excluded and today is None,
            "as_of": meta.get("as_of"),
            "stored_on": meta.get("stored_on"),
            "inputs": [i for i in meta.get("inputs") or [] if isinstance(i, dict)],
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

    Global: a category the snapshot lists in ``excluded_categories`` (no live or recent
    stored score) is left out and the remaining weights are renormalized, as the composite
    is. Yesterday uses the same categories and weights, so the change compares like with
    like. ``today`` and ``tier`` are None only if a category has no live score and is not
    excluded.

    Sector: today is the snapshot's sector index (None below coverage, or in a snapshot
    without sectors); yesterday is that day's stored sector mean under the coverage rule.
    """
    key = tab_key(profile_key)
    if key != DEFAULT_TAB:
        today = _finite(sector_block(data, key).get("index"))
        yday = _sector_day(data, key, _today_utc(data) - timedelta(days=1))
        change = today - yday if today is not None and yday is not None else None
        return {"today": today, "yday": yday, "change": change,
                "tier": tier_for(today) if today is not None else None}
    rows = [r for r in category_rows(data, profile_key) if not r["is_excluded"]]
    total = sum(r["weight"] for r in rows)
    weights = [r["weight"] / total for r in rows] if rows and total > 0 else []
    today = _weighted([r["today"] for r in rows], weights) if weights else None
    yday = _weighted([r["yday"] for r in rows], weights) if weights else None
    change = today - yday if today is not None and yday is not None else None
    return {
        "today": today,
        "yday": yday,
        "change": change,
        "tier": tier_for(today) if today is not None else None,
    }


def index_history(data: dict, profile_key: str, days: int) -> list[float | None]:
    """Weighted index per day over the last ``days`` days; last point is the live index.

    Global: a past day is None unless every category has a stored score for it.
    Sector: a past day follows the sector coverage rule (``_sector_day``).
    """
    key = tab_key(profile_key)
    today_date = _today_utc(data)
    if key != DEFAULT_TAB:
        out = [_sector_day(data, key, d) for d in _window(today_date, days)[:-1]]
        out.append(index_summary(data, key)["today"])
        return out
    weights = tab_weights(key)
    cats = list(weights)
    wts = [weights[c] for c in cats]
    out = [
        _weighted([_stored(data, c, d) for c in cats], wts)
        for d in _window(today_date, days)[:-1]
    ]
    out.append(index_summary(data, profile_key)["today"])
    return out
