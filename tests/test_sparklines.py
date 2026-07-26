"""Coverage for the server-rendered SVG sparklines in components/cards.py.

Plotly figures were replaced with SVG built as a string and served via an
``html.Img`` data URI. Y-axis zooms to the window (minimum span) so high
scores still show movement; sparse points keep calendar x positions.
"""
from __future__ import annotations

from urllib.parse import unquote

import pandas as pd
import pytest
from dash import html

from components.cards import (
    _sparkline,
    _SPARK_MIN_POINTS,
    _SPARK_VB_H,
    _SPARK_WINDOW,
    _y_domain,
)


def _dates(n: int, end: str = "2026-07-25") -> pd.DatetimeIndex:
    return pd.date_range(end=end, periods=n, freq="D")


def _img_child(wrap: html.Div) -> html.Img:
    img = next(c for c in wrap.children if isinstance(c, html.Img))
    assert img.src.startswith("data:image/svg+xml")
    return img


def _svg_markup(wrap: html.Div) -> str:
    src = _img_child(wrap).src
    assert src.startswith("data:image/svg+xml;charset=utf-8,")
    return unquote(src.split(",", 1)[1])


def _caption(wrap: html.Div) -> str | None:
    span = next((c for c in wrap.children if isinstance(c, html.Span)), None)
    return span.children if span is not None else None


def _stroke_ys(markup: str) -> list[float]:
    line_path = markup.split('<path d="')[-1].split('"')[0]
    return [float(p.split(",")[1]) for p in line_path.replace("M ", "").split(" L ")]


class TestEmptySeries:
    def test_empty_series_renders_wrapper_and_svg(self):
        wrap = _sparkline(pd.Series(dtype=float), "#3d9b6e")

        assert isinstance(wrap, html.Div)
        assert wrap.className == "spark-wrap spark-wrap--empty"

        markup = _svg_markup(wrap)
        assert markup.count("<svg") == 1
        assert 'xmlns="http://www.w3.org/2000/svg"' in markup
        assert "<line" in markup
        assert "<path" not in markup
        assert "<circle" not in markup

    def test_empty_series_shows_no_history_caption(self):
        wrap = _sparkline(pd.Series(dtype=float), "#3d9b6e")
        assert _caption(wrap) == "No history"

    def test_all_nan_series_treated_as_empty(self):
        series = pd.Series([float("nan")] * 10, index=_dates(10))
        wrap = _sparkline(series, "#3d9b6e")
        assert wrap.className == "spark-wrap spark-wrap--empty"


class TestShortSeries:
    @pytest.mark.parametrize("n", [1, 2, _SPARK_MIN_POINTS - 1])
    def test_short_series_renders_dots_not_trend_path(self, n):
        series = pd.Series([60.0 + i for i in range(n)], index=_dates(n))
        wrap = _sparkline(series, "#3d9b6e")

        assert wrap.className == "spark-wrap spark-wrap--sparse"
        markup = _svg_markup(wrap)
        assert markup.count("<circle") == n
        assert "<path" not in markup
        assert "<line" in markup  # guide line so a lone point is visible

    def test_short_series_caption_shows_count_over_window(self):
        series = pd.Series([60.0, 61.0, 62.0], index=_dates(3))
        wrap = _sparkline(series, "#3d9b6e")
        assert _caption(wrap) == f"3/{_SPARK_WINDOW}d"

    def test_sparse_point_uses_calendar_x_not_left_edge(self):
        # One real observation on the last day of a longer NaN-padded window.
        idx = _dates(30)
        values = [float("nan")] * 29 + [53.5]
        series = pd.Series(values, index=idx)
        wrap = _sparkline(series, "#3d9b6e")
        markup = _svg_markup(wrap)
        assert 'cx="100.0"' in markup or 'cx="100"' in markup


class TestFlatSeries:
    def test_flat_series_renders_line_not_dots(self):
        series = pd.Series([50.0] * 10, index=_dates(10))
        wrap = _sparkline(series, "#c4a35a")

        assert wrap.className == "spark-wrap"
        markup = _svg_markup(wrap)
        assert markup.count("<path") == 2  # fill polygon + stroke line
        assert "<circle" not in markup
        assert _caption(wrap) is None

    def test_flat_series_stays_within_fixed_viewbox(self):
        series = pd.Series([50.0] * 10, index=_dates(10))
        wrap = _sparkline(series, "#c4a35a")
        markup = _svg_markup(wrap)
        assert 'viewBox="0 0 100 32"' in markup


class TestNormalSeries:
    def test_normal_series_renders_fill_and_line_paths(self):
        series = pd.Series(
            [40.0, 45.0, 50.0, 55.0, 60.0, 58.0, 62.0, 65.0, 70.0, 72.0],
            index=_dates(10),
        )
        wrap = _sparkline(series, "#3d9b6e")

        assert wrap.className == "spark-wrap"
        markup = _svg_markup(wrap)
        assert markup.count("<path") == 2
        assert 'fill="none"' in markup  # stroke path has no fill
        assert _caption(wrap) is None

    def test_high_band_movement_uses_local_zoom(self):
        # Weather-like band: fixed 0-100 used to flatten this against the top.
        high_series = pd.Series(
            [87.0, 89.0, 88.0, 92.0, 91.0, 90.0, 93.0, 94.0, 91.0, 95.5],
            index=_dates(10),
        )
        wrap = _sparkline(high_series, "#3d9b6e")
        markup = _svg_markup(wrap)
        ys = _stroke_ys(markup)
        assert max(ys) - min(ys) > _SPARK_VB_H * 0.35

    def test_y_domain_enforces_minimum_span(self):
        lo, hi = _y_domain([73.5, 73.5])
        assert hi - lo >= 15.0 - 1e-9

    def test_only_last_window_points_are_used(self):
        series = pd.Series(range(120), index=_dates(120)).astype(float)
        wrap = _sparkline(series, "#3d9b6e")
        markup = _svg_markup(wrap)
        line_path = markup.split('<path d="')[-1].split('"')[0]
        assert len(line_path.split(" L ")) == _SPARK_WINDOW


def test_trend_color_is_passed_through_to_stroke():
    series = pd.Series([50.0] * 10, index=_dates(10))
    wrap = _sparkline(series, "#c44d5f")
    markup = _svg_markup(wrap)
    assert 'stroke="#c44d5f"' in markup
