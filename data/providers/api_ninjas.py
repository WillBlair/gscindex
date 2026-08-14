"""
API Ninjas commodity client
===========================
Thin wrapper around https://api.api-ninjas.com/v1/commoditysnapshot.

The free tier exposes 7 rotating commodities per week (15-minute delay).
Aluminum and nickel are often premium-locked; gold, heating oil, lumber,
etc. rotate in. Callers MUST treat a missing name as a miss and fall back
to FRED/yfinance — never fail the dashboard because this week's free set
did not include the metal you wanted.

Auth: ``API_NINJAS_KEY`` in the environment (X-Api-Key header).
Docs: https://api-ninjas.com/api/commodityprice
"""

from __future__ import annotations

import logging
import os

import requests

from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.api-ninjas.com/v1"
_SNAPSHOT_CACHE_KEY = "api_ninjas_commodity_snapshot_v1"
_SNAPSHOT_TTL = 3600  # 1 hour — live-ish without burning the monthly quota

# Pounds in a metric ton. Used to convert COMEX lb quotes to IMF USD/mt.
_LB_PER_METRIC_TON = 2204.62262185
_KG_PER_METRIC_TON = 1000.0
_SHORT_TON_PER_METRIC_TON = 1.1023113109  # 1 mt = 1.1023 short tons


def _api_key() -> str:
    return os.environ.get("API_NINJAS_KEY", "").strip()


def fetch_commodity_snapshot() -> dict[str, dict]:
    """Return this week's available commodity quotes keyed by slug (e.g. ``gold``).

    Empty dict if the key is missing or the request fails. Never raises to
    callers — a dead commodities feed must not take down a category score.
    """
    key = _api_key()
    if not key:
        return {}

    cached = get_cached(_SNAPSHOT_CACHE_KEY, ttl=_SNAPSHOT_TTL)
    if isinstance(cached, dict) and cached:
        return cached

    try:
        resp = requests.get(
            f"{_BASE_URL}/commoditysnapshot",
            headers={"X-Api-Key": key},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning("API Ninjas commodity snapshot failed: %s", exc)
        return {}

    if not isinstance(payload, list):
        logger.warning("API Ninjas snapshot returned unexpected payload type %s", type(payload))
        return {}

    by_name: dict[str, dict] = {}
    for item in payload:
        slug = str(item.get("value") or "").strip()
        if slug:
            by_name[slug] = item

    if by_name:
        set_cached(_SNAPSHOT_CACHE_KEY, by_name)
    return by_name


def get_commodity_quote(name: str) -> dict | None:
    """Return the snapshot quote for ``name``, or None if it is not in this week's free set."""
    if not name:
        return None
    return fetch_commodity_snapshot().get(name)


def usd_per_metric_ton(quote: dict) -> float:
    """Convert a Ninjas quote into USD per metric ton.

    Raises ValueError if the quote is not a mass unit we can convert (e.g.
    troy ounces, barrels, board feet). USX (cents) is divided by 100 first.
    """
    if not quote:
        raise ValueError("empty commodity quote")
    price = float(quote["price"])
    if str(quote.get("currency_unit", "USD")).upper() == "USX":
        price /= 100.0
    unit = str(quote.get("unit") or "").lower()
    if unit in {"metric_ton", "tonne", "mt"}:
        return price
    if unit == "kg":
        return price * _KG_PER_METRIC_TON
    if unit == "lb":
        return price * _LB_PER_METRIC_TON
    if unit == "short_ton":
        return price * _SHORT_TON_PER_METRIC_TON
    raise ValueError(f"cannot convert unit {unit!r} to USD/metric ton")
