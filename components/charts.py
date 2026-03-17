"""
Dashboard Charts
================
All Plotly figures and Dash panels that appear in the main dashboard body:

    - ``build_history_chart``  — 90-day multi-line trend of every category
    - ``build_category_panel`` — Horizontal health bars for each category
    - ``build_world_map``      — Scatter-geo map with regional risk dots
"""

from __future__ import annotations

import plotly.graph_objects as go
from dash import html

from config import (
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_WEIGHTS,
    COLORS,
)
from scoring import get_health_tier

import pandas as pd



def build_history_chart(category_history: dict[str, pd.Series]) -> go.Figure:
    """Build a multi-line 90-day trend chart for all categories.

    Parameters
    ----------
    category_history : dict[str, pd.Series]
        Mapping of category key to pandas Series indexed by date.

    Returns
    -------
    go.Figure
        Plotly line chart with one trace per category.
    """
    fig = go.Figure()

    for cat in CATEGORY_WEIGHTS:
        series = category_history[cat]
        color = CATEGORY_COLORS.get(cat, COLORS["accent"])

        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                name=CATEGORY_LABELS[cat],
                mode="lines",
                line={"color": color, "width": 2},
                fill="none",
                hovertemplate=f"<b>{CATEGORY_LABELS[cat]}</b><br>"
                              "%{x|%b %d}<br>"
                              "Score: %{y:.1f}<extra></extra>",
            )
        )

    fig.update_layout(
        title={
            "text": "90-Day Category Trends",
            "font": {"size": 14, "color": COLORS["text"], "family": "Inter"},
            "x": 0,
            "xanchor": "left",
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter", "color": COLORS["text_muted"]},
        margin={"t": 40, "b": 40, "l": 45, "r": 16},
        height=300,
        dragmode=False,  # Disable drag interactions (pan/zoom selection)
        yaxis={
            "range": [0, 100],
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "tickfont": {"size": 10},
            "title": None,
            "fixedrange": True,  # Disable y-axis zoom/pan
        },
        xaxis={
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "tickfont": {"size": 10},
            "title": None,
            "fixedrange": True,  # Disable x-axis zoom/pan
        },
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.15,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 10},
        },
        hovermode="x unified",
    )

    return fig


def build_category_panel(current_scores: dict[str, float]) -> html.Div:
    """Build horizontal health bars for each category.

    Parameters
    ----------
    current_scores : dict[str, float]
        Mapping of category key to current score (0–100).

    Returns
    -------
    html.Div
        Dash component containing styled health bars.
    """
    bars = []
    for cat in CATEGORY_WEIGHTS:
        score = current_scores[cat]
        tier = get_health_tier(score)
        label = CATEGORY_LABELS[cat]
        cat_color = CATEGORY_COLORS.get(cat, COLORS["accent"])

        bar = html.Div(
            className="health-bar-item",
            children=[
                html.Div(
                    className="health-bar-label",
                    children=[
                        html.Span(
                            label,
                            # Inline style removed to allow CSS to control font/color
                            # style={...} 
                        ),
                        html.Span(
                            f"{score:.0f}",
                            # Inline style removed, color controlled by CSS or parent
                            # actually score color IS variable, so we need to keep color but remove font styles
                            style={
                                "color": tier["color"],
                                # "fontSize": "0.8rem",  <-- Removed
                                # "fontWeight": "700",   <-- Removed
                            },
                        ),
                    ],
                ),
                html.Div(
                    className="health-bar-track",
                    children=[
                        html.Div(
                            className="health-bar-fill",
                            style={
                                "width": f"{score}%",
                                "backgroundColor": cat_color,
                            },
                        ),
                    ],
                ),
            ],
        )
        bars.append(bar)

    return html.Div(
        children=[
            html.H3(
                "Category Health",
                style={
                    "margin": "4px 0 16px",  # Reduced margin to align with Plotly title
                    "fontSize": "14px",      # Matches Plotly
                    "fontFamily": "Inter, sans-serif", # Matches Plotly
                    "fontWeight": "500",     # Matches Plotly (Medium)
                    "color": COLORS["text"],
                },
            ),
            html.Div(className="health-bar-container", children=bars),
        ],
    )


