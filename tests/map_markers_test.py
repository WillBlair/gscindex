"""Port map: composite + local weather minus one news/AI penalty; word-boundary port keywords."""

import re

import pytest

from data import aggregator
from data.ports_data import MAJOR_PORTS


class _Weather:
    """Stands in for WeatherProvider; scores by port name."""

    def __init__(self, scores=None, error=None):
        self.scores = scores or {}
        self.error = error

    def fetch_batch_port_weather(self, coords):
        if self.error:
            raise self.error
        return {n: {"score": s, "summary": f"{n} weather"} for n, s in self.scores.items()}


def _marker(markers, name):
    return next((m for m in markers if m["name"] == name), None)


def _alert(title, sentiment=-5.0, severity="high", body=""):
    return {"title": title, "body": body, "sentiment": sentiment, "severity": severity}


def test_oman_does_not_match_woman():
    alerts = [_alert("Woman arrested after dock protest"), _alert("Romania ferry strike")]
    assert aggregator._match_news_to_ports(alerts) == {}
    matched = aggregator._match_news_to_ports([_alert("Oman port closes after storm")])
    assert list(matched) == ["Dubai"]


def test_hamburger_does_not_match_hamburg():
    assert aggregator._match_news_to_ports([_alert("Hamburger chain recalls beef")]) == {}
    assert "Hamburg" in aggregator._match_news_to_ports([_alert("Hamburg port strike widens")])


def test_plural_and_generic_keywords_still_match():
    matched = aggregator._match_news_to_ports([
        _alert("Gulf coast ports shut for hurricane"),
        _alert("Gulf states weigh Hormuz closure"),
    ])
    assert "Houston" in matched
    assert "Dubai" in matched


def test_port_authority_keyword_is_not_generic():
    alerts = [_alert("Port Authority of Los Angeles reports delays")]
    assert "New York" not in aggregator._match_news_to_ports(alerts)


def test_casablanca_maps_to_casablanca():
    # Casablanca is not one of the 37 ports, so no port may claim it.
    assert "Casablanca" not in [name for name, *_ in MAJOR_PORTS]
    matched = aggregator._match_news_to_ports([_alert("Casablanca port congestion worsens")])
    assert "Port Said" not in matched
    assert matched == {}


def test_keywords_do_not_contain_unbounded_short_tokens():
    for name, _lat, _lon, keywords in MAJOR_PORTS:
        for kw in keywords:
            assert len(kw) >= 4, (name, kw)
            assert kw == kw.lower() and re.fullmatch(r"[a-z ]+", kw), (name, kw)


def test_port_score_formula():
    # composite 50, weather 100, AI penalty 10 -> 0.6*50 + 0.4*100 - 10 = 60
    markers = aggregator._derive_map_markers(
        50.0, [], _Weather({"Rotterdam": 100.0}),
        {"Rotterdam": {"summary": "Quiet.", "disruption_penalty": 10.0}})
    assert _marker(markers, "Rotterdam")["score"] == 60.0


def test_news_penalty_wins_when_larger_than_ai_penalty():
    markers = aggregator._derive_map_markers(
        80.0, [_alert("Houston refinery fire halts shipping", severity="high")],
        _Weather({"Houston": 80.0}),
        {"Houston": {"summary": "x", "disruption_penalty": 5.0}})
    marker = _marker(markers, "Houston")
    assert marker["score"] == 50.0  # 0.6*80 + 0.4*80 - 30
    assert "-30.0 pts (news)" in marker["description"]
    assert "(AI port summary)" not in marker["description"]


def test_composite_alone_without_weather():
    markers = aggregator._derive_map_markers(72.0, [], _Weather({"Rotterdam": 90.0}), {})
    assert _marker(markers, "Rotterdam")["score"] == pytest.approx(0.6 * 72 + 0.4 * 90, abs=0.05)
    assert _marker(markers, "Hamburg")["score"] == 72.0


def test_no_composite_uses_weather_alone_and_skips_ports_without_inputs():
    markers = aggregator._derive_map_markers(None, [], _Weather({"Rotterdam": 90.0}), {})
    assert [m["name"] for m in markers] == ["Rotterdam"]
    assert markers[0]["score"] == 90.0


def test_no_composite_no_weather_gives_no_markers():
    assert aggregator._derive_map_markers(None, [], _Weather(), {}) == []


def test_weather_failure_falls_back_to_composite():
    markers = aggregator._derive_map_markers(66.0, [], _Weather(error=RuntimeError("down")), {})
    assert len(markers) == len(MAJOR_PORTS)
    assert all(m["score"] == 66.0 for m in markers)


def test_unscored_alerts_never_penalize():
    unscored = {"title": "Houston port closed", "body": "", "sentiment": None, "severity": None}
    markers = aggregator._derive_map_markers(70.0, [unscored], _Weather(), {})
    assert _marker(markers, "Houston")["score"] == 70.0


def test_hover_lists_composite_weather_and_penalty_source():
    markers = aggregator._derive_map_markers(
        50.0, [], _Weather({"Rotterdam": 100.0}),
        {"Rotterdam": {"summary": "Lock closure.", "disruption_penalty": 10.0}})
    text = _marker(markers, "Rotterdam")["description"]
    assert "Composite" in text and "50" in text
    assert "Rotterdam weather" in text
    assert "-10.0 pts (AI port summary)" in text
    assert "egional" not in text and "Structural" not in text


def test_marker_shape_unchanged():
    markers = aggregator._derive_map_markers(70.0, [], _Weather(), {})
    assert set(markers[0]) == {"name", "lat", "lon", "score", "description"}
