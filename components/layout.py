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
    │  Gauge        │  Global Supply Chain Map      │
    ├──────┬──────┬─┴────┬──────┬──────┬──────┬───┤
    │ Card │ Card │ Card │ Card │ Card │ Card │Card│
    ├──────────────────┬──────────────────────────┤
    │ Category Health  │  90-Day Trend (multi-line) │
    │ Bars             │                            │
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
from components.gauge import build_gauge_figure, build_score_tooltip
from config import APP_AUTHOR_URL, APP_SUBTITLE, APP_TITLE
from config import COLORS, DEFAULT_PROFILE, INDUSTRY_PROFILES
from scoring import build_score_explanation, compute_composite_index

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

    # Compute data age for display
    if last_updated:
        age_seconds = (datetime.now(last_updated.tzinfo) - last_updated).total_seconds()
        age_minutes = int(age_seconds // 60)
        if age_minutes < 1:
            data_age_str = "Data: <1m ago"
        elif age_minutes < 60:
            data_age_str = f"Data: {age_minutes}m ago"
        else:
            data_age_str = f"Data: {age_minutes // 60}h {age_minutes % 60}m ago"
    else:
        data_age_str = "Data: loading..."

    # Compute composite index and day-over-day delta
    composite = compute_composite_index(current_scores)
    
    from data.database import get_previous_daily_score
    
    if is_provisional:
        # Provisional fallback can carry stale history; suppress misleading delta.
        delta = 0.0
    else:
        try:
            previous_score = get_previous_daily_score()
            if previous_score is not None:
                delta = round(composite - previous_score, 1)
            else:
                delta = 0.0
        except Exception:
            # DB timeout (e.g. Neon cold start) must not block page render
            delta = 0.0

    # Build sub-components
    gauge_fig = build_gauge_figure(composite, delta, show_delta=not is_provisional)
    category_metadata = data.get("category_metadata", {})
    score_context = build_score_explanation(
        composite,
        current_scores,
        category_metadata,
        delta=delta if not is_provisional else None,
    )
    ai_score_summary = str(data.get("score_explanation", "") or "").strip()
    if ai_score_summary:
        score_context = {**score_context, "summary": ai_score_summary}
    gauge_tooltip = build_score_tooltip(score_context)
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
                        html.P(
                            (
                                [
                                    "by ",
                                    html.A(
                                        APP_SUBTITLE[3:],
                                        href=APP_AUTHOR_URL,
                                        target="_blank",
                                        rel="noopener noreferrer",
                                        className="app-subtitle",
                                        style={"color": "inherit", "textDecoration": "none"},
                                    ),
                                ]
                                if APP_SUBTITLE.lower().startswith("by ")
                                else [APP_SUBTITLE]
                            ),
                            className="app-subtitle",
                        ),
                    ]),
                    html.Div(
                        className="header-meta",
                        children=[
                            dcc.Dropdown(
                                id="profile-selector",
                                options=[
                                    {"label": p["label"], "value": k}
                                    for k, p in INDUSTRY_PROFILES.items()
                                ],
                                value=DEFAULT_PROFILE,
                                clearable=False,
                                searchable=False,
                                style={
                                    "width": "200px",
                                    "backgroundColor": COLORS["card"],
                                    "borderRadius": "6px",
                                    "fontSize": "13px",
                                },
                            ),
                            html.Span(
                                (
                                    f"Last updated: {display_last_updated.strftime('%b %d, %Y %H:%M')}"
                                    if display_last_updated
                                    else ("Last updated: provisional snapshot" if is_provisional else "Last updated: warming up...")
                                ),
                                className="last-updated",
                            ),
                            html.Span(
                                "Updating — refreshing in ~20s..." if is_provisional else "Auto-refreshes every 5 min",
                                className="refresh-note",
                            ),
                            
                            html.Span(
                                data_age_str,
                                className="system-stats",
                            ),
                            
                            # Docs Link
                            dbc.Button(
                                "Docs",
                                href="/docs",
                                external_link=True,
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

                            # Newsletter Button
                            dbc.Button(
                                "Newsletter",
                                id="newsletter-btn",
                                color="link",
                                className="newsletter-btn-header",
                                style={"color": "#10b981", "fontWeight": "600", "fontSize": "14px", "textDecoration": "none", "marginLeft": "10px"}
                            ),
                            
                            html.Span(
                                "● Updating..." if is_provisional else "● Live",
                                className="live-dot" if is_provisional else "live-dot pulsing",
                                style={"color": "#00d97e", "marginLeft": "20px"} if not is_provisional else {"color": "#fbbf24", "marginLeft": "20px"},
                            ),
                        ],
                    ),
                ],
            ),

            # ── Hero Row (gauge + map side-by-side) ────────────────
            html.Section(
                className="hero-row",
                children=[
                    html.Div(
                        className="chart-panel gauge-panel",
                        style={"minHeight": "340px", "position": "relative"},
                        children=[
                            dcc.Graph(
                                id="gauge",
                                figure=gauge_fig,
                                config={"displayModeBar": False, "responsive": False},
                                style={"height": "100%", "width": "100%"},
                            ),
                            html.Div(
                                className="gauge-score-hover-zone",
                                tabIndex=0,
                                children=[
                                    gauge_tooltip,
                                    html.Span("?", className="gauge-score-hint", **{"aria-hidden": "true"}),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="chart-panel",
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

            # ── Market Costs Ticker ─────────────────────────────────
            market_panel,

            # ── Category Cards ──────────────────────────────────────
            html.Section(
                className="cards-row",
                id="cards-container",
                children=category_cards,
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

            # ── Middle Row (health bars + 90-day trend) ─────────────
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
                                id="trend-chart",
                                figure=trend_fig,
                                config={
                                    "displayModeBar": False,
                                    "responsive": True,
                                    "scrollZoom": False,
                                    "doubleClick": False,
                                },
                            ),
                        ],
                    ),
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
            dcc.Store(id="profile-store", data=DEFAULT_PROFILE),
            
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

            # ── Newsletter Modal ──────────────────────────────────────────
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle("Subscribe to the Daily Briefing"),
                        className="modal-header",
                        close_button=True,
                        style={"background": "#13151d", "borderBottom": "1px solid rgba(255,255,255,0.06)", "color": "#f3f4f6"},
                    ),
                    dbc.ModalBody(
                        children=[
                            html.P(
                                "Get the Global Supply Chain Index daily briefing delivered to your inbox every morning at 8:00 AM UTC.",
                                style={"color": "#9ca3af", "fontSize": "14px", "lineHeight": "1.6", "marginBottom": "20px"},
                            ),
                            dbc.Input(
                                id="newsletter-email", type="email",
                                placeholder="Enter your email address",
                                style={
                                    "backgroundColor": "#0f1117", "color": "#e1e4ea",
                                    "border": "1px solid rgba(255,255,255,0.1)",
                                    "borderRadius": "8px", "padding": "12px 14px",
                                    "marginBottom": "14px", "fontSize": "14px",
                                },
                            ),
                            dbc.Button(
                                "Subscribe", id="newsletter-submit",
                                className="w-100",
                                style={
                                    "backgroundColor": "#6366f1", "border": "none",
                                    "borderRadius": "8px", "padding": "10px",
                                    "fontWeight": "600", "fontSize": "14px",
                                },
                            ),
                            html.Div(id="newsletter-feedback", style={"marginTop": "14px", "fontSize": "13px"}),
                        ],
                        style={"background": "#13151d", "padding": "24px"},
                    ),
                    dbc.ModalFooter(
                        dbc.Button(
                            "Close", id="newsletter-modal-close",
                            className="ms-auto", n_clicks=0,
                            style={
                                "backgroundColor": "transparent", "border": "1px solid rgba(255,255,255,0.1)",
                                "color": "#9ca3af", "borderRadius": "6px", "fontSize": "13px",
                            },
                        ),
                        style={"background": "#13151d", "borderTop": "1px solid rgba(255,255,255,0.06)", "padding": "12px 24px"},
                    ),
                ],
                id="newsletter-modal",
                is_open=False,
                size="md",
                centered=True,
                style={"--bs-modal-bg": "#13151d", "--bs-modal-border-color": "rgba(255,255,255,0.08)"},
            ),

            # ── Newsletter Toast (On Load) ─────────────────────────────────
            html.Div(
                html.Div(
                    [
                        html.Div(
                            html.Span("Subscribe to Newsletter", style={"fontWeight": "600", "color": "#f3f4f6", "fontSize": "14px"}),
                            style={"marginBottom": "8px"},
                        ),
                        html.P(
                            "Get the daily GSC Index briefing straight to your inbox.",
                            style={"margin": "0", "fontSize": "13px", "color": "#9ca3af", "lineHeight": "1.5"},
                        ),
                        html.Div(
                            "Click to subscribe",
                            style={
                                "marginTop": "10px", "fontSize": "12px", "fontWeight": "500",
                                "color": "#818cf8", "cursor": "pointer",
                            },
                        ),
                    ],
                    id="newsletter-toast-inner",
                    n_clicks=0,
                    style={
                        "position": "fixed", "bottom": "24px", "right": "24px", "width": "320px",
                        "background": "#1a1d26", "border": "1px solid rgba(255,255,255,0.08)",
                        "borderRadius": "12px", "padding": "16px 20px", "zIndex": 1050,
                        "boxShadow": "0 8px 32px rgba(0,0,0,0.4)", "cursor": "pointer",
                        "animation": "toastIn 0.4s ease-out, toastOut 0.4s ease-in 19.6s forwards",
                    },
                ),
                id="newsletter-toast-wrapper",
            ),
        ],
    )
