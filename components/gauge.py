"""
Composite Index Gauge
=====================
A semicircular gauge chart showing the overall Supply Chain Health Index.
Uses Plotly's ``go.Indicator`` in gauge mode with color-coded arcs matching
the health tiers defined in config.
"""

from __future__ import annotations

import plotly.graph_objects as go

from config import COLORS, FONT_NUMBERS, FONT_SANS, HEALTH_TIERS, hex_to_rgba
from dash import html
from scoring import get_health_tier


def build_score_tooltip(explanation: dict) -> html.Div:
    """Hover card explaining why the composite score is at its current level."""
    bullets = explanation.get("bullets") or []
    return html.Div(
        className="score-explanation-tooltip",
        children=[
            html.Div(explanation.get("headline", ""), className="score-explanation-headline"),
            html.P(explanation.get("summary", ""), className="score-explanation-summary"),
            *[
                html.Div(line, className="score-explanation-bullet")
                for line in bullets
            ],
        ],
    )


def build_gauge_figure(composite: float, delta: float, show_delta: bool = True) -> go.Figure:
    """Build the main gauge indicator for the composite health index.

    Parameters
    ----------
    composite : float
        Current composite score (0–100).
    delta : float
        Day-over-day change in composite score.
    show_delta : bool
        If False, suppresses the delta indicator (used for provisional data).

    Returns
    -------
    go.Figure
        Plotly figure containing a styled gauge indicator.
    """
    tier = get_health_tier(composite)

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta" if show_delta else "gauge+number",
            value=composite,
            number={
                "font": {"size": 48, "color": tier["color"], "family": FONT_NUMBERS},
                "suffix": "",
                "valueformat": ".1f",
            },
            delta=(
                {
                    "reference": composite - delta,
                    "relative": False,
                    "increasing": {"color": COLORS["green"]},
                    "decreasing": {"color": COLORS["red"]},
                    "font": {"size": 16, "family": FONT_NUMBERS},
                    "valueformat": ".1f",
                }
                if show_delta
                else {}
            ),
            title={
                "text": f"Supply Chain Health Index<br><span style='font-size:14px;color:{tier['color']}'>{tier['label']}</span>",
                "font": {"size": 16, "color": COLORS["text"], "family": FONT_SANS},
            },
            gauge={
                "axis": {
                    "range": [0, 100],
                    "tickwidth": 1,
                    "tickcolor": COLORS["text_muted"],
                    "tickfont": {"size": 11, "color": COLORS["text_muted"], "family": FONT_NUMBERS},
                },
                "bar": {"color": tier["color"], "thickness": 0.3},
                "bgcolor": "#111113",
                "borderwidth": 0,
                "steps": [
                    {"range": [t["min"], t["max"] + 1], "color": hex_to_rgba(t["color"], 0.1)}
                    for t in HEALTH_TIERS
                ],
                "threshold": {
                    "line": {"color": "#ffffff", "width": 3},
                    "thickness": 0.8,
                    "value": composite,
                },
            },
        )
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT_SANS},
        margin={"t": 40, "b": 10, "l": 30, "r": 30},
        height=250,
    )

    return fig
