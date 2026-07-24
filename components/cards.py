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
    # Drop NaN: history may legitimately be short (real measurements only
    # accumulate day by day), and NaN breaks the manual fill polygon.
    recent = series.tail(30).dropna()

    fig = go.Figure()

    if recent.empty:
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin={"t": 0, "b": 0, "l": 0, "r": 0},
            height=40,
            xaxis={"visible": False, "fixedrange": True},
            yaxis={"visible": False, "fixedrange": True},
            showlegend=False,
            autosize=False,
        )
        return fig

    # Center the data vertically with a minimum amplitude. Monthly-updated
    # categories (GSCPI, tariffs, freight) are flat or stepped day-to-day; a
    # tight data-hugging range pins them to the top or bottom edge and looks
    # broken. Anchoring the range to the data midpoint keeps every sparkline —
    # flat, stepped, or volatile — sitting cleanly in the middle of the box.
    # This is a viewport only (no axis labels), so it may extend past 0–100.
    y_min = float(recent.min())
    y_max = float(recent.max())
    mid = (y_min + y_max) / 2.0
    # Data occupies ~65% of the vertical height; the remainder is breathing room.
    half_height = max((y_max - y_min) / 2.0, 3.0) / 0.65
    y_lo = mid - half_height
    y_hi = mid + half_height

    # Build the filled shape manually: line data + a baseline return to y_lo
    # This avoids tozeroy (which fills to y=0, far below the visible range).
    x_vals = list(range(len(recent)))
    y_vals = list(recent.values)

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

    # Actual sparkline on top (markers when too short to draw a line)
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines" if len(recent) > 1 else "markers",
            line={"color": color, "width": 2},
            marker={"color": color, "size": 5},
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
    metadata: dict[str, dict] | None = None,
    active_weights: dict[str, float] | None = None,
) -> list:
    """Build a list of 'Tech HUD' card components for all categories.

    Parameters
    ----------
    current_scores : dict[str, float]
        Latest score per category.
    category_history : dict[str, pd.Series]
        Full history per category.
    metadata : dict[str, dict], optional
        Metadata/Context per category (source, raw values).
    active_weights : dict[str, float], optional
        Category weights dict (e.g. from an industry profile).
        If provided, only cards for these categories are rendered.
        Defaults to ``CATEGORY_WEIGHTS``.

    Returns
    -------
    list
        List of technical card components.
    """
    from dash import dcc  # deferred to avoid circular imports during load

    if metadata is None:
        metadata = {}
    active_weights = active_weights or CATEGORY_WEIGHTS
    cards = []
    for cat in active_weights:
        score = current_scores.get(cat, 0.0)
        tier = get_health_tier(score)
        history = category_history.get(cat, pd.Series(dtype=float))
        meta = metadata.get(cat, {})
        
        # Extract raw label (e.g. "Matson (Port Ops)")
        # Truncate if super long to avoid blowing up layout
        raw_label = meta.get("raw_label", "")
        if len(raw_label) > 25:
            raw_label = raw_label[:23] + ".."

        # 30-day stats (NaN-safe: history may be short while real
        # measurements are still accumulating)
        recent = history.tail(30).dropna()
        
        # FAIL-SAFE: Explicitly include the CURRENT score in the min/max calculation.
        # This prevents the UI from ever showing a Current Score that is outside the Lo/Hi range,
        # regardless of history series alignment or caching lag.
        min_val = min(float(recent.min()), score) if not recent.empty else score
        max_val = max(float(recent.max()), score) if not recent.empty else score

        # Daily change from the last two real observations
        valid_history = history.dropna()
        if len(valid_history) >= 2:
            delta = round(float(valid_history.iloc[-1] - valid_history.iloc[-2]), 1)
        else:
            delta = 0.0

        delta_color = COLORS["green"] if delta >= 0 else COLORS["red"]
        delta_arrow = "▲" if delta >= 0 else "▼"
        sparkline_color = delta_color  # Match sparkline to trend

        weight_pct = int(active_weights[cat] * 100)

        # Visible flag when the score is an injected fallback, not a measurement
        is_fallback = bool(meta.get("is_fallback"))
        fallback_badge = (
            html.Span(
                "FALLBACK",
                title="Provider failed — showing a neutral default, not a measured value",
                style={
                    "color": COLORS["orange"],
                    "border": f"1px solid {COLORS['orange']}",
                    "borderRadius": "3px",
                    "padding": "0 4px",
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "marginRight": "6px",
                    "letterSpacing": "0.5px",
                },
            )
            if is_fallback
            else None
        )

        # Technical HUD Card
        card = html.Div(
            className="tech-card",
            id=f"card-{cat}",
            n_clicks=0,
            style={"cursor": "pointer"}, # Indicate clickability
            children=[
                # Top decorative bar (like a bezel)
                html.Div(className="tech-card-bezel"),

                # Header: Label + [Weight]
                html.Div(
                    className="tech-card-header",
                    children=[
                        html.Div([
                            html.Span(CATEGORY_LABELS[cat], className="tech-label"),
                            # Sub-label for context (e.g. "Matson")
                            html.Div(raw_label, className="tech-sublabel", style={
                                "fontSize": "11px", "color": "#6b7280", "marginTop": "2px"
                            }) if raw_label else None
                        ]),
                        html.Div([
                            fallback_badge,
                            html.Span(f"W:{weight_pct:02d}%", className="tech-weight"),
                        ], style={"display": "flex", "alignItems": "center"}),
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