def build_world_map(map_markers: list[dict]) -> go.Figure:
    """Build a scatter-geo map showing every major shipping port.

    Each dot is color-coded by its composite health score:

        green  (80–100)  Healthy — no disruptions
        yellow (60–79)   Moderate Risk — mild signals / negative news
        orange (40–59)   Elevated Risk — significant disruption detected
        red    (0–39)    Critical — severe news, API, or global stress

    Hovering shows a rich tooltip with news headlines, VADER sentiment
    scores, and any stressed global factors that explain the color.

    Parameters
    ----------
    map_markers : list[dict]
        Dicts with keys ``name``, ``lat``, ``lon``, ``score``, ``description``.
        ``description`` is pre-built HTML from the aggregator.
    """
    lats: list[float] = []
    lons: list[float] = []
    scores: list[float] = []
    sizes: list[float] = []
    hover_texts: list[str] = []

    # Sort markers so healthiest (score ~ 100) are drawn first and most critical
    # (score ~ 0, largest) are drawn last. This ensures the large red dots
    # sit on top of the DOM and catch hover events even if they overlap.
    sorted_markers = sorted(map_markers, key=lambda m: m.get("score", 100), reverse=True)

    for marker in sorted_markers:
        score = marker.get("score", 100)

        lats.append(marker["lat"])
        lons.append(marker["lon"])
        scores.append(score)

        # Risk-based sizing: troubled ports are huge, healthy ports are tiny.
        # Score 100 -> 4px, Score 80 -> ~8.8px (30% smaller than previous 11.6px)
        sizes.append(max(4, 28 - score * 0.24))

        hover_texts.append(
            f"<b>{marker['name']}</b><br>{marker['description']}"
        )

    # Continuous color scale: green → yellow → orange → red
    # Uses a smooth gradient, but anchors the deep red and orange
    # so critical ports don't wash out.
    _colorscale = [
        [0.00, COLORS["red"]],       # 0   — Solid critical red
        [0.30, COLORS["red"]],       # 30  — Begin transition to orange
        [0.50, COLORS["orange"]],    # 50  — Solid orange
        [0.60, COLORS["yellow"]],    # 60  — Solid yellow (Stable boundary)
        [0.80, COLORS["green"]],     # 80  — Solid green (Healthy boundary)
        [1.00, COLORS["green"]],     # 100 — Solid green
    ]

    fig = go.Figure(
        go.Scattergeo(
            lat=lats,
            lon=lons,
            text=hover_texts,
            hoverinfo="text",
            mode="markers",
            marker={
                "size": sizes,
                "color": scores,
                "colorscale": _colorscale,
                "cmin": 0,
                "cmax": 100,
                "showscale": False,
                # Use solid dark background color for the border to create a sharp cutout effect
                "line": {"width": 1.5, "color": COLORS["bg"]},
                "opacity": 1.0,  # Full opacity for maximum contrast
            },
        )
    )

    fig.update_layout(
        title={
            "text": "Major Shipping Ports & Risk Status",
            "font": {"size": 14, "color": COLORS["text"], "family": "Inter"},
            "x": 0,
            "xanchor": "left",
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 25, "b": 0, "l": 0, "r": 0},
        height=310,
        hoverlabel={
            "bgcolor": COLORS["card"],
            "bordercolor": COLORS["card_border"],
            "font": {"family": "Inter", "size": 12, "color": COLORS["text"]},
            "align": "left",
            "namelength": -1,
        },
        geo={
            "bgcolor": "rgba(0,0,0,0)",
            "showframe": False,
            "showcoastlines": True,
            "coastlinecolor": COLORS["card_border"],
            "showland": True,
            "landcolor": COLORS["card"],
            "showocean": True,
            "oceancolor": COLORS["bg"],
            "showlakes": False,
            "showcountries": True,
            "countrycolor": COLORS["card_border"],
            "projection": {"type": "natural earth"},
        },
    )

    return fig
