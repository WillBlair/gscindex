"""
Port Analyst Module
====================
Uses Gemini AI to generate supply chain status summaries for each major port.
Cached for 12 hours (twice-daily updates) to minimize API costs.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import google.generativeai as genai
from dotenv import load_dotenv

from data.cache import get_cached, set_cached
from data.ports_data import MAJOR_PORTS

load_dotenv()
logger = logging.getLogger(__name__)

# Configure Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# Cache TTL: 24 hours = 86400 seconds (reduced API usage)
CACHE_TTL = 86400
CACHE_KEY = "ai_port_summaries"

GENERATION_CONFIG = {
    "temperature": 0.7,  # Higher for more varied, specific responses
    "top_p": 0.9,
    "response_mime_type": "application/json",
}

SYSTEM_PROMPT = """You are a senior supply chain intelligence analyst providing LIVE OPERATIONAL BRIEFINGS for major global shipping ports.

CRITICAL REQUIREMENTS:
1. EVERY port MUST have a UNIQUE summary - no duplicate responses allowed
2. Include SPECIFIC details like: vessel queue counts, container dwell times, gate move volumes, or berth utilizations
3. Mention REGIONAL factors: weather impacts, labor conditions, customs processing, or trade policy effects
4. Reference ACTUAL trade lanes and cargo types relevant to each port's specialty

For each port, provide a 2-3 sentence intelligence briefing covering:
- Current throughput vs normal capacity (use percentages or vessel counts)
- Active disruptions OR specific operational conditions
- Regional supply chain context (trade partners, dominant cargo types)

NEVER use generic phrases like "Normal operations reported" or "No significant delays."
Each port has unique characteristics - highlight them.

Examples of GOOD responses:
{
    "Rotterdam": "Throughput at 94% capacity with 23 vessels at anchor. Container terminals seeing 6-hour average berth wait times. European inland rail connections operating at peak efficiency.",
    "Shanghai": "Export volumes up 12% week-over-week ahead of Lunar New Year. Yangshan terminal experiencing 18-hour truck queues. Trans-Pacific rates holding steady at $2,100/FEU.",
    "Singapore": "Malacca Strait transits running smoothly with 847 vessels processed this week. Bunker fuel availability tight following refinery maintenance. PSA terminals at 89% utilization."
}

Return a JSON object with port names as exact keys matching the input list.
"""



def generate_port_summaries() -> dict[str, str]:
    """Generate AI-powered summaries for all major ports.
    
    Returns
    -------
    dict[str, str]
        Mapping of port name → AI-generated summary.
        Falls back to generic message if API fails.
    """
    # Check cache first
    cached = get_cached(CACHE_KEY, ttl=CACHE_TTL)
    if cached:
        logger.info("Using cached port summaries (updated %s)", cached.get("_updated", "unknown"))
        return cached.get("summaries", {})
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. Using fallback summaries.")
        return _get_fallback_summaries()
    
    # Build port list
    port_names = [name for name, _, _, _, _ in MAJOR_PORTS]
    
    logger.info("Generating AI summaries for %d ports...", len(port_names))
    
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config=GENERATION_CONFIG,
            system_instruction=SYSTEM_PROMPT
        )
        
        prompt = f"""Analyze the current supply chain status for these major shipping ports:

{chr(10).join(f"- {name}" for name in port_names)}

Provide a status summary for each port."""

        response = model.generate_content(prompt)
        summaries = json.loads(response.text)
        
        # Cache the result
        set_cached(CACHE_KEY, {
            "summaries": summaries,
            "_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        
        logger.info("Successfully generated and cached %d port summaries", len(summaries))
        return summaries
        
    except Exception as e:
        logger.error("Gemini port analysis failed: %s", e)
        return _get_fallback_summaries()


def _get_fallback_summaries() -> dict[str, str]:
    """Return empty dict to trigger fallback to global context display."""
    return {}
