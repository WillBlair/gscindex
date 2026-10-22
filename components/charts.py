"""
Dashboard Charts
================
The Terminal port map:

    - ``build_world_map`` — Natural-earth port map with tier-colored risk dots
"""

from __future__ import annotations

from html import escape
import math
import re
from textwrap import wrap

import plotly.graph_objects as go

from components.terminal_data import tier_for
from components.workspace import plain_text
from scoring import get_health_tier


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


# Global Constraints palette for the Terminal map.
MAP_LAND = "#151B22"
MAP_BG = "#07090C"
MAP_BORDER = "#1E252E"
MAP_COAST = "#27303B"


def _finite_score(score) -> bool:
    """False for None, NaN, infinities and non-numbers, so one bad marker is skipped."""
    try:
        return math.isfinite(float(score))
    except (TypeError, ValueError):
        return False


def build_world_map(map_markers: list[dict]) -> go.Figure:
    """Show port risk by health tier with source-provided conditions directly on hover."""
    lats: list[float] = []
    lons: list[float] = []
    scores: list[float] = []
    sizes: list[float] = []
    hover_texts: list[str] = []

    # Sort markers so healthiest (score ~ 100) are drawn first and most critical
    # (score ~ 0, largest) are drawn last. This ensures the large red dots
    # sit on top of the DOM and catch hover events even if they overlap.
    usable = [m for m in map_markers if _finite_score(m.get("score", 100))]
    sorted_markers = sorted(usable, key=lambda m: m.get("score", 100), reverse=True)

    for marker in sorted_markers:
        score = marker.get("score", 100)

        lats.append(marker["lat"])
        lons.append(marker["lon"])
        scores.append(score)

        sizes.append(11 + (100 - score) * 0.07)

        hover_texts.append(_port_hover_text(marker))

    # Absolute tier colors (Terminal palette); thresholds stay in HEALTH_TIERS.
    colors = [tier_for(score)["color"] for score in scores]

    fig = go.Figure(
        go.Scattergeo(
            lat=lats,
            lon=lons,
            text=hover_texts,
            hoverinfo="text",
            mode="markers",
            marker={
                "size": sizes,
                "color": colors,
                "opacity": 1.0,  # Full opacity for maximum contrast
                "line": {"width": 1, "color": MAP_BG},
            },
        )
    )

    fig.update_layout(
        paper_bgcolor=MAP_BG,
        plot_bgcolor=MAP_BG,
        margin={"t": 0, "b": 0, "l": 0, "r": 0},
        autosize=True,
        uirevision="port-map-fill",
        dragmode="pan",
        hoverlabel={
            "bgcolor": "#0D1117",
            "bordercolor": "#1D232B",
            "font": {"family": "JetBrains Mono, monospace", "size": 12, "color": "#F2F4F7"},
            "align": "left",
            "namelength": -1,
        },
        geo={
            "projection": {"type": "natural earth"},
            "showland": True, "landcolor": MAP_LAND,
            "showocean": True, "oceancolor": MAP_BG,
            "showcountries": True, "countrycolor": MAP_BORDER,
            "showcoastlines": True, "coastlinecolor": MAP_COAST,
            "showlakes": False,
            "showframe": False,
            "bgcolor": MAP_BG,
            "lataxis": {"range": [-50, 72]},
        },
    )

    return fig
