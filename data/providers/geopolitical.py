"""
Geopolitical Risk + News Intelligence Provider
================================================
Uses NewsAPI to fetch supply chain articles, then applies VADER sentiment
analysis to score each article's negativity and classify it into the
correct supply chain category.

VADER (Valence Aware Dictionary and sEntiment Reasoner) runs locally —
no AI API key needed. It's specifically designed for news/social media
text and produces a compound score from -1 (most negative) to +1 (most
positive).

Score Logic
-----------
1. Fetch 30 recent supply chain articles from NewsAPI
2. Run VADER on each article's title + description
3. Classify each article into a supply chain category via keywords
4. Compute geopolitical score: start at 85, deduct based on VADER
   negativity of each article (more negative articles = lower score)
5. Return categorized alerts for the dashboard feed

The score starts at 85 (not 100) because there's ALWAYS some negative
supply chain news — a score of 100 would mean "no news at all" which
isn't realistic or useful.
"""

from datetime import datetime, timedelta
import logging
import os
import requests
import numpy as np
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from data.cache import get_cached, set_cached
from data.providers.base import BaseProvider
from data.ai_analyst import analyze_news_batch

# ...

logger = logging.getLogger(__name__)

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_VADER = SentimentIntensityAnalyzer()

# ---------------------------------------------------------------------------
# Category classification keywords
# When an article matches multiple categories, the FIRST match wins
# (ordered by specificity — most specific categories first).
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "weather":      {"hurricane", "typhoon", "storm", "flood", "drought", "cyclone", "tornado", "wildfire", "earthquake"},
    "ports":        {"port", "congestion", "container terminal", "vessel queue", "berth", "dock worker", "longshoreman", "dwell time"},
    "energy":       {"oil", "crude", "gas price", "fuel", "opec", "petroleum", "brent", "lng", "refinery", "pipeline", "energy cost"},
    "tariffs":      {"tariff", "trade war", "duty", "import ban", "export ban", "sanctions", "trade deal", "cbam", "trade policy", "customs"},
    "shipping":     {"freight rate", "container rate", "shipping cost", "blank sailing", "feu", "teu", "carrier", "maersk", "hapag", "cosco"},
    "demand":       {"inventory", "shortage", "surplus", "consumer demand", "retail sales", "stockpile", "backlog", "pmi"},
    "geopolitical": {"war", "conflict", "missile", "blockade", "military", "coup", "protest", "unrest", "territory", "houthi", "red sea"},
    "chokepoint":   {"suez canal", "panama canal", "malacca strait", "strait of hormuz", "bab el-mandeb", "bosporus", "dardanelles", "cape of good hope"},
}


# Terms that indicate an article is clearly NOT about supply chains.
# If any of these appear in the title or body, the article is skipped
# before it ever matches to a port.  Keeps garbage out of scores.
_IRRELEVANT_TERMS: set[str] = {
    "fantasy", "baseball", "football", "basketball", "hockey", "nfl",
    "nba", "nhl", "mlb", "premier league", "world cup", "olympics",
    "vacation", "resort", "airbnb", "tourism", "travel deal",
    "gaming", "playstation", "xbox", "nintendo", "handheld",
    "upsc", "exam prep", "exam result", "board exam", "college admission",
    "recipe", "cookbook", "celebrity", "red carpet", "box office",
    "movie review", "album review", "concert", "streaming service",
    "cryptocurrency", "bitcoin", "ethereum", "nft", "meme coin",
    "horoscope", "zodiac", "astrology", "lottery", "powerball",
    "free shipping", "promo code", "discount code", "gift card",
    
    # Toys & Consumer Junk
    "disney", "lego", "mattel", "hasbro", "funko",
    
    # Health Supplements & niche products
    "supplement", "nutrition", "vitamin", "protein powder", "creatine", 
    "pre-workout", "nootropic", "skin care", "skincare", "makeup",
    
    # 3D Printing / Hobbyist
    "printer", "3d print", "filament", "elegoo", "bambu", "creality",
    
    # Corporate Noise
    "securities fraud", "fraud investigation", "shareholder alert",
    
    # Clothing / Retail
    "pants", "shirt", "jeans", "mens", "womens", "apparel", "clothing", 
    "shoe", "sneaker", "boot", "sandal", "heel", "watch", "jewelry",
    
    # Generic Market Research Spam
    "market size", "market share", "market growth", "market forecast", 
    "market analysis", "growth analysis", "forecast 20", "cagr",
}


