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
from dash import dcc, html

from config import (
    CATEGORY_LABELS,
    CATEGORY_WEIGHTS,
    COLORS,
    HEALTH_TIERS,
    hex_to_rgba,
)
from scoring import get_health_tier

# SVG viewBox for every sparkline. Height is small (32) so the line has
# visible amplitude; the wrapper CSS stretches it to the card's screen height.
_SPARK_VB_W = 100
_SPARK_VB_H = 32
_SPARK_MIN_POINTS = 5  # below this, real chart shape is not meaningful — plot dots only

# NOTE ON IMPLEMENTATION: `dash.html` has no Svg/Path/Circle/Rect/Line
# components — SVG was never added to core Dash (see plotly/dash#219); the
# only Python wrapper for real SVG *components* is the third-party
# `dash-svg` package, which this task explicitly avoids. The Dash-native
# way to render raw markup without a callback round-trip is `dcc.Markdown`
# with `dangerously_allow_html=True`, which passes an HTML/SVG string
# through to the browser unescaped. We build the SVG as a plain string
# below and hand it to `dcc.Markdown` — still server-rendered, still no
# Plotly figure, still no extra package.


def _tier_band_svg() -> str:
    """Faint background bands for each health tier, fixed to the 0-100 domain.

    Gives every sparkline the same visual reference frame (e.g. "this line
    is sitting in the Stressed band") regardless of the category's own
    min/max, which is the whole point of a fixed 0-100 y domain.
    """
    parts = []
    for tier in HEALTH_TIERS:
        y_top = _SPARK_VB_H - (tier["max"] / 100.0) * _SPARK_VB_H
        y_bottom = _SPARK_VB_H - (tier["min"] / 100.0) * _SPARK_VB_H
        parts.append(
            f'<rect x="0" y="{y_top:.2f}" width="{_SPARK_VB_W}" '
            f'height="{(y_bottom - y_top):.2f}" '
            f'fill="{hex_to_rgba(tier["color"], 0.07)}" stroke="none"></rect>'
        )
    return "".join(parts)


def _score_to_y(value: float) -> float:
    """Map a 0-100 score to an SVG y-coordinate (0 = top of the viewBox)."""
    clamped = max(0.0, min(100.0, value))
    return round(_SPARK_VB_H - (clamped / 100.0) * _SPARK_VB_H, 2)


def _wrap_svg(inner: str) -> str:
    return (
        f'<svg class="spark-svg" viewBox="0 0 {_SPARK_VB_W} {_SPARK_VB_H}" '
        f'preserveAspectRatio="none">{inner}</svg>'
    )


def _sparkline(series: pd.Series, color: str) -> html.Div:
    """Build a tiny server-rendered SVG sparkline for a category card.

    Unlike a Plotly figure with a data-hugging y-axis, this always maps the
    fixed 0-100 score domain onto the viewBox, so a card sitting at 90 always
    looks near the top and a card at 20 always looks near the bottom —
    comparable across every category at a glance.

    Parameters
    ----------
    series : pd.Series
        History to display (last 30 points are used).
    color : str
        Line color (hex) — green if trending up, red if trending down.

    Returns
    -------
    html.Div
        A ``.spark-wrap`` div containing an inline SVG (via
        ``dcc.Markdown(dangerously_allow_html=True)``) and an optional
        caption for sparse/empty history.
    """
    # Drop NaN: history may legitimately be short (real measurements only
    # accumulate day by day), and NaN breaks the polyline/fill path.
    recent = series.tail(30).dropna()
    n = len(recent)

    bands = _tier_band_svg()

    if n == 0:
        mid_y = _score_to_y(50.0)
        line = (
            f'<line x1="0" y1="{mid_y}" x2="{_SPARK_VB_W}" y2="{mid_y}" '
            f'stroke="{COLORS["text_faint"]}" stroke-width="1" '
            f'stroke-dasharray="3,3"></line>'
        )
        svg_markup = _wrap_svg(bands + line)
        return html.Div(
            className="spark-wrap spark-wrap--empty",
            children=[
                dcc.Markdown(svg_markup, dangerously_allow_html=True, className="spark-markdown"),
                html.Span("No history", className="spark-caption"),
            ],
        )

    x_step = _SPARK_VB_W / max(n - 1, 1)
    points = [
        (round(i * x_step, 2), _score_to_y(float(v)))
        for i, v in enumerate(recent.values)
    ]

    if n < _SPARK_MIN_POINTS:
        # Too few real measurements to imply a trend shape — show discrete
        # dots (never a connecting line, which would fabricate a slope).
        dots = "".join(
            f'<circle cx="{px}" cy="{py}" r="1.8" fill="{color}"></circle>'
            for px, py in points
        )
        svg_markup = _wrap_svg(bands + dots)
        return html.Div(
            className="spark-wrap spark-wrap--sparse",
            children=[
                dcc.Markdown(svg_markup, dangerously_allow_html=True, className="spark-markdown"),
                html.Span(f"{n}/30d", className="spark-caption"),
            ],
        )

    line_d = "M " + " L ".join(f"{px},{py}" for px, py in points)
    # Filled-to-bottom polygon: line points, then back along the baseline.
    fill_d = (
        "M " + " L ".join(f"{px},{py}" for px, py in points)
        + f" L {points[-1][0]},{_SPARK_VB_H} L {points[0][0]},{_SPARK_VB_H} Z"
    )

    fill_path = f'<path d="{fill_d}" fill="{hex_to_rgba(color, 0.15)}" stroke="none"></path>'
    line_path = (
        f'<path d="{line_d}" fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"></path>'
    )
    svg_markup = _wrap_svg(bands + fill_path + line_path)

    return html.Div(
        className="spark-wrap",
        children=[dcc.Markdown(svg_markup, dangerously_allow_html=True, className="spark-markdown")],
    )


def build_category_cards(
    current_scores: dict[str, float],
    category_history: dict[str, pd.Series],
    metadata: dict[str, dict] | None = None,
    active_weights: dict[str, float] | None = None,
    card_categories: list[str] | None = None,
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
        Used for weight badges. Defaults to ``CATEGORY_WEIGHTS``.
    card_categories : list[str], optional
        Explicit category order for the card row. When set, these cards
        replace the previous row (used by industry profiles). Defaults to
        the keys of ``active_weights``.

    Returns
    -------
    list
        List of technical card components.
    """
    if metadata is None:
        metadata = {}
    active_weights = active_weights or CATEGORY_WEIGHTS
    categories = card_categories or list(active_weights.keys())
    cards = []
    for cat in categories:
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

        weight_pct = int(active_weights.get(cat, CATEGORY_WEIGHTS.get(cat, 0.0)) * 100)

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
                # Header: Label + [Weight]
                html.Div(
                    className="tech-card-header",
                    children=[
                        html.Div([
                            html.Span(CATEGORY_LABELS[cat], className="tech-label"),
                            # Sub-label for context (e.g. "Matson")
                            html.Div(raw_label, className="tech-sublabel", style={
                                "fontSize": "11px", "color": COLORS["text_faint"], "marginTop": "2px"
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
                    children=[_sparkline(history, sparkline_color)],
                ),
            ],
        )
        cards.append(card)

    return cards
