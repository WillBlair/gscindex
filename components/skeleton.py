"""Cold-start skeleton layout matching production chrome."""

from dash import dcc, html

from config import COLORS


def build_skeleton_layout():
    """Returns a skeleton version of the dashboard layout."""

    header = html.Header(
        className="dash-header",
        children=[
            html.Div(
                className="header-brand",
                children=[
                    html.Div([
                        html.Div(
                            className="skeleton-pulse",
                            style={"height": "32px", "width": "300px", "borderRadius": "8px", "marginBottom": "8px"},
                        ),
                        html.Div(
                            className="skeleton-pulse",
                            style={"height": "16px", "width": "200px", "borderRadius": "8px"},
                        ),
                    ]),
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "34px", "width": "200px", "borderRadius": "8px"},
                    ),
                ],
            ),
            html.Div(
                className="header-meta",
                children=[
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "20px", "width": "150px", "borderRadius": "999px"},
                    ),
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "20px", "width": "100px", "borderRadius": "999px"},
                    ),
                ],
            ),
        ],
    )

    hero_row = html.Section(
        className="hero-row",
        children=[
            html.Div(
                className="chart-panel gauge-panel",
                style={"height": "340px"},
                children=[
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "100%", "width": "100%", "borderRadius": "10px"},
                    )
                ],
            ),
            html.Div(
                className="chart-panel",
                style={"height": "340px"},
                children=[
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "100%", "width": "100%", "borderRadius": "10px"},
                    )
                ],
            ),
        ],
    )

    ticker = html.Div(
        className="market-section-ticker",
        children=[
            html.Div(
                className="skeleton-pulse",
                style={"height": "40px", "width": "100%", "borderRadius": "8px"},
            )
        ],
    )

    cards = []
    for _ in range(6):
        cards.append(
            html.Div(
                className="tech-card",
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "marginBottom": "10px"},
                        children=[
                            html.Div(
                                className="skeleton-pulse",
                                style={"height": "12px", "width": "60px", "borderRadius": "4px"},
                            ),
                            html.Div(
                                className="skeleton-pulse",
                                style={"height": "12px", "width": "30px", "borderRadius": "999px"},
                            ),
                        ],
                    ),
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "32px", "width": "80px", "borderRadius": "6px", "marginBottom": "4px"},
                    ),
                    html.Div(
                        className="skeleton-pulse",
                        style={"marginTop": "auto", "height": "40px", "width": "100%", "borderRadius": "6px"},
                    ),
                ],
            )
        )

    cards_row = html.Section(className="cards-row", children=cards)

    bottom_row = html.Section(
        className="bottom-row",
        children=[
            html.Div(
                className="bottom-panel",
                children=[
                    html.Div(
                        className="panel",
                        style={"height": "300px"},
                        children=[
                            html.Div(
                                className="skeleton-pulse",
                                style={"height": "100%", "width": "100%", "borderRadius": "10px"},
                            )
                        ],
                    )
                ],
            ),
            html.Div(
                className="bottom-panel",
                children=[
                    html.Div(
                        className="panel",
                        style={"height": "300px"},
                        children=[
                            html.Div(
                                className="skeleton-pulse",
                                style={"height": "100%", "width": "100%", "borderRadius": "10px"},
                            )
                        ],
                    )
                ],
            ),
        ],
    )

    charts_row = html.Section(
        className="charts-row",
        children=[
            html.Div(
                className="chart-panel chart-narrow",
                style={"height": "400px"},
                children=[
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "100%", "width": "100%", "borderRadius": "10px"},
                    )
                ],
            ),
            html.Div(
                className="chart-panel chart-wide",
                style={"height": "400px"},
                children=[
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "100%", "width": "100%", "borderRadius": "10px"},
                    )
                ],
            ),
        ],
    )

    return html.Div(
        className="dashboard",
        children=[
            header,
            hero_row,
            ticker,
            cards_row,
            bottom_row,
            charts_row,
            html.Div(id="refresh-trigger", style={"display": "none"}),
            html.Div(id="boot-trigger", style={"display": "none"}),
            html.Div(
                id="loading-message",
                children="Initializing system...",
                style={
                    "position": "fixed",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "backgroundColor": COLORS["card"],
                    "border": f"1px solid {COLORS['card_border']}",
                    "borderRadius": "10px",
                    "padding": "24px 40px",
                    "color": COLORS["text"],
                    "fontFamily": "IBM Plex Mono, monospace",
                    "fontSize": "18px",
                    "fontWeight": "600",
                    "zIndex": "9999",
                    "minWidth": "300px",
                    "textAlign": "center",
                },
            ),
            html.Div(id="boot-reload-trigger", style={"display": "none"}),
            dcc.Interval(id="boot-interval", interval=1000, n_intervals=0),
        ],
    )
