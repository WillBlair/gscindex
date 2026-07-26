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

from urllib.parse import quote

import pandas as pd
from dash import html

from config import (
    CATEGORY_LABELS,
    CATEGORY_WEIGHTS,
    COLORS,
    hex_to_rgba,
)
from scoring import get_health_tier

# SVG viewBox for every sparkline. Height is small (32) so the line has
# visible amplitude; the wrapper CSS stretches it to the card's screen height.
_SPARK_VB_W = 100
_SPARK_VB_H = 32
_SPARK_WINDOW = 90  # match HISTORY_DAYS so monthly series can show steps
_SPARK_MIN_POINTS = 5  # below this, real chart shape is not meaningful — plot dots only
_SPARK_MIN_Y_SPAN = 15.0  # zoom floor so 87→96 weather movement is visible
_SPARK_Y_PAD = 0.12  # fraction of data range added as headroom

# NOTE ON IMPLEMENTATION: `dash.html` has no Svg/Path/Circle/Rect/Line
# components (plotly/dash#219). `dcc.Markdown(dangerously_allow_html=True)`
# still strips <svg> via rehype sanitize, which left blank spark screens in
# production. Serve the SVG as an <img> data URI instead — no Plotly, no
# dash-svg, still server-rendered.


def _y_domain(scores: list[float]) -> tuple[float, float]:
    """Local y-domain so within-band movement is readable.

    Fixed 0–100 made Weather (~90s) look flatlined at the top of the card
    even when it moved ~8 points. Zoom to the window with a minimum span.
    """
    lo = float(min(scores))
    hi = float(max(scores))
    span = hi - lo
    pad = max(span * _SPARK_Y_PAD, 0.75)
    lo -= pad
    hi += pad
    if hi - lo < _SPARK_MIN_Y_SPAN:
        mid = (hi + lo) / 2.0
        lo = mid - _SPARK_MIN_Y_SPAN / 2.0
        hi = mid + _SPARK_MIN_Y_SPAN / 2.0
    return lo, hi


def _score_to_y(value: float, y_min: float, y_max: float) -> float:
    """Map a score into the SVG y-axis (0 = top of the viewBox)."""
    if y_max <= y_min:
        return round(_SPARK_VB_H / 2.0, 2)
    t = (float(value) - y_min) / (y_max - y_min)
    t = max(0.0, min(1.0, t))
    return round(_SPARK_VB_H - t * _SPARK_VB_H, 2)


def _wrap_svg(inner: str) -> str:
    # xmlns is required for data:image/svg+xml img sources to render.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="spark-svg" '
        f'viewBox="0 0 {_SPARK_VB_W} {_SPARK_VB_H}" '
        f'preserveAspectRatio="none">{inner}</svg>'
    )


def _spark_img(svg_markup: str) -> html.Img:
    """Render SVG markup via a data URI so browsers actually paint it."""
    return html.Img(
        src="data:image/svg+xml;charset=utf-8," + quote(svg_markup),
        className="spark-svg",
        draggable="false",
        alt="",
        **{"aria-hidden": "true"},
    )


def _spark_points(window: pd.Series) -> tuple[list[tuple[float, float]], list[float]]:
    """Build (x, score) points using calendar position in the window.

    Sparse series (e.g. geopolitical with one stored day) keep their day
    index so today's point sits on the right, not packed to x=0.
    """
    n_slots = len(window)
    denom = max(n_slots - 1, 1)
    points: list[tuple[float, float]] = []
    scores: list[float] = []
    for i, value in enumerate(window.to_numpy(dtype=float, copy=False)):
        if pd.isna(value):
            continue
        score = float(value)
        points.append((round((i / denom) * _SPARK_VB_W, 2), score))
        scores.append(score)
    return points, scores


def _sparkline(series: pd.Series, color: str) -> html.Div:
    """Build a tiny server-rendered SVG sparkline for a category card.

    Y-axis zooms to the window (with a minimum span) so small real moves in
    high-scoring categories stay visible. X uses the calendar slot in the
    trailing window so sparse history is not jammed to the left edge.

    Parameters
    ----------
    series : pd.Series
        History to display (last ``_SPARK_WINDOW`` points are used).
    color : str
        Line color (hex) — green if trending up, red if trending down.

    Returns
    -------
    html.Div
        A ``.spark-wrap`` div containing an SVG ``img`` (data URI) and an
        optional caption for sparse/empty history.
    """
    window = series.tail(_SPARK_WINDOW)
    points, scores = _spark_points(window)
    n = len(scores)

    if n == 0:
        mid_y = round(_SPARK_VB_H / 2.0, 2)
        line = (
            f'<line x1="0" y1="{mid_y}" x2="{_SPARK_VB_W}" y2="{mid_y}" '
            f'stroke="{COLORS["text_faint"]}" stroke-width="1" '
            f'stroke-dasharray="3,3"></line>'
        )
        svg_markup = _wrap_svg(line)
        return html.Div(
            className="spark-wrap spark-wrap--empty",
            children=[
                _spark_img(svg_markup),
                html.Span("No history", className="spark-caption"),
            ],
        )

    y_min, y_max = _y_domain(scores)
    plotted = [(px, _score_to_y(score, y_min, y_max)) for px, score in points]

    if n < _SPARK_MIN_POINTS:
        # Too few real measurements to imply a trend shape — larger dots at
        # true calendar x, plus a guide line so a single geo point is visible.
        guide_y = plotted[-1][1]
        guide = (
            f'<line x1="0" y1="{guide_y}" x2="{_SPARK_VB_W}" y2="{guide_y}" '
            f'stroke="{hex_to_rgba(color, 0.35)}" stroke-width="1" '
            f'stroke-dasharray="2,3"></line>'
        )
        dots = "".join(
            f'<circle cx="{px}" cy="{py}" r="2.6" fill="{color}"></circle>'
            for px, py in plotted
        )
        svg_markup = _wrap_svg(guide + dots)
        return html.Div(
            className="spark-wrap spark-wrap--sparse",
            children=[
                _spark_img(svg_markup),
                html.Span(f"{n}/{_SPARK_WINDOW}d", className="spark-caption"),
            ],
        )

    line_d = "M " + " L ".join(f"{px},{py}" for px, py in plotted)
    fill_d = (
        "M " + " L ".join(f"{px},{py}" for px, py in plotted)
        + f" L {plotted[-1][0]},{_SPARK_VB_H} L {plotted[0][0]},{_SPARK_VB_H} Z"
    )

    fill_path = f'<path d="{fill_d}" fill="{hex_to_rgba(color, 0.15)}" stroke="none"></path>'
    line_path = (
        f'<path d="{line_d}" fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"></path>'
    )
    svg_markup = _wrap_svg(fill_path + line_path)

    return html.Div(
        className="spark-wrap",
        children=[_spark_img(svg_markup)],
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
