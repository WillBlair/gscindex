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

from dash import dcc, html

from components.cards import build_category_cards
from components.charts import build_category_panel, build_history_chart, build_world_map
from components.feed import build_alerts_feed, build_disruptions_table
from components.gauge import build_gauge_figure
from config import APP_SUBTITLE, APP_TITLE, COLORS
from scoring import compute_composite_index

# Auto-refresh interval: 5 minutes (in milliseconds)
_REFRESH_MS = 5 * 60 * 1000


def build_layout(data: dict) -> html.Div:
    """Construct the full dashboard layout from aggregated data.

    Parameters
    ----------
    data : dict
        Output of ``aggregate_data()`` containing all data needed
        by every component.

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

    # Compute composite index and day-over-day delta
    composite = compute_composite_index(current_scores)
    yesterday_scores = {
        cat: float(series.iloc[-2])
        for cat, series in category_history.items()
    }
    composite_yesterday = compute_composite_index(yesterday_scores)
    delta = round(composite - composite_yesterday, 1)

    # Build sub-components
    gauge_fig = build_gauge_figure(composite, delta)
    category_cards = build_category_cards(current_scores, category_history)
    trend_fig = build_history_chart(category_history)
    health_panel = build_category_panel(current_scores)
    map_fig = build_world_map(map_markers)
    alerts_panel = build_alerts_feed(alerts)
    disruptions_panel = build_disruptions_table(disruptions)

    return html.Div(
        className="dashboard",
        children=[
            # ── Auto-refresh interval (hidden) ──────────────────────
            dcc.Interval(
                id="refresh-interval",
                interval=_REFRESH_MS,
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
                                f"Last updated: {datetime.now().strftime('%b %d, %Y %H:%M')}",
                                className="last-updated",
                            ),
                            html.Span(
                                "Auto-refreshes every 5 min",
                                className="refresh-note",
                            ),
                            html.Span("● Live", className="live-dot"),
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
                                config={"displayModeBar": False, "responsive": True},
                            ),
                        ],
                    ),
                ],
            ),

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

            # ── Bottom Panels (alerts + disruptions) ────────────────
            html.Section(
                className="bottom-row",
                children=[
                    html.Div(className="bottom-panel", children=[alerts_panel]),
                    html.Div(className="bottom-panel", children=[disruptions_panel]),
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
        ],
    )
