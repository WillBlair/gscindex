"""Customs deposits from the Daily Treasury Statement, and the tariff burden built on them.

The DTS (Treasury fiscaldata API, free, no key) reports daily deposits to the Treasury's
operating cash by category, in millions of dollars. Customs duties appear under three
category names as the DTS format changed; the periods do not overlap, so summing the
three gives one continuous series. Deposits are gross of IEEPA refunds: refunds are
withdrawals and are not netted out here.

The tariff burden is customs deposits as a percentage of goods imports (FRED ``BOPGIMP``,
also millions of dollars). Duties are paid about 10 working days after release, or on the
periodic monthly statement in the following month, so most of month m's duties arrive in
month m+1. Deposits are therefore shifted back one month (deposits of m+1 pair with imports
of m) before both sides are summed over three months.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import requests

import config
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
        "deposits_withdrawals_operating_cash")
CUSTOMS_CATEGORIES = (
    "Customs and Certain Excise Taxes",              # 2005-10 to 2020-05
    "DHS - Customs and Certain Excise Taxes",        # 2020-05 to 2025-11
    "DHS - Customs Duties, Taxes, and Fees",         # 2025-11 onward
)
_FIELDS = "record_date,transaction_catg,transaction_type,transaction_today_amt"
_PAGE_SIZE = 10000
_MAX_PAGES = 20
_TIMEOUT = 60
_CACHE_KEY = "dts_customs_v1"
_CACHE_TTL = 12 * 3600


def monthly_customs_from_rows(rows: list[dict], complete_only: bool = False) -> pd.Series:
    """Customs deposits ($M) summed by calendar month, indexed by the first of the month.

    Only ``transaction_type == "Deposits"`` rows in the customs categories count; amounts
    that do not parse as finite numbers are skipped. With ``complete_only`` the newest month
    is dropped: a month is closed only once a customs record exists in a later month.
    """
    frame = pd.DataFrame(
        [r for r in rows
         if r.get("transaction_type") == "Deposits" and r.get("transaction_catg") in CUSTOMS_CATEGORIES],
        columns=["record_date", "transaction_today_amt"])
    frame["amount"] = pd.to_numeric(frame["transaction_today_amt"], errors="coerce")
    frame["date"] = pd.to_datetime(frame["record_date"], errors="coerce")
    frame = frame[frame["date"].notna() & np.isfinite(frame["amount"])]
    if frame.empty:
        return pd.Series(dtype=float, name="customs_m")
    months = frame["date"].dt.to_period("M").dt.to_timestamp()
    monthly = frame["amount"].groupby(months).sum().sort_index()
    if complete_only:
        monthly = monthly[monthly.index < months.max()]
    return monthly.astype(float).rename("customs_m")


def _fetch_category(name: str) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        resp = requests.get(_URL, params={
            "filter": f"transaction_catg:eq:{name},transaction_type:eq:Deposits",
            "fields": _FIELDS,
            "page[size]": str(_PAGE_SIZE),
            "page[number]": str(page),
            "sort": "record_date",
        }, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        rows += body.get("data", [])
        if page >= int(body.get("meta", {}).get("total-pages", 0) or 0):
            break
    return rows


def fetch_customs_monthly() -> pd.Series:
    """Complete calendar months of customs deposits ($M); cached 12 hours under ``dts_customs_v1``.

    Raises ``ValueError`` when the API returns no customs rows (nothing is cached).
    """
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached is not None:
        series = pd.Series(cached["values"], index=pd.DatetimeIndex(cached["dates"]), name="customs_m")
        return series.astype(float)
    rows: list[dict] = []
    for name in CUSTOMS_CATEGORIES:
        rows += _fetch_category(name)
    series = monthly_customs_from_rows(rows, complete_only=True)
    if series.empty:
        raise ValueError("Treasury DTS returned no customs deposits")
    set_cached(_CACHE_KEY, {"dates": series.index.strftime("%Y-%m-%d").tolist(),
                            "values": series.tolist()})
    return series


def _month_start(series: pd.Series) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce").dropna()
    series.index = pd.DatetimeIndex(series.index).to_period("M").to_timestamp()
    return series[~series.index.duplicated(keep="last")].sort_index()


def tariff_burden_series(customs_m: pd.Series, imports_m: pd.Series) -> pd.Series:
    """100 x 3-month customs sum / 3-month goods imports sum, in percent, customs shifted back a month.

    Both inputs are monthly in millions of dollars. Customs deposits dated month m+1 are paired
    with imports of month m, so the value for month m (the last month of the window) sums
    deposits of months m-1..m+1 over imports of months m-2..m and is scorable only once
    deposits for m+1 are complete. A window with a missing month on either side has no value.
    The result is indexed by month m (first of month).
    """
    customs, imports = _month_start(customs_m), _month_start(imports_m)
    customs.index = customs.index - pd.DateOffset(months=1)
    months = config.TARIFF_BURDEN_MONTHS
    both = customs.index.intersection(imports.index)
    if both.empty:
        return pd.Series(dtype=float, name="tariff_burden")
    full = pd.date_range(both.min(), both.max(), freq="MS")
    c3 = customs.reindex(full).rolling(months, min_periods=months).sum()
    i3 = imports.reindex(full).rolling(months, min_periods=months).sum()
    burden = (100.0 * c3 / i3).where(i3 > 0)
    return burden.dropna().rename("tariff_burden")
