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
    HEALTH_TIERS,
    hex_to_rgba,
)
from scoring import get_health_tier

import pandas as pd

# ---------------------------------------------------------------------------
# Region coordinates for the world map scatter points
# ---------------------------------------------------------------------------

_REGION_COORDS: dict[str, dict[str, float]] = {
    "North America":      {"lat": 40.0,  "lon": -100.0},
    "Central America":    {"lat": 15.0,  "lon": -90.0},
    "South America":      {"lat": -15.0, "lon": -60.0},
    "Europe":             {"lat": 48.0,  "lon": 10.0},
    "Eastern Europe":     {"lat": 50.0,  "lon": 30.0},
    "East Asia":          {"lat": 35.0,  "lon": 110.0},
    "Southeast Asia":     {"lat": 5.0,   "lon": 110.0},
    "South Asia":         {"lat": 22.0,  "lon": 78.0},
    "Middle East":        {"lat": 28.0,  "lon": 45.0},
    "North Africa":       {"lat": 25.0,  "lon": 15.0},
    "Sub-Saharan Africa": {"lat": -10.0, "lon": 25.0},
    "Oceania":            {"lat": -25.0, "lon": 135.0},
}


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
        yaxis={
            "range": [0, 100],
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "tickfont": {"size": 10},
            "title": None,
        },
        xaxis={
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "tickfont": {"size": 10},
            "title": None,
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

        bar = html.Div(
            className="health-bar-item",
            children=[
                html.Div(
                    className="health-bar-label",
                    children=[
                        html.Span(
                            label,
                            style={
                                "color": COLORS["text"],
                                "fontSize": "0.8rem",
                                "fontWeight": "500",
                            },
                        ),
                        html.Span(
                            f"{score:.0f}",
                            style={
                                "color": tier["color"],
                                "fontSize": "0.8rem",
                                "fontWeight": "700",
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
                                "backgroundColor": tier["color"],
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
                    "margin": "0 0 16px",
                    "fontSize": "1rem",
                    "fontWeight": "600",
                    "color": COLORS["text"],
                },
            ),
            html.Div(className="health-bar-container", children=bars),
        ],
    )


def build_world_map(map_markers: list[dict]) -> go.Figure:
    """Build a scatter-geo map showing specific shipping hubs.

    Parameters
    ----------
    map_markers : list[dict]
        List of dicts with keys: name, lat, lon, score, description.

    Returns
    -------
    go.Figure
        Plotly scatter-geo figure.
    """
    lats = []
    lons = []
    names = []
    scores = []
    colors = []
    sizes = []
    descriptions = []

    for marker in map_markers:
        score = marker["score"]
        tier = get_health_tier(score)
        
        lats.append(marker["lat"])
        lons.append(marker["lon"])
        names.append(marker["name"])
        scores.append(score)
        colors.append(tier["color"])
        descriptions.append(marker["description"])
        
        # Larger dot for lower scores (more risk = more attention needed)
        sizes.append(max(15, 45 - score * 0.3))

    fig = go.Figure(
        go.Scattergeo(
            lat=lats,
            lon=lons,
            text=[
                f"<b>{n}</b><br>Health: {s:.0f}{d}" 
                for n, s, d in zip(names, scores, descriptions)
            ],
            hoverinfo="text",
            marker={
                "size": sizes,
                "color": colors,
                "line": {"width": 2, "color": "white"},
                "opacity": 0.9,
            },
        )
    )

    fig.update_layout(
        title={
            "text": "Major Shipping Hubs & Risk Status",
            "font": {"size": 14, "color": COLORS["text"], "family": "Inter"},
            "x": 0,
            "xanchor": "left",
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 40, "b": 10, "l": 0, "r": 0},
        height=300,
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
