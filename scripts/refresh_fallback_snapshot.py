"""
Refresh the committed cold-start snapshot (data/fallback_snapshot_safe.json).

The app no longer rewrites this tracked file at runtime. It is only a last
resort on a cold start with no disk cache and no database snapshot, and is
ignored once older than FALLBACK_SNAPSHOT_MAX_AGE_DAYS. Run this before a
deploy when the committed copy is getting old, then commit the file:

    python scripts/refresh_fallback_snapshot.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from config import CATEGORY_WEIGHTS  # noqa: E402
from data.cache import _write_text_atomic, dashboard_to_safe_dict, get_cached_dashboard  # noqa: E402
from data.database import load_dashboard_snapshot  # noqa: E402

OUT = ROOT / "data" / "fallback_snapshot_safe.json"


def main() -> int:
    snapshot = load_dashboard_snapshot()
    source = "database"
    if not snapshot:
        cached = get_cached_dashboard()
        snapshot = dashboard_to_safe_dict(cached) if cached else None
        source = "disk cache"
    if not snapshot:
        print("No snapshot in the database or disk cache. Run the app once first.")
        return 1

    degraded = [c for c in snapshot.get("fallback_categories", []) if c in CATEGORY_WEIGHTS]
    if degraded:
        print(f"Refusing: baseline categories are on fallback values: {degraded}")
        return 1

    # The app clears narrative fields on load; don't commit stale news text.
    snapshot = {**snapshot, "alerts": [], "briefing": "", "full_report": "", "disruptions": []}
    _write_text_atomic(OUT, json.dumps(snapshot, default=str))
    print(f"Wrote {OUT.relative_to(ROOT)} from {source} ({snapshot.get('last_updated_utc')}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
