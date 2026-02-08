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

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from data.cache import get_cached, set_cached
from data.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_NEWSAPI_URL = "https://newsapi.org/v2/everything"

# VADER analyzer — instantiated once, reused across calls
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


def _get_api_key() -> str:
    key = os.environ.get("NEWSAPI_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "NEWSAPI_KEY is not set.\n"
            "  1. Sign up free at https://newsapi.org/register\n"
            "  2. Add NEWSAPI_KEY=your_key to your .env file"
        )
    return key


def _classify_category(text: str) -> str:
    """Assign an article to a supply chain category based on keyword matching.

    Parameters
    ----------
    text : str
        Lowercased title + description of the article.

    Returns
    -------
    str
        Category key (e.g. "energy", "ports"). Falls back to "geopolitical".
    """
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "geopolitical"


def _vader_to_severity(compound: float) -> str:
    """Map VADER compound score to a severity label.

    Parameters
    ----------
    compound : float
        VADER compound score (-1 to +1). Negative = negative sentiment.

    Returns
    -------
    str
        "high", "medium", or "low".
    """
    if compound <= -0.5:
        return "high"
    if compound <= -0.15:
        return "medium"
    return "low"


def fetch_supply_chain_news() -> tuple[float, list[dict]]:
    """Fetch supply chain news, analyze with VADER, and return scored alerts.

    Returns
    -------
    tuple[float, list[dict]]
        (geopolitical_score, alerts) where score is 0–100 and alerts
        are categorized dicts for the dashboard feed.
    """
    cache_key = "newsapi_vader"
    cached = get_cached(cache_key, ttl=1800)  # 30-min cache
    if cached is not None:
        return cached["score"], cached["alerts"]

    api_key = _get_api_key()
    from_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    # Query focuses on PHYSICAL supply chain (logistics, shipping, trade)
    # and excludes software/cyber supply chain noise.
    # Added explicit CHOKEPOINTS to the query.
    resp = requests.get(
        _NEWSAPI_URL,
        params={
            "q": (
                '("supply chain" OR "freight" OR "shipping") '
                'AND (port OR logistics OR cargo OR trade OR tariff OR canal OR strait OR "red sea" OR container)'
            ),
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 50,  # Increased fetch size
            "apiKey": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    articles = resp.json().get("articles", [])

    # --- Analyze each article with VADER ---
    score = 75.0  # baseline — start at "Moderate" to reflect inherent risk
    alerts: list[dict] = []
    negative_weight_total = 0.0

    for article in articles[:40]:  # Analyze more articles
        title = article.get("title") or ""
        description = article.get("description") or ""
        published = article.get("publishedAt", datetime.now().isoformat())
        full_text = f"{title}. {description}"

        # VADER sentiment analysis
        sentiment = _VADER.polarity_scores(full_text)
        compound = sentiment["compound"]

        # Only articles with negative sentiment affect the score
        if compound < -0.05:  # Lower threshold to catch more "slightly negative" news
            # Scale: compound of -1.0 → deduction of 8 pts, -0.5 → 4 pts
            deduction = abs(compound) * 8.0
            negative_weight_total += deduction

        # Classify into supply chain category
        text_lower = f"{title} {description}".lower()
        category = _classify_category(text_lower)
        severity = _vader_to_severity(compound)

        alerts.append({
            "timestamp": published,
            "severity": severity,
            "title": title,
            "body": description or "No description available.",
            "category": category,
            "sentiment": round(compound, 3),
        })

    # Apply total negative weight to score
    score = max(0.0, min(100.0, score - negative_weight_total))

    # Sort by severity (high first), then recency
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 2), a["timestamp"]), reverse=False)

    # Top 10 for the feed
    alerts = alerts[:10]

    result_score = round(score, 1)
    set_cached(cache_key, {"score": result_score, "alerts": alerts})
    logger.info(
        "News analysis: %d articles, %.1f negative weight, score=%.1f",
        len(articles), negative_weight_total, result_score,
    )
    return result_score, alerts


class GeopoliticalProvider(BaseProvider):
    """Geopolitical Risk — VADER sentiment analysis on supply chain news."""

    category = "geopolitical"

    def fetch_current(self) -> float:
        score, _ = fetch_supply_chain_news()
        return score

    def fetch_history(self, days: int) -> pd.Series:
        """NewsAPI free tier only covers the last few days.

        Returns a synthetic series anchored to the current score with
        realistic day-to-day variance. For real long-term history, you'd
        need a paid news archive or GDELT.
        """
        current = self.fetch_current()
        dates = pd.date_range(
            end=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            periods=days,
            freq="D",
        )
        rng = np.random.default_rng(seed=int(current * 100) + days)
        # Simulate realistic day-to-day news sentiment variance
        daily_noise = rng.normal(0, 2.5, size=days)
        values = np.empty(days)
        values[0] = current + rng.normal(0, 3)
        for i in range(1, days):
            # Mean-revert toward current score with noise
            pull = 0.08 * (current - values[i - 1])
            values[i] = values[i - 1] + pull + daily_noise[i]
        values = np.clip(values, 0, 100)
        values[-1] = current  # pin today's value
        return pd.Series(values.round(1), index=dates, name="geopolitical")
