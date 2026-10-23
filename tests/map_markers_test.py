"""Port map: composite + local weather minus the AI port penalty; no headlines; word-boundary port keywords."""

import re

import pytest

from data import aggregator
from data.ports_data import MAJOR_PORTS, keyword_in_text


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


def _ports_matching(title):
    return [name for name, _lat, _lon, kws in MAJOR_PORTS if any(keyword_in_text(k, title.lower()) for k in kws)]


def test_oman_does_not_match_woman():
    assert _ports_matching("Woman arrested after dock protest") == []
    assert _ports_matching("Romania ferry strike") == []
    assert _ports_matching("Oman port closes after storm") == ["Dubai"]


def test_hamburger_does_not_match_hamburg():
    assert _ports_matching("Hamburger chain recalls beef") == []
    assert "Hamburg" in _ports_matching("Hamburg port strike widens")


def test_plural_and_generic_keywords_still_match():
    assert "Houston" in _ports_matching("Gulf coast ports shut for hurricane")
    assert "Dubai" in _ports_matching("Gulf states weigh Hormuz closure")


def test_port_authority_keyword_is_not_generic():
    assert "New York" not in _ports_matching("Port Authority of Los Angeles reports delays")


def test_casablanca_matches_no_port():
    assert "Casablanca" not in [name for name, *_ in MAJOR_PORTS]
    assert _ports_matching("Casablanca port congestion worsens") == []


def test_keywords_do_not_contain_unbounded_short_tokens():
    for name, _lat, _lon, keywords in MAJOR_PORTS:
        for kw in keywords:
            assert len(kw) >= 4, (name, kw)
            assert kw == kw.lower() and re.fullmatch(r"[a-z ]+", kw), (name, kw)


def test_port_score_formula():
    # composite 50, weather 100, AI penalty 10 -> 0.6*50 + 0.4*100 - 10 = 60
    markers = aggregator._derive_map_markers(
        50.0, _Weather({"Rotterdam": 100.0}),
        {"Rotterdam": {"summary": "Quiet.", "disruption_penalty": 10.0}})
    assert _marker(markers, "Rotterdam")["score"] == 60.0


def test_headlines_never_penalize_or_appear_in_the_hover():
    # Only Claude's port summary sets a port penalty; matched headlines do not.
    markers = aggregator._derive_map_markers(
        80.0, _Weather({"Houston": 80.0}),
        {"Houston": {"summary": "Refinery fire nearby.", "disruption_penalty": 5.0}})
    marker = _marker(markers, "Houston")
    assert marker["score"] == 75.0  # 0.6*80 + 0.4*80 - 5
    assert "[HIGH]" not in marker["description"] and "[MEDIUM]" not in marker["description"]
    assert "(news)" not in marker["description"]


def test_no_ai_summary_means_no_penalty():
    markers = aggregator._derive_map_markers(70.0, _Weather(), {})
    assert _marker(markers, "Houston")["score"] == 70.0
    assert "Penalty" not in _marker(markers, "Houston")["description"]


def test_composite_alone_without_weather():
    markers = aggregator._derive_map_markers(72.0, _Weather({"Rotterdam": 90.0}), {})
    assert _marker(markers, "Rotterdam")["score"] == pytest.approx(0.6 * 72 + 0.4 * 90, abs=0.05)
    assert _marker(markers, "Hamburg")["score"] == 72.0


def test_no_composite_uses_weather_alone_and_skips_ports_without_inputs():
    markers = aggregator._derive_map_markers(None, _Weather({"Rotterdam": 90.0}), {})
    assert [m["name"] for m in markers] == ["Rotterdam"]
    assert markers[0]["score"] == 90.0


def test_no_composite_no_weather_gives_no_markers():
    assert aggregator._derive_map_markers(None, _Weather(), {}) == []


def test_weather_failure_falls_back_to_composite():
    markers = aggregator._derive_map_markers(66.0, _Weather(error=RuntimeError("down")), {})
    assert len(markers) == len(MAJOR_PORTS)
    assert all(m["score"] == 66.0 for m in markers)


def test_hover_lists_composite_weather_and_penalty_source():
    markers = aggregator._derive_map_markers(
        50.0, _Weather({"Rotterdam": 100.0}),
        {"Rotterdam": {"summary": "Lock closure.", "disruption_penalty": 10.0}})
    text = _marker(markers, "Rotterdam")["description"]
    assert "Composite" in text and "50" in text
    assert "Rotterdam weather" in text
    assert "<b>Penalty:</b> -10.0 pts (AI port summary)" in text
    assert "egional" not in text and "Structural" not in text


def test_marker_shape_unchanged():
    markers = aggregator._derive_map_markers(70.0, _Weather(), {})
    assert set(markers[0]) == {"name", "lat", "lon", "score", "description"}
