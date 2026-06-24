"""
Composite Score Explanation
===========================
Builds human-readable context for the main health index number — which
categories are pulling the score up or down and by how much.
"""

from __future__ import annotations

from config import CATEGORY_LABELS, CATEGORY_WEIGHTS
from scoring.engine import get_health_tier


def _delta_phrase(delta: float | None) -> str:
    if delta is None or abs(delta) < 0.05:
        return "unchanged from the last recorded daily score"
    direction = "up" if delta > 0 else "down"
    return f"{direction} {abs(delta):.1f} pts from the last recorded daily score"


def _category_line(cat: str, score: float, weight: float, meta: dict | None) -> str:
    label = CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
    pct = int(round(weight * 100))
    meta = meta or {}
    context = str(meta.get("raw_label") or meta.get("description") or "").strip()
    if context:
        context = context.rstrip(".")
        if len(context) > 90:
            context = context[:87].rstrip() + "..."
        return f"{label} ({score:.0f}, {pct}% weight) — {context}"
    return f"{label} ({score:.0f}, {pct}% weight)"


def build_score_explanation(
    composite: float,
    category_scores: dict[str, float],
    category_metadata: dict[str, dict] | None = None,
    *,
    delta: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, str | list[str]]:
    """Return tooltip copy explaining why the composite is at its current level."""
    weights = weights or CATEGORY_WEIGHTS
    category_metadata = category_metadata or {}
    tier = get_health_tier(composite)

    ranked = sorted(
        ((cat, category_scores[cat], weights.get(cat, 0.0)) for cat in weights if cat in category_scores),
        key=lambda item: item[1],
    )
    weak = [item for item in ranked if item[1] < 60]
    strong = [item for item in ranked if item[1] >= 75]

    bullets: list[str] = []
    if weak:
        for cat, score, weight in weak[:3]:
            bullets.append(f"↓ {_category_line(cat, score, weight, category_metadata.get(cat))}")
    if strong:
        for cat, score, weight in reversed(strong[-2:]):
            bullets.append(f"↑ {_category_line(cat, score, weight, category_metadata.get(cat))}")

    if not bullets:
        mid = ranked[len(ranked) // 2][0] if ranked else None
        if mid:
            score = category_scores[mid]
            bullets.append(
                f"• {_category_line(mid, score, weights[mid], category_metadata.get(mid))}"
            )

    fallback_categories = sorted(
        cat for cat, meta in category_metadata.items() if meta.get("is_fallback")
    )
    if fallback_categories:
        labels = ", ".join(CATEGORY_LABELS.get(c, c) for c in fallback_categories[:3])
        bullets.append(f"⚠ {labels} using estimated values — live feed unavailable")

    summary = (
        f"The index reads {tier['label'].lower()} at {composite:.0f}/100, "
        f"{_delta_phrase(delta)}. "
        f"It is a weighted blend of six live signals — lower category scores pull the headline number down."
    )

    return {
        "headline": f"{composite:.0f} · {tier['label']}",
        "summary": summary,
        "bullets": bullets,
    }
