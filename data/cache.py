"""
Simple File-Based Cache
========================
Prevents hammering APIs on every page load during development.

Cached data is stored as JSON files in ``data/.cache/`` with a configurable
TTL (time-to-live). The cache directory is git-ignored.

Usage
-----
>>> from data.cache import get_cached, set_cached
>>> result = get_cached("fred_DCOILWTICO")
>>> if result is None:
...     result = expensive_api_call()
...     set_cached("fred_DCOILWTICO", result)
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

# Use /tmp in serverless environments (Vercel), otherwise local .cache
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    _CACHE_DIR = Path(tempfile.gettempdir()) / "supply_chain_cache"
else:
    _CACHE_DIR = Path(__file__).parent / ".cache"

# Default TTL: 1 hour. Override per call if needed.
DEFAULT_TTL_SECONDS = 3600


def get_cached(key: str, ttl: int = DEFAULT_TTL_SECONDS) -> dict | list | None:
    """Return cached data if it exists and hasn't expired.

    Parameters
    ----------
    key : str
        Cache key (used as filename, so keep it filesystem-safe).
    ttl : int
        Maximum age in seconds before the cache is considered stale.

    Returns
    -------
    dict | list | None
        The cached data, or ``None`` if cache is missing or expired.
    """
    path = _CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None

    age_seconds = time.time() - path.stat().st_mtime
    if age_seconds > ttl:
        return None

    return json.loads(path.read_text())


def set_cached(key: str, data: dict | list) -> None:
    """Write data to the cache.

    Parameters
    ----------
    key : str
        Cache key.
    data : dict | list
        JSON-serializable data to store.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data, default=str))


def clear_cache() -> None:
    """Delete all cached files. Useful for forcing a full refresh."""
    if _CACHE_DIR.exists():
        for f in _CACHE_DIR.glob("*.json"):
            f.unlink()
