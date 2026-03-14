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
CACHE_KEY = "ai_port_summaries_v2"

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



def generate_port_summaries() -> dict[str, dict]:
    """Generate AI-powered summaries for all major ports.
    
    Returns
    -------
    dict[str, dict]
        Mapping of port name → {"summary": str, "disruption_penalty": float}
        Falls back to empty dict if API fails.
    """
    # Check cache first
    cached = get_cached(CACHE_KEY, ttl=CACHE_TTL)
    if cached:
        logger.info("Using cached port summaries (updated %s)", cached.get("_updated", "unknown"))
        return cached.get("summaries", {})
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. Using fallback summaries.")
        return {}
    
    # 1. Gather context: get top 100 recent news articles (grounding AI in reality)
    from data.rss_fetcher import fetch_rss_articles
    recent_news = fetch_rss_articles(max_items=100)
    
    news_context = "RECENT SUPPLY CHAIN NEWS:\n\n"
    for art in recent_news:
        news_context += f"- {art.get('title', '')}: {art.get('description', '')[:200]}\n"
    
    # 2. Build port list
    # FIX: MAJOR_PORTS contains 4 elements per tuple: name, lat, lon, keywords
    port_names = [name for name, _, _, _ in MAJOR_PORTS]
    
    logger.info("Generating AI summaries for %d ports based on live news...", len(port_names))
    
    SYSTEM_PROMPT = """You are a senior supply chain intelligence analyst providing LIVE OPERATIONAL CONTEXT for major global shipping ports.

You will be provided with a list of recent supply chain news headlines and snippets.
Using this news context AND your expert knowledge of current global events, evaluate the status of the requested ports.

CRITICAL REQUIREMENTS:
1. EVERY port MUST have a UNIQUE evaluation - no duplicate responses allowed.
2. For each port, provide a 'summary' (3-4 sentences) detailing exactly what is currently happening there (e.g., vessel queues, specific delays, strike impacts, trade lane volumes, or capacity utilization). Include specific metrics or percentages where possible.
3. For each port, provide a 'disruption_penalty' value from 0.0 to 50.0.
   - 0.0 means the port is operating normally or perfectly.
   - 10.0-20.0 means moderate delays or friction.
   - 30.0-40.0 means severe disruption (major strikes, heavy congestion).
   - 50.0 means catastrophic closure or complete blockade (e.g., trapped ships, war zone, complete port strike).
   
Return a JSON object where the keys are the EXACT port names provided, and the values are objects containing the 'summary' and 'disruption_penalty'.

Example Output Format:
{
    "Rotterdam": {"summary": "Operating at 94% capacity with minor 6-hour berth wait times. Inland rail is clear.", "disruption_penalty": 5.0},
    "Dubai": {"summary": "Severe congestion as ships redirect due to Red Sea attacks. Yard saturation resulting in 4-day delays.", "disruption_penalty": 25.5}
}
"""
    
    try:
        # Grounding with massive news context since SDK search is unavailable
        model = genai.GenerativeModel(
            model_name="gemini-3-flash-preview",
            generation_config=GENERATION_CONFIG,
            system_instruction=SYSTEM_PROMPT
        )
        
        prompt = f"""{news_context}

Analyze the current supply chain status for these 37 major shipping ports:

{chr(10).join(f"- {name}" for name in port_names)}

Provide the JSON status summary and disruption_penalty for each port."""

        response = model.generate_content(prompt)
        summaries = json.loads(response.text)
        
        # Cache the result
        set_cached(CACHE_KEY, {
            "summaries": summaries,
            "_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        
        logger.info("Successfully generated and cached %d dynamic port summaries", len(summaries))
        return summaries
        
    except Exception as e:
        logger.error("Gemini dynamic port analysis failed: %s", e)
        return {}
