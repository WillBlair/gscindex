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

import requests

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


def _query(where: str, fields: str, order: str | None = None, count: int = 2000) -> list[dict]:
    params = {"where": where, "outFields": fields, "f": "json", "resultRecordCount": count}
    if order:
        params["orderByFields"] = order
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
