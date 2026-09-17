"""Supply chain monitoring workspace with persistent, accessible controls."""
from datetime import datetime
import dash_bootstrap_components as dbc
from dash import dcc, html

from components.cards import build_category_cards
from components.charts import build_history_chart, build_world_map
from components.feed import build_briefing_panel, build_news_panel
from components.market_costs import build_market_costs_panel
from components.workspace import build_overview, build_drivers, build_freshness, build_port_rows
from config import APP_AUTHOR_URL, CATEGORY_LABELS, COLORS, DEFAULT_PROFILE, INDUSTRY_PROFILES


def section_heading(number, title, note):
    return html.Div([html.Div([html.Span(number, className="section-number"), html.H2(title)]),
                     html.Span(note, className="section-note")], className="section-heading")


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
        dcc.Store(id="port-watchlist", data=[], storage_type="local"),
        dcc.Download(id="snapshot-download"),
        html.A("Skip to dashboard", href="#overview", className="skip-link"),
        html.Header([
            html.A([html.Span("G", className="brand-mark"), html.Div([html.Strong("GSC", className="brand-name"), html.Span("INDEX", className="brand-index")])], href="/", className="brand-lockup", **{"aria-label": "Global Supply Chain Index home"}),
            html.Nav([html.A("Overview", href="#overview", className="nav-active"), html.A("Port monitor", href="#ports"), html.A("Intelligence", href="#intelligence"), html.A("Methodology", href="#methodology")], className="workspace-nav", **{"aria-label": "Main navigation"}),
            html.Div([html.Button("API", id="api-btn", className="button-quiet"), html.Button("Daily briefing ↗", id="newsletter-btn", className="button-primary")], className="header-actions"),
        ], className="workspace-header"),
        html.Main([
            html.Section([
                html.Div([html.P([html.Span(className="status-dot"), "GLOBAL SUPPLY CHAIN INTELLIGENCE"], className="eyebrow hero-eyebrow"),
                          html.H1(["Global trade. ", html.Span("In perspective.")]),
                          html.P("Track the pressure. Understand the signals. See what matters next.", className="intro-copy")]),
                html.Div([control("INDUSTRY LENS", dbc.Select(id="profile-selector", value=DEFAULT_PROFILE, options=[{"label": p["label"], "value": k} for k, p in INDUSTRY_PROFILES.items()], **persist)),
                          html.Div([html.Button("↻ Refresh", id="refresh-btn", n_clicks=0, className="button-secondary", title="Read the latest cached snapshot; providers refresh in the background"), html.Button("↓ Export CSV", id="export-btn", n_clicks=0, className="button-secondary")], className="toolbar-actions")], className="intro-tools"),
            ], id="overview", className="workspace-intro"),
            html.Div(build_freshness(data, DEFAULT_PROFILE, is_provisional), id="snapshot-status"),
            html.Section([
                html.Div(build_overview(data, provisional=is_provisional), id="overview-summary", className="overview-card"),
                html.Div([
                    html.Div([html.Div([html.Span("GLOBAL NETWORK", className="eyebrow"), html.H2("A world of moving parts")]), html.A("Explore ports ↗", href="#ports", className="text-link")], className="panel-heading map-heading"),
                    dcc.Graph(id="world-map", style={"height": "290px"}, figure=build_world_map(markers), config={"displayModeBar": False, "responsive": True, "scrollZoom": False}),
                    html.Div([html.Span(f"{len(markers)} ports monitored", id="map-count"), html.Div([html.Span([html.I(className="legend-dot tier-" + name.lower()), name]) for name in ("Critical", "Stressed", "Stable", "Healthy")], className="map-legend")], className="map-footer"),
                ], className="network-card"),
            ], className="overview-grid"),
            section_heading("01", "The signals behind the score", "Higher is healthier · Select a signal to explore"),
            html.Section(build_category_cards(scores, history, metadata, active_weights=profile["weights"], card_categories=profile["card_categories"]), id="cards-container", className="cards-row", **{"aria-label": "Category scores"}),
            html.Section([
                html.Div(build_drivers(data), id="pressure-drivers", className="drivers-card"),
                html.Div([
                    html.Div([html.Div([html.Span("THE BIGGER PICTURE", className="eyebrow"), html.H2("How conditions are changing")]), dbc.RadioItems(id="trend-range", options=[{"label": f"{n}D", "value": n} for n in (7, 30, 90)], value=90, inline=True, className="range-switch", **persist)], className="panel-heading"),
                    dcc.Graph(id="trend-chart", style={"height": "300px"}, figure=build_history_chart({c: history[c] for c in profile["weights"] if c in history}), config={"displayModeBar": False, "responsive": True}),
                    html.P("Daily observations · Click a legend label to toggle a signal · Gaps mean no recorded measurement", className="chart-note"),
                ], className="trend-card"),
            ], className="analysis-grid"),
            html.Section([
                section_heading("02", "Your port monitor", "Local weather + regional macro conditions"),
                html.Div([
                    html.Div([
                        control("Find a port", dcc.Input(id="port-search", type="search", placeholder="Search ports…", debounce=True, **persist)),
                        control("Condition", dbc.Select(id="port-tier", options=[{"label": "All conditions", "value": "all"}] + [{"label": t, "value": t.lower()} for t in ("Critical", "Stressed", "Stable", "Healthy")], value="all", **persist)),
                        control("Sort by", dbc.Select(id="port-order", options=[{"label": "Most at risk", "value": "risk"}, {"label": "Port name", "value": "name"}], value="risk", **persist)),
                        dbc.Checklist(id="watch-only", options=[{"label": "Watchlist only", "value": "saved"}], value=[], switch=True, className="watch-filter", **persist),
                    ], className="filter-bar"),
                    html.Div(f"{len(markers)} ports · Star a port to save it on this device", id="port-results-count", className="results-count", role="status"),
                    html.Div(build_port_rows(sorted(markers, key=lambda m: m.get("score", 100))), id="port-results", className="port-results"),
                ], className="ports-card"),
            ], id="ports"),
            html.Section([
                section_heading("03", "The intelligence desk", "Context behind the numbers"),
                html.Div([
                    html.Div([html.Div(build_briefing_panel(data.get("briefing", "")), id="briefing-panel"),
                              html.Div([html.Span("MARKET CONTEXT", className="eyebrow"), html.H3("The cost of moving goods"), html.Div(build_market_costs_panel(data.get("market_data", {})), id="market-panel"), html.P("Price changes vs previous close. Market moves are context, not health scores.", className="fine-print")], className="market-context")], className="briefing-column"),
                    html.Div([
                        html.Div([control("Search news", dcc.Input(id="news-search", type="search", placeholder="Search headlines or sources…", debounce=True, **persist)),
                                  control("Severity", dbc.Select(id="news-severity", value="all", options=[{"label": "All severities", "value": "all"}] + [{"label": x.title(), "value": x} for x in ("high", "medium", "low")], **persist)),
                                  control("Topic", dbc.Select(id="news-category", value="all", options=[{"label": "All topics", "value": "all"}] + [{"label": CATEGORY_LABELS[c], "value": c} for c in profile["weights"]], **persist))], className="filter-bar news-filters"),
                        html.Div(id="news-results-count", className="results-count", role="status"),
                        html.Div(build_news_panel(data.get("alerts", [])), id="news-results"),
                    ], className="news-column"),
                ], className="intelligence-grid"),
            ], id="intelligence"),
            html.Section([
                html.Div([html.Span("OPEN DATA. CLEAR METHODOLOGY.", className="eyebrow"), html.H2("Know what you’re looking at."), html.P("The index combines measured signals into a weighted health score from 0 to 100. Higher means healthier conditions. Industry lenses change the weights and relevant signals.")]),
                html.Div([
                    html.Details([html.Summary("What does the score mean?"), html.P("80–100 Healthy · 60–<80 Stable · 40–<60 Stressed · 0–<40 Critical. These describe indicator conditions, not the probability of an individual shipment being delayed. Energy is a cost-pressure measure; a low energy price does not prove strong demand.")], open=True),
                    html.Details([html.Summary("How current is the data?"), html.P("Snapshots refresh in the background about every five minutes. The underlying sources have different schedules: weather and markets update frequently, while economic releases can be weekly or monthly. Open a signal for its source timestamp. Cached snapshots and provider fallbacks are flagged.")]),
                    html.Details([html.Summary("How are port conditions calculated?"), html.P("Port scores blend local weather with regional macro signals and disruption context. Map colors use the same absolute health bands as the table. Ports use the global model and do not change with the industry lens. They are indicators, not live vessel tracking or measured queue times.")]),
                    html.A("Explore documentation & data sources ↗", href="/docs", className="text-link"),
                ], className="methodology-details"),
            ], id="methodology", className="methodology-section"),
            html.Div([html.Div([html.H3("Start the day with the bigger picture."), html.P("A daily supply chain briefing, delivered to your inbox.")]), html.Button("Get the daily briefing ↗", id="newsletter-toast-inner", n_clicks=0, className="button-primary")], className="newsletter-banner"),
        ]),
        html.Footer([html.Div([html.Strong("GSC INDEX"), html.Span("Independent supply chain intelligence")]), html.Div(["Built by ", html.A("William Blair", href=APP_AUTHOR_URL, target="_blank", rel="noopener noreferrer"), html.Span(" · "), html.A("Documentation", href="/docs")])], className="workspace-footer"),
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
