"""The long index history (every day since config.HISTORY_START_DATE), loaded once a UTC day.

About 23,000 stored category rows are read from the database at most once per UTC day,
built into a plain dict (``components.history_data.build_history``), kept in memory behind
a lock and copied to disk. Request handlers call ``get()``, which touches neither disk nor
the database. A failed or empty read never replaces a good copy.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone

import config
from components import history_data
from data import cache, database

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_HISTORY: dict | None = None


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def get() -> dict | None:
    """The memory copy, or None before the first load. Never touches disk or the database."""
    with _LOCK:
        return _HISTORY


def reset() -> None:
    global _HISTORY
    with _LOCK:
        _HISTORY = None


def _set(history: dict) -> None:
    global _HISTORY
    with _LOCK:
        _HISTORY = history


def _disk_copy(max_age_seconds: int) -> dict | None:
    """A well-formed disk copy for the configured start date, else None."""
    try:
        data = cache.get_cached(config.HISTORY_CACHE_KEY, ttl=max_age_seconds)
    except Exception as exc:
        logger.warning("Long history disk copy unreadable: %s", exc)
        return None
    if (isinstance(data, dict) and data.get("start") == config.HISTORY_START_DATE
            and isinstance(data.get("loaded_on"), str) and data.get("dates")
            and isinstance(data.get("scores"), dict)):
        return data
    return None


def refresh_if_due(today: date | None = None) -> bool:
    """True when memory holds a load made on ``today`` (UTC) after the call. Never raises."""
    try:
        today = today or _utc_today()
        current = get()
        if current is not None and current.get("loaded_on") == today.isoformat():
            return True
        disk = _disk_copy(config.HISTORY_CACHE_MAX_AGE_SECONDS)
        if disk is not None and disk["loaded_on"] == today.isoformat():
            _set(disk)
            return True
        start = date.fromisoformat(config.HISTORY_START_DATE)
        rows = database.export_category_rows(start, list(config.CATEGORY_WEIGHTS), strict=True)
        history = history_data.build_history(rows, start, today)
        if not history["dates"]:
            logger.warning("Long history read returned no days; keeping the previous copy")
            return False
        _set(history)
        try:
            cache.set_cached(config.HISTORY_CACHE_KEY, history)
        except Exception as exc:
            logger.warning("Long history disk copy not written: %s", exc)
        return True
    except Exception as exc:
        logger.warning("Long history refresh failed: %s", exc)
        return False


def prime_from_disk() -> bool:
    """Fill an empty memory from a recent disk copy. No database. Never raises."""
    try:
        if get() is not None:
            return True
        disk = _disk_copy(config.HISTORY_CACHE_MAX_AGE_SECONDS)
        if disk is None:
            return False
        _set(disk)
        return True
    except Exception as exc:
        logger.warning("Long history prime failed: %s", exc)
        return False
