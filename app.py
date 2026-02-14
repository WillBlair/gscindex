"""
Global Supply Chain Index — Global Supply Chain Health Index Dashboard
========================================================
Entry point. Run with:

    python app.py

Then open http://127.0.0.1:8050 in your browser.

The dashboard auto-refreshes every 5 minutes by reloading the page
with fresh data from all providers. Cached data (1-hour TTL) prevents
unnecessary API calls during rapid reloads.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, html, dcc
from dotenv import load_dotenv

from components.layout import build_layout
from config import APP_TITLE, CATEGORY_WEIGHTS
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
_LOCK = threading.Lock()

from data.status import set_status, get_status

# ── Key Migration: Remap old category names to current ones ──────────
_KEY_MIGRATIONS: dict[str, str] = {
    "ports": "supply_chain",
    "shipping": "trucking",
}

def _migrate_keys(data: dict) -> dict:
    """Remap legacy category keys to current names in-place."""
    for section in ("current_scores", "category_history", "category_metadata"):
        sub = data.get(section)
        if not isinstance(sub, dict):
            continue
        for old_key, new_key in _KEY_MIGRATIONS.items():
            if old_key in sub and new_key not in sub:
                sub[new_key] = sub.pop(old_key)
    return data


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
        required_keys = set(CATEGORY_WEIGHTS.keys())
        cached_keys = set(startup_data.get("current_scores", {}).keys())
        if not required_keys.issubset(cached_keys):
            logging.getLogger(__name__).warning(
                "INVALIDATING CACHE: Missing keys %s. Schema has changed.",
                required_keys - cached_keys,
            )
            startup_data = None
        else:
            logging.getLogger(__name__).info("INSTANT STARTUP: Loaded persisted dashboard state (cache).")
except Exception as e:
    logging.getLogger(__name__).warning("Disk cache load failed: %s", e)
    startup_data = None

# Layer 2: NO fallback snapshot.  On cold start, stay empty so we show skeleton
# until the background thread completes.  Never show days-old committed data.
if not startup_data:
    logging.getLogger(__name__).info("Cold start: no cache. Showing skeleton until background fetch completes.")

# _DATA_CACHE = None on cold start; populated by background thread in ~60s
_DATA_CACHE = startup_data
_LAST_UPDATE = _extract_last_updated(startup_data) if startup_data else None
# Disk cache = prior successful fetch, so treat as fresh (no 20s refresh loop)
if startup_data:
    _DATA_IS_FRESH = True

# ── Clear Stale News Cache (Deploy Cache Bust) ──────────────────────
# On every startup (i.e. every deploy), clear the newsapi briefing cache
# so the background thread regenerates the report with the latest code.
# Without this, old cached reports survive for 4 hours after a deploy.
try:
    from data.cache import _CACHE_DIR
    _news_cache = _CACHE_DIR / "newsapi_briefing_v14.json"
    if _news_cache.exists():
        _news_cache.unlink()
        logging.getLogger(__name__).info("Cleared stale news cache for fresh report generation.")
except Exception as e:
    logging.getLogger(__name__).warning(f"Failed to clear stale news cache: {e}")


def update_data_loop():
    """Background loop that refreshes data every 5 minutes."""
    global _DATA_CACHE, _LAST_UPDATE, _DATA_IS_FRESH
    global _LAST_FETCH_STATUS, _LAST_FETCH_ERROR, _LAST_FETCH_DURATION_SECONDS
    
    logger = logging.getLogger("DataUpdater")
    logger.info("Starting background data updater...")
    
    while True:
        try:
            logger.info("Fetching fresh data from all providers...")
            fetch_started = datetime.now(timezone.utc)
            with _LOCK:
                _LAST_FETCH_STATUS = "running"
                _LAST_FETCH_ERROR = None
            set_status("Starting data update...")
            new_data = aggregate_data(status_callback=set_status)
            fetch_duration = (datetime.now(timezone.utc) - fetch_started).total_seconds()
            
            with _LOCK:
                _DATA_CACHE = new_data
                _LAST_UPDATE = _extract_last_updated(new_data) or datetime.now(timezone.utc)
                _DATA_IS_FRESH = True
                _LAST_FETCH_STATUS = "ok"
                _LAST_FETCH_ERROR = None
                _LAST_FETCH_DURATION_SECONDS = round(fetch_duration, 2)
            
            logger.info("Data update complete. Sleeping for 5 minutes.")
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"Data update failed: {e}")
            with _LOCK:
                _LAST_FETCH_STATUS = "failed"
                _LAST_FETCH_ERROR = str(e)
            time.sleep(60)

def create_app() -> dash.Dash:
    """Factory function that creates and configures the Dash application."""
    app = dash.Dash(
        __name__,
        title=APP_TITLE,
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        ],
        external_stylesheets=[
            dbc.themes.DARKLY,
            "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
            "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap",
        ],
        suppress_callback_exceptions=True,
    )

    # ── Custom Index String (Prevents White Flash) ──────────────────────
    app.index_string = '''
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
            <style>
                body {
                    background-color: #0f1117;
                    color: #e1e4ea;
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
    from api.routes import api_bp, get_limiter
    from api.report import report_bp
    
    # Initialize Rate Limiter
    limiter = get_limiter(app.server)
    
    # Register API Blueprint
    app.server.register_blueprint(api_bp)
    app.server.register_blueprint(report_bp)
    
    import flask
    
    # Exempt Dash's hot-reload endpoint from rate limiting
    # This prevents "429 Too Many Requests" during development
    @limiter.request_filter
    def ignore_dash_reload():
        return flask.request.path.startswith("/_reload-hash")

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

        age_seconds = round((now_utc - last_update).total_seconds(), 1) if last_update else None
        try:
            status_message = get_status()
        except Exception:
            status_message = "status_unavailable"

        # Health policy:
        # - healthy: data exists and is not too old
        # - warming_up: no data yet
        # - degraded: data exists but stale (>30m) or fetch is failing
        state = "healthy"
        http_status = 200
        if not has_data:
            state = "warming_up"
            http_status = 503
        elif fetch_status == "failed":
            state = "degraded"
            if age_seconds is None or age_seconds > 1800:
                http_status = 503
        elif age_seconds is not None and age_seconds > 1800:
            state = "degraded"

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
            "status_message": status_message,
            "update_interval_seconds": 300,
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
            
        # If no memory cache, try lazy-load from disk (recovers if another worker updated it)
        if data is None:
            from data.cache import get_cached_dashboard
            try:
                disk_data = get_cached_dashboard()
                if disk_data:
                    with _LOCK:
                        _DATA_CACHE = disk_data
                        _LAST_UPDATE = _extract_last_updated(disk_data) or datetime.now(timezone.utc)
                        _DATA_IS_FRESH = True  # disk cache = prior successful fetch
                    data = disk_data
                    is_fresh = True
                    last_update = _LAST_UPDATE
            except Exception as e:
                logging.getLogger(__name__).warning(f"Lazy load from disk failed: {e}")

        if data is None:
            return build_skeleton_layout()

        # Build the actual dashboard.
        # When data is provisional (from fallback/cache, not a live fetch),
        # use a 20-second refresh so the page auto-reloads once the
        # background thread finishes (~50-60s).  Once fresh, back to 5 min.
        layout = build_layout(data, is_provisional=not is_fresh, last_updated=last_update)
        return layout

    app.layout = serve_layout
    
    # Client-side auto-refresh (reload page) every 5 minutes 
    # to pick up the new data from the backend
    app.clientside_callback(
        """
        function(n) {
            if (n > 0) {
                window.location.reload();
            }
            return '';
        }
        """,
        Output("refresh-trigger", "children"),
        Input("refresh-interval", "n_intervals"),
    )

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
    
    # Callback to auto-reload the page once data is ready (replaces "boot-check")
    # We use the same interval-based polling pattern, but now hidden in the skeleton
    # Actually, the skeleton doesn't have the interval component by default.
    # We should inject it into the skeleton or keep a global interval.
    # The simplest way is to add the poller to the skeleton layout components/skeleton.py,
    # OR better: Add it here to index_string or layout wrapper? 
    # For now, let's just make sure the skeleton layout INCLUDES the poller.
    # I'll rely on the user manually refreshing or adds a simple meta-refresh for now to keep it simple,
    # OR I'll add a client-side interval to the skeleton in a future step if needed. 
    # Wait, the previous code had dcc.Interval(id="boot-check"). 
    # The skeleton layout purely replacing HTML means we LOSE that interval.
    # I should wrap the return.
    


    # ── Generate Briefing On-Demand (Option 5: User-Triggered) ───────────
    @app.callback(
        Output("briefing-content", "children"),
        Input("generate-briefing-btn", "n_clicks"),
        prevent_initial_call=True
    )
    def generate_briefing_callback(n_clicks):
        """Generate AI briefing only when user clicks the button."""
        if not n_clicks:
            return dash.no_update
        
        from api.briefing import get_on_demand_briefing
        from config import COLORS
        
        result = get_on_demand_briefing()
        
        if result["success"] and result["briefing"]:
            # Return formatted briefing content
            return [
                html.P(line, style={"marginBottom": "8px"}) 
                for line in result["briefing"].split("\n") 
                if line.strip()
            ]
        else:
            # Return error message
            return html.P(
                result.get("error", "Failed to generate briefing. Please try again later."),
                style={"color": COLORS["red"], "fontSize": "13px"}
            )

    # ── Modal Interaction Callback ──────────────────────────────────────
    from dash import ALL, ctx
    from config import CATEGORY_LABELS, CATEGORY_WEIGHTS

    @app.callback(
        Output("details-modal", "is_open"),
        Output("modal-header", "children"),
        Output("modal-body", "children"),
        Input("modal-close", "n_clicks"),
        [Input(f"card-{cat}", "n_clicks") for cat in CATEGORY_WEIGHTS],
        Input("category-metadata-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_modal(close_clicks, *args):
        # args = (card_click_1, ..., card_click_N, metadata)
        # We need *args because the number of cards (and thus Inputs) is dynamic
        # based on config.CATEGORY_WEIGHTS.
        metadata = args[-1]
        
        import traceback
        
        try:
            triggered = ctx.triggered_id
            
            # If closed via button
            if triggered == "modal-close":
                return False, dash.no_update, dash.no_update
                
            # If clicked a card
            # triggered will be "card-energy", "card-ports", etc.
            if triggered and triggered.startswith("card-"):
                # Safety check for metadata
                if metadata is None:
                    logging.error("Metadata is None in callback!")
                    metadata = {}

                cat = triggered.replace("card-", "")
                meta = metadata.get(cat, {})
                
                label = CATEGORY_LABELS.get(cat, cat.title())
                
                # Build Metadata Content
                tier = meta.get("tier", {})
                score = meta.get("score", "N/A")
                tier_color = tier.get("color", "#ffffff")
                tier_label = tier.get("label", "Unknown")

                # Progress bar style visual for score
                progress_style = {
                    "width": f"{score}%" if isinstance(score, (int, float)) else "0%",
                    "height": "8px",
                    "backgroundColor": tier_color,
                    "borderRadius": "4px",
                    "marginTop": "5px"
                }

                content = html.Div([
                    # Top Section: Score & Tier
                    html.Div([
                        html.Div([
                            html.H6("Index Score", style={"color": "#9ca3af", "marginBottom": "0"}),
                            html.H1(f"{score}", style={"fontWeight": "900", "fontSize": "48px", "color": tier_color, "margin": "0"}),
                            html.Div(style=progress_style),
                        ], style={"flex": "1"}),
                        
                        html.Div([
                            html.H6("Health Tier", style={"color": "#9ca3af", "marginBottom": "5px"}),
                            dbc.Badge(tier_label, color="light", style={
                                "backgroundColor": tier_color, 
                                "color": "#000" if tier_label in ["Healthy", "Stable"] else "#fff",
                                "fontSize": "18px", 
                                "padding": "8px 12px"
                            }),
                        ], style={"flex": "1", "textAlign": "right"})
                    ], style={"display": "flex", "alignItems": "center", "marginBottom": "25px", "paddingBottom": "20px", "borderBottom": "1px solid #2a2d3a"}),

                    # Middle Section: Raw Data & Source
                    html.H5("Underlying Data", style={"color": "#fff", "fontWeight": "bold", "marginBottom": "15px"}),
                    html.Div([
                        html.Div([
                            html.Span("Raw Value", style={"color": "#9ca3af", "fontSize": "14px"}),
                            html.H3(meta.get("raw_value", "N/A"), style={"fontWeight": "bold", "marginTop": "5px"}),
                        ], style={"flex": "1"}),
                        html.Div([
                            html.Span("Data Source", style={"color": "#9ca3af", "fontSize": "14px"}),
                            html.P(meta.get("source", "Unknown"), style={"fontWeight": "500", "marginTop": "5px", "color": "#6366f1"}),
                        ], style={"flex": "1"})
                    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px", "backgroundColor": "#1a1d26", "padding": "15px", "borderRadius": "8px"}),
                    
                    # Bottom Section: Reasoning
                    html.H5("Analysis", style={"color": "#fff", "fontWeight": "bold", "marginBottom": "10px"}),
                    html.P(meta.get("description", "No detailed description available."), style={"fontSize": "15px", "lineHeight": "1.6", "color": "#d1d5db", "marginBottom": "25px"}),

                    # Extra Bottom Section: Math / Calculation Logic
                    html.H5("Scoring Logic", style={"color": "#fff", "fontWeight": "bold", "marginBottom": "10px"}),
                    html.Div(
                        html.Code(meta.get("calculation", "Calculation logic not available."), style={"color": "#a5b4fc", "fontFamily": "monospace"}),
                        style={"backgroundColor": "#1e1b4b", "padding": "15px", "borderRadius": "8px", "border": "1px solid #4338ca"}
                    ),
                    
                    html.Hr(style={"borderColor": "#2a2d3a", "marginTop": "20px"}),
                    html.Small(f"Raw Label: {meta.get('raw_label', '')} | Last Updated: {meta.get('updated', 'Unknown')}", style={"color": "#6b7280"})
                ])
                
                # Use html.H5 instead of dbc.ModalTitle for safety
                return True, html.H5(f"{label} Details"), content
                
            return False, dash.no_update, dash.no_update
            
        except Exception as e:
            logging.error(f"Callback Error: {e}")
            logging.error(traceback.format_exc())
            return False, dash.no_update, dash.no_update

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

    # ── Docs Modal Callback ─────────────────────────────────────────────
    @app.callback(
        Output("docs-modal", "is_open"),
        Input("docs-btn", "n_clicks"),
        Input("docs-modal-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_docs_modal(open_click, close_click):
        ctx_id = ctx.triggered_id
        if ctx_id == "docs-btn":
            return True
        return False

    return app


# ── Main ────────────────────────────────────────────────────────────────────

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
else:
    start_background_thread()
