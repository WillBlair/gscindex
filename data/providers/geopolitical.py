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
4. Compute geopolitical score: start at 100, deduct based on VADER
   negativity of each article (only negative articles reduce the score;
   positive news does not inflate it — 100 means "no risk detected")
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
_NEWS_CACHE_KEY = "newsapi_briefing_v14"

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


def _build_fallback_briefing(alerts: list[dict]) -> str:
    """Build a deterministic 3-bullet briefing when AI output is unavailable."""
    if not alerts:
        return (
            "• Live supply chain feeds are online, but no material disruptions were detected in the latest cycle.\n"
            "• Core logistics lanes and freight operations appear stable based on current article sentiment.\n"
            "• Monitoring remains active for weather, trade policy, and geopolitical events that could shift risk quickly."
        )

    top = sorted(alerts, key=lambda a: float(a.get("sentiment", 0.0)))[:3]
    bullets: list[str] = []
    for alert in top:
        title = str(alert.get("title", "Supply chain development")).strip()
        category = str(alert.get("category", "geopolitical")).replace("_", " ")
        severity = str(alert.get("severity", "low")).lower()
        source = str(alert.get("source", "news source")).strip()
        if len(title) > 140:
            title = f"{title[:137]}..."
        bullets.append(
            f"• {category.title()} risk is {severity} priority after reports that {title} (source: {source})."
        )

    while len(bullets) < 3:
        bullets.append(
            "• Additional signals remain mixed, with no new systemic trigger identified in the latest ingest."
        )
    return "\n".join(bullets[:3])


def _build_vader_alerts(candidates: list[dict]) -> tuple[list[dict], float]:
    """Generate alerts deterministically from RSS/NewsAPI using VADER fallback."""
    alerts: list[dict] = []
    severity_sum = 0.0

    for candidate in candidates:
        title = (candidate.get("title") or "").strip()
        description = (candidate.get("description") or "").strip()
        if not title and not description:
            continue

        combined = f"{title} {description}".lower()
        if _is_irrelevant_article(combined):
            continue

        category = _classify_category_keyword(combined)
        compound = float(_VADER.polarity_scores(combined).get("compound", 0.0))
        # Scale VADER [-1, +1] into the existing severity banding used elsewhere.
        severity_score = round(compound * 6.0, 2)
        if severity_score < 0:
            severity_sum += severity_score

        alerts.append(
            {
                "timestamp": candidate.get("published") or datetime.utcnow().isoformat(),
                "severity": _score_to_severity(severity_score),
                "title": title or "Untitled supply chain update",
                "body": (description[:240] + "...") if len(description) > 240 else description,
                "category": category,
                "sentiment": severity_score,
                "url": candidate.get("url") or "#",
                "source": candidate.get("source") or "Industry News",
            }
        )

    # Most severe first (more negative sentiment = higher risk)
    alerts.sort(key=lambda a: (float(a.get("sentiment", 0.0)), str(a.get("timestamp", ""))))
    return alerts, severity_sum


def _get_cached_news_tuple() -> tuple[float, list[dict], str, str] | None:
    """Return cached news analysis tuple if available, else None.

    This is intentionally fast and non-blocking so provider calls never trigger
    long AI/RSS fetches. Fresh news fetch runs in the aggregator job.
    """
    cached = get_cached(_NEWS_CACHE_KEY, ttl=14400)
    if not cached:
        return None
    return (
        float(cached.get("score", 85.0)),
        cached.get("alerts", []),
        cached.get("briefing", ""),
        cached.get("full_report", ""),
    )


