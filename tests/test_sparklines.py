"""Coverage for the server-rendered SVG sparklines in components/cards.py.

Plotly figures were replaced with SVG built as a string and served via an
``html.Img`` data URI. ``dcc.Markdown(dangerously_allow_html=True)`` still
strips ``<svg>`` (rehype sanitize), which left blank spark screens in
production. These tests assert on wrapper classNames and the decoded SVG
markup for each history-length state.
"""
from __future__ import annotations

from urllib.parse import unquote

import pandas as pd
import pytest
from dash import html

from components.cards import _sparkline, _SPARK_MIN_POINTS, _SPARK_VB_H


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
    def test_short_series_renders_dots_only(self, n):
        series = pd.Series([60.0 + i for i in range(n)], index=_dates(n))
        wrap = _sparkline(series, "#3d9b6e")

        assert wrap.className == "spark-wrap spark-wrap--sparse"
        markup = _svg_markup(wrap)
        assert markup.count("<circle") == n
        # Dots only — a connecting line/path would imply a trend shape
        # that a handful of points cannot actually support.
        assert "<path" not in markup

    def test_short_series_caption_shows_count_over_30(self):
        series = pd.Series([60.0, 61.0, 62.0], index=_dates(3))
        wrap = _sparkline(series, "#3d9b6e")
        assert _caption(wrap) == "3/30d"


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

    def test_score_domain_is_fixed_0_100_not_data_min_max(self):
        # A category pinned near the top of its own range (90-95) should
        # still sit near the top of the fixed 0-100 viewBox, not be
        # re-centered to fill the box (the old data-hugging behavior).
        high_series = pd.Series([90.0, 92.0, 91.0, 95.0, 93.0], index=_dates(5))
        wrap = _sparkline(high_series, "#3d9b6e")
        markup = _svg_markup(wrap)

        # y=0 is the top of the viewBox; a score of ~90-95 maps close to it.
        line_path = markup.split('<path d="')[2]
        first_point = line_path.split('"')[0].split(" ")[1]
        _, y = first_point.split(",")
        assert float(y) < _SPARK_VB_H * 0.2

    def test_only_last_30_points_are_used(self):
        series = pd.Series(range(50), index=_dates(50)).astype(float)
        wrap = _sparkline(series, "#3d9b6e")
        markup = _svg_markup(wrap)
        # 30 points -> 30 "L "/"M " path commands in the stroke line path
        line_path = markup.split('<path d="')[2].split('"')[0]
        assert len(line_path.split(" L ")) == 30

    def test_tier_bands_always_present(self):
        from config import HEALTH_TIERS

        series = pd.Series([50.0] * 10, index=_dates(10))
        wrap = _sparkline(series, "#3d9b6e")
        markup = _svg_markup(wrap)
        assert markup.count("<rect") == len(HEALTH_TIERS)


def test_trend_color_is_passed_through_to_stroke():
    series = pd.Series([50.0] * 10, index=_dates(10))
    wrap = _sparkline(series, "#c44d5f")
    markup = _svg_markup(wrap)
    assert 'stroke="#c44d5f"' in markup
