"""Regional Fed manufacturing surveys: prices paid (scored) and supplier delivery times (context).

Prices paid, monthly diffusion indexes, all from FRED (no HTML scraping):

    philly  - FRED ``PPCDFSA066MSFRBPHI``  Philadelphia Fed, current prices paid, seasonally adjusted
    empire  - FRED ``PPCDISA066MSFRBNY``   New York Fed Empire State, prices paid, seasonally adjusted
    dallas  - FRED ``PRMSAMFRBDAL``        Dallas Fed Texas Manufacturing Outlook Survey, current prices
                                           paid for raw materials, seasonally adjusted

Kansas City is NOT included. Its Fed publishes the manufacturing survey history as a
spreadsheet linked from https://www.kansascityfed.org/surveys/manufacturing-survey/, and the file
URL carries a numeric id that changes with each upload, so finding it means scraping that HTML
page. The site also stalled the TLS handshake for plain HTTP clients when this was checked
(2026-10-22). The composite averages whichever surveys are available, so leaving KC out costs
breadth, not correctness. Add it only if the Kansas City Fed publishes a stable file or a FRED series.

Supplier delivery times (hover context only, never scored):

    philly  - FRED ``DTCDFSA066MSFRBPHI``
    empire  - FRED ``DTCDISA066MSFRBNY``

A survey that cannot be fetched, or comes back empty or with no finite values, is omitted with
a warning; fetching never raises.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

import config
from data.providers.fred_client import fetch_fred_series

logger = logging.getLogger(__name__)

PRICES_PAID_SERIES: dict[str, str] = {
    "philly": "PPCDFSA066MSFRBPHI",
    "empire": "PPCDISA066MSFRBNY",
    "dallas": "PRMSAMFRBDAL",
}
DELIVERY_TIME_SERIES: dict[str, str] = {
    "philly": "DTCDFSA066MSFRBPHI",
    "empire": "DTCDISA066MSFRBNY",
}


def _fetch_all(series_ids: dict[str, str]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for survey, series_id in series_ids.items():
        try:
            raw = fetch_fred_series(series_id, lookback_days=config.INPUTS_FRED_LOOKBACK_DAYS)
            series = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().sort_index()
            series = series[~series.index.duplicated(keep="last")]
            if series.empty:
                raise ValueError("no finite observations")
            out[survey] = series
        except Exception as exc:
            logger.warning("Fed survey %s (%s) unavailable, omitted: %s", survey, series_id, exc)
    return out


def fetch_prices_paid() -> dict[str, pd.Series]:
    """Monthly prices-paid index per survey (first-of-month dates, as FRED dates them)."""
    return _fetch_all(PRICES_PAID_SERIES)


def fetch_delivery_times() -> dict[str, pd.Series]:
    """Monthly supplier delivery times index per survey; context only."""
    return _fetch_all(DELIVERY_TIME_SERIES)


def prices_paid_composite(surveys: dict[str, pd.Series],
                          stats: dict[str, tuple[float, float]]) -> pd.Series:
    """Mean over the surveys available each month of (value - mean) / sd.

    ``stats[survey]`` is that survey's own (mean, sd), fixed over 2004-2019 in the anchors file.
    A survey with no entry in ``stats`` is skipped; a non-positive or non-finite sd is a
    ValueError. The result is empty when no survey has a usable value.
    """
    z: dict[str, pd.Series] = {}
    for survey, series in surveys.items():
        if survey not in stats:
            logger.warning("No prices-paid stats for survey %s; skipped", survey)
            continue
        mean, sd = float(stats[survey][0]), float(stats[survey][1])
        if not (math.isfinite(mean) and math.isfinite(sd) and sd > 0):
            raise ValueError(f"unusable prices-paid stats for {survey}: mean={mean}, sd={sd}")
        series = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        z[survey] = (series - mean) / sd
    if not z:
        return pd.Series(dtype=float)
    return pd.DataFrame(z).mean(axis=1, skipna=True).dropna().sort_index()