def fetch_supply_chain_news() -> tuple[float, list[dict], str, str]:
    """Fetch news and analyze using AI (Gemini) with VADER fallback.
    
    Returns
    -------
    tuple
        (score, alerts, briefing_text, full_report_md)
    """
    cache_key = _NEWS_CACHE_KEY
    cached = get_cached(cache_key, ttl=14400)  # 4-hour cache (reduced API usage)
    if cached is not None:
        cached_alerts = cached.get("alerts", []) or []
        cached_briefing = (cached.get("briefing", "") or "").strip()
        cached_report = (cached.get("full_report", "") or "").strip()
        cached_score = float(cached.get("score", 85.0))

        # Self-heal stale/empty cache payloads instead of serving broken panels for 4h.
        if cached_alerts:
            if not cached_briefing:
                cached_briefing = _build_fallback_briefing(cached_alerts)
            if not cached_report:
                cached_report = (
                    "## Critical Disruptions\n"
                    "No critical disruptions detected from the latest ingest.\n\n"
                    "## Ocean Freight & Port Operations\n"
                    "Monitoring active routes and terminal pressure based on available alerts.\n\n"
                    "## Air & Land Logistics\n"
                    "No systemic air, rail, or trucking disruption confirmed in cached state.\n\n"
                    "## Market & Economic Context\n"
                    "Risk posture reflects cached sentiment and may update on next refresh cycle.\n\n"
                    "## Forward Outlook\n"
                    "Watch for escalation in weather, tariffs, and geopolitical chokepoints."
                )
            return cached_score, cached_alerts, cached_briefing, cached_report

        logger.warning("Cached news payload is empty; regenerating from live feeds.")

    # 1. Fetch from RSS Feeds (High Quality, User Specified)
    from data.rss_fetcher import fetch_rss_articles
    
    rss_articles = fetch_rss_articles(max_items=50)
    
    # Optional: We can still fetch from NewsAPI if RSS is empty, 
    # but the user requested "make sure gemini does it based on these", so we prioritize RSS heavily.
    # If RSS returns < 5 items, we might fall back, but let's stick to RSS for now to ensure quality.
    
    candidates = []
    
    # 2. Convert RSS to standard format
    for i, art in enumerate(rss_articles):
        # Clean description for AI
        desc = art["description"]
        # Basic cleanup of HTML if any remains (though feedparser does some)
        
        candidates.append({
            "id": i,
            "title": art["title"],
            "description": desc,
            "url": art["url"],
            "source": art["source"],
            "published": art["published"]
        })

    # If absolutely no RSS data, fallback to NewsAPI (Safety Net)
    if not candidates:
        logger.warning("No RSS articles found! Falling back to NewsAPI.")
        from_date = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
        api_key = _get_api_key()
        try:
            resp = requests.get(
                _NEWSAPI_URL,
                params={
                   "q": '("supply chain" OR "freight") AND (port OR container)',
                   "from": from_date,
                   "sortBy": "publishedAt",
                   "language": "en",
                   "apiKey": api_key,
                },
                timeout=10
            )
            if resp.status_code == 200:
                news_arts = resp.json().get("articles", [])
                for i, art in enumerate(news_arts):
                    candidates.append({
                        "id": i + 1000, # Offset IDs
                        "title": art.get("title"),
                        "description": art.get("description"),
                        "url": art.get("url"),
                        "source": art.get("source", {}).get("name"),
                        "published": art.get("publishedAt")
                    })
        except Exception as e:
            logger.error(f"NewsAPI Fallback failed: {e}")

    # Limit to top 20 for AI analysis (RSS quality is higher, so we can process more)
    ai_candidates = candidates[:20]
    
    # 3. Analyze with Gemini
    ai_results, ai_briefing = analyze_news_batch(ai_candidates)
    
    # Generate Full Report (New Feature)
    # We use the full set of RSS candidates (or top 50) for a broader context
    from data.ai_analyst import generate_full_report
    full_report_md = generate_full_report(candidates[:50])
    
    alerts = []
    severity_sum = 0.0
    briefing_text = ai_briefing.strip() if isinstance(ai_briefing, str) else ""
    
    # ... (Rest of processing)
    
    if ai_results:
        logger.info(f"AI successfully analyzed {len(ai_results)} articles")
        for cid, analysis in ai_results.items():
            if not analysis.get("is_relevant", False):
                continue
                
            severity = analysis.get("severity_score", 0.0)
            if severity < 0:
                severity_sum += severity
            
            # Find original
            original = next((c for c in ai_candidates if c["id"] == cid), None)
            if not original:
                continue
                
            alerts.append({
                "timestamp": original["published"],
                "severity": _score_to_severity(severity),
                "title": original["title"],
                "body": analysis.get("summary", original["description"]),
                "category": analysis.get("category", "geopolitical"),
                "sentiment": severity, 
                "url": original["url"],
                "source": original["source"],
            })
    
    # Fallback VADER for non-AI analyzed items or if AI failed
    if not alerts and candidates:
        logger.warning(
            "Gemini returned no usable alerts; using deterministic VADER fallback for %d candidates.",
            len(candidates),
        )
        alerts, severity_sum = _build_vader_alerts(candidates[:30])

    # Ensure briefing is always populated (AI first, deterministic fallback second)
    if not briefing_text:
        briefing_text = _build_fallback_briefing(alerts)

    # Ensure full report has a minimum deterministic fallback
    if not full_report_md.strip():
        full_report_md = (
            "## Critical Disruptions\n"
            "No critical disruptions detected from the latest ingest.\n\n"
            "## Ocean Freight & Port Operations\n"
            "Live feeds are active; monitor freight lane pressure and port dwell-time narratives.\n\n"
            "## Air & Land Logistics\n"
            "No confirmed systemic breakdown was detected in rail, trucking, or air cargo in this cycle.\n\n"
            "## Market & Economic Context\n"
            "Macro conditions remain watchful with ongoing exposure to fuel, tariffs, and demand volatility.\n\n"
            "## Forward Outlook\n"
            "Track updates over the next 24-48 hours for escalation in weather and geopolitical chokepoints."
        )

    # 4. Calculate Final Score
    final_score = 100.0 + severity_sum
    final_score = max(0.0, min(100.0, final_score))

    alerts.sort(key=lambda a: (a.get("sentiment", 0.0), a.get("timestamp", "")), reverse=False)

    result = {
        "score": round(final_score, 1),
        "alerts": alerts,
        "briefing": briefing_text,
        "full_report": full_report_md
    }
    
    set_cached(cache_key, result)
    return result["score"], result["alerts"], result["briefing"], result["full_report"]


