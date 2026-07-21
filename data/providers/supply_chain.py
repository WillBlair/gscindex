"""
Supply Chain Pressure Provider
================================
Scores the supply chain category from the NY Fed **GSCPI** (Global Supply
Chain Pressure Index): a monthly z-score built from transport costs and
PMI delivery-time/backlog components. 0 = average pressure, positive =
elevated pressure.

    score = 50 - GSCPI * 25, clipped to 0-100

The NY Fed **WEI** (Weekly Economic Index) is fetched for context only and
shown in the metadata. It does NOT contribute to the score: WEI is a
GDP-growth nowcast, and high growth historically coincides with supply
chain STRESS (2021: WEI ~+7 while GSCPI hit its all-time peak), so it has
no defensible sign in a linear health blend.
"""

from __future__ import annotations

import logging

import pandas as pd

from config import GSCPI_SCORE_SCALE, HISTORY_DAYS, SUPPLY_CHAIN_PROXY_WEIGHT
from data.gscpi_client import (
    fetch_gscpi_series,
    gscpi_to_score,
    latest_published_gscpi,
)
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_series
from data.providers.freight_rate_proxy import (
    fetch_freight_rate_score,
    fetch_freight_rate_score_history,
)

logger = logging.getLogger(__name__)


class SupplyChainProvider(BaseProvider):
    """Supply Chain Pressure — NY Fed GSCPI (monthly) blended with a daily
    dry-bulk freight-rate proxy (BDRY) so the category moves day to day
    instead of sitting flat between GSCPI prints."""

    category = "supply_chain"
    _WEI_SERIES_ID = "WEI"

    def fetch_current(self) -> tuple[float, dict]:
        # GSCPI is the anchor score. If it fails, the provider fails and the
        # aggregator flags the category as a fallback — no silent stand-in.
        gscpi_series = fetch_gscpi_series()
        gscpi_value, gscpi_dt = latest_published_gscpi(gscpi_series)
        gscpi_score = gscpi_to_score(gscpi_value)
        gscpi_date = str(gscpi_dt.date())

        if gscpi_value > 1.0:
            gscpi_condition = "supply chain pressures are well above normal"
        elif gscpi_value > 0.25:
            gscpi_condition = "pressures are elevated"
        elif gscpi_value > -0.25:
            gscpi_condition = "pressures are near historical average"
        else:
            gscpi_condition = "pressures are below average (favorable)"

        # Daily proxy: dry-bulk freight rates (BDRY). Best-effort — if this
        # fails, we fall back to 100% GSCPI rather than crash the provider.
        proxy_note = ""
        blend_weight = 0.0
        score = gscpi_score
        try:
            proxy_score, proxy_price, proxy_date = fetch_freight_rate_score()
            blend_weight = SUPPLY_CHAIN_PROXY_WEIGHT
            score = (1 - blend_weight) * gscpi_score + blend_weight * proxy_score
            proxy_note = (
                f" Blended with a daily dry-bulk freight-rate proxy (BDRY @ "
                f"${proxy_price:.2f}, {proxy_date}) at {blend_weight:.0%} weight "
                "so this category moves between monthly GSCPI prints."
            )
        except Exception as exc:
            logger.warning("Freight-rate proxy fetch failed (using 100%% GSCPI): %s", exc)

        # WEI: context only, never part of the score.
        wei_context = ""
        raw_value = f"GSCPI {gscpi_value:+.2f}"
        try:
            wei_raw = fetch_fred_series(self._WEI_SERIES_ID)
            wei_value = float(wei_raw.iloc[-1])
            wei_context = (
                f" For context, the Weekly Economic Index is at {wei_value:+.2f} "
                "(macro activity, not scored)."
            )
            raw_value = f"GSCPI {gscpi_value:+.2f} | WEI {wei_value:+.2f} (context)"
        except Exception as exc:
            logger.warning("WEI context fetch failed (score unaffected): %s", exc)

        return score, {
            "source": "NY Fed GSCPI + BDRY daily proxy" if blend_weight else "NY Fed GSCPI",
            "raw_value": raw_value,
            "raw_label": "Global Supply Chain Pressure",
            "description": (
                f"GSCPI at {gscpi_value:+.2f} standard deviations from its historical "
                f"average: {gscpi_condition}.{wei_context}{proxy_note}"
            ),
            "calculation": (
                f"Score = 50 - GSCPI × {GSCPI_SCORE_SCALE:g}, clipped 0-100 (GSCPI is a "
                "z-score, 0 = average pressure, monthly from the NY Fed)"
                + (
                    f", blended {1 - blend_weight:.0%}/{blend_weight:.0%} with a daily "
                    "BDRY dry-bulk freight-rate proxy scored by inverse percentile."
                    if blend_weight
                    else "."
                )
            ),
            "updated": f"GSCPI {gscpi_date}" + (" + BDRY daily" if blend_weight else ""),
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        gscpi_raw = fetch_gscpi_series()
        gscpi_scores = gscpi_raw.apply(gscpi_to_score)
        gscpi_daily = gscpi_scores.resample("D").ffill().tail(days)

        try:
            proxy_daily = fetch_freight_rate_score_history(days)
            blended = gscpi_daily.copy()
            # Align on the intersection of dates; where the proxy has data,
            # blend it in. Where it doesn't (e.g. early in the window), keep
            # the pure GSCPI value rather than introducing NaNs.
            common_idx = blended.index.intersection(proxy_daily.index)
            blended.loc[common_idx] = (
                (1 - SUPPLY_CHAIN_PROXY_WEIGHT) * blended.loc[common_idx]
                + SUPPLY_CHAIN_PROXY_WEIGHT * proxy_daily.loc[common_idx]
            )
            return blended.rename("supply_chain")
        except Exception as exc:
            logger.warning("Freight-rate proxy history fetch failed (using 100%% GSCPI): %s", exc)
            return gscpi_daily.rename("supply_chain")
