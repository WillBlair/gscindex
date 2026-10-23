"""
Weather Scoring Unit Tests
===========================
Verifies the deduction functions produce sane scores across the full
range of weather conditions.  Every function is tested with:
    - No-deduction boundary (calm/clear/comfortable)
    - Moderate conditions (typical bad-weather day)
    - Extreme conditions (hurricane / flood / blizzard)
    - Max-cap enforcement

Run with: python -m pytest tests/test_weather_scoring.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

# Allow running from repo root or tests/ dir
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.providers.weather import (
    WeatherProvider,
    _precip_deduction,
    _score_hub_current,
    _score_hub_daily,
    _temp_deduction,
    _wind_deduction,
    _wmo_deduction,
)


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------

def test_wind_calm():
    """Wind <= 10 km/h should never penalize."""
    assert _wind_deduction(0) == 0.0
    assert _wind_deduction(10) == 0.0


def test_wind_moderate():
    """Wind at 40 km/h — crane delays, but not a shutdown."""
    d = _wind_deduction(40)
    assert 10 < d < 20, f"Expected 10–20 pt deduction, got {d}"


def test_wind_hurricane():
    """Wind >= 80 km/h — hard cap at 30."""
    assert _wind_deduction(80) == 30.0
    assert _wind_deduction(200) == 30.0


# ---------------------------------------------------------------------------
# Precipitation
# ---------------------------------------------------------------------------

def test_precip_dry():
    assert _precip_deduction(0) == 0.0


def test_precip_light_rain():
    """10 mm of rain — moderate, not catastrophic."""
    d = _precip_deduction(10)
    assert 3 < d < 8, f"Expected 3–8 pt deduction, got {d}"


def test_weather_precip_uses_daily_total():
    """30 mm over the day: 25 x 30 / 50 = 15 pts, and the hub score takes the daily total."""
    assert _precip_deduction(30) == 15.0
    assert _score_hub_current({"temperature_2m": 20}, precip_mm=30) == 85.0


def test_weather_request_asks_for_daily_precipitation_and_gusts():
    url = WeatherProvider._build_open_meteo_url("29.76,51.92", "-95.37,4.48")
    assert "daily=precipitation_sum" in url and "forecast_days=1" in url
    assert "wind_gusts_10m" in url
    # The 15-minute precipitation and mean wind are not requested.
    current = url.split("current=")[1].split("&")[0].split(",")
    assert "precipitation" not in current and "wind_speed_10m" not in current


def test_weather_wind_deduction_uses_gusts():
    gusty = _score_hub_current({"wind_gusts_10m": 80, "temperature_2m": 20})
    calm = _score_hub_current({"wind_gusts_10m": 5, "temperature_2m": 20})
    assert (calm, gusty) == (100.0, 70.0)
    # The mean wind field is no longer read.
    assert _score_hub_current({"wind_speed_10m": 80, "temperature_2m": 20}) == 100.0


def test_weather_batch_scores_from_daily_precip_and_gusts():
    provider = WeatherProvider()
    location = {
        "current": {"weather_code": 0, "wind_gusts_10m": 45.0, "temperature_2m": 20.0},
        "daily": {"time": ["2026-10-22"], "precipitation_sum": [30.0]},
    }
    with mock.patch("data.providers.weather.get_cached", return_value=None), \
         mock.patch("data.providers.weather.set_cached") as save, \
         mock.patch.object(provider, "_fetch_chunk", return_value=[location]):
        batch = provider.fetch_batch_port_weather([("Houston", 29.76, -95.37)])
    expected = 100.0 - _wind_deduction(45.0) - 15.0
    assert batch["Houston"]["score"] == round(expected, 1)
    assert batch["Houston"]["precip"] == 30.0 and batch["Houston"]["wind"] == 45.0
    assert save.call_args.args[0] == "weather_batch_ports_v3"


def test_precip_flood():
    """50+ mm — hard cap at 25."""
    assert _precip_deduction(50) == 25.0
    assert _precip_deduction(200) == 25.0


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

def test_temp_comfortable():
    """10–30°C is the comfort zone — no penalty."""
    assert _temp_deduction(10) == 0.0
    assert _temp_deduction(20) == 0.0
    assert _temp_deduction(30) == 0.0


def test_temp_cold():
    """0°C — icing risk but still operational."""
    d = _temp_deduction(0)
    assert 3 < d < 10, f"Expected 3–10 pt deduction, got {d}"


def test_temp_extreme():
    """Below -20°C or above 50°C — hard cap at 15."""
    assert _temp_deduction(-30) == 15.0
    assert _temp_deduction(60) == 15.0


# ---------------------------------------------------------------------------
# WMO Weather Codes
# ---------------------------------------------------------------------------

def test_wmo_clear():
    assert _wmo_deduction(0) == 0.0
    assert _wmo_deduction(1) == 0.0


def test_wmo_fog():
    """Fog is a major port hazard — should have significant deduction."""
    assert _wmo_deduction(45) == 15.0
    assert _wmo_deduction(48) == 15.0


def test_wmo_thunderstorm():
    """Thunderstorm with hail — max WMO deduction."""
    assert _wmo_deduction(95) == 30.0
    assert _wmo_deduction(96) == 30.0
    assert _wmo_deduction(99) == 30.0


# ---------------------------------------------------------------------------
# Combined scoring
# ---------------------------------------------------------------------------

def test_total_max_deduction_equals_100():
    """The theoretical worst case (all maxes) should yield score 0."""
    score = 100.0
    score -= _wind_deduction(200)    # 30
    score -= _precip_deduction(200)  # 25
    score -= _temp_deduction(-40)    # 15
    score -= _wmo_deduction(99)      # 30
    assert score == 0.0, f"Max deduction should zero out the score, got {score}"


def test_perfect_day():
    """Clear, calm, comfortable — should score 100."""
    current = {
        "weather_code": 0,
        "wind_gusts_10m": 5,
        "temperature_2m": 22,
    }
    assert _score_hub_current(current, precip_mm=0) == 100.0


def test_moderate_bad_weather():
    """Moderate wind + light rain + slightly cold + overcast → ~77 (Stable)."""
    current = {
        "weather_code": 3,     # overcast (-2)
        "wind_gusts_10m": 30,  # moderate gusts (-8.6)
        "temperature_2m": 5,   # slightly cold (-3.75)
    }
    score = _score_hub_current(current, precip_mm=5)  # light rain (-2.5)
    assert 70 < score < 90, f"Moderate bad weather should be Stable, got {score}"


def test_severe_storm():
    """Thunderstorm + strong wind + heavy rain + freezing → Critical."""
    current = {
        "weather_code": 95,    # thunderstorm (-30)
        "wind_gusts_10m": 70,  # storm (-25.7)
        "temperature_2m": -5,  # freezing (-11.25)
    }
    score = _score_hub_current(current, precip_mm=40)  # heavy (-20)
    assert score < 20, f"Severe storm should be Critical, got {score}"


def test_daily_scoring():
    """Daily scoring uses worst-case temp correctly."""
    score = _score_hub_daily(
        wmo_code=0,
        wind_max=15,
        precip_sum=2,
        temp_max=35,   # slightly warm → small deduction
        temp_min=8,    # slightly cool → small deduction
    )
    # Should pick the worse temp (8°C → 1.5 pts) over 35°C (3.75 pts)
    # Actually 35°C is worse: deviation=5, deduction=3.75
    # 8°C: deviation=2, deduction=1.5
    # So it picks 3.75
    assert 85 < score < 98, f"Mild bad day should score in the 90s, got {score}"
