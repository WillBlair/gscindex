"""
On-Demand Briefing API Endpoint
================================
Generates AI briefing only when user requests it, reducing automatic API usage.
"""
from __future__ import annotations

import json
import logging
from flask import jsonify

from config import GEMINI_CACHE_TTL_SECONDS, NEWS_BRIEFING_CACHE_KEY
from data.ai_analyst import generate_briefing
from data.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

ALERTS_CACHE_KEY = NEWS_BRIEFING_CACHE_KEY
_GEMINI_OD_BRIEFING_KEY = "gemini_on_demand_briefing_v1"


def get_on_demand_briefing() -> dict:
    """Generate briefing from cached alerts without making a new API call for news.
    
    Returns
    -------
    dict
        {"briefing": str, "success": bool, "error": str | None}
    """
    # Try to get existing alerts from cache
    cached = get_cached(ALERTS_CACHE_KEY, ttl=GEMINI_CACHE_TTL_SECONDS)
    
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
    
    od_cached = get_cached(_GEMINI_OD_BRIEFING_KEY, ttl=GEMINI_CACHE_TTL_SECONDS)
    if od_cached and od_cached.get("briefing"):
        logger.info("Returning cached on-demand Gemini briefing")
        return {
            "success": True,
            "briefing": od_cached["briefing"],
            "error": None,
        }

    logger.info("Generating on-demand briefing from %d cached alerts (Gemini)...", len(alerts))
    try:
        briefing_text = generate_briefing(alerts[:10])
        set_cached(_GEMINI_OD_BRIEFING_KEY, {"briefing": briefing_text})
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
