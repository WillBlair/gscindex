"""
Scoring Engine
==============
Calculates the composite Supply Chain Health Index from individual category
scores using a weighted-average approach.


    composite = Σ (weight_i × score_i)  for each category i

Each category score is 0–100 (100 = best). Weights are defined in config.py
and must sum to 1.0.
"""

from __future__ import annotations

import math

import numpy as np

from config import CATEGORY_WEIGHTS, HEALTH_TIERS


def compute_composite_index(
    category_scores: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """Return a single 0–100 composite index from per-category scores.

    Parameters
    ----------
    category_scores : dict[str, float]
        Mapping of category key → score (0–100).
    weights : dict[str, float] | None
        Override weights. Defaults to ``CATEGORY_WEIGHTS`` from config.

    Returns
    -------
    float
        Weighted composite score, clipped to [0, 100].

    Raises
    ------
    ValueError
        If weights don't sum to ~1.0 or a required category is missing.
    """
    weights = weights or CATEGORY_WEIGHTS

    # Sanity check: weights must sum to 1.0 (within floating-point tolerance)
    weight_sum = sum(weights.values())
    if not np.isclose(weight_sum, 1.0, atol=0.01):
        raise ValueError(
            f"Category weights must sum to 1.0, got {weight_sum:.4f}. "
            f"Fix CATEGORY_WEIGHTS in config.py."
        )

    missing = set(weights) - set(category_scores)
    if missing:
        raise ValueError(
            f"Missing category scores for: {missing}. "
            f"Every weighted category needs a score."
        )

    composite = sum(
        weights[cat] * category_scores[cat]
        for cat in weights
    )
    return float(np.clip(composite, 0.0, 100.0))


def renormalized_weights(weights: dict[str, float], present: set[str]) -> dict[str, float]:
    """``weights`` restricted to ``present`` and rescaled to sum to 1.0.

    Used when a category is excluded from the composite: the remaining weights keep
    their proportions. Raises ValueError when no weighted category is present.
    """
    kept = {cat: w for cat, w in weights.items() if cat in present}
    total = sum(kept.values())
    if not kept or total <= 0:
        raise ValueError("No weighted category is present; the composite is undefined.")
    if len(kept) == len(weights):
        return dict(weights)
    return {cat: w / total for cat, w in kept.items()}


def snapshot_composite(data: dict) -> float | None:
    """The composite stored in a dashboard snapshot (``data["composite"]``).

    Older snapshots have no ``composite`` key; for those it is computed from
    ``current_scores``, and None is returned when a weighted category is missing
    (a snapshot from before the current categories, or one with an exclusion).
    """
    if "composite" in data:
        value = data.get("composite")
        # bool is an int subclass, but True / False are not composites.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None
    scores = data.get("current_scores") or {}
    try:
        return compute_composite_index(scores) if scores else None
    except ValueError:
        return None


def get_health_tier(score: float) -> dict:
    """Return the health tier dict for a given score.

    Parameters
    ----------
    score : float
        Composite index value (0–100).

    Returns
    -------
    dict
        The matching tier from ``HEALTH_TIERS`` containing keys:
        ``min``, ``max``, ``label``, ``color``.
    """
    for tier in HEALTH_TIERS:
        if score >= tier["min"]:
            return tier
    # Fallback — should never happen if tiers cover 0–100
    return HEALTH_TIERS[-1]
