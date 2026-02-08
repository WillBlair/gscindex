"""
Category Score Cards
====================
Renders a row of cards, one per supply-chain category, each showing:
    - Label & weight badge
    - Current score (color-coded by health tier)
    - Sparkline colored GREEN (trending up) or RED (trending down)
    - Daily change delta
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from dash import html

from config import CATEGORY_LABELS, CATEGORY_WEIGHTS, COLORS, hex_to_rgba
from scoring import get_health_tier


def _sparkline(series: pd.Series, color: str) -> go.Figure:
    """Build a tiny sparkline chart for a category card.

    Parameters
    ----------
    series : pd.Series
        Last 30 data points to display.
    color : str
        Line color (hex) — green if trending up, red if trending down.

    Returns
    -------
    go.Figure
        A minimal Plotly figure with no axes, suitable for inline display.
    """
    recent = series.tail(30)

    # Tight y-range around actual data so the fill doesn't create a huge
    # rectangle below the line (scores typically cluster 60–100).
    y_min = float(recent.min())
    y_max = float(recent.max())
    padding = max((y_max - y_min) * 0.15, 2.0)
    y_lo = max(0, y_min - padding)
    y_hi = min(100, y_max + padding)

    # Build the filled shape manually: line data + a baseline return to y_lo
    # This avoids tozeroy (which fills to y=0, far below the visible range).
    x_vals = list(range(len(recent)))
    y_vals = list(recent.values)

    fig = go.Figure()

    # Filled area: draw the line, then return along the baseline at y_lo
    fig.add_trace(
        go.Scatter(
            x=x_vals + x_vals[::-1],
            y=y_vals + [y_lo] * len(x_vals),
            fill="toself",
            fillcolor=hex_to_rgba(color, 0.15),
            line={"width": 0},
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # Actual sparkline on top
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines",
            line={"color": color, "width": 2},
            hoverinfo="skip",
            showlegend=False,
        )
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 0, "b": 0, "l": 0, "r": 0},
        height=40,
        xaxis={"visible": False, "fixedrange": True},
        yaxis={"visible": False, "range": [y_lo, y_hi], "fixedrange": True},
        showlegend=False,
        autosize=False,
    )

    return fig


def build_category_cards(
    current_scores: dict[str, float],
    category_history: dict[str, pd.Series],
) -> list:
    """Build a list of 'Tech HUD' card components for all categories.

    Parameters
    ----------
    current_scores : dict[str, float]
        Latest score per category.
    category_history : dict[str, pd.Series]
        Full history per category.

    Returns
    -------
    list
        List of technical card components.
    """
    from dash import dcc  # deferred to avoid circular imports during load

    cards = []
    for cat in CATEGORY_WEIGHTS:
        score = current_scores[cat]
        tier = get_health_tier(score)
        history = category_history[cat]
        
        # 30-day stats
        recent = history.tail(30)
        min_val = recent.min()
        max_val = recent.max()

        # Daily change
        if len(history) >= 2:
            delta = round(float(history.iloc[-1] - history.iloc[-2]), 1)
        else:
            delta = 0.0

        delta_color = COLORS["green"] if delta >= 0 else COLORS["red"]
        delta_arrow = "▲" if delta >= 0 else "▼"
        sparkline_color = delta_color  # Match sparkline to trend

        weight_pct = int(CATEGORY_WEIGHTS[cat] * 100)

        # Technical HUD Card
        card = html.Div(
            className="tech-card",
            children=[
                # Top decorative bar (like a bezel)
                html.Div(className="tech-card-bezel"),

                # Header: Label + [Weight]
                html.Div(
                    className="tech-card-header",
                    children=[
                        html.Span(CATEGORY_LABELS[cat], className="tech-label"),
                        html.Span(f"W:{weight_pct:02d}%", className="tech-weight"),
                    ],
                ),

                # Main Data Row: Big Score + Delta
                html.Div(
                    className="tech-main-row",
                    children=[
                        html.Span(
                            f"{score:.1f}",  # One decimal for precision
                            className="tech-score",
                            style={"color": tier["color"]},
                        ),
                        html.Div(
                            className="tech-delta-box",
                            children=[
                                html.Span("24H Δ", className="tech-meta-label"),
                                html.Span(
                                    f"{delta_arrow} {abs(delta):.1f}", 
                                    className="tech-delta-value",
                                    style={"color": delta_color}
                                )
                            ]
                        )
                    ]
                ),

                # Secondary Stats Grid (Min/Max)
                html.Div(
                    className="tech-stats-grid",
                    children=[
                        html.Div([
                            html.Span("LO", className="tech-meta-label"),
                            html.Span(f"{min_val:.1f}", className="tech-meta-value")
                        ]),
                        html.Div(className="tech-grid-sep"),
                        html.Div([
                            html.Span("HI", className="tech-meta-label"),
                            html.Span(f"{max_val:.1f}", className="tech-meta-value")
                        ]),
                    ]
                ),

                # Sparkline Container (The "Screen")
                html.Div(
                    className="tech-sparkline-container",
                    children=[
                        dcc.Graph(
                            figure=_sparkline(history, sparkline_color),
                            config={"displayModeBar": False, "responsive": True},
                            className="tech-sparkline",
                            style={"height": "40px", "width": "100%"}
                        )
                    ]
                ),
                
                # Corner decoration
                html.Div(className="tech-corner-tr"),
                html.Div(className="tech-corner-bl"),
            ],
        )
        cards.append(card)

    return cards
