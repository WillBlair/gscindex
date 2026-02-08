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

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, html
from dotenv import load_dotenv

from components.layout import build_layout
from config import APP_TITLE
from data import aggregate_data

# Load .env before anything reads API keys
load_dotenv()

# Logging so provider activity is visible in the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


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
        ],
        suppress_callback_exceptions=True,
    )

    # ── Layout as a function: re-executes on every page load ────────────
    # This means every browser refresh fetches fresh data (subject to cache TTL).
    def serve_layout():
        try:
            data = aggregate_data()
            if data.get("provider_errors"):
                for cat, err in data["provider_errors"].items():
                    logging.getLogger(__name__).warning(
                        "Category '%s' using fallback: %s", cat, err
                    )
            return build_layout(data)
        except Exception as e:
            import traceback
            logging.error("Error loading layout: %s", e)
            return html.Div([
                html.H1("Error loading layout"),
                html.Pre(traceback.format_exc(), style={"color": "red", "whiteSpace": "pre-wrap"})
            ], style={"padding": "20px", "backgroundColor": "#1a1d26", "color": "white"})

    app.layout = serve_layout

    # ── Auto-refresh: reload the page every 5 minutes ───────────────────
    # The dcc.Interval fires every 5 min, the clientside callback reloads
    # the page so serve_layout() runs again with fresh data.
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

    return app


# ── Main ────────────────────────────────────────────────────────────────────

# Create the app globally so Gunicorn can find it
app = create_app()
server = app.server  # Expose the Flask server for Gunicorn

if __name__ == "__main__":
    # This block only runs when you run "python app.py" locally
    app.run(debug=True, host="127.0.0.1", port=8050)
