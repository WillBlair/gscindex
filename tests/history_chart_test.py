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


def test_live_label_sits_left_of_a_rule_in_the_right_half_and_right_of_one_in_the_left():
    right = chart.chart_html(pts([60.0] * 10, first=date(2026, 10, 15)), [], LIVE)
    assert 'class="live to-left"' in right
    left = chart.chart_html(pts([60.0] * 10, first=date(2026, 10, 22)), [], LIVE)
    assert 'class="live"' in left and "to-left" not in left


def test_skipped_dates_become_gaps():
    first = date(2026, 10, 20)
    points = [(first, 60.0), (first + timedelta(days=1), 61.0), (first + timedelta(days=3), 62.0)]
    html = chart.chart_html(points, [], LIVE)
    data = json.loads(re.search(r'id="hchart-data">(.*?)</script>', html, re.S).group(1))
    assert len(data["values"]) == 4 and data["values"][2] is None
    assert line(html).count("M") == 2


def test_an_episode_on_the_last_day_stays_inside_the_box():
    points = pts([60.0] * 5)
    html = chart.chart_html(points, [{"n": 1, "date": points[-1][0], "index": 100.0}], LIVE)
    assert "left:100.00%;top:0.00%" in html and "overflow:hidden" in chart.CHART_CSS


def test_tier_names_sit_in_a_legend_under_the_plot_and_not_inside_it():
    html = chart.chart_html(pts([60.0] * 5), [], LIVE)
    assert 'class="tier"' not in html and ".hchart .tier{" not in chart.CHART_CSS
    legend = re.search(r'<div class="tier-key">(.*?)</div>', html, re.S).group(1)
    items = re.findall(r'<span class="tk">(.*?)</span>', legend, re.S)
    text = " ".join(re.sub(r"<[^>]+>", "", i) for i in items)
    assert [re.sub(r"<[^>]+>", "", i) for i in items] == ["Healthy 80 to 100", "Stable 60 to 79", "Stressed 40 to 59", "Critical 0 to 39"]
    assert "Healthy" in html and "#35D07F" in legend and "–" not in legend and "-" not in text
    assert html.index("tier-key") > html.index("</svg>")


def test_the_y_axis_numbers_sit_in_a_gutter_at_their_levels():
    html = chart.chart_html(pts([60.0] * 5), [], LIVE)
    axis = re.search(r'<div class="hchart-axis">(.*?)</div>', html, re.S).group(1)
    found = re.findall(r'<span style="top:([\d.]+)%">(\d+)</span>', axis)
    assert found == [("0.00", "100"), ("20.00", "80"), ("40.00", "60"), ("60.00", "40"), ("100.00", "0")]
    assert html.index("hchart-axis") < html.index('class="hchart-plot"')
