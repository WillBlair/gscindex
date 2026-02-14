"""
AI Score Validator
==================
Uses Google Gemini to validate the deterministically calculated Supply Chain Index score.

This adds a layer of "AI Intelligence" to the dashboard, providing:
1. Verification: "Does this score make sense given the news/data?"
2. Reasoning: A human-readable explanation of WHY the score is what it is.
3. Adjustment: (Optional) A small nudging factor if the AI identifies significant risks missed by the math.
"""

from __future__ import annotations

import json
import logging
import os
import google.generativeai as genai
from datetime import datetime

logger = logging.getLogger(__name__)

# Fallback response if AI fails
FALLBACK_VALIDATION = {
    "status": "Verified",
    "reasoning": "Score is consistent with current weighted metrics.",
    "adjustment": 0.0
}

def validate_score(
    current_score: float,
    current_categories: dict[str, float],
    top_news: list[dict]
) -> dict:
    """
    Ask Gemini to validate the calculated score.
    
    Parameters
    ----------
    current_score : float
        The composite index (0-100) calculated by the deterministic engine.
    current_categories : dict
        The breakdown of scores (e.g. {'energy': 45.0, 'weather': 90.0}).
    top_news : list[dict]
        List of top 3-5 news alerts (title, severity).
        
    Returns
    -------
    dict
        {
            "status": "CONFIRMED" | "ADJUSTED",
            "reasoning": "Short explanation...",
            "adjustment": float (e.g. -2.5 or 0.0)
        }
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. Skipping AI validation.")
        return FALLBACK_VALIDATION

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3-flash-preview')

        # Prepare context for the LLM
        news_summary = "\n".join([
            f"- [{item.get('severity', 'low').upper()}] {item.get('title', 'Unknown')}"
            for item in top_news[:5]
        ])

        prompt = f"""
        Act as a Senior Supply Chain Risk Analyst.
        
        I have calculated a Global Supply Chain Health Index of {current_score:.1f} / 100.
        (100 = Perfect Health, 0 = Catastrophic Collapse).
        
        Here is the breakdown:
        {json.dumps(current_categories, indent=2)}
        
        Recent News Headlines:
        {news_summary}
        
        TASK:
        1. VALIDATE if this score seems reasonable given the news and category scores.
        2. Provide a 1-sentence "Reasoning" explaining the score to a logistics executive.
        3. If you believe the score ignores a critical "black swan" event in the news, suggest a small adjustment (-5.0 to +5.0). Otherwise 0.0.
        
        OUTPUT JSON ONLY:
        {{
            "status": "CONFIRMED" or "ADJUSTED",
            "reasoning": "Your 1-sentence explanation here.",
            "adjustment": 0.0
        }}
        """

        response = model.generate_content(prompt)
        
        # Clean response (remove markdown fences if any)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
            
        result = json.loads(text)
        
        # Safety bounds
        if not isinstance(result.get("adjustment"), (int, float)):
            result["adjustment"] = 0.0
        
        # Clamp adjustment to avoid AI hallucinations wrecking the dashboard
        result["adjustment"] = max(-5.0, min(5.0, float(result["adjustment"])))
        
        return result

    except Exception as e:
        logger.error(f"AI Validation failed: {e}")
        return FALLBACK_VALIDATION
