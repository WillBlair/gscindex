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
import logging
import os
import pickle
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

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
        for f in _CACHE_DIR.glob("*"):
            f.unlink()


# ── Pickle Support for Complex Objects (DataFrames, etc.) ──────────────────

def get_cached_pickle(key: str, ttl: int = 3600) -> Any | None:
    """Retrieve a pickled object from cache if it exists and is fresh."""
    filename = _get_cache_path(key, ext=".pkl")
    if not filename.exists():
        return None
        
    try:
        mod_time = filename.stat().st_mtime
        if (time.time() - mod_time) > ttl:
            return None
            
        with open(filename, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"Cache miss (pickle error) for {key}: {e}")
        return None


def set_cached_pickle(key: str, data: Any) -> None:
    """Save an object to cache using pickle."""
    filename = _get_cache_path(key, ext=".pkl")
    try:
        with open(filename, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        logger.warning(f"Failed to write cache (pickle) {key}: {e}")


def set_cached_dashboard(data: dict) -> None:
    """Save the full dashboard state as JSON (safe serialization).
    
    Converts complex types (Pandas Series/Index) to standard lists/strings
    to avoid pickle dependency issues on production servers.
    """
    
    safe_data = data.copy()
    
    # 1. Convert Index to list of strings
    if "dates" in safe_data and isinstance(safe_data["dates"], pd.Index):
        safe_data["dates"] = safe_data["dates"].strftime("%Y-%m-%d").tolist()
        
    # 2. Convert DataFrames/Series to primitive dictionaires/lists
    if "category_history" in safe_data:
        # Convert {cat: Series} -> {cat: list[float]}
        safe_history = {}
        for cat, series in safe_data["category_history"].items():
            if isinstance(series, pd.Series):
                safe_history[cat] = series.replace({np.nan: None}).tolist()
            else:
                safe_history[cat] = series
        safe_data["category_history"] = safe_history

    set_cached("dashboard_snapshot_safe", safe_data)


def reconstruct_dashboard_state(data: dict) -> dict:
    """Helper to reconstruct Pandas types from JSON-safe dashboard state."""
    try:
        if "dates" in data and data["dates"]:
             data["dates"] = pd.to_datetime(data["dates"])
            
        if "category_history" in data and "dates" in data:
            restored_history = {}
            for cat, values in data["category_history"].items():
                # Reconstruct Series using the datetime index
                restored_history[cat] = pd.Series(values, index=data["dates"], name=cat)
            data["category_history"] = restored_history
        return data
    except Exception as e:
        logger.error(f"Failed to reconstruct dashboard state: {e}")
        return data  # Return partial/best-effort data if reconstruction fails

    data = get_cached("dashboard_snapshot_safe", ttl=3600)
    if not data:
        return None
    return reconstruct_dashboard_state(data)
