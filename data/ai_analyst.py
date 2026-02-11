"""
AI Analyst Module
==================
Uses Google's Gemini API to analyze supply chain news.
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Configure Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
else:
    logger.warning("GEMINI_API_KEY not found. AI analysis will be skipped.")

# Model configuration
GENERATION_CONFIG = {
    "temperature": 0.2,
    "top_p": 0.8,
    "top_k": 40,
    "response_mime_type": "application/json",
}

# Briefing configuration (Plain Text)
BRIEFING_CONFIG = {
    "temperature": 0.4,
    "top_p": 0.8,
    "top_k": 40,
    "response_mime_type": "text/plain",
}

SYSTEM_PROMPT = """
You are an expert global supply chain risk analyst. 
Your job is to analyze news headlines and determine if they are relevant to the GLOBAL COMMERCIAL SUPPLY CHAIN.

Relevance Rules:
- RELEVANT: Port strikes, canal blockages, tariff announcements, major shipping company news, energy price shocks, trade wars, piracy, natural disasters hitting logistics hubs.
- IRRELEVANT: Consumer product launches (e.g., "New Lego set"), retail sales promos ("Free shipping"), stock market daily moves (unless major logistics firm crash), sports, entertainment, local politics without trade impact.

Severity Scoring (-10 to +10):
- -10: Catastrophic (Suez Canal blocked, Global Pandemic)
- -5: Major Disruption (Port strike, widespread tariffs)
- 0: Neutral / Info only
- +5: Positive (Strike resolved, Trade deal signed)
- +10: Miracle (Teleportation invented)
Most news is between -3 and +3.

Return a JSON object with this exact schema:
{
    "analysis": [
        {
            "id": 0,
            "is_relevant": true/false,
            "category": "ports" | "shipping" | "energy" | "tariffs" | "geopolitical" | "weather",
            "severity_score": -10.0 to 10.0,
            "summary": "1-sentence summary of the supply chain impact",
            "reasoning": "Why relevant or irrelevant"
        }
    ],
    "briefing": "• Bullet 1\\n• Bullet 2\\n• Bullet 3"
}

The "briefing" field should be a 3-bullet executive summary of the most important supply chain developments.
Format: Plain text. 3 detailed bullet points starting with '•'.
Constraint: NO JSON. NO MARKDOWN. NO TITLES. Each bullet should be a single, comprehensive sentence.
Focus on: Disruptions, Risks, and Major Market Moves. Be punchy and concise."""


def analyze_news_batch(articles: list[dict]) -> tuple[dict[int, dict], str]:
    """
    Analyze a batch of articles using Gemini Flash.
    
    Returns both analysis AND briefing in a single API call to reduce usage.
    
    Args:
        articles: List of dicts checks {"id": int, "title": str, "description": str}
        
    Returns:
        Tuple of (analysis_map, briefing_text)
        - analysis_map: Dict mapping article_id -> analysis_dict
        - briefing_text: 3-bullet executive summary
    """
    if not api_key:
        return {}, ""
        
    if not articles:
        return {}, ""

    # detailed usage logging
    logger.info(f"Sending {len(articles)} articles to Gemini for analysis + briefing...")

    model = genai.GenerativeModel(
        model_name="gemini-flash-latest",
        generation_config=GENERATION_CONFIG,
        system_instruction=SYSTEM_PROMPT
    )

    # Construct the user prompt
    prompt_lines = ["Analyze these news items:"]
    for art in articles:
        prompt_lines.append(f"ID {art['id']}: {art['title']} - {art['description']}")
    
    prompt = "\n".join(prompt_lines)

    try:
        response = model.generate_content(prompt)
        result = json.loads(response.text)
        
        # Map back to ID
        analysis_map = {}
        for item in result.get("analysis", []):
            analysis_map[item["id"]] = item
        
        # Extract briefing from same response (pre-generated)
        briefing = result.get("briefing", "")
        
        return analysis_map, briefing
        
    except Exception as e:
        logger.error(f"Gemini API Analysis failed: {e}")
        return {}, ""

def generate_briefing(articles: list[dict]) -> str:
    """
    Generate a 3-bullet executive summary of the provided articles.
    """
    if not api_key or not articles:
        return "No briefing available."

    logger.info(f"Generating briefing from {len(articles)} articles...")
    
    model = genai.GenerativeModel(
        model_name="gemini-flash-latest",
        generation_config=BRIEFING_CONFIG,
    )

    prompt_lines = [
        "You are a global supply chain intelligence officer.",
        "Write a 'Daily Situation Report' based ONLY on the following news headlines.",
        "Format: Plain text. 3 detailed bullet points starting with '•'.",
        "Constraint: NO JSON. NO MARKDOWN. NO TITLES. Each bullet should be a single, comprehensive sentence.",
        "Focus on: Disruptions, Risks, and Major Market Moves.",
        "Do NOT mention specific article sources or 'The news says'. Just state the facts.",
        "\nHeadlines:"
    ]
    
    for art in articles[:15]: # Limit context context
        prompt_lines.append(f"- {art['title']}")
        
    prompt = "\n".join(prompt_lines)

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Briefing generation failed: {e}")
        return "Global supply chain outlook is stable. No major disruptions reported at this time."


REPORT_PROMPT = """
You are the Chief Strategy Officer for a global logistics firm.
Write a comprehensive "Daily Supply Chain Intelligence Report" based on the provided news headlines.

Format: GitHub-flavored Markdown. Do NOT use any emojis whatsoever.

Structure:
Start immediately with the first section header (## Critical Disruptions). 
Do NOT include any title, date, or meta-information like "To:", "From:", or "Subject:". 

## Critical Disruptions
[Identify the single most dangerous event (e.g., strikes, canal blocks). If none, say "No critical disruptions detected."]

## Ocean Freight & Port Operations
[Summarize port congestion, shipping rates, and carrier news]

## Air & Land Logistics
[Trucking, rail, and air cargo updates]

## Market & Economic Context
[Trade policy, tariffs, fuel prices, and demand signals]

## Forward Outlook
[What should supply chain managers watch for in the next 48 hours?]

Constraints:
- Use professional, executive tone.
- Be specific (mention company names, ports, percentages).
- Length: Approximately 400-600 words.
- Do NOT use emojis anywhere.
- Do NOT use "The news says" or "Article 1 says". Synthesize the information.
"""

def generate_full_report(articles: list[dict]) -> str:
    """
    Generate a long-form Markdown report from a large batch of articles.
    """
    if not api_key or not articles:
        return "## System Error\nAI service unavailable or no news data found."

    logger.info(f"Generating full report from {len(articles)} articles...")
    
    model = genai.GenerativeModel(
        model_name="gemini-flash-latest",
        generation_config={
            "temperature": 0.3,
            "top_p": 0.8,
            "top_k": 40,
            "response_mime_type": "text/plain",
        },
        system_instruction=REPORT_PROMPT
    )

    from zoneinfo import ZoneInfo
    prompt_lines = [
        "Synthesize these news items into a cohesive daily report:",
        f"Date: {datetime.now(ZoneInfo('America/Denver')).strftime('%Y-%m-%d')}",
        "\nHeadlines:"
    ]
    
    # Use a larger context window for the full report (up to 40-50 headlines)
    for art in articles[:50]:
        prompt_lines.append(f"- {art['title']} ({art['source']}) - {art['description'][:100]}")
        
    prompt = "\n".join(prompt_lines)

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Full report generation failed: {e}")
        return f"## Generation Failed\nError: {e}"
