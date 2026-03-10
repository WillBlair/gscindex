"""
Weather Disruptions Provider
==============================
Uses the Open-Meteo API to assess weather conditions at ALL major global
shipping ports (derived from ``ports_data.MAJOR_PORTS``) and compute a
supply-chain-relevant weather health score.

Open-Meteo is completely free — no API key needed.
Docs: https://open-meteo.com/en/docs

Score Logic
-----------
Weather affects supply chains in ways that go far beyond hurricanes:
    - Moderate wind (20+ km/h) slows crane operations at ports
    - Any precipitation delays loading/unloading and road freight
    - Temperature extremes stress infrastructure and workers
    - Fog and poor visibility delay vessel arrivals

For each port, we compute a score from 0–100 and average them.
The deductions are CONTINUOUS (not just thresholds), making the score
vary meaningfully from day to day.

Deduction budget (max total = 100, matching the 0–100 scale):
    Wind:        0 at <10 km/h, up to -30 at ≥80 km/h (linear ramp)
    Precip:      0 at 0 mm, up to -25 at ≥50 mm (linear ramp)
    Temp:        0 in 10–30°C, up to -15 at extremes
    WMO code:    0 for clear, up to -30 for thunderstorm/hail
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from data.cache import get_cached, set_cached
from data.ports_data import MAJOR_PORTS
from data.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Derive (name, lat, lon) tuples from the canonical port list.
# Every port in MAJOR_PORTS gets real weather — no separate hub list.
_SHIPPING_HUBS: list[tuple[str, float, float]] = [
    (name, lat, lon) for name, lat, lon, _, _ in MAJOR_PORTS
]

_CURRENT_URL = "https://api.open-meteo.com/v1/forecast"
_HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"


def _wind_deduction(speed_kmh: float) -> float:
    """Continuous wind penalty. Port cranes stop at ~60 km/h.

    0 km/h  →  0 pts
    10      →  0 pts  (calm)
    20      →  4 pts  (light breeze, minor delays)
    35      →  11 pts (moderate, affects crane ops)
    50      →  17 pts (strong, crane shutdown likely)
    65      →  24 pts (storm, port closed)
    80+     →  30 pts (hurricane-force)
    """
    if speed_kmh <= 10:
        return 0.0
    return min(30.0, (speed_kmh - 10) * 30 / 70)


def _precip_deduction(mm: float) -> float:
    """Continuous precipitation penalty. Even light rain slows port ops.

    0 mm  →  0 pts
    2 mm  →  1 pts  (light drizzle, minor impact)
    10 mm →  5 pts  (steady rain, moderate delays)
    25 mm → 13 pts  (heavy rain, operations paused)
    50+ mm → 25 pts (severe flooding risk)
    """
    if mm <= 0:
        return 0.0
    return min(25.0, mm * 25 / 50)


def _temp_deduction(temp_c: float) -> float:
    """Temperature penalty — extremes in either direction are disruptive.

    10–30°C  →  0 pts (comfortable operating range)
    0°C/35°C →  4 pts (worker productivity drops, icing/heat risk)
    -10°C/45°C → 11 pts (severe: equipment stress, safety shutdowns)
    Below -20 or above 50 → 15 pts
    """
    if 10 <= temp_c <= 30:
        return 0.0
    if temp_c < 10:
        deviation = 10 - temp_c
    else:
        deviation = temp_c - 30
    return min(15.0, deviation * 15 / 20)


def _wmo_deduction(code: int) -> float:
    """WMO weather code penalty for the condition type itself.

    Codes: https://open-meteo.com/en/docs#weathervariables

    Max deduction: 30 pts (severe thunderstorm).
    Total budget across all four deduction functions: 30+25+15+30 = 100.
    """
    if code in (95, 96, 99):
        return 30.0   # thunderstorm with hail — port shutdown
    if code in (65, 67, 75, 77, 86):
        return 20.0   # heavy rain/snow/freezing rain
    if code in (63, 73, 82, 85):
        return 12.0   # moderate rain/snow/showers
    if code in (61, 71, 80, 81):
        return 6.0    # slight rain/snow/showers
    if code in (51, 53, 55, 56, 57, 66):
        return 4.0    # drizzle / light freezing
    if code in (45, 48):
        return 15.0   # fog / rime fog (major visibility issue)
    if code == 3:
        return 2.0    # overcast (minor visibility reduction)
    if code == 2:
        return 1.0    # partly cloudy
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


# WMO weather code → human-readable condition description
# Reference: https://open-meteo.com/en/docs#weathervariables
_WMO_DESCRIPTIONS: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Light snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains",
    80: "Light showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
}


class WeatherProvider(BaseProvider):
    """Weather Disruptions — no API key needed (Open-Meteo is free)."""

    category = "weather"

    def fetch_batch_port_weather(
        self,
        ports: list[tuple[str, float, float]],
    ) -> dict[str, dict]:
        """Fetch current weather for an arbitrary list of ports in ONE call.

        Open-Meteo accepts comma-separated lat/lon values and returns an
        array of results — one per location.  This lets us get real,
        location-specific weather for all 37 map ports with a single HTTP
        request instead of 37.

        Parameters
        ----------
        ports : list[tuple[str, float, float]]
            ``(name, latitude, longitude)`` for every port to plot.

        Returns
        -------
        dict[str, dict]
            Mapping of port name → ``{"score", "summary", "temp", "wind",
            "precip", "wmo_code"}``.  Cached for 30 minutes.
        """
        cache_key = "weather_batch_ports"
        cached = get_cached(cache_key, ttl=1800)
        if cached is not None:
            return cached

        lats = ",".join(str(lat) for _, lat, _ in ports)
        lons = ",".join(str(lon) for _, _, lon in ports)

        # Open-Meteo can be slow with 37 locations; try batch first, then
        # fall back to smaller chunks if it times out.
        try:
            resp = requests.get(
                _CURRENT_URL,
                params={
                    "latitude": lats,
                    "longitude": lons,
                    "current": "weather_code,wind_speed_10m,temperature_2m,precipitation",
                    "timezone": "auto",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Batch weather fetch failed (%s), retrying in chunks...", exc)
            # Retry in chunks of 10 to avoid timeout/payload issues
            data = []
            chunk_size = 10
            for ci in range(0, len(ports), chunk_size):
                chunk = ports[ci:ci + chunk_size]
                chunk_lats = ",".join(str(lat) for _, lat, _ in chunk)
                chunk_lons = ",".join(str(lon) for _, _, lon in chunk)
                try:
                    resp = requests.get(
                        _CURRENT_URL,
                        params={
                            "latitude": chunk_lats,
                            "longitude": chunk_lons,
                            "current": "weather_code,wind_speed_10m,temperature_2m,precipitation",
                            "timezone": "auto",
                        },
                        timeout=15,
                    )
                    resp.raise_for_status()
                    chunk_data = resp.json()
                    if isinstance(chunk_data, list):
                        data.extend(chunk_data)
                    else:
                        data.append(chunk_data)
                except Exception as chunk_exc:
                    logger.error("Chunk weather fetch failed for ports %d-%d: %s", ci, ci + len(chunk), chunk_exc)
                    # Fill this chunk with None so indexing stays aligned
                    data.extend([None] * len(chunk))

            if not any(d is not None for d in data):
                logger.error("All weather chunks failed — returning fallback")
                fallback: dict[str, dict] = {}
                for name, _lat, _lon in ports:
                    fallback[name] = {
                        "score": 75.0,
                        "summary": "Weather data temporarily unavailable",
                        "temp": None,
                        "wind": None,
                        "precip": None,
                        "wmo_code": None,
                    }
                return fallback

        # Open-Meteo returns a list when given multiple locations
        results_list = data if isinstance(data, list) else [data]

        result: dict[str, dict] = {}
        for i, (name, _lat, _lon) in enumerate(ports):
            if i >= len(results_list) or results_list[i] is None:
                result[name] = {
                    "score": 75.0, "summary": "No data", "temp": None,
                    "wind": None, "precip": None, "wmo_code": None,
                }
                continue

            current = results_list[i].get("current", {})
            score = _score_hub_current(current)

            wmo = current.get("weather_code", 0) or 0
            wind = current.get("wind_speed_10m", 0) or 0
            precip = current.get("precipitation", 0) or 0
            temp = current.get("temperature_2m", 20) or 20

            # Build human-readable summary from real conditions
            wmo_desc = _WMO_DESCRIPTIONS.get(wmo, f"Code {wmo}")
            parts: list[str] = [f"{temp:.0f}°C", wmo_desc]
            if wind > 10:
                parts.append(f"Wind {wind:.0f} km/h")
            if precip > 0:
                parts.append(f"Precip {precip:.1f} mm")

            result[name] = {
                "score": score,
                "summary": ", ".join(parts),
                "temp": round(temp, 1),
                "wind": round(wind, 1),
                "precip": round(precip, 1),
                "wmo_code": wmo,
            }

            logger.info(
                "Batch weather %s: %.1f (%s)",
                name, score, result[name]["summary"],
            )

        set_cached(cache_key, result)
        return result

    def fetch_current_hub_data(self) -> list[dict]:
        """Fetch current weather for all hubs with full details.

        Uses the batched ``fetch_batch_port_weather()`` call under the
        hood — one HTTP request for all ports, not N serial calls.
        """
        cache_key = "weather_hubs_detailed"
        cached = get_cached(cache_key, ttl=1800)
        if cached is not None:
            return cached

        # Single batch call for all ports
        batch = self.fetch_batch_port_weather(_SHIPPING_HUBS)

        results: list[dict] = []
        for name, lat, lon in _SHIPPING_HUBS:
            wx = batch.get(name, {})
            score = wx.get("score", 75.0)

            # Build human-readable reason string from weather details
            reasons: list[str] = []
            wmo = wx.get("wmo_code") or 0
            wind = wx.get("wind") or 0
            precip = wx.get("precip") or 0
            temp = wx.get("temp")

            wmo_desc = _WMO_DESCRIPTIONS.get(wmo, f"Code {wmo}")
            if _wmo_deduction(wmo) > 0:
                reasons.append(wmo_desc)
            if _wind_deduction(wind) > 0:
                reasons.append(f"Wind {wind:.0f} km/h")
            if _precip_deduction(precip) > 0:
                reasons.append(f"Precip {precip:.1f} mm")
            if temp is not None and _temp_deduction(temp) > 0:
                reasons.append(f"Temp {temp:.1f}°C")

            reason_text = ", ".join(reasons) if reasons else "Clear conditions"

            results.append({
                "name": name,
                "lat": lat,
                "lon": lon,
                "score": score,
                "weather_summary": reason_text,
            })

        set_cached(cache_key, results)
        return results

    def fetch_current(self) -> tuple[float, dict]:
        """Fetch current weather at all hubs and return the average score.

        Uses the batched ``fetch_batch_port_weather()`` call — one HTTP
        request instead of N serial calls.
        """
        cache_key = "weather_current_v3"  # Bumped after deduction rebalance
        cached = get_cached(cache_key, ttl=1800)  # 30-min cache
        if cached is not None:
            if "metadata" in cached:
                return cached["score"], cached["metadata"]
            return cached["score"], {}

        # Single batch call for all ports
        batch = self.fetch_batch_port_weather(_SHIPPING_HUBS)

        hub_scores: list[float] = []
        for name, _lat, _lon in _SHIPPING_HUBS:
            wx = batch.get(name, {})
            hub_scores.append(wx.get("score", 75.0))

        avg_score = round(float(np.mean(hub_scores)), 1)

        bad_weather_count = sum(1 for s in hub_scores if s < 80)

        metadata = {
            "source": "Open-Meteo API",
            "raw_value": f"{len(_SHIPPING_HUBS)} Major Ports",
            "raw_label": "Global Port Weather",
            "description": (
                f"Real-time weather analysis of {len(_SHIPPING_HUBS)} major shipping ports. "
                f"Currently tracking {bad_weather_count} locations with suboptimal operating conditions."
            ),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        set_cached(cache_key, {"score": avg_score, "metadata": metadata})
        return avg_score, metadata

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
