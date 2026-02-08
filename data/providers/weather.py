"""
Weather Disruptions Provider
==============================
Uses the Open-Meteo API to assess weather conditions at major global
shipping hubs and compute a supply-chain-relevant weather health score.

Open-Meteo is completely free — no API key needed.
Docs: https://open-meteo.com/en/docs

Score Logic
-----------
Weather affects supply chains in ways that go far beyond hurricanes:
    - Moderate wind (20+ km/h) slows crane operations at ports
    - Any precipitation delays loading/unloading and road freight
    - Temperature extremes stress infrastructure and workers
    - Fog and poor visibility delay vessel arrivals

For each of the 8 hubs, we compute a score from 0–100 and average them.
The deductions are CONTINUOUS (not just thresholds), making the score
vary meaningfully from day to day.

Hub deductions:
    Wind:        0 at <10 km/h, up to -25 at >80 km/h (linear ramp)
    Precip:      0 at 0 mm, up to -20 at >25 mm (linear ramp)
    Temp:        0 in 10–30°C, up to -10 at extremes
    WMO code:    0 for clear, up to -15 for thunderstorm/hail
    Visibility:  Not available in free API, derived from WMO fog codes
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from data.cache import get_cached, set_cached
from data.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Major global shipping hubs: (name, lat, lon)
_SHIPPING_HUBS: list[tuple[str, float, float]] = [
    ("Houston",     29.76,  -95.37),
    ("New York",    40.71,  -74.00),
    ("Los Angeles", 33.75, -118.27),
    ("Rotterdam",   51.92,    4.48),
    ("Hamburg",     53.55,    9.99),
    ("Shanghai",    31.23,  121.47),
    ("Singapore",    1.35,  103.82),
    ("Mumbai",      19.08,   72.88),
    ("Busan",       35.10,  129.03),
    ("Dubai",       25.28,   55.30),
    ("Santos",     -23.96,  -46.33),
    ("Durban",     -29.86,   31.02),
    ("Sydney",     -33.86,  151.20),
    ("Colon",        9.36,  -79.90),
]

_CURRENT_URL = "https://api.open-meteo.com/v1/forecast"
_HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"


def _wind_deduction(speed_kmh: float) -> float:
    """Continuous wind penalty. Port cranes stop at ~60 km/h.

    0 km/h  →  0 pts
    10      →  0 pts  (calm)
    20      →  2 pts  (light breeze, minor delays)
    35      →  6 pts  (moderate, affects crane ops)
    50      →  12 pts (strong, crane shutdown likely)
    65      →  18 pts (storm, port closed)
    80+     →  25 pts (hurricane)
    """
    if speed_kmh <= 10:
        return 0.0
    return min(25.0, (speed_kmh - 10) * 25 / 70)


def _precip_deduction(mm: float) -> float:
    """Continuous precipitation penalty. Even light rain slows port ops.

    0 mm  →  0 pts
    2 mm  →  2 pts  (light drizzle, minor impact)
    10 mm →  8 pts  (steady rain, significant delays)
    25 mm →  16 pts (heavy rain, operations paused)
    50+ mm → 20 pts (severe flooding risk)
    """
    if mm <= 0:
        return 0.0
    return min(20.0, mm * 20 / 50)


def _temp_deduction(temp_c: float) -> float:
    """Temperature penalty — extremes in either direction are disruptive.

    10–30°C →  0 pts  (comfortable operating range)
    0°C/35°C → 3 pts  (worker productivity drops, icing/heat risk)
    -10°C/45°C → 8 pts (severe: equipment stress, safety shutdowns)
    Below -20 or above 50 → 10 pts
    """
    if 10 <= temp_c <= 30:
        return 0.0
    if temp_c < 10:
        deviation = 10 - temp_c
    else:
        deviation = temp_c - 30
    return min(10.0, deviation * 10 / 20)


def _wmo_deduction(code: int) -> float:
    """WMO weather code penalty for the condition type itself.

    Codes: https://open-meteo.com/en/docs#weathervariables
    """
    if code in (95, 96, 99):
        return 15.0   # thunderstorm with hail
    if code in (65, 67, 75, 77, 86):
        return 10.0   # heavy rain/snow/freezing rain
    if code in (63, 73, 82, 85):
        return 7.0    # moderate rain/snow/showers
    if code in (61, 71, 80, 81):
        return 4.0    # slight rain/snow/showers
    if code in (51, 53, 55, 56, 57, 66):
        return 3.0    # drizzle / light freezing
    if code in (45, 48):
        return 6.0    # fog / rime fog (visibility issue)
    if code == 3:
        return 1.0    # overcast (minor visibility reduction)
    if code == 2:
        return 0.5    # partly cloudy
    return 0.0        # clear


def _score_hub_current(current: dict) -> float:
    """Score a hub from its current weather conditions (0–100)."""
    score = 100.0

    wmo_code = current.get("weather_code", 0) or 0
    wind = current.get("wind_speed_10m", 0) or 0
    temp = current.get("temperature_2m", 20) or 20
    precip = current.get("precipitation", 0) or 0

    score -= _wmo_deduction(wmo_code)
    score -= _wind_deduction(wind)
    score -= _precip_deduction(precip)
    score -= _temp_deduction(temp)

    return round(max(0.0, min(100.0, score)), 1)


def _score_hub_daily(
    wmo_code: int,
    wind_max: float,
    precip_sum: float,
    temp_max: float,
    temp_min: float,
) -> float:
    """Score a hub for a single historical day (0–100)."""
    score = 100.0

    score -= _wmo_deduction(wmo_code or 0)
    score -= _wind_deduction(wind_max or 0)
    score -= _precip_deduction(precip_sum or 0)

    # Use the more extreme of max/min temp for the deduction
    temp_max = temp_max if temp_max is not None else 25
    temp_min = temp_min if temp_min is not None else 15
    score -= max(_temp_deduction(temp_max), _temp_deduction(temp_min))

    return round(max(0.0, min(100.0, score)), 1)


class WeatherProvider(BaseProvider):
    """Weather Disruptions — no API key needed (Open-Meteo is free)."""

    category = "weather"

    def fetch_current_hub_data(self) -> list[dict]:
        """Fetch current weather for all hubs with full details."""
        cache_key = "weather_hubs_detailed"
        cached = get_cached(cache_key, ttl=1800)
        if cached is not None:
            return cached

        results = []

        for name, lat, lon in _SHIPPING_HUBS:
            try:
                resp = requests.get(
                    _CURRENT_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "weather_code,wind_speed_10m,temperature_2m,precipitation",
                        "timezone": "auto",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                current = resp.json().get("current", {})
                score = _score_hub_current(current)
                
                # Construct reason string
                reasons = []
                wmo = current.get("weather_code", 0)
                wind = current.get("wind_speed_10m", 0)
                precip = current.get("precipitation", 0)
                temp = current.get("temperature_2m", 0)
                
                if _wmo_deduction(wmo) > 0:
                    reasons.append(f"Condition: Code {wmo}")
                if _wind_deduction(wind) > 0:
                    reasons.append(f"Wind: {wind:.0f} km/h")
                if _precip_deduction(precip) > 0:
                    reasons.append(f"Precip: {precip} mm")
                if _temp_deduction(temp) > 0:
                    reasons.append(f"Temp: {temp:.1f}°C")
                
                reason_text = ", ".join(reasons) if reasons else "Clear conditions"

                results.append({
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "score": score,
                    "weather_summary": reason_text
                })
            except Exception as exc:
                logger.warning("Failed to fetch hub weather for %s: %s", name, exc)
                results.append({
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "score": 75.0,
                    "weather_summary": "Data unavailable"
                })

        set_cached(cache_key, results)
        return results

    def fetch_current(self) -> float:
        """Fetch current weather at all hubs and return the average score."""
        cache_key = "weather_current"
        cached = get_cached(cache_key, ttl=1800)  # 30-min cache
        if cached is not None:
            return cached["score"]

        hub_scores: list[float] = []

        for name, lat, lon in _SHIPPING_HUBS:
            try:
                resp = requests.get(
                    _CURRENT_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "weather_code,wind_speed_10m,temperature_2m,precipitation",
                        "timezone": "auto",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                current = resp.json().get("current", {})
                hub_score = _score_hub_current(current)
                hub_scores.append(hub_score)
                logger.info(
                    "Weather at %s: %.1f (WMO=%s wind=%.0f precip=%.1f temp=%.1f)",
                    name, hub_score,
                    current.get("weather_code"),
                    current.get("wind_speed_10m", 0),
                    current.get("precipitation", 0),
                    current.get("temperature_2m", 0),
                )
            except Exception as exc:
                logger.warning("Failed to fetch weather for %s: %s", name, exc)
                hub_scores.append(75.0)

        avg_score = round(float(np.mean(hub_scores)), 1)
        set_cached(cache_key, {"score": avg_score})
        return avg_score

    def fetch_history(self, days: int) -> pd.Series:
        """Fetch historical weather from Open-Meteo, averaged across all hubs."""
        cache_key = f"weather_history_{days}"
        cached = get_cached(cache_key, ttl=3600)
        if cached is not None:
            s = pd.Series(cached["values"], name="weather")
            s.index = pd.DatetimeIndex(cached["dates"])
            return s

        end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        all_hub_series: list[pd.Series] = []

        for name, lat, lon in _SHIPPING_HUBS:
            try:
                resp = requests.get(
                    _HISTORICAL_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "start_date": start_date,
                        "end_date": end_date,
                        "daily": "weather_code,wind_speed_10m_max,precipitation_sum,temperature_2m_max,temperature_2m_min",
                        "timezone": "auto",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                daily = resp.json().get("daily", {})
                dates = daily.get("time", [])
                codes = daily.get("weather_code", [])
                winds = daily.get("wind_speed_10m_max", [])
                precips = daily.get("precipitation_sum", [])
                t_maxes = daily.get("temperature_2m_max", [])
                t_mins = daily.get("temperature_2m_min", [])

                scores = [
                    _score_hub_daily(c, w, p, tmax, tmin)
                    for c, w, p, tmax, tmin
                    in zip(codes, winds, precips, t_maxes, t_mins)
                ]
                s = pd.Series(scores, index=pd.DatetimeIndex(dates))
                all_hub_series.append(s)
                logger.info("Weather history for %s: %d days", name, len(scores))
            except Exception as exc:
                logger.warning("Failed to fetch weather history for %s: %s", name, exc)

        if all_hub_series:
            df = pd.concat(all_hub_series, axis=1)
            avg_scores = df.mean(axis=1).round(1)
        else:
            dates_idx = pd.date_range(start=start_date, end=end_date, freq="D")
            avg_scores = pd.Series(75.0, index=dates_idx)

        result = avg_scores.rename("weather")

        set_cached(cache_key, {
            "dates": [d.isoformat() for d in result.index],
            "values": result.tolist(),
        })

        return result