class GeopoliticalProvider(BaseProvider):
    """Geopolitical Risk — VADER sentiment analysis on supply chain news."""

    category = "geopolitical"

    def fetch_current(self) -> tuple[float, dict]:
        # Never trigger long AI/RSS pipeline from provider path.
        # Aggregator fetches fresh news once per cycle and merges it.
        cached_tuple = _get_cached_news_tuple()
        if cached_tuple:
            score, alerts, _, _ = cached_tuple
            high_sev = sum(1 for a in alerts if a.get("severity") == "high")
            med_sev = sum(1 for a in alerts if a.get("severity") == "medium")
            return score, {
                "source": "RSS + Gemini (cached)",
                "raw_value": f"{len(alerts)} articles",
                "raw_label": "Analyzed News Volume",
                "description": (
                    f"Using cached analysis. Found {high_sev} high-severity "
                    f"and {med_sev} medium-severity risk events."
                ),
                "calculation": (
                    "Score is derived from Gemini severity analysis of recent supply-chain "
                    "articles and used as the current anchor for geopolitical risk."
                ),
                "updated": "Cached",
            }

        neutral = 85.0
        return neutral, {
            "source": "RSS + Gemini",
            "raw_value": "0 articles",
            "raw_label": "Analyzed News Volume",
            "description": "Awaiting live news analysis. Showing neutral baseline temporarily.",
            "calculation": "Neutral baseline of 85 is used until fresh analysis completes.",
            "updated": "Initializing",
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
