"""
Inland Freight (Trucking) Provider
====================================
Scores inland freight COST PRESSURE from the US retail diesel price.

Current score
-------------
Official DOE retail diesel (FRED ``GASDESW``) is weekly, so the current
value is nowcast from two inputs:

1. Live Heating Oil futures (``HO=F``) — the high-frequency market signal.
   Heating oil is chemically near-identical to diesel and trades real-time.
2. The retail spread — taxes plus distribution margin, estimated as the gap
   between the latest weekly DOE print and the HO=F close nearest that date.

    estimated_diesel = live_HO_price + spread

The result is explicitly labeled an estimate in the UI metadata. The score
is the inverse percentile of the estimate within the trailing 2-year DOE
retail price distribution (low price = low cost pressure = high score).

Like the energy category, this is a COST gauge, not a demand gauge.

History
-------
Official weekly DOE data only, forward-filled to daily. No synthetic
daily series — the weekly step pattern is what was actually measured.
"""

from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.fred_client import (
    fetch_fred_series,
    inverse_percentile_value,
    normalize_series_inverse,
)

# Typical US retail diesel spread over heating oil futures (taxes plus
# distribution), used only when the dynamic spread cannot be computed.
_FALLBACK_SPREAD = 1.30


class TruckingProvider(BaseProvider):
    """Inland Freight — diesel cost pressure (DOE weekly + HO=F nowcast)."""

    category = "trucking"
    _TICKER = "HO=F"
    _FRED_SERIES = "GASDESW"

    def fetch_current(self) -> tuple[float, dict]:
        # 1. Live market signal (HO=F)
        ticker = yf.Ticker(self._TICKER)
        try:
            info = ticker.fast_info
            live_ho_price = float(info.last_price) if info.last_price else float(info.previous_close)
            if not live_ho_price:
                hist = ticker.history(period="5d")
                live_ho_price = float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning("HO=F fast_info failed, using history: %s", e)
            hist = ticker.history(period="5d")
            live_ho_price = float(hist["Close"].iloc[-1])

        # 2. Latest official weekly retail price (DOE via FRED)
        retail_series = fetch_fred_series(self._FRED_SERIES)
        last_retail_price = float(retail_series.iloc[-1])
        last_retail_date = retail_series.index[-1]

        # 3. Retail spread: latest DOE print minus the HO=F close nearest
        #    that print's date. Falls back to a typical fixed spread.
        spread = _FALLBACK_SPREAD
        try:
            ho_hist = ticker.history(period="1mo")["Close"]
            idx_loc = ho_hist.index.get_indexer([last_retail_date], method="nearest")[0]
            if idx_loc != -1:
                spread = last_retail_price - float(ho_hist.iloc[idx_loc])
        except Exception:
            pass

        # 4. Nowcast today's retail diesel and score it by percentile
        #    within the trailing DOE retail distribution.
        est_daily_price = live_ho_price + spread
        score = inverse_percentile_value(est_daily_price, retail_series)

        # Intraday change in the estimate equals the change in HO=F
        # (the spread is assumed constant intraday).
        try:
            change_ho = live_ho_price - float(info.previous_close)
            change_str = f"{change_ho:+.3f}"
        except Exception:
            change_str = "0.000"

        if est_daily_price > 4.50:
            condition = "Diesel prices are critically high"
        elif est_daily_price > 4.00:
            condition = "Diesel prices are elevated"
        elif est_daily_price > 3.50:
            condition = "Diesel prices are moderate"
        else:
            condition = "Diesel prices are low — favorable for carriers"

        return score, {
            "source": f"Estimated Real-Time (HO=F + ${spread:.2f} spread)",
            "raw_value": f"${est_daily_price:.3f}/gal ({change_str})",
            "raw_label": "Est. Daily Diesel Price",
            "description": (
                f"Estimated National Average Diesel Price is ${est_daily_price:.3f} today. {condition}. "
                "This is a nowcast: live Heating Oil futures plus the retail distribution spread "
                f"(${spread:.2f}) implied by the latest weekly DOE print. It measures fuel cost "
                "pressure on inland freight, not demand-side health."
            ),
            "calculation": (
                "Score = inverse percentile of the estimated diesel price within the trailing "
                f"{FRED_SCORE_LOOKBACK_DAYS}-day DOE retail price distribution. "
                f"Estimate = live heating oil (${live_ho_price:.3f}) + spread (${spread:.2f})."
            ),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        """Official weekly DOE retail diesel, scored and forward-filled to daily."""
        retail_series = fetch_fred_series(self._FRED_SERIES)
        scores = normalize_series_inverse(retail_series)
        return scores.resample("D").ffill().tail(days).rename("trucking")
