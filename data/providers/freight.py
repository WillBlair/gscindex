"""
Freight Flow Provider
======================
Scores physical freight THROUGHPUT — whether goods are actually moving —
from the U.S. Bureau of Transportation Statistics Freight Transportation
Services Index (FRED ``TSIFRGHT``).

The Freight TSI tracks the volume of for-hire freight moved across trucking,
rail (including rail-based intermodal), inland waterways, pipelines, and air
freight. It is published monthly with a ~1-2 month lag.

Score Logic
-----------
This is a DISRUPTION gauge, not a cost gauge. It complements the GSCPI
supply-chain category: GSCPI measures pressure/congestion (delivery times,
backlogs), while this measures raw throughput. The two can diverge — e.g.
2021 saw high throughput *and* high congestion.

The signal is year-over-year growth of the index:

    score = FREIGHT_YOY_BASELINE + yoy_pct * FREIGHT_YOY_SLOPE   (clipped 0-100)

A freight *contraction* (negative YoY) signals demand destruction or a
logistics breakdown and pulls the score down; steady or growing volume reads
as a healthy, functioning freight network. YoY is used (rather than a level
percentile) because it naturally de-seasonalizes and has a defensible sign:
goods physically moving is good, a freight recession is bad.
"""

from __future__ import annotations

import logging

import pandas as pd

from config import FREIGHT_PROXY_WEIGHT, FREIGHT_YOY_BASELINE, FREIGHT_YOY_SLOPE, HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.transport_equity_proxy import (
    fetch_transport_equity_score,
    fetch_transport_equity_score_history,
)

logger = logging.getLogger(__name__)

# Months between observations used for the year-over-year comparison.
_YOY_LAG_MONTHS = 12


def _yoy_to_score(yoy_pct: float) -> float:
    """Map year-over-year freight growth (%) to a 0–100 health score."""
    score = FREIGHT_YOY_BASELINE + yoy_pct * FREIGHT_YOY_SLOPE
    return round(float(max(0.0, min(100.0, score))), 1)


def _score_series(raw: pd.Series) -> pd.Series:
    """Convert the raw monthly index into a YoY-based health score series."""
    raw = raw.sort_index()
    yoy = raw.pct_change(_YOY_LAG_MONTHS) * 100.0
    return yoy.dropna().apply(_yoy_to_score)


class FreightProvider(BaseProvider):
    """Freight Flow — physical throughput from the BTS Freight TSI (monthly,
    1-2 month lag), blended with a daily transportation-sector equity proxy
    (IYT) so the category moves between BTS prints instead of sitting flat
    for 8-12 weeks at a time."""

    category = "freight"
    _SERIES_ID = "TSIFRGHT"

    def fetch_current(self) -> tuple[float, dict]:
        raw = fetch_fred_series(self._SERIES_ID).sort_index()
        if len(raw) <= _YOY_LAG_MONTHS:
            raise ValueError("TSIFRGHT history too short for a year-over-year read")

        current = float(raw.iloc[-1])
        year_ago = float(raw.iloc[-(_YOY_LAG_MONTHS + 1)])
        yoy_pct = (current / year_ago - 1.0) * 100.0 if year_ago else 0.0
        tsifrght_score = _yoy_to_score(yoy_pct)
        obs_date = raw.index[-1].date()

        if yoy_pct <= -4.0:
            condition = "freight volumes are contracting sharply (recessionary)"
        elif yoy_pct < -0.5:
            condition = "freight volumes are softening"
        elif yoy_pct <= 1.5:
            condition = "freight volumes are roughly flat (steady flow)"
        else:
            condition = "freight volumes are expanding (healthy demand)"

        # Daily proxy: transportation-sector equities (IYT). Best-effort —
        # if this fails, we fall back to 100% TSIFRGHT rather than crash.
        proxy_note = ""
        blend_weight = 0.0
        score = tsifrght_score
        try:
            proxy_score, proxy_price, proxy_date = fetch_transport_equity_score()
            blend_weight = FREIGHT_PROXY_WEIGHT
            score = (1 - blend_weight) * tsifrght_score + blend_weight * proxy_score
            proxy_note = (
                f" Blended with a daily transportation-sector equity proxy (IYT @ "
                f"${proxy_price:.2f}, {proxy_date}) at {blend_weight:.0%} weight so "
                "this category moves between monthly BTS prints (which carry a "
                "1-2 month publication lag)."
            )
        except Exception as exc:
            logger.warning("Transport-equity proxy fetch failed (using 100%% TSIFRGHT): %s", exc)

        return score, {
            "source": "FRED TSIFRGHT (BTS) + IYT daily proxy" if blend_weight else "FRED Series TSIFRGHT (BTS)",
            "raw_value": f"{yoy_pct:+.1f}% YoY",
            "raw_label": "Freight Throughput Growth",
            "description": (
                f"The Freight Transportation Services Index is at {current:.1f} "
                f"({yoy_pct:+.1f}% vs a year ago): {condition}. This index tracks the "
                "physical volume of for-hire freight moved across trucking, rail, "
                "inland waterways, pipelines, and air cargo — a measure of whether "
                f"goods are actually moving, not what they cost.{proxy_note}"
            ),
            "calculation": (
                f"Score = {FREIGHT_YOY_BASELINE:g} + YoY% × {FREIGHT_YOY_SLOPE:g}, clipped 0-100. "
                "Contracting freight volume (negative YoY) lowers the score; steady or "
                "growing volume reads healthy. Updated monthly by the BTS (1-2 month lag)."
                + (
                    f" Blended {1 - blend_weight:.0%}/{blend_weight:.0%} with a daily "
                    "IYT transportation-equity proxy scored by direct percentile."
                    if blend_weight
                    else ""
                )
            ),
            "updated": str(obs_date) + (" + IYT daily" if blend_weight else ""),
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = _score_series(raw)
        if scores.empty:
            return pd.Series(dtype=float, name="freight")
        daily = scores.resample("D").ffill().tail(days)

        try:
            proxy_daily = fetch_transport_equity_score_history(days)
            blended = daily.copy()
            common_idx = blended.index.intersection(proxy_daily.index)
            blended.loc[common_idx] = (
                (1 - FREIGHT_PROXY_WEIGHT) * blended.loc[common_idx]
                + FREIGHT_PROXY_WEIGHT * proxy_daily.loc[common_idx]
            )
            return blended.rename("freight")
        except Exception as exc:
            logger.warning("Transport-equity proxy history fetch failed (using 100%% TSIFRGHT): %s", exc)
            return daily.rename("freight")
