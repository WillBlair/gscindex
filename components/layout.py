"""
Dashboard Layout
================
Assembles all components into the final page layout.

Includes a ``dcc.Interval`` component that triggers an auto-refresh
every 5 minutes so the dashboard stays live without manual reloads.

Layout structure:
    ┌─────────────────────────────────────────────┐
    │  Header (title + subtitle + last updated)   │
    ├───────────────┬─────────────────────────────┤
    │  Gauge        │  90-Day Trend (multi-line)   │
    ├──────┬──────┬─┴────┬──────┬──────┬──────┬───┤
    │ Card │ Card │ Card │ Card │ Card │ Card │Card│
    ├──────────────────┬──────────────────────────┤
    │ Category Health  │  Global Supply Chain Map   │
    │ Bars             │  (dots)                    │
    ├──────────────────┴──────────────────────────┤
    │    Alerts Feed       │  Disruptions Table    │
    └──────────────────────┴──────────────────────┘
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import dash_bootstrap_components as dbc
from dash import dcc, html

from components.cards import build_category_cards
from components.charts import build_category_panel, build_history_chart, build_world_map
from components.feed import build_briefing_panel, build_news_panel
from components.gauge import build_gauge_figure
from config import APP_SUBTITLE, APP_TITLE
from components.docs import build_docs_modal
from scoring import compute_composite_index

from components.market_costs import build_market_costs_panel

# Auto-refresh intervals (milliseconds)
_REFRESH_MS_NORMAL = 5 * 60 * 1000       # 5 min when data is fresh
_REFRESH_MS_PROVISIONAL = 20 * 1000       # 20 sec when serving stale/cached data


def build_layout(
    data: dict,
    *,
    is_provisional: bool = False,
    last_updated: datetime | None = None,
) -> html.Div:
    """Construct the full dashboard layout from aggregated data.

    Parameters
    ----------
    data : dict
        Output of ``aggregate_data()`` containing all data needed
        by every component.
    is_provisional : bool
        If True, the data is from a cache/fallback (not a live fetch this
        session).  A shorter auto-refresh interval is used so the page
        reloads automatically once the background thread finishes.

    last_updated : datetime | None
        Actual fetch/update time in UTC from the backend cache.

    Returns
    -------
    html.Div
        Root layout element for the Dash app.
    """
    current_scores = data["current_scores"]
    category_history = data["category_history"]
    map_markers = data["map_markers"]
    alerts = data["alerts"]
    disruptions = data["disruptions"]
    market_data = data.get("market_data", {})
    display_last_updated = last_updated.astimezone(ZoneInfo("America/Denver")) if last_updated else None

    # Compute composite index and day-over-day delta
    composite = compute_composite_index(current_scores)
    yesterday_scores = {
        cat: float(series.iloc[-2] if len(series) > 1 else series.iloc[-1])
        for cat, series in category_history.items()
    }
    composite_yesterday = compute_composite_index(yesterday_scores)
    delta = round(composite - composite_yesterday, 1)

    # Build sub-components
    gauge_fig = build_gauge_figure(composite, delta)
    category_metadata = data.get("category_metadata", {})
    category_cards = build_category_cards(current_scores, category_history, category_metadata)
    trend_fig = build_history_chart(category_history)
    health_panel = build_category_panel(current_scores)
    map_fig = build_world_map(map_markers)
    briefing = data.get("briefing", "")
    
    # New Layout Components
    briefing_panel = build_briefing_panel(briefing_text=briefing)
    news_panel = build_news_panel(alerts)
    
    market_panel = build_market_costs_panel(market_data)

    return html.Div(
        className="dashboard",
        children=[
            # ── Auto-refresh interval (hidden) ──────────────────────
            # 20s when provisional (waiting for background fetch), 5 min when fresh
            dcc.Interval(
                id="refresh-interval",
                interval=_REFRESH_MS_PROVISIONAL if is_provisional else _REFRESH_MS_NORMAL,
                n_intervals=0,
            ),
            html.Div(id="refresh-trigger", style={"display": "none"}),

            # ── Header ──────────────────────────────────────────────
            html.Header(
                className="dash-header",
                children=[
                    html.Div([
                        html.H1(APP_TITLE, className="app-title"),
                        html.P(APP_SUBTITLE, className="app-subtitle"),
                    ]),
                    html.Div(
                        className="header-meta",
                        children=[
                            html.Span(
                                (
                                    f"Last updated: {display_last_updated.strftime('%b %d, %Y %H:%M')}"
                                    if display_last_updated
                                    else "Last updated: warming up..."
                                ),
                                className="last-updated",
                            ),
                            html.Span(
                                "Updating — refreshing in ~20s..." if is_provisional else "Auto-refreshes every 5 min",
                                className="refresh-note",
                            ),
                            html.Span(
                                "● Updating..." if is_provisional else "● Live",
                                className="live-dot",
                                style={"color": "#fbbf24"} if is_provisional else {},
                            ),
                            
                            # Docs Button
                            dbc.Button(
                                "Docs",
                                id="docs-btn",
                                color="link",
                                className="docs-btn-header",
                                style={"color": "#9ca3af", "fontWeight": "600", "fontSize": "14px", "textDecoration": "none", "marginLeft": "15px"}
                            ),
                            
                            # API Button
                            dbc.Button(
                                "API",
                                id="api-btn",
                                color="link",
                                className="api-btn-header",
                                style={"color": "#6366f1", "fontWeight": "600", "fontSize": "14px", "textDecoration": "none", "marginLeft": "10px"}
                            ),
                        ],
                    ),
                ],
            ),

            # ── Hero Row (gauge + trend side-by-side) ───────────────
            html.Section(
                className="hero-row",
                children=[
                    html.Div(
                        className="chart-panel",
                        children=[
                            dcc.Graph(
                                id="gauge",
                                figure=gauge_fig,
                                config={"displayModeBar": False, "responsive": True},
                            ),
                        ],
                    ),
                    html.Div(
                        className="chart-panel",
                        children=[
                            dcc.Graph(
                                id="trend-chart",
                                figure=trend_fig,
                                # Disable scroll zoom and double-click reset for mobile stability
                                config={
                                    "displayModeBar": False, 
                                    "responsive": True,
                                    "scrollZoom": False,
                                    "doubleClick": False
                                },
                            ),
                        ],
                    ),
                ],
            ),

            # ── Market Costs Ticker ─────────────────────────────────
            market_panel,

            # ── Category Cards ──────────────────────────────────────
            html.Section(
                className="cards-row",
                children=category_cards,
            ),

            # ── Middle Row (health bars + world map) ────────────────
            html.Section(
                className="charts-row",
                children=[
                    html.Div(
                        className="chart-panel chart-narrow",
                        children=[health_panel],
                    ),
                    html.Div(
                        className="chart-panel chart-wide",
                        children=[
                            dcc.Graph(
                                id="world-map",
                                figure=map_fig,
                                config={"displayModeBar": False, "responsive": True},
                            ),
                        ],
                    ),
                ],
            ),

            # ── Bottom Panels (Briefing + News) ─────────────────────
            # Replacing Disruptions Table with News Panel as requested
            html.Section(
                className="bottom-row",
                children=[
                    html.Div(className="bottom-panel", children=[briefing_panel]),
                    html.Div(className="bottom-panel", children=[news_panel]),
                ],
            ),

            # ── Footer ──────────────────────────────────────────────
            html.Footer(
                className="dash-footer",
                children=[
                    html.P(
                        "Global Supply Chain Index — Built by William Blair  |  "
                        "Data: FRED, Open-Meteo, NewsAPI + VADER Sentiment",
                        className="footer-text",
                    ),
                ],
            ),
            
            # ── Hidden Data Stores ──────────────────────────────────
            dcc.Store(id="category-metadata-store", data=data.get("category_metadata", {})),
            
            # ── Detail Modal ────────────────────────────────────────
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Category Details"), id="modal-header"),
                    dbc.ModalBody(id="modal-body"),
                    dbc.ModalFooter(
                        dbc.Button("Close", id="modal-close", className="ms-auto", n_clicks=0)
                    ),
                ],
                id="details-modal",
                is_open=False,
                size="lg",  # Large modal
                centered=True,
                className="dark-modal" # Custom class for dark theme styling
            ),

            # ── API Documentation Modal ─────────────────────────────
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Public API Access"), className="modal-header"),
                    dbc.ModalBody(
                        children=[
                            html.P("Access the Global Supply Chain Index programmatically for your own dashboards or research."),
                            html.H5("Endpoint", style={"marginTop": "20px"}),
                            html.Code("GET https://gscindex.com/api/v1/latest", style={"display": "block", "padding": "10px", "backgroundColor": "#111", "borderRadius": "5px", "color": "#a5b4fc"}),
                            
                            html.H5("Usage Example (curl)", style={"marginTop": "20px"}),
                            html.Code("curl -X GET https://gscindex.com/api/v1/latest", style={"display": "block", "padding": "10px", "backgroundColor": "#111", "borderRadius": "5px", "color": "#22c55e"}),
                            
                            html.H5("Rate Limits", style={"marginTop": "20px"}),
                            html.Ul([
                                html.Li("60 requests per minute per IP"),
                                html.Li("2000 requests per day"),
                            ]),
                            
                            html.P("Data is cached globally and updated every 5 minutes. Please do not poll faster than that.", style={"color": "#fbbf24", "marginTop": "20px"}),
                        ]
                    ),
                    dbc.ModalFooter(
                        dbc.Button("Close", id="api-modal-close", className="ms-auto", n_clicks=0)
                    ),
                ],
                id="api-modal",
                is_open=False,
                size="lg",
                centered=True,
            ),

            # ── Docs Modal ──────────────────────────────────────────
            build_docs_modal(),
        ],
    )
