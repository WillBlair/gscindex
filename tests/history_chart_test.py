import json
import re
from datetime import date, timedelta

import components.history_chart as chart

LIVE = date(2026, 10, 23)


def pts(values, first=date(2026, 10, 20)):
    return [(first + timedelta(days=i), v) for i, v in enumerate(values)]


def line(html):
    return re.search(r'<path class="line"[^>]* d="([^"]+)"', html).group(1)


def test_a_missing_day_breaks_the_line():
    html = chart.chart_html(pts([60.0, 61.0, None, 62.0, 63.0]), [], LIVE)
    assert line(html).count("M") == 2 and "None" not in html and "nan" not in html.lower()


def test_the_y_axis_is_fixed_and_a_lone_day_still_draws():
    html = chart.chart_html(pts([80.0, None, 40.0]), [], LIVE)
    assert line(html) == "M0.00 20.00h0M1000.00 60.00h0"
    assert 'viewBox="0 0 1000 100"' in html and 'preserveAspectRatio="none"' in html


def test_episode_marks_are_numbered_and_skip_an_episode_without_a_value():
    points = pts([60.0] * 5)
    eps = [{"n": 1, "date": points[1][0], "index": 60.0}, {"n": 2, "date": points[3][0], "index": None},
           {"n": 3, "date": date(2030, 1, 1), "index": 50.0}]
    html = chart.chart_html(points, eps, LIVE)
    assert html.count('class="mark"') == 1 and 'href="#ep-1"' in html and "left:25.00%;top:40.00%" in html


def test_labels_the_live_rule_and_the_hover_data():
    points = pts([60.0] * 699 + [None], first=date(2025, 1, 1))
    html = chart.chart_html(points, [], LIVE)
    assert html.count("recorded live from here") == 1 and ">2025<" in html and ">2026<" in html
    assert all(name in html for name in ("Healthy", "Stable", "Stressed", "Critical"))
    data = json.loads(re.search(r'id="hchart-data">(.*?)</script>', html, re.S).group(1))
    assert data["start"] == "2025-01-01" and len(data["values"]) == 700 and data["values"][-1] is None
    assert "recorded live from here" not in chart.chart_html(pts([60.0] * 3, first=date(2020, 1, 1)), [], LIVE)
    assert chart.chart_html([], [], LIVE) == ""


def test_out_of_range_and_non_finite_values_stay_in_the_box():
    html = chart.chart_html(pts([150.0, -20.0, float("nan"), 50.0]), [], LIVE)
    assert line(html) == "M0.00 0.00L333.33 100.00M1000.00 50.00h0"
    assert "nan" not in html.lower() and "None" not in html
