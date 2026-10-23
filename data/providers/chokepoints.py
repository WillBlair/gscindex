"""
Chokepoints category
====================
How much of normal traffic is still moving through the eight maritime corridors that
carry the most world trade, from IMF PortWatch daily ship transits (AIS, free, no key).

Each corridor's ratio is the 7-day mean of daily transits over the mean for the same
calendar month in 2022-01..2023-10 (before the Red Sea attacks). A corridor above 90% of
normal costs nothing; below that, its shortfall is weighted by its share of trade tonnage.
See ``portwatch.chokepoint_score``. Weights and baselines are generated into
``config.SCORE_ANCHORS``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
from data import portwatch
from data.providers.base import BaseProvider
from data.providers.readings import (
    InputReading, blend_inputs, freshness_status, inputs_metadata, oldest_as_of)

logger = logging.getLogger(__name__)

CREDIT = "Sources: UN Global Platform; IMF PortWatch"
_KEY = "chokepoint_flow"
_DISPLAY = {"RedSea": "Red Sea"}
# Enough lead-in for the 7-day window plus a few missing days.
_CURRENT_LOOKBACK_DAYS = 60
_WINDOW_PADDING_DAYS = 14


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _pct(ratio: float) -> str:
    return f"{round(100 * ratio)}%"


class ChokepointsProvider(BaseProvider):
    category = "chokepoints"

    @staticmethod
    def _anchors() -> tuple[dict, dict]:
        weights = config.SCORE_ANCHORS.get("chokepoint_weights")
        baseline = config.SCORE_ANCHORS.get("chokepoint_baseline")
        if not weights or not baseline:
            raise RuntimeError(f"no anchor for {_KEY}")
        return weights, baseline

    def _ratios_and_scores(self, start: date) -> tuple[pd.DataFrame, pd.Series]:
        weights, baseline = self._anchors()
        daily = portwatch.fetch_chokepoint_daily(start)
        ratios = portwatch.corridor_ratios(daily, baseline)
        if ratios.empty:
            raise RuntimeError("PortWatch returned no chokepoint rows")
        scores = ratios.apply(lambda row: portwatch.chokepoint_score(row, weights), axis=1)
        scores = scores.dropna()
        if scores.empty:
            raise RuntimeError("PortWatch rows do not cover every chokepoint")
        return ratios, scores

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        ratios, scores = self._ratios_and_scores(today - timedelta(days=_CURRENT_LOOKBACK_DAYS))
        latest = scores.index[-1]
        row = ratios.loc[latest]
        as_of = latest.date()

        worst = row[portwatch.CORRIDORS].sort_values().head(3)
        raw_value = " · ".join(f"{_DISPLAY.get(n, n)} {_pct(r)}" for n, r in worst.items())
        reading = InputReading(
            _KEY, round(float(scores.iloc[-1]), 1), as_of, "IMF PortWatch", raw_value,
            freshness_status(as_of, today, _KEY),
        )
        score, status = blend_inputs([reading], {_KEY: 1.0})
        if score is None:
            raise RuntimeError(f"chokepoint data is too old (as of {as_of})")

        cape = row.get("Cape")
        cape_text = ""
        if pd.notna(cape):
            cape_text = (f" Cape of Good Hope traffic is {_pct(cape)} of normal; it rises when "
                         "ships reroute, so it is shown for context and not scored.")
        metadata = {
            "source": "IMF PortWatch",
            "raw_value": raw_value,
            "raw_label": "Three weakest corridors, 7-day average transits as % of normal",
            "description": (
                "Share of normal ship traffic still passing through eight chokepoints: Malacca, "
                "Taiwan Strait, Gibraltar, Hormuz, Dover, Red Sea (the worse of Bab el-Mandeb and "
                "Suez), Bosporus and Panama. A closed corridor means delayed or rerouted cargo."
                f"{cape_text} {CREDIT}."
            ),
            "calculation": (
                f"Per corridor, ratio = 7-day mean daily transits / mean for the same month in "
                f"2022-01 to 2023-10. Score = 100 - {config.CHOKEPOINT_SEVERITY * 100:.0f} x "
                f"sum(tonnage weight x (1 - min(ratio / {config.CHOKEPOINT_DEADBAND:.2f}, 1))), "
                "clipped to 0-100."
            ),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of([reading]).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata([reading]),
        }
        return score, metadata

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        lag = config.PUBLICATION_LAG_DAYS[_KEY]
        _, scores = self._ratios_and_scores(
            today - timedelta(days=days + lag + portwatch.RECENT_DAYS + _WINDOW_PADDING_DAYS))
        scores = scores.copy()
        scores.index = scores.index + pd.Timedelta(days=lag)
        return scores[scores.index > pd.Timestamp(today - timedelta(days=days))]
