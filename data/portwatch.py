"""
IMF PortWatch chokepoint traffic
================================
Daily vessel transit counts through the world's main maritime chokepoints,
from IMF PortWatch (satellite AIS ship tracking; free, public, no key).
https://portwatch.imf.org

For each chokepoint we compare the average daily transits over the latest
7 days of data with "normal": the average for the same calendar month in
2022 and 2023, before the Red Sea attacks rerouted shipping. PortWatch
publishes with a lag of a few days, so the result carries its own as-of
date.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

import config
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)
_TIMEOUT = 20
_CACHE_KEY = "portwatch_chokepoints_v1"
_CACHE_TTL = 6 * 3600
_STALE_TTL = 3 * 86400
RECENT_DAYS = 7
BASELINE_YEARS = (2022, 2023)

# Category scoring (Chokepoints provider). Short names -> PortWatch portids; the Dover
# and Bosporus ids come from the PortWatch_chokepoints_database layer.
PORTIDS: dict[str, str] = {
    "Hormuz": "chokepoint6",
    "BabM": "chokepoint4",
    "Suez": "chokepoint1",
    "Panama": "chokepoint2",
    "Malacca": "chokepoint5",
    "Taiwan": "chokepoint11",
    "Gibraltar": "chokepoint8",
    "Dover": "chokepoint9",
    "Bosporus": "chokepoint3",
    "Cape": "chokepoint7",
}
# The eight scored corridors. RedSea is the worse of Bab el-Mandeb and Suez; Cape of
# Good Hope is context only (it rises when ships reroute).
CORRIDORS = ["Malacca", "Taiwan", "Gibraltar", "Hormuz", "Dover", "RedSea", "Bosporus", "Panama"]
RATIO_COLUMNS = CORRIDORS + ["BabM", "Suez", "Cape"]
_DAILY_KEY = "portwatch_daily_v1"
_DAILY_TTL = 6 * 3600
_PAGE_SIZE = 1000
_MAX_PAGES = 200

# (PortWatch id, display name) in display order.
CHOKEPOINTS: list[tuple[str, str]] = [
    ("chokepoint6", "Hormuz"),
    ("chokepoint4", "Bab el-Mandeb"),
    ("chokepoint1", "Suez"),
    ("chokepoint2", "Panama"),
    ("chokepoint5", "Malacca"),
    ("chokepoint11", "Taiwan Strait"),
    ("chokepoint8", "Gibraltar"),
    ("chokepoint7", "Cape of Good Hope"),
]


def _query(where: str, fields: str, order: str | None = None, count: int = 2000,
           offset: int = 0) -> list[dict]:
    params = {"where": where, "outFields": fields, "f": "json", "resultRecordCount": count}
    if order:
        params["orderByFields"] = order
    if offset:
        params["resultOffset"] = offset
    resp = requests.get(_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"PortWatch error: {body['error']}")
    return [f["attributes"] for f in body.get("features", [])]


def _ids_clause() -> str:
    return "portid IN (" + ",".join(f"'{pid}'" for pid, _ in CHOKEPOINTS) + ")"


def _month_window(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return start, end


def compute_traffic(recent_rows: list[dict], baseline_rows: list[dict], as_of: date) -> dict:
    """Pure: turn raw PortWatch rows into the panel payload."""
    recent: dict[str, list[float]] = {}
    for row in recent_rows:
        recent.setdefault(row["portid"], []).append(float(row.get("n_total") or 0))
    normal: dict[str, list[float]] = {}
    for row in baseline_rows:
        normal.setdefault(row["portid"], []).append(float(row.get("n_total") or 0))

    items = []
    for pid, name in CHOKEPOINTS:
        r, b = recent.get(pid), normal.get(pid)
        if not r or not b:
            continue
        recent_avg = sum(r) / len(r)
        normal_avg = sum(b) / len(b)
        if normal_avg <= 0:
            continue
        items.append({
            "name": name,
            "recent_per_day": round(recent_avg, 1),
            "normal_per_day": round(normal_avg, 1),
            "pct_of_normal": round(100 * recent_avg / normal_avg),
        })
    return {
        "as_of": as_of.isoformat(),
        "recent_days": RECENT_DAYS,
        "baseline": f"same month in {BASELINE_YEARS[0]}-{BASELINE_YEARS[-1]}",
        "source": "IMF PortWatch",
        "chokepoints": items,
    }


def fetch_chokepoint_traffic() -> dict | None:
    """Return chokepoint traffic vs normal, or None when unavailable."""
    cached = get_cached(_CACHE_KEY, ttl=_CACHE_TTL)
    if cached:
        return cached
    try:
        latest_rows = _query(_ids_clause(), "date", order="date DESC", count=1)
        if not latest_rows:
            raise RuntimeError("PortWatch returned no rows")
        as_of = date.fromisoformat(str(latest_rows[0]["date"])[:10])
        start = as_of - timedelta(days=RECENT_DAYS - 1)
        recent_rows = _query(
            f"{_ids_clause()} AND date >= DATE '{start}' AND date <= DATE '{as_of}'",
            "date,portid,n_total",
        )
        windows = [_month_window(y, as_of.month) for y in BASELINE_YEARS]
        period = " OR ".join(f"(date >= DATE '{a}' AND date <= DATE '{b}')" for a, b in windows)
        baseline_rows = _query(f"{_ids_clause()} AND ({period})", "date,portid,n_total")
        result = compute_traffic(recent_rows, baseline_rows, as_of)
        if not result["chokepoints"]:
            raise RuntimeError("PortWatch rows did not match any chokepoint")
    except Exception as exc:
        logger.warning("PortWatch chokepoint fetch failed: %s", exc)
        return get_cached(_CACHE_KEY, ttl=_STALE_TTL)
    set_cached(_CACHE_KEY, result)
    return result


def _daily_frame(rows: list[dict]) -> pd.DataFrame:
    """Rows from the daily layer as a frame of known corridors; anything unusable is dropped."""
    cols = ["date", "portid", "n_total", "capacity"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows).reindex(columns=cols)
    df = df[df["portid"].isin(PORTIDS.values())].copy()
    dates = df["date"]
    if pd.api.types.is_numeric_dtype(dates):
        df["date"] = pd.to_datetime(dates, unit="ms", errors="coerce")
    else:
        df["date"] = pd.to_datetime(dates.astype("string").str[:10], errors="coerce")
    df["n_total"] = pd.to_numeric(df["n_total"], errors="coerce")
    df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce")
    return df.dropna(subset=["date"]).reset_index(drop=True)


def fetch_chokepoint_daily(start: date) -> pd.DataFrame:
    """Daily transits for every scored corridor from ``start``: date, portid, n_total, capacity.

    Pages the ArcGIS layer; an empty result is returned as an empty frame, and the
    caller decides what that means. Network errors propagate.
    """
    cached = get_cached(_DAILY_KEY, ttl=_DAILY_TTL)
    if isinstance(cached, dict) and cached.get("rows"):
        try:
            if date.fromisoformat(cached["start"]) <= start:
                return _daily_frame(cached["rows"])
        except (KeyError, TypeError, ValueError):
            pass
    ids = ",".join(f"'{pid}'" for pid in PORTIDS.values())
    where = f"portid IN ({ids}) AND date >= DATE '{start}'"
    rows: list[dict] = []
    for _ in range(_MAX_PAGES):
        page = _query(where, "date,portid,n_total,capacity", order="ObjectId",
                      count=_PAGE_SIZE, offset=len(rows))
        if not page:
            break
        rows.extend(page)
    else:
        raise RuntimeError("PortWatch paging did not finish")
    df = _daily_frame(rows)
    if not df.empty:
        records = df.assign(date=df["date"].dt.strftime("%Y-%m-%d"))
        records = records.astype(object).where(records.notna(), None).to_dict("records")
        set_cached(_DAILY_KEY, {"start": start.isoformat(), "rows": records})
    return df


def corridor_ratios(daily: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    """Daily 7-day mean transits over the same calendar month's baseline, per corridor.

    Columns are RATIO_COLUMNS. A corridor with no data, a gap inside the 7 days, or a
    missing or non-positive baseline is NaN. RedSea is the worse of BabM and Suez.
    """
    if daily is None or daily.empty:
        return pd.DataFrame(columns=RATIO_COLUMNS, dtype=float)
    names = {pid: name for name, pid in PORTIDS.items()}
    d = daily.assign(name=daily["portid"].map(names)).dropna(subset=["name"])
    d = d.drop_duplicates(["date", "name"], keep="last")
    wide = d.pivot(index="date", columns="name", values="n_total").astype(float)
    wide = wide.sort_index().asfreq("D").reindex(columns=list(PORTIDS))
    mean7 = wide.rolling(RECENT_DAYS, min_periods=RECENT_DAYS).mean()
    months = wide.index.month
    base = pd.DataFrame(index=wide.index, columns=wide.columns, dtype=float)
    for name in wide.columns:
        by_month = baseline.get(name) or {}
        vals = np.array([float(by_month.get(str(m), by_month.get(m, np.nan))) for m in range(1, 13)])
        vals[~(np.isfinite(vals) & (vals > 0))] = np.nan
        base[name] = vals[months - 1]
    ratios = mean7 / base
    ratios["RedSea"] = ratios[["BabM", "Suez"]].min(axis=1, skipna=False)
    return ratios[RATIO_COLUMNS]


def chokepoint_score(ratios_row: pd.Series, weights: dict) -> float:
    """0-100 category score from one day's ratios; NaN when any weighted corridor is NaN."""
    ratios = np.array([ratios_row.get(c, np.nan) for c in weights], dtype=float)
    if not np.isfinite(ratios).all():
        return float("nan")
    w = np.array(list(weights.values()), dtype=float)
    share = np.clip(ratios / config.CHOKEPOINT_DEADBAND, 0.0, 1.0)
    score = 100.0 - 100.0 * config.CHOKEPOINT_SEVERITY * float(np.sum(w * (1.0 - share)))
    return float(np.clip(score, 0.0, 100.0))
