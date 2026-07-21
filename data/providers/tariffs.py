"""
Trade & Tariffs Provider
=========================
Uses FRED series ``EPUTRADE`` (Economic Policy Uncertainty: Categorical
Index, Trade Policy) as the trade and tariff disruption signal. Unlike
the general EPU index (which spikes on fiscal, monetary, and electoral
news), this categorical index counts only trade-policy coverage.

Score Logic
-----------
Higher trade policy uncertainty = worse for supply chains. Score is the
inverse percentile of the latest value within a trailing 2-year window:
    - Calm end of the window      → score near 100
    - Most uncertain end          → score near 0

The series is monthly, so this category moves slowly by design.

Source: https://fred.stlouisfed.org/series/EPUTRADE
Based on: Baker, Bloom, and Davis categorical EPU data
"""

from __future__ import annotations

import logging

import pandas as pd

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS, TARIFFS_PROXY_WEIGHT
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    normalize_series_inverse,
)
from data.providers.tariff_news_nowcast import fetch_tariff_news_score

logger = logging.getLogger(__name__)


class TariffsProvider(BaseProvider):
    """Trade & Tariffs — derived from the Trade Policy Uncertainty categorical
    index (monthly), blended with a daily trade-policy news sentiment nowcast
    so the category moves between EPUTRADE prints instead of sitting flat."""

    category = "tariffs"
    _SERIES_ID = "EPUTRADE"

    def fetch_current(self) -> tuple[float, dict]:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        eputrade_score = float(scores.iloc[-1])
        val = float(raw.iloc[-1])

        # Daily proxy: trade-policy news sentiment nowcast. Best-effort — if
        # this fails, we fall back to 100% EPUTRADE rather than crash.
        proxy_note = ""
        blend_weight = 0.0
        score = eputrade_score
        try:
            news_score, matched_count, news_summary = fetch_tariff_news_score()
            if matched_count > 0:
                blend_weight = TARIFFS_PROXY_WEIGHT
                score = (1 - blend_weight) * eputrade_score + blend_weight * news_score
                proxy_note = (
                    f" Blended with a daily trade-policy news sentiment nowcast "
                    f"({news_summary}) at {blend_weight:.0%} weight so this category "
                    "moves between monthly EPUTRADE prints."
                )
        except Exception as exc:
            logger.warning("Tariff news nowcast fetch failed (using 100%% EPUTRADE): %s", exc)

        return score, {
            "source": "FRED EPUTRADE + daily news nowcast" if blend_weight else "FRED Series EPUTRADE",
            "raw_value": f"{val:.1f}",
            "raw_label": "Trade Policy Uncertainty",
            "description": (
                f"Trade Policy Uncertainty (categorical EPU) is at {val:.1f}. "
                "This index counts newspaper coverage of trade policy uncertainty "
                "specifically — tariffs, trade wars, import/export policy — rather "
                f"than general economic policy noise. Updated monthly.{proxy_note}"
            ),
            "calculation": (
                "Score = inverse percentile of the latest value within the trailing "
                f"{FRED_SCORE_LOOKBACK_DAYS}-day range. Higher trade policy "
                "uncertainty = lower score."
                + (
                    f" Blended {1 - blend_weight:.0%}/{blend_weight:.0%} with a daily "
                    "VADER-scored trade-policy news nowcast."
                    if blend_weight
                    else ""
                )
            ),
            "updated": str(raw.index[-1].date()) + (" + news daily" if blend_weight else "")
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_inverse(raw)
        daily = scores.resample("D").ffill().tail(days)

        # History blend uses only today's live news nowcast (no historical
        # news score is stored), applied to the most recent day so the chart
        # tail reflects the same blend fetch_current() reports.
        try:
            news_score, matched_count, _ = fetch_tariff_news_score()
            if matched_count > 0 and not daily.empty:
                daily = daily.copy()
                last_idx = daily.index[-1]
                daily.loc[last_idx] = (
                    (1 - TARIFFS_PROXY_WEIGHT) * daily.loc[last_idx]
                    + TARIFFS_PROXY_WEIGHT * news_score
                )
        except Exception as exc:
            logger.warning("Tariff news nowcast history blend failed (using EPUTRADE only): %s", exc)

        return daily.rename("tariffs")