def _is_irrelevant_article(text: str) -> bool:
    """Return True if the article text contains clearly off-topic terms."""
    return any(term in text for term in _IRRELEVANT_TERMS)


def _get_api_key() -> str:
    key = os.environ.get("NEWSAPI_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "NEWSAPI_KEY is not set.\n"
            "  1. Sign up free at https://newsapi.org/register\n"
            "  2. Add NEWSAPI_KEY=your_key to your .env file"
        )
    return key


def _classify_category_keyword(text: str) -> str:
    """Assign an article to a supply chain category based on keyword matching (Fallback)."""
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "geopolitical"


def _score_to_severity(score: float) -> str:
    """Map severity score to label."""
    if score <= -4: return "high"
    if score <= -1.5: return "medium"
    return "low"


def fetch_supply_chain_news() -> tuple[float, list[dict], str]:
    """Fetch news and analyze using AI (Gemini) with VADER fallback.
    
    Returns
    -------
    tuple
        (score, alerts, briefing_text)
    """
    cache_key = "newsapi_briefing_v4"
    cached = get_cached(cache_key, ttl=14400)  # 4-hour cache (reduced API usage)
    if cached is not None:
        return cached["score"], cached["alerts"], cached.get("briefing", "")

    api_key = _get_api_key()
    from_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    # 1. Fetch from NewsAPI
    try:
        resp = requests.get(
            _NEWSAPI_URL,
            params={
                "q": (
                    '("supply chain" OR "freight" OR "shipping") '
                    'AND (port OR logistics OR cargo OR trade OR tariff OR canal OR strait OR "red sea" OR container) '
                    'AND NOT ("free shipping" OR "promo code")'
                ),
                "from": from_date,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 60,  # Fetch plenty to filter down
                "apiKey": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as e:
        logger.error(f"NewsAPI fetch failed: {e}")
        return 75.0, [], ""

    # 2. Pre-filter and Prepare for AI
    candidates = []
    
    for i, article in enumerate(articles):
        title = article.get("title") or ""
        description = article.get("description") or ""
        full_text = f"{title}. {description}".lower()

        # Keyword Spam Filter (Save AI tokens)
        if _is_irrelevant_article(full_text):
            continue
            
        candidates.append({
            "id": i,
            "title": title,
            "description": description,
            "url": article.get("url", "#"),
            "source": article.get("source", {}).get("name", "Unknown Source"),
            "published": article.get("publishedAt", datetime.now().isoformat())
        })

    # Limit to top 15 for AI analysis to avoid rate limits/latency
    ai_candidates = candidates[:15]
    
    # 3. Analyze with Gemini (single call returns both analysis AND briefing)
    ai_results, ai_briefing = analyze_news_batch(ai_candidates)
    
    alerts = []
    severity_sum = 0.0
    briefing_text = ai_briefing  # Use briefing from consolidated API call
    
    # Process AI results
    if ai_results:
        logger.info(f"AI successfully analyzed {len(ai_results)} articles")
        for cid, analysis in ai_results.items():
            if not analysis.get("is_relevant", False):
                continue
                
            severity = analysis.get("severity_score", 0.0)
            severity_sum += severity
            
            # Find original article data
            original = next((c for c in ai_candidates if c["id"] == cid), None)
            if not original:
                continue
                
            alerts.append({
                "timestamp": original["published"],
                "severity": _score_to_severity(severity),
                "title": original["title"],
                "body": analysis.get("summary", original["description"]), # Use AI summary if available
                "category": analysis.get("category", "geopolitical"),
                "sentiment": severity, # Storing severity score as sentiment for compatibility
                "url": original["url"],
                "source": original["source"],
            })
            
    else:
        # Fallback to VADER if AI fails or returns nothing
        logger.warning("AI analysis failed or returned empty. Using VADER fallback.")
        briefing_text = ""  # No briefing available in fallback mode
        for article in candidates[:15]:
            title = article["title"]
            desc = article["description"]
            text = f"{title} {desc}"
            
            v_score = _VADER.polarity_scores(text)["compound"]
            if v_score < -0.05:
                deduction = abs(v_score) * 8.0
                severity_sum -= deduction
                
            alerts.append({
                "timestamp": article["published"],
                "severity": "high" if v_score < -0.5 else "medium" if v_score < -0.15 else "low",
                "title": title,
                "body": desc,
                "category": _classify_category_keyword(text.lower()),
                "sentiment": v_score * 10, # rough mapping
                "url": article["url"],
                "source": article["source"],
            })

    # 4. Calculate Final Score
    # Start at 100 (Perfect). Add severity scores (usually negative).
    # If we have +severity (good news), score can go up, but cap at 100.
    final_score = 100.0 + severity_sum
    final_score = max(0.0, min(100.0, final_score))

    # Sort alerts by severity (lowest score = highest risk)
    alerts.sort(key=lambda a: (a["sentiment"], a["timestamp"]), reverse=False) # Ascending sentiment (negative first)

    result = {
        "score": round(final_score, 1),
        "alerts": alerts,
        "briefing": briefing_text
    }
    
    set_cached(cache_key, result)
    return result["score"], result["alerts"], result["briefing"]


class GeopoliticalProvider(BaseProvider):
    """Geopolitical Risk — VADER sentiment analysis on supply chain news."""

    category = "geopolitical"

    def fetch_current(self) -> tuple[float, dict]:
        score, alerts, _ = fetch_supply_chain_news()
        
        # Calculate recent negative news count
        high_sev = sum(1 for a in alerts if a['severity'] == 'high')
        med_sev = sum(1 for a in alerts if a['severity'] == 'medium')
        
        return score, {
            "source": "NewsAPI + VADER Sentiment",
            "raw_value": f"{len(alerts)} articles",
            "raw_label": "Analyzed News Volume",
            "description": (
                f"Analyzed recent supply chain news. Found {high_sev} high-severity "
                f"and {med_sev} medium-severity risk events affecting the score."
            ),
            "calculation": (
                "Score = 85 - (Total VADER Negativity). "
                "We start at 85 (perfect stability is rare). "
                "Each negative news article deducts points based on its severity "
                "(High = -8, Medium = -4). "
                "Historical trend is modeled using the VIX Volatility Index."
            ),
            "updated": "Live"
        }

    def fetch_history(self, days: int) -> pd.Series:
        """Fetch historical VIX (Volatility Index) as a proxy for geopolitical risk.

        We align the VIX series so that the *last* point (today) matches our
        actual NewsAPI-derived score. This ensures the trend looks real (it is)
        but the absolute level reflects current supply chain news sentiment.
        """
        from data.providers.fred_client import fetch_fred_series
        
        # 1. Get current score (anchor point)
        # Handle tuple return from fetch_current
        current_result = self.fetch_current()
        if isinstance(current_result, tuple):
            current_score = current_result[0]
        else:
            current_score = current_result

        try:
            # We fetch a bit more history than needed to ensure we have enough data points
            # after dropping NaNs and alignment.
            vix = fetch_fred_series("VIXCLS", lookback_days=days + 60)
            
            # 2. Normalize (Inverted: Low VIX is good)
            # We use a fixed "reasonable" range for VIX normalization to keep it consistent
            # Low: 10 (very calm), High: 60 (crisis like 2008/2020)
            # This is better than min/max because VIX can spike hugely.
            # a VIX of 10 -> Score 100
            # a VIX of 35 -> Score 50
            # a VIX of 60 -> Score 0
            # Formula: Score = 120 - 2 * VIX (clipped 0-100)
            #   10 -> 100
            #   35 -> 50
            #   60 -> 0
            vix_score = (120 - 2 * vix).clip(0, 100)
            
            # 3. Align to current score
            # We want the shape of the VIX, but the level of our NewsAPI score.
            if not vix_score.empty:
                latest_vix = vix_score.iloc[-1]
                delta = current_score - latest_vix
                
                # Apply delta to the whole series
                adjusted_score = (vix_score + delta).clip(0, 100)
                
                # Resample to daily (VIX is trading days only) and fill gaps
                dates = pd.date_range(
                    end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
                    periods=days,
                    freq="D",
                )
                aligned = adjusted_score.reindex(dates, method="ffill")
                
                # Force the last point to be exactly our current score (integrity check)
                aligned.iloc[-1] = current_score
                
                return aligned.rename("geopolitical")

        except Exception as e:
            logger.warning("Failed to fetch VIX history: %s", e)

        # Fallback: Flat line at current score
        dates = pd.date_range(
            end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            periods=days,
            freq="D",
        )
        return pd.Series(current_score, index=dates, name="geopolitical")
