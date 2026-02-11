import dash_bootstrap_components as dbc
from dash import html, dcc

def build_skeleton_layout():
    """Returns a skeleton version of the dashboard layout."""
    
    # ── Header Skeleton ──────────────────────────────────────────────
    header = html.Header(
        className="dash-header",
        children=[
            html.Div([
                html.Div(className="skeleton-pulse", style={"height": "32px", "width": "300px", "borderRadius": "4px", "marginBottom": "8px"}),
                html.Div(className="skeleton-pulse", style={"height": "16px", "width": "200px", "borderRadius": "4px"}),
            ]),
            html.Div(
                className="header-meta",
                children=[
                    html.Div(className="skeleton-pulse", style={"height": "20px", "width": "150px", "borderRadius": "12px"}),
                    html.Div(className="skeleton-pulse", style={"height": "20px", "width": "100px", "borderRadius": "12px"}),
                ],
            ),
        ],
    )

    # ── Gauge + Trend Skeleton ───────────────────────────────────────
    hero_row = html.Section(
        className="hero-row",
        children=[
            html.Div(
                className="chart-panel",
                style={"height": "300px"},
                children=[
                    html.Div(className="skeleton-pulse", style={"height": "100%", "width": "100%", "borderRadius": "8px"})
                ]
            ),
            html.Div(
                className="chart-panel",
                style={"height": "300px"},
                children=[
                    html.Div(className="skeleton-pulse", style={"height": "100%", "width": "100%", "borderRadius": "8px"})
                ]
            ),
        ],
    )

    # ── Category Cards Skeleton ─────────────────────────────────────
    cards = []
    for _ in range(6):
        cards.append(
            html.Div(
                className="metric-card",
                children=[
                    html.Div(style={"display": "flex", "justifyContent": "space-between", "marginBottom": "10px"}, children=[
                        html.Div(className="skeleton-pulse", style={"height": "12px", "width": "60px", "borderRadius": "2px"}),
                        html.Div(className="skeleton-pulse", style={"height": "12px", "width": "30px", "borderRadius": "8px"}),
                    ]),
                    html.Div(className="skeleton-pulse", style={"height": "32px", "width": "80px", "borderRadius": "4px", "marginBottom": "4px"}),
                    html.Div(className="skeleton-pulse", style={"marginTop": "auto", "height": "40px", "width": "100%", "borderRadius": "4px"}),
                ]
            )
        )
    
    cards_row = html.Section(
        className="cards-row",
        children=cards
    )

    # ── Middle Row Skeleton ─────────────────────────────────────────
    charts_row = html.Section(
        className="charts-row",
        children=[
            html.Div(
                className="chart-panel chart-narrow",
                style={"height": "400px"},
                children=[html.Div(className="skeleton-pulse", style={"height": "100%", "width": "100%", "borderRadius": "8px"})]
            ),
            html.Div(
                className="chart-panel chart-wide",
                style={"height": "400px"},
                children=[html.Div(className="skeleton-pulse", style={"height": "100%", "width": "100%", "borderRadius": "8px"})]
            ),
        ],
    )

    # ── Bottom Row Skeleton ─────────────────────────────────────────
    bottom_row = html.Section(
        className="bottom-row",
        children=[
            html.Div(className="panel", style={"height": "300px"}, children=[html.Div(className="skeleton-pulse", style={"height": "100%", "width": "100%", "borderRadius": "8px"})]),
            html.Div(className="panel", style={"height": "300px"}, children=[html.Div(className="skeleton-pulse", style={"height": "100%", "width": "100%", "borderRadius": "8px"})]),
        ],
    )

    return html.Div(
        className="dashboard",
        children=[
            # Dummy interval to trigger reload once data is ready is handled in app.py's waiting logic
            # This layout is just visual.
            header,
            hero_row,
            cards_row,
            charts_row,
            bottom_row,
            
            # ── Hidden Infrastructure ───────────────────────────────────────
            # Vital for auto-reloading from skeleton to main dash.
            # We reuse the same IDs so app.py callbacks can target them.
            html.Div(id="refresh-trigger", style={"display": "none"}),
            html.Div(id="boot-trigger", style={"display": "none"}), # Preserved for safety
            
            # Check every 2 seconds if data is ready
            # This shares the ID with the main layout's refresher or we use a dedicated one.
            # app.py uses "refresh-interval". Let's use that one.
            dcc.Interval(
                id="refresh-interval",
                interval=2000,  # 2 seconds (faster check during boot)
                n_intervals=0
            ),
        ]
    )
