"""
Composite Index Gauge
=====================
A semicircular gauge chart showing the overall Supply Chain Health Index.
Uses Plotly's ``go.Indicator`` in gauge mode with color-coded arcs matching
the health tiers defined in config.
"""

from __future__ import annotations

import plotly.graph_objects as go

from config import COLORS, HEALTH_TIERS, hex_to_rgba
from scoring import get_health_tier


def build_gauge_figure(composite: float, delta: float) -> go.Figure:
    """Build the main gauge indicator for the composite health index.

    Parameters
    ----------
    composite : float
        Current composite score (0–100).
    delta : float
        Day-over-day change in composite score.

    Returns
    -------
    go.Figure
        Plotly figure containing a styled gauge indicator.
    """
    tier = get_health_tier(composite)

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=composite,
            number={
                "font": {"size": 48, "color": tier["color"], "family": "Inter"},
                "suffix": "",
            },
            delta={
                "reference": composite - delta,
                "relative": False,
                "increasing": {"color": COLORS["green"]},
                "decreasing": {"color": COLORS["red"]},
                "font": {"size": 16},
            },
            title={
                "text": f"Supply Chain Health Index<br><span style='font-size:14px;color:{tier['color']}'>{tier['label']}</span>",
                "font": {"size": 16, "color": COLORS["text"], "family": "Inter"},
            },
            gauge={
                "axis": {
                    "range": [0, 100],
                    "tickwidth": 1,
                    "tickcolor": COLORS["text_muted"],
                    "tickfont": {"size": 11, "color": COLORS["text_muted"]},
                },
                "bar": {"color": tier["color"], "thickness": 0.3},
                "bgcolor": COLORS["card"],
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
        font={"family": "Inter"},
        margin={"t": 60, "b": 20, "l": 30, "r": 30},
        height=300,
    )

    return fig
