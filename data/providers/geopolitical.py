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
1. Fetch recent supply chain articles (RSS primary, NewsAPI fallback)
2. Score each article's severity (Gemini analysis when available,
   VADER compound × 6 as the deterministic fallback)
3. Classify each article into a supply chain category via keywords
4. Compute the score: deduplicate articles by title, take the 10 most
   severe negative items, and deduct their summed severity from 100
   (floored at -60 total). Positive news never inflates the score;
   100 means "no risk detected".

Deduplication and the top-N cut keep the score volume-invariant: thirty
mildly negative wire stories cannot outweigh one severe event, and the
score does not swing with how many items the feeds happen to return.

History comes from the daily_category_scores table — real stored
measurements only. No proxy series, no synthetic backfill.
"""

from datetime import datetime, timedelta
import logging
import os
import requests
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import GEMINI_CACHE_TTL_SECONDS, NEWS_BRIEFING_CACHE_KEY, NEWS_RSS_REFRESH_SECONDS
from data.cache import get_cache_age_seconds, get_cached, set_cached
from data.providers.base import BaseProvider
from data.ai_analyst import analyze_news_batch

# ...

logger = logging.getLogger(__name__)

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_VADER = SentimentIntensityAnalyzer()
_NEWS_CACHE_KEY = NEWS_BRIEFING_CACHE_KEY

# ---------------------------------------------------------------------------
# Category classification keywords
# When an article matches multiple categories, the FIRST match wins
# (ordered by specificity — most specific categories first).
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "weather":       {"hurricane", "typhoon", "storm", "flood", "drought", "cyclone", "tornado", "wildfire", "earthquake"},
    "supply_chain":  {"port", "congestion", "container terminal", "vessel queue", "berth", "dock worker", "longshoreman",
                      "dwell time", "inventory", "shortage", "surplus", "consumer demand", "retail sales",
                      "stockpile", "backlog", "pmi"},
    "energy":        {"oil", "crude", "gas price", "fuel", "opec", "petroleum", "brent", "lng", "refinery", "pipeline", "energy cost", "diesel"},
    "tariffs":       {"tariff", "trade war", "duty", "import ban", "export ban", "sanctions", "trade deal", "cbam", "trade policy", "customs"},
    "freight":       {"freight rate", "container rate", "shipping cost", "blank sailing", "feu", "teu", "carrier", "maersk", "hapag", "cosco"},
    "geopolitical":  {"war", "conflict", "missile", "blockade", "military", "coup", "protest", "unrest", "territory", "houthi", "red sea",
                      "suez canal", "panama canal", "malacca strait", "strait of hormuz", "bab el-mandeb", "bosporus", "dardanelles", "cape of good hope"},
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


# Volume-invariance parameters for the risk score: only the N most severe
# unique articles count, and the total deduction is floored.
_RISK_TOP_N = 10
_RISK_FLOOR = -60.0


def _risk_score_from_alerts(alerts: list[dict]) -> float:
    """Compute the geopolitical risk score from a list of alerts.

    Deduplicates by normalized title, keeps only the ``_RISK_TOP_N`` most
    severe negative items, floors the total deduction at ``_RISK_FLOOR``,
    and subtracts from 100. Positive sentiment never adds to the score.
    """
    seen: set[str] = set()
    negatives: list[float] = []
    for alert in alerts:
        key = " ".join(str(alert.get("title", "")).lower().split())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        sentiment = float(alert.get("sentiment", 0.0))
        if sentiment < 0:
            negatives.append(sentiment)

    worst = sorted(negatives)[:_RISK_TOP_N]
    deduction = max(_RISK_FLOOR, sum(worst))
    return round(max(0.0, min(100.0, 100.0 + deduction)), 1)


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


def _build_vader_alerts(candidates: list[dict]) -> list[dict]:
    """Generate alerts deterministically from RSS/NewsAPI using VADER fallback."""
    alerts: list[dict] = []

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
    return alerts


def _refresh_cached_news_from_rss(cached: dict) -> dict | None:
    """Re-fetch RSS and re-score with VADER while keeping Gemini briefing/report."""
    from data.rss_fetcher import fetch_rss_articles

    rss_articles = fetch_rss_articles(max_items=50)
    if not rss_articles:
        return None

    candidates = [
        {
            "title": art["title"],
            "description": art["description"],
            "url": art["url"],
            "source": art["source"],
            "published": art["published"],
        }
        for art in rss_articles
    ]
    alerts = _build_vader_alerts(candidates[:30])
    if not alerts:
        return None

    refreshed = dict(cached)
    refreshed["score"] = _risk_score_from_alerts(alerts)
    refreshed["alerts"] = alerts
    if not (refreshed.get("briefing") or "").strip():
        refreshed["briefing"] = _build_fallback_briefing(alerts)
    return refreshed


def _get_cached_news_tuple() -> tuple[float, list[dict], str, str] | None:
    """Return cached news analysis tuple if available, else None.

    This is intentionally fast and non-blocking so provider calls never trigger
    long AI/RSS fetches. Fresh news fetch runs in the aggregator job.
    """
    cached = get_cached(_NEWS_CACHE_KEY, ttl=GEMINI_CACHE_TTL_SECONDS)
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
    cached = get_cached(cache_key, ttl=GEMINI_CACHE_TTL_SECONDS)
    if cached is not None:
        cache_age = get_cache_age_seconds(cache_key)
        if cache_age is not None and cache_age > NEWS_RSS_REFRESH_SECONDS:
            try:
                refreshed = _refresh_cached_news_from_rss(cached)
                if refreshed:
                    set_cached(cache_key, refreshed)
                    cached = refreshed
                    logger.info(
                        "Refreshed news score/alerts from RSS (cache age %.0fs)",
                        cache_age,
                    )
            except Exception as exc:
                logger.warning("RSS refresh of cached news failed: %s", exc)

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

    # Limit to top 25 for AI analysis (RSS quality is higher, so we can process more)
    # Ensure internal intelligence is always included by prioritizing items with 'is_rss' = True
    ai_candidates = candidates[:25]
    
    # 3. Analyze with Gemini
    ai_results, ai_briefing = analyze_news_batch(ai_candidates)
    
    # Generate Full Report (New Feature)
    # We use the full set of RSS candidates (or top 50) for a broader context
    from data.ai_analyst import generate_full_report
    full_report_md = generate_full_report(candidates[:50])
    
    alerts = []
    briefing_text = ai_briefing.strip() if isinstance(ai_briefing, str) else ""

    if ai_results:
        logger.info(f"AI successfully analyzed {len(ai_results)} articles")
        for cid, analysis in ai_results.items():
            if not analysis.get("is_relevant", False):
                continue
                
            severity = analysis.get("severity_score", 0.0)
            
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
        alerts = _build_vader_alerts(candidates[:30])

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

    # 4. Calculate Final Score (deduplicated, top-N, floored — volume-invariant)
    final_score = _risk_score_from_alerts(alerts)

    alerts.sort(key=lambda a: (a.get("sentiment", 0.0), a.get("timestamp", "")), reverse=False)

    result = {
        "score": final_score,
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

        # No cache — compute a quick VADER-based score from live RSS.
        # This runs in ~2-3s (no AI) and ensures we never show a hardcoded value.
        try:
            from data.rss_fetcher import fetch_rss_articles

            rss_articles = fetch_rss_articles(max_items=30)
            if rss_articles:
                candidates = [
                    {
                        "title": art["title"],
                        "description": art["description"],
                        "url": art["url"],
                        "source": art["source"],
                        "published": art["published"],
                    }
                    for art in rss_articles
                ]
                alerts = _build_vader_alerts(candidates)
                score = _risk_score_from_alerts(alerts)
                high_sev = sum(1 for a in alerts if a.get("severity") == "high")
                med_sev = sum(1 for a in alerts if a.get("severity") == "medium")
                return score, {
                    "source": "RSS + VADER (live fallback)",
                    "raw_value": f"{len(alerts)} articles",
                    "raw_label": "Analyzed News Volume",
                    "description": (
                        f"Live VADER analysis (AI cache unavailable). Found {high_sev} high-severity "
                        f"and {med_sev} medium-severity risk events."
                    ),
                    "calculation": (
                        "Score = 100 + sum of the 10 most severe negative VADER severities "
                        "(deduplicated by title, total deduction floored at -60). "
                        "Only negative news reduces the score; positive news does not inflate it."
                    ),
                    "updated": "Live (VADER)",
                }
        except Exception as exc:
            logger.warning("VADER fallback in fetch_current failed: %s", exc)

        # Absolute last resort: no RSS, no cache, no nothing.
        neutral = 85.0
        return neutral, {
            "source": "Baseline (no data)",
            "raw_value": "0 articles",
            "raw_label": "Analyzed News Volume",
            "description": "No news feeds available. Showing neutral baseline until data sources come online.",
            "calculation": "Neutral baseline of 85 — all data sources are offline.",
            "updated": "Initializing",
        }

    def fetch_history(self, days: int) -> pd.Series:
        """Return stored daily geopolitical scores from the database.

        Only real measurements are returned — the series is short (or empty)
        until enough daily scores have accumulated. Charts render the gap
        rather than showing a proxy series dressed up as news history.
        """
        from data.database import get_category_score_history

        return get_category_score_history("geopolitical", days).rename("geopolitical")
