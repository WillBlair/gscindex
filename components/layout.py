"""Supply chain monitoring workspace with persistent, accessible controls."""
from datetime import datetime
import dash_bootstrap_components as dbc
from dash import dcc, html

from components.cards import build_category_cards
from components.charts import build_history_chart, build_world_map
from components.feed import build_briefing_panel, build_news_panel
from components.market_costs import build_market_costs_panel
from components.workspace import build_overview, build_drivers, build_freshness
from config import APP_AUTHOR_URL, CATEGORY_LABELS, COLORS, DEFAULT_PROFILE, INDUSTRY_PROFILES


def section_heading(title):
    return html.Div(html.H2(title), className="section-heading")


def control(label, component):
    return html.Div([html.Label(label, htmlFor=component.id), component], className="filter-control")


def build_layout(data: dict, *, is_provisional=False, last_updated: datetime | None = None):
    profile = INDUSTRY_PROFILES[DEFAULT_PROFILE]
    scores, history = data["current_scores"], data.get("category_history", {})
    metadata, markers = data.get("category_metadata", {}), data.get("map_markers", [])
    persist = {"persistence": True, "persistence_type": "session"}
    return html.Div(className="dashboard workspace", children=[
        dcc.Interval(id="refresh-interval", interval=20_000 if is_provisional else 300_000, n_intervals=0),
        dcc.Store(id="refresh-request", data=0),
        dcc.Store(id="category-metadata-store", data=metadata),
        dcc.Store(id="profile-store", data=DEFAULT_PROFILE),
        dcc.Download(id="snapshot-download"),
        html.A("Skip to dashboard", href="#overview", className="skip-link"),
        html.Header([
            html.A(html.H1("Global Supply Chain Index"), href="/", className="brand-lockup", **{"aria-label": "Global Supply Chain Index home"}),
            html.Nav([html.A("Overview", href="#overview", className="nav-active"), html.A("News", href="#intelligence"), html.A("Docs", href="/docs")], className="workspace-nav", **{"aria-label": "Main navigation"}),
            html.Div([html.Button("API", id="api-btn", className="button-quiet"), html.Button("Subscribe", id="newsletter-btn", className="button-primary")], className="header-actions"),
        ], className="workspace-header"),
        html.Main([
            html.Section([
                control("Profile", dbc.Select(id="profile-selector", value=DEFAULT_PROFILE, options=[{"label": p["label"], "value": k} for k, p in INDUSTRY_PROFILES.items()], **persist)),
                html.Div(build_freshness(data, DEFAULT_PROFILE, is_provisional), id="snapshot-status"),
                html.Div([html.Button("↻ Refresh", id="refresh-btn", n_clicks=0, className="button-secondary", title="Read the latest cached snapshot"), html.Button("↓ CSV", id="export-btn", n_clicks=0, className="button-secondary")], className="toolbar-actions"),
            ], id="overview", className="dashboard-toolbar"),
            html.Div(build_market_costs_panel(data.get("market_data", {})), id="market-panel", className="market-strip"),
            html.Section([
                html.Div([html.Div(build_overview(data, provisional=is_provisional), id="overview-summary"), html.Div(build_drivers(data), id="pressure-drivers")], className="overview-card"),
                html.Div([
                    html.Div([html.H2("Ports"), html.Span("Drag to move · scroll to zoom", className="map-hint")], className="panel-heading map-heading"),
                    dcc.Graph(id="world-map", responsive=True, style={"height": "100%", "width": "100%"}, figure=build_world_map(markers), config={"displayModeBar": True, "displaylogo": False, "responsive": True, "scrollZoom": True, "modeBarButtons": [["zoomInMap", "zoomOutMap", "resetViewMap"]]}),
                    html.Div([html.Span(f"{len(markers)} ports", id="map-count"), html.Div([html.Span("Higher relative risk"), html.I(className="risk-gradient"), html.Span("Lower")], className="map-legend")], className="map-footer"),
                ], className="network-card"),
            ], className="overview-grid"),

            html.Section(build_category_cards(scores, history, metadata, active_weights=profile["weights"], card_categories=profile["card_categories"]), id="cards-container", className="cards-row", **{"aria-label": "Category scores"}),
            html.Section([
                html.Div([
                    html.Div([html.H2("Health score history"), dbc.RadioItems(id="trend-range", options=[{"label": f"{n}D", "value": n} for n in (7, 30, 90)], value=90, inline=True, className="range-switch", **persist)], className="panel-heading"),
                    dcc.Graph(id="trend-chart", responsive=True, style={"height": "320px"}, figure=build_history_chart({c: history[c] for c in profile["weights"] if c in history}), config={"displayModeBar": False, "responsive": True}),
                ], className="trend-card"),
            ], className="analysis-grid"),
            html.Section([
                section_heading("News"),
                html.Div([
                    html.Div(build_briefing_panel(data.get("briefing", "")), id="briefing-panel", className="briefing-column"),
                    html.Div([
                        html.Div([control("Search news", dcc.Input(id="news-search", type="search", placeholder="Search headlines or sources…", debounce=True, **persist)),
                                  control("Severity", dbc.Select(id="news-severity", value="all", options=[{"label": "All severities", "value": "all"}] + [{"label": x.title(), "value": x} for x in ("high", "medium", "low")], **persist)),
                                  control("Topic", dbc.Select(id="news-category", value="all", options=[{"label": "All topics", "value": "all"}] + [{"label": CATEGORY_LABELS[c], "value": c} for c in profile["weights"]], **persist))], className="filter-bar news-filters"),
                        html.Div(id="news-results-count", className="results-count", role="status"),
                        html.Div(build_news_panel(data.get("alerts", [])), id="news-results"),
                    ], className="news-column"),
                ], className="intelligence-grid"),
            ], id="intelligence"),
        ]),
        html.Footer([html.Div([html.A("William Blair", href=APP_AUTHOR_URL, target="_blank", rel="noopener noreferrer"), html.Span(" · "), html.A("Methodology", href="/docs")]), html.Button("Email updates", id="newsletter-toast-inner", n_clicks=0, className="button-quiet")], className="workspace-footer"),
            # ── Detail Modal ────────────────────────────────────────
            # Close uses a pattern-matching id so an empty ALL match while the
            # modal is unmounted does not block the separate card-open callback.
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Category Details"), id="modal-header"),
                    dbc.ModalBody(id="modal-body"),
                    dbc.ModalFooter(
                        dbc.Button(
                            "Close",
                            id={"type": "modal-dismiss", "index": "footer"},
                            className="ms-auto",
                            n_clicks=0,
                        )
                    ),
                ],
                id="details-modal",
                is_open=False,
                size="lg",  # Large modal
                centered=True,
                className="dark-modal",
                content_class_name="gsc-modal-content",
            ),

            # ── API Documentation Modal ─────────────────────────────
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Public API Access"), className="modal-header"),
                    dbc.ModalBody(
                        children=[
                            html.P("Access the Global Supply Chain Index programmatically for your own dashboards or research."),
                            html.H5("Endpoint", style={"marginTop": "20px"}),
                            html.Code("GET https://gscindex.com/api/v1/latest", style={"display": "block", "padding": "10px", "backgroundColor": "#111", "borderRadius": "var(--radius)", "color": "#a5b4fc"}),

                            html.H5("Usage Example (curl)", style={"marginTop": "20px"}),
                            html.Code("curl -X GET https://gscindex.com/api/v1/latest", style={"display": "block", "padding": "10px", "backgroundColor": "#111", "borderRadius": "var(--radius)", "color": "#22c55e"}),

                            html.H5("Rate Limits", style={"marginTop": "20px"}),
                            html.Ul([
                                html.Li("500 requests per hour per IP"),
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
                content_class_name="gsc-modal-content",
            ),

            # ── Newsletter Modal ──────────────────────────────────────────
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle("Subscribe to the Daily Briefing"),
                        className="modal-header",
                        close_button=True,
                        style={
                            "background": COLORS["card"],
                            "borderBottom": f"1px solid {COLORS['card_border']}",
                            "color": COLORS["text"],
                        },
                    ),
                    dbc.ModalBody(
                        children=[
                            html.P(
                                "Get the Global Supply Chain Index daily briefing delivered to your inbox every morning at 8:00 AM UTC.",
                                style={
                                    "color": COLORS["text_muted"],
                                    "fontSize": "14px",
                                    "lineHeight": "1.6",
                                    "marginBottom": "20px",
                                },
                            ),
                            html.Label("Email address", htmlFor="newsletter-email", className="newsletter-email-label"),
                            dbc.Input(
                                id="newsletter-email", type="email",
                                placeholder="Enter your email address",
                                style={
                                    "backgroundColor": COLORS["bg"],
                                    "color": COLORS["text"],
                                    "border": f"1px solid {COLORS['card_border']}",
                                    "borderRadius": "var(--radius)",
                                    "padding": "12px 14px",
                                    "marginBottom": "14px",
                                    "fontSize": "14px",
                                },
                            ),
                            dbc.Button(
                                "Subscribe", id="newsletter-submit",
                                className="w-100",
                                style={
                                    "backgroundColor": COLORS["text"],
                                    "color": COLORS["bg"],
                                    "border": "none",
                                    "borderRadius": "var(--radius)",
                                    "padding": "10px",
                                    "fontWeight": "600",
                                    "fontSize": "14px",
                                },
                            ),
                            html.Div(id="newsletter-feedback", role="status", style={"marginTop": "14px", "fontSize": "13px"}),
                        ],
                        style={"background": COLORS["card"], "padding": "24px"},
                    ),
                    dbc.ModalFooter(
                        dbc.Button(
                            "Close", id="newsletter-modal-close",
                            className="ms-auto", n_clicks=0,
                            style={
                                "backgroundColor": "transparent",
                                "border": f"1px solid {COLORS['card_border']}",
                                "color": COLORS["text_muted"],
                                "borderRadius": "var(--radius)",
                                "fontSize": "13px",
                            },
                        ),
                        style={
                            "background": COLORS["card"],
                            "borderTop": f"1px solid {COLORS['card_border']}",
                            "padding": "12px 24px",
                        },
                    ),
                ],
                id="newsletter-modal",
                is_open=False,
                size="md",
                centered=True,
                content_class_name="gsc-modal-content",
                style={
                    "--bs-modal-bg": COLORS["card"],
                    "--bs-modal-border-color": COLORS["card_border"],
                },
            ),


    ])
