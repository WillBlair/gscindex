"""
Dashboard Charts
================
All Plotly figures and Dash panels that appear in the main dashboard body:

    - ``build_history_chart``  — 90-day multi-line trend of every category
    - ``build_category_panel`` — Horizontal health bars for each category
    - ``build_world_map``      — Responsive tile map with regional risk dots
"""

from __future__ import annotations

from html import escape
import re
from textwrap import wrap

from components.workspace import plain_text

import plotly.graph_objects as go
from dash import html

from config import (
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_WEIGHTS,
    COLORS,
    HEALTH_TIERS,
    MAP_RISK_SCALE,
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

    for cat, series in category_history.items():
        if series is None or getattr(series, "empty", False):
            continue
        color = CATEGORY_COLORS.get(cat, COLORS["text_muted"])
        label = CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())

        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                name=label,
                mode="lines+markers" if series.count() < 5 else "lines",
                connectgaps=False,
                marker={"size": 6},
                line={"color": color, "width": 2},
                fill="none",
                hovertemplate=f"<b>{label}</b><br>"
                              "%{x|%b %d}<br>"
                              "Score: %{y:.1f}<extra></extra>",
            )
        )

    fig.update_layout(
        title={
            "text": "",
            "font": {"size": 14, "color": COLORS["text"], "family": "Satoshi"},
            "x": 0,
            "xanchor": "left",
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Satoshi", "color": COLORS["text_muted"]},
        margin={"t": 42, "b": 25, "l": 32, "r": 10},
        height=320,
        dragmode=False,  # Disable drag interactions (pan/zoom selection)
        yaxis={
            "range": [0, 100],
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "tickfont": {"size": 11},
            "title": None,
            "fixedrange": True,  # Disable y-axis zoom/pan
        },
        xaxis={
            "gridcolor": COLORS["grid"],
            "zeroline": False,
            "tickfont": {"size": 11},
            "title": None,
            "fixedrange": True,  # Disable x-axis zoom/pan
        },
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.04,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 12},
        },
        hovermode="x unified",
        uirevision="category-trends",
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
        cat_color = CATEGORY_COLORS.get(cat, COLORS["text_muted"])

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
            html.H3("Category Health", className="panel-title"),
            html.Div(className="health-bar-container", children=bars),
        ],
    )


def _port_hover_text(marker: dict) -> str:
    """Wrap semantic paragraphs once, removing legacy pre-wrapped line breaks."""
    score = marker.get("score", 100)
    heading = f"<b>{escape(plain_text(marker['name']))}</b><br>{score:.1f} / 100 · {get_health_tier(score)['label']}"
    sections = []
    for raw in re.split(r"<br\s*/?>", str(marker.get("description") or ""), flags=re.IGNORECASE):
        text = plain_text(raw)
        if not text or text.startswith("Score:") or not text.strip("─—-_ "):
            continue
        # Field labels and severity tags start sections; all other breaks were
        # inserted by the aggregator to fit its old, smaller hover label.
        starts_section = re.match(r"^(?:Region|Structural risk|Top risk|AI Status|AI Penalty|Global alert|Global):|^\[(?:HIGH|MEDIUM|LOW)\]", text)
        if starts_section or not sections:
            sections.append(text)
        else:
            sections[-1] += " " + text

    paragraphs = []
    for section in sections:
        section = section.replace("AI Status:", "Port update:", 1)
        lines = [escape(line) for line in wrap(section, width=44, break_long_words=False, break_on_hyphens=False)]
        if lines and ":" in lines[0]:
            label, rest = lines[0].split(":", 1)
            lines[0] = f"<b>{label}:</b>{rest}"
        paragraphs.append("<br>".join(lines))
    return heading + "<br><br>" + ("<br><br>".join(paragraphs) or "Port context unavailable.")


def build_world_map(map_markers: list[dict]) -> go.Figure:
    """Show relative port risk with source-provided conditions directly on hover."""
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

        sizes.append(11 + (100 - score) * 0.07)

        hover_texts.append(_port_hover_text(marker))

    # Ties share a hue; identical readings stay neutral.
    ranks = pd.Series(scores, dtype=float).rank(method="average")
    colors = ((ranks - ranks.min()) / (ranks.max() - ranks.min())).tolist() if len(set(scores)) > 1 else [0.5] * len(scores)

    fig = go.Figure(
        go.Scattermap(
            lat=lats,
            lon=lons,
            text=hover_texts,
            hoverinfo="text",
            mode="markers",
            marker={
                "size": sizes,
                "color": colors,
                "colorscale": MAP_RISK_SCALE,
                "cmin": 0, "cmax": 1,
                "showscale": False,
                "opacity": 1.0,  # Full opacity for maximum contrast
            },
        )
    )

    fig.update_layout(
        title={
            "text": "",
            "font": {"size": 14, "color": COLORS["text"], "family": "Satoshi"},
            "x": 0,
            "xanchor": "left",
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 0, "b": 0, "l": 0, "r": 0},
        autosize=True,
        uirevision="port-map-fill",
        dragmode="pan",
        hoverlabel={
            "bgcolor": "#101923",
            "bordercolor": "#9ab0c8",
            "font": {"family": "Arial, sans-serif", "size": 14, "color": "#f4f7fb"},
            "align": "left",
            "namelength": -1,
        },
        map={
            "style": "carto-darkmatter",
            "fitbounds": "locations",
            "uirevision": "port-map-fill",
        },
    )

    return fig
