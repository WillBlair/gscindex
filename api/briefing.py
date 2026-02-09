"""
On-Demand Briefing API Endpoint
================================
Generates AI briefing only when user requests it, reducing automatic API usage.
"""
from __future__ import annotations

import json
import logging
from flask import jsonify

from data.ai_analyst import generate_briefing
from data.cache import get_cached

logger = logging.getLogger(__name__)

# Cache key used by geopolitical provider for alerts
ALERTS_CACHE_KEY = "newsapi_briefing_v4"


def get_on_demand_briefing() -> dict:
    """Generate briefing from cached alerts without making a new API call for news.
    
    Returns
    -------
    dict
        {"briefing": str, "success": bool, "error": str | None}
    """
    # Try to get existing alerts from cache
    cached = get_cached(ALERTS_CACHE_KEY, ttl=86400)  # Accept up to 24h old cache
    
    if not cached or not cached.get("alerts"):
        return {
            "success": False,
            "briefing": "",
            "error": "No cached news data available. Please wait for the next data refresh."
        }
    
    alerts = cached.get("alerts", [])
    
    # Check if we already have a briefing in the cached data
    if cached.get("briefing"):
        logger.info("Returning cached briefing")
        return {
            "success": True,
            "briefing": cached["briefing"],
            "error": None
        }
    
    # Generate new briefing from cached alerts (requires API call)
    logger.info(f"Generating on-demand briefing from {len(alerts)} cached alerts...")
    
    try:
        briefing_text = generate_briefing(alerts[:10])
        return {
            "success": True,
            "briefing": briefing_text,
            "error": None
        }
    except Exception as e:
        logger.error(f"On-demand briefing generation failed: {e}")
        return {
            "success": False,
            "briefing": "",
            "error": str(e)
        }
