"""
Port Congestion Provider
=========================
Uses FRED series ``TSIFRGHT`` (Transportation Services Index: Freight, monthly)
as a proxy for port and freight throughput.

The TSI Freight index measures the volume of freight carried by for-hire
transportation companies. When freight volume drops, it often signals
congestion, capacity issues, or demand shocks.

Score Logic
-----------
Higher freight volume = supply chain is flowing = healthy. Direct normalization:
    - At the 5-year HIGH → score = 100 (freight moving freely)
    - At the 5-year LOW  → score = 0   (freight stalled)

Note: This is a proxy. For real port congestion data, you'd need a
paid API like MarineTraffic, VesselFinder, or project44.

Source: https://fred.stlouisfed.org/series/TSIFRGHT
"""

from __future__ import annotations

import pandas as pd
import requests
import numpy as np
from datetime import datetime

from config import HISTORY_DAYS
from data.providers.base import BaseProvider
from data.providers.geopolitical import fetch_supply_chain_news
from data.providers.fred_client import (
    fetch_fred_series,
    normalize_series_direct,
)


class PortsProvider(BaseProvider):
    """Port Congestion — derived from TSI Freight Index."""

    category = "ports"
    _SERIES_ID = "TSIFRGHT"

    def fetch_current(self) -> tuple[float, dict]:
        # -------------------------------------------------------------------
        # STRATEGY: Composite Port Operations Index
        # -------------------------------------------------------------------
        # User rejected stock prices (MATX). We now use operational realities:
        # 1. Live Weather: Wind/Storms at major Global Hubs (Singapore, Rotterdam, LA).
        # 2. Live News: Sentiment analysis of "port" and "chokepoint" news.
        # 
        # Logic: Bad Weather + Negative News = Operations Stalled (Low Score)
        # -------------------------------------------------------------------
        
        # --- 1. Live Weather at Major Hubs ---
        # Singapore (Asia), Rotterdam (Europe), Los Angeles (US)
        hubs = [
            ("Singapore", 1.35, 103.82),
            ("Rotterdam", 51.92, 4.48),
            ("Los Angeles", 33.75, -118.27)
        ]
        
        weather_scores = []
        weather_details = []
        
        try:
            # Loop is safer for small number of requests
            for name, lat, lon in hubs:
                resp = requests.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "wind_speed_10m,precipitation",
                        "timezone": "auto"
                    },
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json().get("current", {})
                    wind = data.get("wind_speed_10m", 0)
                    precip = data.get("precipitation", 0)
                    
                    # Simple Deduction: Wind > 20km/h is bad, Rain > 5mm is bad
                    deduction = 0
                    if wind > 20: deduction += (wind - 20) * 1.5
                    if precip > 5: deduction += (precip - 5) * 2.0
                    
                    score = max(0.0, 100.0 - deduction)
                    weather_scores.append(score)
                    if score < 90:
                        weather_details.append(f"{name}: Wind {wind:.0f}kph")
                else:
                    weather_scores.append(80.0) # Assume okay if API fails
                    
            avg_weather_score = float(np.mean(weather_scores)) if weather_scores else 80.0
            
        except Exception as e:
            print(f"Port Weather Error: {e}")
            avg_weather_score = 80.0
            weather_details.append("Weather API Unavailable")

        # --- 2. Live News Sentiment ---
        # Fetch shared news cache
        try:
            geo_score, alerts, _ = fetch_supply_chain_news()
            
            # Filter specifically for PORTS and CHOKEPOINTS
            port_alerts = [
                a for a in alerts 
                if a.get("category") in ["ports", "chokepoint"]
            ]
            
            # Default to perfect score if no news, then deduct for negative news
            news_score = 100.0
            news_impacts = []
            
            for alert in port_alerts:
                # Severity: high (-8), medium (-4), low (-2)
                sev = alert.get("severity", "low")
                deduction = 8.0 if sev == "high" else 4.0 if sev == "medium" else 2.0
                news_score -= deduction
                if sev in ["high", "medium"]:
                    news_impacts.append(f"Alert: {alert.get('title')[:30]}...")
            
            news_score = max(0.0, news_score)
            
        except Exception as e:
            print(f"Port News Error: {e}")
            news_score = 80.0
            
        # --- Composite Score ---
        # 50% Weather (Operations), 50% News (Strikes/Congestion)
        final_score = (avg_weather_score * 0.5) + (news_score * 0.5)
        final_score = round(final_score, 1)
        
        # Description
        desc_parts = [
            f"Global Weather Score: {avg_weather_score:.0f}/100"
        ]
        if weather_details:
            desc_parts.append(f"Issues: {', '.join(weather_details)}")
        else:
            desc_parts.append("Major hubs operational")
        
        desc_parts.append(f"News Sentiment Score: {news_score:.0f}/100")
        if news_impacts:
             desc_parts.append(f"News: {', '.join(news_impacts[:2])}")
             
        description = ". ".join(desc_parts) + "."

        return final_score, {
            "source": "Live Weather & News",
            "raw_value": f"Wx {avg_weather_score:.0f} / News {news_score:.0f}",
            "raw_label": "Composite (Wx & News)",
            "description": description,
            "updated": datetime.now().strftime("%H:%M UTC")
        }

    def fetch_history(self, days: int = HISTORY_DAYS) -> pd.Series:
        raw = fetch_fred_series(self._SERIES_ID)
        scores = normalize_series_direct(raw)
        # TSI is monthly — forward-fill to daily for dashboard charts
        daily = scores.resample("D").ffill()
        return daily.tail(days).rename("ports")
