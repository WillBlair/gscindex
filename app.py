"""
Global Supply Chain Index — Global Supply Chain Health Index Dashboard
========================================================
Entry point. Run with:

    python app.py

Then open http://127.0.0.1:8050 in your browser.

The dashboard refreshes its panels in place every five minutes. Provider
fetches run in the background; UI callbacks only read the cached snapshot.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, ctx, html, dcc
from dotenv import load_dotenv

from components.layout import build_layout
from config import APP_TITLE, CATEGORY_WEIGHTS, FALLBACK_SNAPSHOT_MAX_AGE_DAYS, RETIRED_CATEGORIES
from data import aggregate_data

# Load .env before anything reads API keys
load_dotenv()


# Logging so provider activity is visible in the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ── Background Data Fetching ─────────────────────────────────────────
# Fetch data in a background thread so page loads are instant.
# --------------------------------------------------------------------

_DATA_CACHE = None
_LAST_UPDATE = None
_DATA_IS_FRESH = False  # True only after the background thread completes a real fetch
_LAST_FETCH_STATUS = "starting"
_LAST_FETCH_ERROR = None
_LAST_FETCH_DURATION_SECONDS = None
_FETCH_STARTED_AT: datetime | None = None   # start of the fetch in progress
_HAS_FETCHED_OK = False                       # any successful fetch since boot
_LOCK = threading.Lock()

from data.status import set_status, get_status
from data.runtime import memory_usage

# ── Key Migration: Remap old category names to current ones ──────────
_KEY_MIGRATIONS: dict[str, str] = {
    "ports": "supply_chain",
}

def _migrate_keys(data: dict) -> dict:
    """Remap legacy category keys to current names in-place.

    The retired industry categories (``config.RETIRED_CATEGORIES``) are dropped, so an old
    snapshot never shows them.
    """
    for section in ("current_scores", "category_history", "category_metadata"):
        sub = data.get(section)
        if not isinstance(sub, dict):
            continue
        for old_key, new_key in _KEY_MIGRATIONS.items():
            if old_key in sub and new_key not in sub:
                sub[new_key] = sub.pop(old_key)
        for key in RETIRED_CATEGORIES & set(sub):
            del sub[key]
    history = data.get("daily_history")
    if isinstance(history, dict) and isinstance(history.get("scores"), dict):
        for key in RETIRED_CATEGORIES & set(history["scores"]):
            del history["scores"][key]
    for section in ("fallback_categories", "stale_categories", "excluded_categories"):
        if isinstance(data.get(section), list):
            data[section] = [c for c in data[section] if c not in RETIRED_CATEGORIES]
    return data


def _has_current_categories(data: dict) -> bool:
    """Whether a stored snapshot covers every weighted category (current schema).

    A category the aggregator excluded (no live or recent stored score) is absent from
    ``current_scores`` but listed in ``excluded_categories``; that snapshot is current.
    """
    present = set(data.get("current_scores") or {}) | set(data.get("excluded_categories") or [])
    return set(CATEGORY_WEIGHTS).issubset(present)


def _extract_last_updated(data: dict | None) -> datetime | None:
    """Parse last update timestamp from dashboard payload if present."""
    if not data:
        return None
    raw = data.get("last_updated_utc")
    if not raw or not isinstance(raw, str):
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_placeholder_news_state(data: dict | None) -> bool:
    """Detect startup fallback state where news panels are intentionally blank."""
    if not data or not isinstance(data, dict):
        return False
    briefing = str(data.get("briefing", "") or "").strip().lower()
    alerts = data.get("alerts", [])
    return briefing.startswith("loading live supply-chain news analysis") and not alerts


def _is_stale(last_update: datetime | None, *, max_age_seconds: int) -> bool:
    """Return True if timestamp is missing or older than max_age_seconds."""
    if last_update is None:
        return True
    return (datetime.now(timezone.utc) - last_update).total_seconds() > max_age_seconds

# ── Load Persisted State (Fast Startup) ──────────────────────────────
# On Render, the filesystem is ephemeral: wiped on every deploy and spin-down.
# So we ONLY trust the disk cache if it exists (written by a prior run in this
# instance).  We do NOT load the committed fallback_snapshot_safe.json — it is
# always days old and was the root cause of "stuck on 87.9 for 5 days".
#
# Cold start flow: _DATA_CACHE = None → skeleton → background thread fetches
# → boot callback triggers reload → fresh data.  No stale fallback ever.

startup_data = None

# Layer 1: Disk cache only (from a previous successful run in this instance)
try:
    from data.cache import get_cached_dashboard
    startup_data = get_cached_dashboard()
    if startup_data:
        startup_data = _migrate_keys(startup_data)
        if not _has_current_categories(startup_data):
            logging.getLogger(__name__).warning(
                "INVALIDATING CACHE: Missing keys %s. Schema has changed.",
                set(CATEGORY_WEIGHTS) - set(startup_data.get("current_scores") or {}),
            )
            startup_data = None
        else:
            logging.getLogger(__name__).info("INSTANT STARTUP: Loaded persisted dashboard state (cache).")
except Exception as e:
    logging.getLogger(__name__).warning("Disk cache load failed: %s", e)
    startup_data = None

# Layer 1.5: Last good snapshot from the database (written hourly by the
# aggregator). Survives deploys, so a new instance starts from data that is
# at most about an hour old instead of the committed file.
if not startup_data:
    try:
        from data.cache import reconstruct_dashboard_state, set_cached_dashboard
        from data.database import load_dashboard_snapshot

        raw = load_dashboard_snapshot()
        if raw:
            raw = _migrate_keys(raw)
            if _has_current_categories(raw):
                startup_data = reconstruct_dashboard_state(raw)
                # Seed the disk cache too, so /api/v1/latest answers at once.
                set_cached_dashboard(startup_data)
                logging.getLogger(__name__).info(
                    "Cold start: loaded last snapshot from the database (%s).",
                    raw.get("last_updated_utc"),
                )
    except Exception as e:
        logging.getLogger(__name__).warning("Database snapshot load failed: %s", e)

# Layer 2: Fallback snapshot for cold start.  On Render, disk cache is empty on
# every deploy.  Without fallback, users see skeleton for 60+ seconds while the
# background fetch runs — often causing "waiting for gscindex.com" timeouts.
# Stale fallback (2–3 days old) is preferable to infinite loading.
if not startup_data:
    from pathlib import Path
    from data.cache import reconstruct_dashboard_state
    _fallback_path = Path(__file__).parent / "data" / "fallback_snapshot_safe.json"
    try:
        if _fallback_path.exists():
            raw = json.loads(_fallback_path.read_text())
            raw = _migrate_keys(raw)
            fallback_updated = _extract_last_updated(raw)
            too_old = _is_stale(
                fallback_updated, max_age_seconds=FALLBACK_SNAPSHOT_MAX_AGE_DAYS * 86400
            )
            if too_old:
                # Months-old numbers presented as the index are worse than
                # the loading skeleton for the ~60s first fetch.
                logging.getLogger(__name__).warning(
                    "Committed fallback snapshot is older than %d days; not serving it.",
                    FALLBACK_SNAPSHOT_MAX_AGE_DAYS,
                )
            elif _has_current_categories(raw):
                startup_data = reconstruct_dashboard_state(raw)
                # Never show stale narrative/news from committed fallback.
                startup_data["alerts"] = []
                startup_data["briefing"] = "Loading live supply-chain news analysis..."
                startup_data["full_report"] = ""
                startup_data["disruptions"] = []
                logging.getLogger(__name__).info(
                    "Cold start: Loaded fallback snapshot. Background fetch will refresh."
                )
    except Exception as e:
        logging.getLogger(__name__).warning("Fallback load failed: %s", e)
if not startup_data:
    logging.getLogger(__name__).info("Cold start: no cache or fallback. Showing skeleton until background fetch completes.")

# _DATA_CACHE = None on cold start; populated by background thread in ~60s
_DATA_CACHE = startup_data
_LAST_UPDATE = _extract_last_updated(startup_data) if startup_data else None

def _startup_is_fresh(data, last_update, now=None) -> bool:
    """Whether a snapshot loaded at startup may be treated as a live fetch.

    A disk cache is a prior successful fetch; it counts as fresh under 2 hours old.

    Snapshots saved before the Terminal redesign carry no ``daily_history``;
    those stay provisional so the 20s poll shows the first refresh.
    """
    if not data or not last_update:
        return False
    if "daily_history" not in data:
        logging.getLogger(__name__).warning("Startup snapshot has no daily_history. Marking as provisional.")
        return False
    age = ((now or datetime.now(timezone.utc)) - last_update).total_seconds()
    if age >= 7200:
        logging.getLogger(__name__).warning(f"Startup cache is stale ({age/3600:.1f}h old). Marking as provisional.")
        return False
    return True


_DATA_IS_FRESH = _startup_is_fresh(startup_data, _LAST_UPDATE)

# Preserve versioned news caches across worker recycling. Schema/prompt changes
# invalidate them through NEWS_BRIEFING_CACHE_KEY, not on every worker startup.


def update_data_loop():
    """Background loop that refreshes data every 5 minutes."""
    global _DATA_CACHE, _LAST_UPDATE, _DATA_IS_FRESH
    global _LAST_FETCH_STATUS, _LAST_FETCH_ERROR, _LAST_FETCH_DURATION_SECONDS
    global _FETCH_STARTED_AT, _HAS_FETCHED_OK
    
    logger = logging.getLogger("DataUpdater")
    logger.info("Starting background data updater...")
    
    while True:
        try:
            logger.info("Fetching fresh data from all providers; memory=%s", memory_usage())
            fetch_started = datetime.now(timezone.utc)
            with _LOCK:
                _LAST_FETCH_STATUS = "running"
                _LAST_FETCH_ERROR = None
                _FETCH_STARTED_AT = fetch_started
            set_status("Starting data update...")
            new_data = aggregate_data(status_callback=set_status)
            fetch_duration = (datetime.now(timezone.utc) - fetch_started).total_seconds()
            
            with _LOCK:
                _DATA_CACHE = new_data
                _LAST_UPDATE = _extract_last_updated(new_data) or datetime.now(timezone.utc)
                _DATA_IS_FRESH = True
                _LAST_FETCH_STATUS = "ok"
                _LAST_FETCH_ERROR = None
                _FETCH_STARTED_AT = None
                _HAS_FETCHED_OK = True
                _LAST_FETCH_DURATION_SECONDS = round(fetch_duration, 2)
            
            logger.info("Data update complete; memory=%s. Sleeping for 5 minutes.", memory_usage())
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"Data update failed: {e}")
            with _LOCK:
                _LAST_FETCH_STATUS = "failed"
                # Public on /health: say what failed, never the exception text
                # (request errors can include URLs with API keys).
                _LAST_FETCH_ERROR = type(e).__name__
                _FETCH_STARTED_AT = None
            time.sleep(60)

def create_app() -> dash.Dash:
    """Factory function that creates and configures the Dash application."""
    app = dash.Dash(
        __name__,
        title=APP_TITLE,
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
            {"name": "description", "content": "Independent global supply chain intelligence: health scores, port conditions, industry signals and the news behind them."},
        ],
        external_stylesheets=[
            dbc.themes.BOOTSTRAP,
            "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap",
        ],
        suppress_callback_exceptions=True,
    )

    # ── Custom Index String (Prevents White Flash) ──────────────────────
    app.index_string = '''
    <!DOCTYPE html>
    <html lang="en" data-bs-theme="dark">
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            {%css%}
            <style>
                body {
                    background-color: #000000;
                    color: #F2F4F7;
                    margin: 0;
                }
                ._dash-loading {
                    display: none;
                }
            </style>
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    '''

    # ── API & Rate Limiting ──────────────────────────────────────────────
    from api.routes import API_RATE_LIMIT, api_bp, get_limiter
    from api.report import report_bp
    from api.admin import admin_bp
    from api.docs import docs_bp
    from api.newsletter import newsletter_bp

    # Rate-limit the JSON API and admin routes per visitor IP. Dash page
    # loads and callbacks are not limited (one page view makes several).
    limiter = get_limiter(app.server)
    limiter.limit(API_RATE_LIMIT)(api_bp)
    limiter.limit(API_RATE_LIMIT)(admin_bp)

    app.server.register_blueprint(api_bp)
    app.server.register_blueprint(report_bp)
    app.server.register_blueprint(admin_bp)
    app.server.register_blueprint(docs_bp)
    app.server.register_blueprint(newsletter_bp)

    import flask

    @app.server.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return response

    @app.server.get("/health")
    @app.server.get("/healthz")
    def health():
        """Lightweight operational health endpoint for freshness monitoring."""
        now_utc = datetime.now(timezone.utc)
        with _LOCK:
            has_data = _DATA_CACHE is not None
            is_fresh = _DATA_IS_FRESH
            last_update = _as_utc(_LAST_UPDATE)
            fetch_status = _LAST_FETCH_STATUS
            fetch_error = _LAST_FETCH_ERROR
            fetch_duration = _LAST_FETCH_DURATION_SECONDS
            fetch_started_at = _FETCH_STARTED_AT
            has_fetched_ok = _HAS_FETCHED_OK
            snapshot = _DATA_CACHE or {}
            fallback_categories = list(snapshot.get("fallback_categories") or [])
            stale_categories = list(snapshot.get("stale_categories") or [])
            excluded_categories = list(snapshot.get("excluded_categories") or [])

        age_seconds = round((now_utc - last_update).total_seconds(), 1) if last_update else None
        try:
            status_message = get_status()
        except Exception:
            status_message = "status_unavailable"

        # Health policy:
        # - warming_up: no successful fetch since boot yet, first fetch not
        #   overdue (200 — Render fails a deploy if health returns 503)
        # - healthy: data exists and is under 30 minutes old
        # - degraded (503): data older than 30 minutes, or a fetch has been
        #   running for over 10 minutes (hung upstream call)
        running_for = (
            (now_utc - fetch_started_at).total_seconds() if fetch_started_at else 0.0
        )
        state = "healthy"
        http_status = 200
        if not has_fetched_ok and running_for <= 600:
            state = "warming_up"
        elif not has_data or age_seconds is None or age_seconds > 1800 or running_for > 600:
            state = "degraded"
            http_status = 503

        payload = {
            "state": state,
            "now_utc": now_utc.isoformat().replace("+00:00", "Z"),
            "is_fresh": is_fresh,
            "has_data": has_data,
            "last_updated_utc": last_update.isoformat().replace("+00:00", "Z") if last_update else None,
            "data_age_seconds": age_seconds,
            "last_fetch_status": fetch_status,
            "last_fetch_error": fetch_error,
            "last_fetch_duration_seconds": fetch_duration,
            "fallback_categories": fallback_categories,
            "stale_categories": stale_categories,
            "excluded_categories": excluded_categories,
            "status_message": status_message,
            "update_interval_seconds": 300,
            "process_memory": memory_usage(),
        }
        return flask.jsonify(payload), http_status

    # ── Skeleton Loading Import ─────────────────────────────────────────
    from components.skeleton import build_skeleton_layout

    # ── Layout as a function: Reads from memory instantly ────────────────
    def serve_layout():
        global _DATA_CACHE, _LAST_UPDATE, _DATA_IS_FRESH
        
        with _LOCK:
            data = _DATA_CACHE
            is_fresh = _DATA_IS_FRESH
            last_update = _LAST_UPDATE

        # Keep worker memory in sync with disk snapshot.
        # This self-heals stale workers and protects against background-thread hangs.
        # We refresh from disk when:
        # - memory is empty
        # - memory still has startup placeholder news
        # - memory timestamp is stale
        # - disk has a strictly newer snapshot
        from data.cache import get_cached_dashboard
        try:
            disk_data = get_cached_dashboard()
            if disk_data:
                disk_data = _migrate_keys(disk_data)
                disk_last_update = _extract_last_updated(disk_data)
                disk_age_seconds = (
                    (datetime.now(timezone.utc) - disk_last_update).total_seconds()
                    if disk_last_update else None
                )
                disk_is_fresh = bool(disk_age_seconds is not None and disk_age_seconds < 7200)
                memory_stale = _is_stale(last_update, max_age_seconds=1800)
                disk_is_newer = bool(
                    disk_last_update
                    and (
                        last_update is None
                        or disk_last_update > (last_update + timedelta(seconds=30))
                    )
                )
                needs_disk_refresh = (
                    data is None
                    or _is_placeholder_news_state(data)
                    or memory_stale
                    or disk_is_newer
                )
                if needs_disk_refresh:
                    with _LOCK:
                        # Never overwrite a newer background fetch with older disk data.
                        if _LAST_UPDATE is None or (disk_last_update and disk_last_update >= _LAST_UPDATE):
                            _DATA_CACHE = disk_data
                            _LAST_UPDATE = disk_last_update
                            _DATA_IS_FRESH = disk_is_fresh
                        data, is_fresh, last_update = _DATA_CACHE, _DATA_IS_FRESH, _LAST_UPDATE
        except Exception as e:
            logging.getLogger(__name__).warning(f"Lazy load from disk failed: {e}")

        if data is None:
            return build_skeleton_layout()

        # Build the actual dashboard.
        # When data is provisional (from fallback/cache, not a live fetch),
        # poll the snapshot every 20 seconds until providers finish.
        # Once fresh, panels update in place every five minutes.
        layout = build_layout(data, is_provisional=not is_fresh, last_updated=last_update)
        return layout

    app.layout = serve_layout
    
    # ── Boot Sequence: Polling & Reload ─────────────────────────────────
    # This callback handles the "Loading..." screen updates and triggers
    # a reload once data is ready.
    
    @app.callback(
        [Output("loading-message", "children"), 
         Output("boot-reload-trigger", "children")],
        Input("boot-interval", "n_intervals"),
    )
    def update_boot_status(n):
        # 1. Check if data is ready in memory
        with _LOCK:
            if _DATA_CACHE is not None:
                return "Data loaded! Launching dashboard...", "RELOAD"

        # 2. If startup exceeds 5 minutes, show actionable status.
        if n >= 300:
            return "Startup is taking longer than expected. Please refresh in 30 seconds.", dash.no_update
        
        # 3. Check the disk-based status file (handles multi-worker case)
        try:
            current_status = get_status()
            if current_status == "Data ready!":
                return "Data loaded! Launching dashboard...", "RELOAD"
            return current_status, dash.no_update
        except Exception:
            return "Initializing...", dash.no_update

    app.clientside_callback(
        """
        function(trigger) {
            if (trigger === "RELOAD") {
                window.location.reload();
            }
            return '';
        }
        """,
        Output("boot-reload-trigger", "children", allow_duplicate=True),
        Input("boot-reload-trigger", "children"),
        prevent_initial_call=True
    )

    # ── API Modal Callback ──────────────────────────────────────────────
    @app.callback(
        Output("api-modal", "is_open"),
        Input("api-btn", "n_clicks"),
        Input("api-modal-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_api_modal(open_click, close_click):
        ctx_id = ctx.triggered_id
        if ctx_id == "api-btn":
            return True
        return False

    # ── Newsletter Submit Callback ────────────────────────────────────────────
    from components.terminal_data import TIER_COLORS

    _FEEDBACK_OK = {"color": TIER_COLORS["Healthy"]}
    _FEEDBACK_ERROR = {"color": TIER_COLORS["Critical"]}
    # Letters, digits and . _ % + - in the local part; no quotes, commas or
    # spaces, which could otherwise end up inside the email To header.
    _EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}")

    @app.callback(
        Output("newsletter-feedback", "children"),
        Output("newsletter-feedback", "style"),
        Output("newsletter-email", "value"),
        Input("newsletter-submit", "n_clicks"),
        State("newsletter-email", "value"),
        prevent_initial_call=True,
    )
    def handle_newsletter_submit(n_clicks, email):
        email = str(email or "").strip().lower()
        if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
            return "Please enter a valid email address.", _FEEDBACK_ERROR, dash.no_update
        
        from data.database import add_subscriber
        result = add_subscriber(email)
        
        if result.get("success"):
            return "You're subscribed to the daily briefing.", _FEEDBACK_OK, ""
        else:
            return result.get("message", "An error occurred."), _FEEDBACK_ERROR, dash.no_update

    from components.workspace_callbacks import register_workspace_callbacks

    def get_snapshot():
        with _LOCK:
            return _DATA_CACHE, _DATA_IS_FRESH

    register_workspace_callbacks(app, get_snapshot)

    return app


# ── Main ────────────────────────────────────────────────────────────────────

# Initialize Database
from data.database import init_db
init_db()

# Create the app globally so Gunicorn can find it
app = create_app()
server = app.server  # Expose the Flask server for Gunicorn

# ── Background Thread: Hot Reload Fix ───────────────────────────────────────
# Only start the background thread if we are NOT in the reloader process (WERKZEUG_RUN_MAIN=true)
# OR if we are running in a production WSGI container.
# The previous logic was: if not os.environ.get("WERKZEUG_RUN_MAIN") or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
# This meant it ran in BOTH the parent and the reloader child. 
# We want it ONLY in the child (actual server) to avoid double threads, 
# BUT aggressive reloading kills threads.
# A common pattern for robust background tasks in Dash dev is to check specifically.

def start_background_thread():
    if not any(t.name == "DataUpdater" for t in threading.enumerate()):
        # Delayed start to allow Flask/Dash to fully initialize ports
        def delayed_start():
            logger = logging.getLogger("DataUpdater")
            logger.info("Initializing background data updater thread...")
            time.sleep(2) 
            bg_thread = threading.Thread(target=update_data_loop, daemon=True, name="DataUpdater")
            bg_thread.start()
            logger.info("Background data updater thread started.")
        
        threading.Thread(target=delayed_start, daemon=True).start()

# When running via `python app.py`:
if __name__ == "__main__":
    # In debug mode, Werkzeug runs a parent process (monitor) and a child process (worker).
    # WERKZEUG_RUN_MAIN is set 'true' in the child.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_thread()
    
    app.run(debug=True, host="127.0.0.1", port=8050)

# When running via Gunicorn (Production):
# WERKZEUG_RUN_MAIN is not set. We just start it.
elif os.environ.get("GSC_DISABLE_BACKGROUND") != "1":
    start_background_thread()
