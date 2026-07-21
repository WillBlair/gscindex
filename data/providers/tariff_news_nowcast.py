"""
Daily Trade-Policy News Nowcast
================================
EPUTRADE (the core tariffs signal) is a monthly FRED series — it only
updates once a month. This module supplies a genuinely DAILY nowcast so
the tariffs category can move on trade-war headlines instead of sitting
flat between prints.

Reuses the existing RSS + VADER pipeline (data/rss_fetcher.py) rather
than adding a new news source: it re-classifies already-fetched articles
into the "tariffs" bucket using the same keyword set the geopolitical
provider uses, then scores them the same volume-invariant way (top-N
most severe negative items, deduped, floored deduction).

Score Logic
-----------
    score = 100 + sum(top 5 most severe negative tariff-tagged articles)
            floored at -50, i.e. never below 50.0

Deliberately narrower/gentler floor than the main geopolitical score
(-60 over top 10) because this is a secondary signal blended at partial
weight into the tariffs category, not a standalone risk score — see
tariffs.py for the blend logic. Falls back to a neutral 85.0 with zero
articles found (no tariff news = no signal, not "everything is fine").
"""

from __future__ import annotations

import logging

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

_VADER = SentimentIntensityAnalyzer()

_TARIFF_KEYWORDS: set[str] = {
    "tariff", "trade war", "duty", "import ban", "export ban", "sanctions",
    "trade deal", "cbam", "trade policy", "customs", "trade tension",
    "retaliatory duty", "trade barrier", "wto dispute", "section 301",
    "anti-dumping",
}

_TOP_N = 5
_FLOOR = -50.0
_NEUTRAL_FALLBACK = 85.0


def _is_tariff_article(text: str) -> bool:
    return any(kw in text for kw in _TARIFF_KEYWORDS)


def _severity_from_vader(compound: float) -> float:
    """Scale VADER [-1, +1] into the same severity banding used elsewhere."""
    return round(compound * 6.0, 2)


def fetch_tariff_news_score() -> tuple[float, int, str]:
    """Return (score_0_100, matched_article_count, summary_str) for today's
    tariff/trade-policy news sentiment.

    Uses the same RSS pool the geopolitical provider already fetches (no
    extra network cost), so this is effectively free to compute on every
    cycle. Falls back to a neutral score if no tariff-tagged articles are
    found in the current window — silence isn't good news, it's absence
    of signal.
    """
    from data.rss_fetcher import fetch_rss_articles

    articles = fetch_rss_articles(max_items=60)
    if not articles:
        return _NEUTRAL_FALLBACK, 0, "No news data available"

    seen: set[str] = set()
    negatives: list[float] = []
    matched = 0

    for art in articles:
        title = (art.get("title") or "").strip()
        desc = (art.get("description") or "").strip()
        combined = f"{title} {desc}".lower()
        if not _is_tariff_article(combined):
            continue

        key = " ".join(title.lower().split())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        matched += 1

        compound = float(_VADER.polarity_scores(combined).get("compound", 0.0))
        severity = _severity_from_vader(compound)
        if severity < 0:
            negatives.append(severity)

    if matched == 0:
        return _NEUTRAL_FALLBACK, 0, "No tariff/trade-policy articles in current news window"

    worst = sorted(negatives)[:_TOP_N]
    deduction = max(_FLOOR, sum(worst))
    score = round(max(0.0, min(100.0, 100.0 + deduction)), 1)

    summary = f"{matched} trade-policy article(s) scanned, {len(negatives)} negative"
    return score, matched, summary
