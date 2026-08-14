"""
Energy & Fuel Provider
=======================
Scores combined energy + inland-fuel COST PRESSURE on supply chains from two
oil-complex prices, blended into a single category:

    1. WTI crude oil  — live ``CL=F`` futures, FRED ``DCOILWTICO`` for history.
    2. Retail diesel  — DOE weekly via FRED ``GASDESW`` (inland freight fuel).

Score Logic
-----------
Each leg is the inverse percentile of the current price within its trailing
2-year distribution (cheapest end → ~100, most expensive → ~0). The category
score is the average of the two legs.

Crude and diesel are the same petroleum complex (diesel is refined crude, the
two correlate north of 0.9), so they are deliberately blended into ONE gauge
rather than scored as two independent categories — that avoids placing an
oversized effective weight on a single price signal.

This is explicitly a COST gauge, not a demand gauge: a price collapse driven
by falling demand reads as low cost pressure even though the demand picture
may be bad. Demand-side health is not measured here.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    inverse_percentile_value,
    normalize_series_inverse,
)


class EnergyProvider(BaseProvider):
    """Energy & Fuel — blend of WTI crude and retail diesel cost pressure."""

    category = "energy"
    _CRUDE_SERIES = "DCOILWTICO"
    _DIESEL_SERIES = "GASDESW"

    def _live_crude_price(self) -> tuple[float, str]:
        """Return the latest WTI price and a change string (live, FRED fallback)."""
        import yfinance as yf

        try:
            ticker = yf.Ticker("CL=F")
            price = ticker.fast_info.get("last_price")
            if not price:
                hist = ticker.history(period="1d")
                price = float(hist["Close"].iloc[-1])
            prev_close = ticker.fast_info.get("previous_close")
            change_str = ""
            if prev_close:
                pct = ((price - prev_close) / prev_close) * 100
                change_str = f" ({pct:+.2f}%)"
            return float(price), change_str
        except Exception as exc:
            logger.warning("yfinance crude failed, falling back to FRED: %s", exc)
            return float(fetch_fred_series(self._CRUDE_SERIES).iloc[-1]), ""

    def fetch_current(self) -> tuple[float, dict]:
        # 1. Crude leg — live price scored against its trailing FRED distribution.
        crude_hist = fetch_fred_series(self._CRUDE_SERIES)
        crude_price, crude_change = self._live_crude_price()
        crude_score = inverse_percentile_value(crude_price, crude_hist)

        # 2. Diesel leg — latest weekly DOE retail price scored against its own range.
        diesel_hist = fetch_fred_series(self._DIESEL_SERIES)
        diesel_price = float(diesel_hist.iloc[-1])
        diesel_note = ""
        diesel_source = "DOE Diesel (GASDESW)"
        try:
            from data.providers.api_ninjas import get_commodity_quote

            ho = get_commodity_quote("heating_oil")
            if ho and ho.get("change_24h") is not None:
                # Apply today's heating-oil move to the weekly retail print.
                # Do not mix absolute futures and retail levels — only the day change.
                ho_change = float(ho["change_24h"])
                diesel_price = diesel_price + ho_change
                diesel_note = (
                    f" Diesel nowcasted {ho_change:+.3f}/gal from API Ninjas "
                    "heating oil vs the prior session."
                )
                diesel_source = "DOE Diesel (GASDESW) + API Ninjas heating_oil"
        except Exception as exc:
            logger.warning("Heating-oil nowcast skipped: %s", exc)
        diesel_score = inverse_percentile_value(diesel_price, diesel_hist)

        # 3. Blend: equal-weight average of the two oil-complex legs.
        score = round((crude_score + diesel_score) / 2.0, 1)

        return score, {
            "source": f"WTI Crude (CL=F) + {diesel_source}",
            "raw_value": f"${crude_price:.0f} oil / ${diesel_price:.2f} diesel",
            "raw_label": f"Crude & Diesel{crude_change}",
            "description": (
                f"WTI crude is ${crude_price:.2f}/bbl{crude_change} and US retail diesel "
                f"is ${diesel_price:.2f}/gal. This category blends both legs of the oil "
                "complex into one fuel-cost-pressure gauge. It measures energy cost "
                f"pressure on supply chains, not demand-side health.{diesel_note}"
            ),
            "calculation": (
                "Score = average of two inverse percentiles (crude price and diesel price, "
                f"each within its trailing {FRED_SCORE_LOOKBACK_DAYS}-day FRED distribution). "
                "Cheaper than most of the window = high score (low cost pressure)."
            ),
            "updated": datetime.now().strftime("%H:%M:%S Live"),
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        crude = normalize_series_inverse(fetch_fred_series(self._CRUDE_SERIES))
        diesel = normalize_series_inverse(fetch_fred_series(self._DIESEL_SERIES))

        # Align both legs onto a common daily index, forward-fill the weekly
        # diesel series, then average. Days where only one leg exists use that
        # leg alone (mean skips NaN).
        idx = crude.index.union(diesel.index)
        blended = pd.concat(
            [crude.reindex(idx).ffill(), diesel.reindex(idx).ffill()],
            axis=1,
        ).mean(axis=1)
        return blended.tail(days).round(1).rename("energy")
