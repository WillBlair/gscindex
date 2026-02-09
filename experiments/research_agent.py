"""
Research Agent
==============
Standalone agent that:
1. "Reads" global news (simulated feed for now, can be connected to NewsAPI/Bing).
2. Uses Gemini to analyze for supply chain risks.
3. Saves high-severity alerts to 'data/disruptions.json'.

Usage:
    python experiments/research_agent.py
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
import random

# Add parent directory to path so we can import from 'data'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.ai_analyst import analyze_news_batch

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ResearchAgent")

# --- SIMULATED NEWS FEED (Replace with Real API later) ---
SAMPLE_HEADLINES = [
    "Maersk vessel stuck in Panama Canal due to drought restrictions",
    "New iPhone 16 released with titanium finish",
    "Dockworkers at Port of LA threaten strike over automation",
    "Oil prices drop slightly as demand waivers",
    "Typhoon signal 8 raised in Hong Kong, port operations suspended",
    "Local bakery wins award for best croissant",
    "Semiconductor shortage eases as TSMC ramps up Arizona plant",
    "Major highway collision delays trucking route in France",
]

def fetch_global_news() -> list[dict]:
    """Simulates fetching fresh news from the web."""
    logger.info("Scanning global news sources...")
    time.sleep(1.5) # Simulate network request
    
    articles = []
    for i, headline in enumerate(SAMPLE_HEADLINES):
        articles.append({
            "id": int(time.time()) + i,
            "title": headline,
            "description": "Breaking news report...",
            "source": "Global Wire"
        })
    
    # Add some random noise
    if random.random() > 0.5:
        articles.append({
            "id": int(time.time()) + 100,
            "title": "Suez Canal blockage fears rise after vessel grounding",
            "description": "A container ship has run aground, traffic halted.",
            "source": "Maritime News"
        })
        
    return articles

def run_research_cycle():
    logger.info("Starting Research Agent Cycle...")
    
    # 1. Gather Info
    articles = fetch_global_news()
    logger.info(f"Collected {len(articles)} potential signals.")
    
    # 2. Analyze with Gemini
    logger.info("Engaging Gemini Analyst...")
    analysis_results = analyze_news_batch(articles)
    
    if not analysis_results:
        logger.warning("No analysis results returned.")
        return

    # 3. Filter & Act
    disruptions = []
    for art in articles:
        aid = art["id"]
        if aid in analysis_results:
            res = analysis_results[aid]
            if res.get("is_relevant") and abs(res.get("severity_score", 0)) >= 4:
                logger.warning(f"🚨 DISRUPTION DETECTED: {art['title']} (Score: {res['severity_score']})")
                disruptions.append({
                    "event": res.get("category", "General").title(),
                    "region": "Global", # Gemini could extract this too
                    "impact_score": res.get("severity_score"),
                    "categories": [res.get("category")],
                    "started": datetime.now().strftime("%Y-%m-%d"),
                    "status": "Active",
                    "summary": res.get("summary")
                })
            else:
                logger.info(f"Irrelevant/Low Impact: {art['title']}")

    # 4. Save Findings
    output_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "disruptions.json")
    
    # Load existing to append? For now just overwrite for demo
    try:
        with open(output_file, "w") as f:
            json.dump(disruptions, f, indent=2)
        logger.info(f"Saved {len(disruptions)} active disruptions to {output_file}")
    except Exception as e:
        logger.error(f"Failed to save disruptions: {e}")

if __name__ == "__main__":
    print(r"""
   ___  ___  ___  ___  ____  ___  ___  ___  _  _    
  / _ \/ _ \/ __\/ _ \/ __ \/ _ \/ __\/ _ \/ \/ \  
 | (_) | (_) | _\ |(_) |     |(_) | _\ |(_) |    |   
  \___/\___/ \___/\___/ \___/\___/ \___/\___/_/\_\   
             RESEARCH AGENT v1.0                     
    """)
    run_research_cycle()
