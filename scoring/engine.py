"""
Scoring Engine
==============
Calculates the composite Supply Chain Health Index from individual category
scores using a weighted-average approach.

The math is intentionally simple so it's easy to explain at a career fair:

    composite = Σ (weight_i × score_i)  for each category i

Each category score is 0–100 (100 = best). Weights are defined in config.py
and must sum to 1.0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

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


def compute_composite_series(
    category_history: dict[str, pd.Series],
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Compute composite index for each date across all categories.

    Parameters
    ----------
    category_history : dict[str, pd.Series]
        Mapping of category key → pandas Series indexed by date.
    weights : dict[str, float] | None
        Override weights. Defaults to ``CATEGORY_WEIGHTS`` from config.

    Returns
    -------
    pd.Series
        Composite index over time, indexed by date.
    """
    weights = weights or CATEGORY_WEIGHTS
    df = pd.DataFrame(category_history)
    composite = sum(df[cat] * w for cat, w in weights.items())
    return composite.clip(0.0, 100.0)


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
        if tier["min"] <= score <= tier["max"]:
            return tier
    # Fallback — should never happen if tiers cover 0–100
    return HEALTH_TIERS[-1]
