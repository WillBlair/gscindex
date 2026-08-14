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
                    html.Div(
                        className="brand-title-row",
                        children=[
                            html.Div(
                                className="skeleton-pulse",
                                style={"height": "34px", "width": "34px", "borderRadius": "50%", "flexShrink": "0"},
                            ),
                            html.Div(
                                className="brand-text",
                                children=[
                                    html.Div(
                                        className="skeleton-pulse",
                                        style={"height": "26px", "width": "280px", "borderRadius": "8px"},
                                    ),
                                    html.Div(
                                        className="skeleton-pulse",
                                        style={"height": "14px", "width": "120px", "borderRadius": "8px", "marginTop": "6px"},
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="header-center",
                children=[
                    html.Div(
                        className="skeleton-pulse",
                        style={"height": "34px", "width": "200px", "borderRadius": "8px", "margin": "0 auto"},
                    ),
                ],
            ),
            html.Div(
                className="header-meta",
                children=[
                    html.Div(
                        className="header-nav",
                        children=[
                            html.Div(
                                className="skeleton-pulse",
                                style={"height": "28px", "width": "160px", "borderRadius": "8px"},
                            ),
                        ],
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
                id="loading-message-wrapper",
                style={
                    "position": "fixed",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "backgroundColor": COLORS["card"],
                    "border": f"1px solid {COLORS['card_border']}",
                    "borderRadius": "10px",
                    "padding": "20px 40px",
                    "zIndex": "9999",
                    "minWidth": "300px",
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                    "gap": "10px",
                },
                children=[
                    html.Div(
                        id="loading-message",
                        children="Initializing system...",
                        style={
                            "color": COLORS["text"],
                            "fontFamily": "Geist Mono, ui-monospace, monospace",
                            "fontSize": "16px",
                            "fontWeight": "600",
                            "textAlign": "center",
                        },
                    ),
                ],
            ),
            html.Div(id="boot-reload-trigger", style={"display": "none"}),
            dcc.Interval(id="boot-interval", interval=1000, n_intervals=0),
        ],
    )
