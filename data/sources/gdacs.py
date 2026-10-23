"""Natural-hazard alerts from GDACS (the UN/EU Global Disaster Alert and Coordination System).

``geteventlist/SEARCH`` (free, no key) returns a GeoJSON FeatureCollection of every event that
overlaps the requested ``fromdate``..``todate`` window. We ask for Orange and Red alerts of four
types: tropical cyclones (TC), floods (FL), earthquakes (EQ) and volcanoes (VO). Each event has a
centre point and the dates it was active; earthquakes start and end on the same day.

Verified 2026-10-22: ``alertlevel=Orange;Red&eventlist=TC;FL;EQ;VO&fromdate=YYYY-MM-DD&todate=...``
returns every event of the window in one response (no paging at six-month size). A window with no
events answers with an empty body rather than an empty collection.
https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone

import requests

import config
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
ALERT_LEVELS = "Orange;Red"
EVENT_TYPES = "TC;FL;EQ;VO"
_TIMEOUT = 120   # GDACS latency varies from 3 s to over 80 s for the same window
_CACHE_PREFIX = "gdacs_events_v1"
CURRENT_CHUNK_TTL = 6 * 3600           # the chunk that touches the present, or ended within the last week
PAST_CHUNK_TTL = 30 * 24 * 3600        # a chunk completed more than a week ago no longer changes
_SETTLE_DAYS = 7
_MIN_NONEMPTY_DAYS = 30                # a window this long always holds some Orange or Red event
_EARTH_RADIUS_KM = 6371.0


def _parse_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _centre(feature: dict) -> tuple[float, float] | None:
    """(lat, lon) of the event: its Point geometry, else the middle of its bounding box."""
    geometry = feature.get("geometry")
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if isinstance(geometry, dict) and geometry.get("type") == "Point" and isinstance(coords, list) \
            and len(coords) >= 2:
        lon, lat = coords[0], coords[1]
    else:
        bbox = feature.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            return None
        lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def parse_events(payload, allow_empty: bool = False) -> list[dict]:
    """Orange and Red events as ``{id, type, alert, lat, lon, name, from, to}`` (dates ISO strings).

    Raises ``ValueError`` for anything that is not a FeatureCollection, and for one with no
    features unless ``allow_empty`` (a short window may truly hold none). Features that are
    Green, of another type, or lack a centre or dates are skipped.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("GDACS payload is not a FeatureCollection")
    features = payload["features"]
    if not features and not allow_empty:
        raise ValueError("GDACS payload has no events")
    events = []
    for feature in features:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        kind, alert = props.get("eventtype"), props.get("alertlevel")
        if kind not in config.HAZARD_RADIUS_KM or alert not in config.HAZARD_LEVEL_POINTS:
            continue
        centre = _centre(feature)
        start, end = _parse_day(props.get("fromdate")), _parse_day(props.get("todate"))
        if centre is None or start is None or end is None or end < start:
            continue
        events.append({
            "id": props.get("eventid"), "type": kind, "alert": alert,
            "lat": centre[0], "lon": centre[1], "name": str(props.get("name") or ""),
            "from": start.isoformat(), "to": end.isoformat(),
        })
    if not events and not allow_empty:
        raise ValueError("GDACS payload has no usable Orange or Red events")
    return events


def _half_years(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar half-years (Jan-Jun, Jul-Dec) covering start..end, each at most 6 months."""
    chunks = []
    year, half = start.year, 0 if start.month <= 6 else 1
    while True:
        first = date(year, 1 if half == 0 else 7, 1)
        last = date(year, 6, 30) if half == 0 else date(year, 12, 31)
        if first > end:
            return chunks
        chunks.append((first, last))
        year, half = (year + 1, 0) if half == 1 else (year, 1)


def _fetch_chunk(first: date, last: date, today: date) -> list[dict]:
    """One aligned half-year, requested up to today; cached per chunk."""
    request_end = min(last, today)
    key = f"{_CACHE_PREFIX}_{first.year}H{1 if first.month <= 6 else 2}"
    settled = request_end < today and (today - request_end).days > _SETTLE_DAYS
    cached = get_cached(key, ttl=PAST_CHUNK_TTL if settled else CURRENT_CHUNK_TTL)
    if cached is not None:
        return cached
    short = (request_end - first).days < _MIN_NONEMPTY_DAYS
    resp = requests.get(URL, params={
        "alertlevel": ALERT_LEVELS, "eventlist": EVENT_TYPES,
        "fromdate": first.isoformat(), "todate": request_end.isoformat(),
    }, timeout=_TIMEOUT)
    resp.raise_for_status()
    try:
        payload = resp.json()
    except ValueError:
        if short and not (resp.text or "").strip():
            return []              # GDACS answers a window without events with an empty body
        raise ValueError("GDACS response is not JSON") from None
    events = parse_events(payload, allow_empty=short)
    set_cached(key, events)
    return events


def fetch_events(start: date, end: date, today: date | None = None) -> list[dict]:
    """Orange and Red events overlapping ``start``..``end``, fetched in half-year chunks.

    Chunks are calendar half-years, cached per chunk (``gdacs_events_v1_<year>H<n>``): six hours
    for the chunk holding the present, 30 days for one completed more than a week ago. A chunk
    that comes back empty or reshaped raises ``ValueError`` and is not cached.
    """
    today = today or datetime.now(timezone.utc).date()
    seen: dict = {}
    for first, last in _half_years(start, min(end, today)):
        for event in _fetch_chunk(first, last, today):
            seen.setdefault(event["id"] if event.get("id") is not None else id(event), event)
    return [e for e in seen.values() if e["to"] >= start.isoformat() and e["from"] <= end.isoformat()]


def active_on(events: list[dict], day: date) -> list[dict]:
    """Events whose [from, to] range covers ``day``."""
    iso = day.isoformat()
    return [e for e in events if e["from"] <= iso <= e["to"]]


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def hazard_score(events: list[dict], ports: list[dict], shares: dict[str, float],
                 radius_km: dict[str, float]) -> float:
    """100 minus the throughput-weighted hazard penalty, clipped to 0-100.

    An event affects a port within ``radius_km[type]`` of its centre. Penalty =
    ``config.HAZARD_SCALE`` x sum over affected (event, port) pairs of share x level points
    (``config.HAZARD_LEVEL_POINTS``). A port with no share counts zero.
    """
    penalty = 0.0
    for event in events:
        radius = radius_km.get(event.get("type"))
        points = config.HAZARD_LEVEL_POINTS.get(event.get("alert"))
        if radius is None or points is None:
            continue
        for port in ports:
            share = shares.get(port["name"], 0.0)
            if share and _distance_km(event["lat"], event["lon"], port["lat"], port["lon"]) <= radius:
                penalty += share * points
    return float(min(100.0, max(0.0, 100.0 - config.HAZARD_SCALE * penalty)))
