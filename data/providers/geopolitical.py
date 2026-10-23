"""
Geopolitical Risk Provider + News Intelligence Helpers
=======================================================
The Geopolitical category is the Caldara-Iacoviello daily Geopolitical Risk (GPR) index:
the 30-day mean, mapped on a log scale through its anchors (see ``GeopoliticalProvider``).
A stored Claude disruption register can be blended in through ``config.GEO_REGISTER_WEIGHT``
(0 for now).

The rest of this module is the older headline pipeline, kept until the aggregator stops
importing it (``fetch_supply_chain_news`` and the VADER helpers still feed the alerts,
briefing and map; the news score no longer reaches any category). It fetches supply chain
articles from curated RSS feeds, scores each article's severity (Claude, with VADER
sentiment as the fallback), and classifies it into the correct supply chain category.

VADER (Valence Aware Dictionary and sEntiment Reasoner) runs locally -
no AI API key needed. It produces a compound score from -1 (most negative) to +1
(most positive).

News severity score logic: deduplicate articles by title, take the 10 most severe negative
items, and deduct their summed severity from 100 (floored at -60 total). Positive news never
inflates the score; 100 means "no risk detected".
"""

from datetime import date, datetime, timezone
import logging
import math
import re
import time
from data.runtime import serialized
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
from config import (
    AI_CACHE_TTL_SECONDS,
    AI_FAILURE_RETRY_SECONDS,
    AI_SEVERITY_MAX,
    NEWS_BRIEFING_CACHE_KEY,
    NEWS_AI_MAX_ARTICLES,
    NEWS_CACHE_MAX_AGE_SECONDS,
    NEWS_RSS_REFRESH_SECONDS,
)
from data.cache import get_cached, set_cached
from data.database import get_last_category_score
from data.providers.base import BaseProvider
from data.providers.readings import (
    InputReading, blend_inputs, freshness_status, inputs_metadata, oldest_as_of)
from data.ai_analyst import analyze_news_batch
from data.sources import gpr
from scoring.anchors import get_anchor, score_raw

# ...

logger = logging.getLogger(__name__)

_VADER = SentimentIntensityAnalyzer()
_NEWS_CACHE_KEY = NEWS_BRIEFING_CACHE_KEY

# Labels for how the cached alerts were scored. The hourly RSS refresh
# re-scores with VADER, so the label has to follow the payload, not the
# pipeline that originally produced it.
SCORING_CLAUDE = "RSS + Claude AI"
SCORING_VADER = "RSS + VADER"


def _clamp_severity(value) -> float:
    """Model severities are documented as -10..+10; never trust the range."""
    try:
        sev = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-AI_SEVERITY_MAX, min(AI_SEVERITY_MAX, sev))


def _ai_refresh_due(cached: dict, now: float | None = None) -> bool:
    """True when the Claude analysis in the cached payload has expired.

    Uses a timestamp stored in the payload, not the cache file's mtime:
    the hourly RSS re-score rewrites the file, which used to reset the
    mtime clock so Claude never ran again after the first hour.
    """
    now = time.time() if now is None else now
    generated_at = cached.get("ai_generated_at")
    if not isinstance(generated_at, (int, float)):
        return True
    return now - float(generated_at) > AI_CACHE_TTL_SECONDS


def news_scoring_label() -> str:
    """Source label matching how the currently cached alerts were scored."""
    cached = get_cached(_NEWS_CACHE_KEY, ttl=NEWS_CACHE_MAX_AGE_SECONDS)
    if isinstance(cached, dict) and cached.get("scoring") == SCORING_CLAUDE:
        return SCORING_CLAUDE
    return SCORING_VADER

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
    "trading card", "magic: the gathering", "pokemon", "collectible",
    "board game", "video game", "toy",
    
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


# Consumer-goods terms are dropped only when the story has no supply chain
# anchor, so "Video game console shipments held at Long Beach port" stays
# relevant while "pokemon cards sell out" is dropped. They match on word
# boundaries (plural "s" allowed), so "toy" does not flag "Toyota".
_CONSUMER_GOODS_TERMS: frozenset[str] = frozenset({
    "trading card", "magic: the gathering", "pokemon", "collectible",
    "board game", "video game", "toy",
})
_SUPPLY_CHAIN_ANCHORS: frozenset[str] = frozenset({
    "port", "ports", "terminal", "shipping", "shipment", "shipments",
    "container", "freight", "carrier", "tariff", "tariffs", "customs",
    "import", "imports", "export", "exports", "sanction", "sanctions",
    "chip", "chips", "semiconductor", "shortage", "factory", "production",
    "suez", "panama canal", "red sea", "hormuz", "malacca",
})
_SUBSTRING_IRRELEVANT_TERMS: frozenset[str] = frozenset(_IRRELEVANT_TERMS - _CONSUMER_GOODS_TERMS)
_CONSUMER_GOODS_PATTERNS = [
    re.compile(rf"\b{re.escape(term)}s?\b") for term in sorted(_CONSUMER_GOODS_TERMS)
]
_SUPPLY_CHAIN_ANCHOR_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(a) for a in sorted(_SUPPLY_CHAIN_ANCHORS, key=len, reverse=True)) + r")\b"
)


def _is_irrelevant_article(text: str) -> bool:
    """Return True if the article text contains clearly off-topic terms."""
    if any(term in text for term in _SUBSTRING_IRRELEVANT_TERMS):
        return True
    if not any(pattern.search(text) for pattern in _CONSUMER_GOODS_PATTERNS):
        return False
    return _SUPPLY_CHAIN_ANCHOR_PATTERN.search(text) is None


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

    # Most severe first, one headline per category so the three bullets
    # cover different risks instead of repeating one template.
    ranked = sorted(alerts, key=lambda a: float(a.get("sentiment", 0.0)))
    top: list[dict] = []
    seen: set[str] = set()
    for alert in ranked:
        category = str(alert.get("category", "geopolitical"))
        if category in seen:
            continue
        seen.add(category)
        top.append(alert)
        if len(top) == 3:
            break
    bullets: list[str] = []
    for alert in top:
        title = str(alert.get("title", "Supply chain development")).strip().rstrip(".")
        source = str(alert.get("source", "news source")).strip()
        source = source[: -len("(web search)")].rstrip() if source.endswith("(web search)") else source
        if len(title) > 140:
            title = f"{title[:137]}..."
        bullets.append(f"• {title} ({source}).")

    while len(bullets) < 3:
        bullets.append(
            "• Additional signals remain mixed, with no new systemic trigger identified in the latest ingest."
        )
    return "\n".join(bullets[:3])


def _build_vader_alerts(candidates: list[dict]) -> list[dict]:
    """Generate alerts deterministically from RSS articles using VADER."""
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
    """Re-fetch RSS and re-score with VADER while keeping Claude briefing/report."""
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
    refreshed["scoring"] = SCORING_VADER
    refreshed["alerts_refreshed_at"] = time.time()
    if not (refreshed.get("briefing") or "").strip():
        refreshed["briefing"] = _build_fallback_briefing(alerts)
    return refreshed


def _get_cached_news_tuple() -> tuple[float, list[dict], str, str] | None:
    """Return cached news analysis tuple if available, else None.

    This is intentionally fast and non-blocking so provider calls never trigger
    long AI/RSS fetches. Fresh news fetch runs in the aggregator job.
    """
    cached = get_cached(_NEWS_CACHE_KEY, ttl=NEWS_CACHE_MAX_AGE_SECONDS)
    if not cached:
        return None
    return (
        float(cached.get("score", 85.0)),
        cached.get("alerts", []),
        cached.get("briefing", ""),
        cached.get("full_report", ""),
    )


@serialized
def fetch_supply_chain_news() -> tuple[float, list[dict], str, str]:
    """Fetch news and analyze using AI (Claude) with VADER fallback.
    
    Returns
    -------
    tuple
        (score, alerts, briefing_text, full_report_md)
    """
    cache_key = _NEWS_CACHE_KEY
    cached = get_cached(cache_key, ttl=NEWS_CACHE_MAX_AGE_SECONDS)
    if cached is not None and _ai_refresh_due(cached):
        logger.info("Claude news analysis is due; regenerating.")
        cached = None
    if cached is not None:
        alerts_age = time.time() - float(cached.get("alerts_refreshed_at") or 0)
        if alerts_age > NEWS_RSS_REFRESH_SECONDS:
            try:
                refreshed = _refresh_cached_news_from_rss(cached)
                if refreshed:
                    set_cached(cache_key, refreshed)
                    cached = refreshed
                    logger.info(
                        "Refreshed news score/alerts from RSS (alerts age %.0fs)",
                        alerts_age,
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
    from data.web_news import merge_articles, search_supply_chain_news

    rss_articles = fetch_rss_articles(max_items=50)
    # Web search runs only here (once per AI refresh, ~daily). Its articles
    # go first so they are inside the Claude analysis window; RSS follows.
    web_articles = search_supply_chain_news()
    rss_articles = merge_articles(web_articles, rss_articles)

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

    # No articles is an outage, not "no risk": raising lets the aggregator
    # keep the cached or flagged-fallback geopolitical score instead of
    # publishing a perfect 100 built from zero articles.
    if not candidates:
        raise RuntimeError("No RSS articles available from any feed")

    # Claude scores the first NEWS_AI_MAX_ARTICLES items (web results, then RSS).
    ai_candidates = candidates[:NEWS_AI_MAX_ARTICLES]
    
    # 3. Analyze with Claude
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
                
            severity = _clamp_severity(analysis.get("severity_score", 0.0))
            
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
                "scored_by": "claude",
            })
    
    # Fallback VADER for non-AI analyzed items or if AI failed
    if not alerts and candidates:
        logger.warning(
            "Claude returned no usable alerts; using deterministic VADER fallback for %d candidates.",
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

    now = time.time()
    claude_scored = bool(ai_results) and any(a.get("scored_by") == "claude" for a in alerts)
    result = {
        "score": final_score,
        "alerts": alerts,
        "briefing": briefing_text,
        "full_report": full_report_md,
        "scoring": SCORING_CLAUDE if claude_scored else SCORING_VADER,
        "alerts_refreshed_at": now,
        "generated_at": now,
        # A failed Claude run retries after AI_FAILURE_RETRY_SECONDS instead
        # of waiting a full AI_CACHE_TTL_SECONDS (or retrying every cycle).
        "ai_generated_at": (
            now if claude_scored else now - AI_CACHE_TTL_SECONDS + AI_FAILURE_RETRY_SECONDS
        ),
    }
    
    set_cached(cache_key, result)
    return result["score"], result["alerts"], result["briefing"], result["full_report"]


_GPR, _REGISTER = "gpr", "geo_register"
_GPR_SOURCE = "Caldara\u2013Iacoviello GPR (daily)"
_REGISTER_SOURCE = "Claude disruption register (stored score)"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _gpr_mean() -> tuple[pd.Series, date]:
    """Rolling 30-row mean of the daily index and the file's last date.

    Days without enough observations behind them stay NaN; the file is the publication,
    so the mean is dated by the day it covers.
    """
    daily = gpr.fetch_gpr_daily()
    mean = daily.rolling(config.GPR_MEAN_DAYS, min_periods=config.GPR_MIN_PERIODS).mean()
    return mean, daily.index[-1].date()


def _safe_score(value: float, anchor: dict) -> float:
    if not (math.isfinite(value) and (anchor["transform"] != "log" or value > 0)):
        return float("nan")
    return score_raw(value, anchor)


class GeopoliticalProvider(BaseProvider):
    """Geopolitical Risk - the Caldara-Iacoviello daily GPR index (30-day mean), with a hook
    for the stored Claude disruption register (``config.GEO_REGISTER_WEIGHT``, 0 for now)."""

    category = "geopolitical"

    # ------------------------------------------------------------------ current

    @staticmethod
    def _gpr_reading(today: date, anchor: dict) -> tuple[InputReading, float | None]:
        try:
            mean, as_of = _gpr_mean()
            value = float(mean.iloc[-1])
            score = _safe_score(value, anchor)
            if not math.isfinite(score):
                raise ValueError(f"no usable 30-day mean ({value})")
            reading = InputReading(
                _GPR, score, as_of, _GPR_SOURCE, f"GPR {config.GPR_MEAN_DAYS}-day mean {value:.0f}",
                freshness_status(as_of, today, _GPR))
            return reading, value
        except Exception as exc:
            logger.warning("GPR unavailable: %s", exc)
            return InputReading(_GPR, None, None, _GPR_SOURCE, status="missing"), None

    @staticmethod
    def _register_reading(today: date) -> InputReading:
        try:
            row = get_last_category_score(_REGISTER)
        except Exception as exc:
            logger.warning("Disruption register unavailable: %s", exc)
            row = None
        if row is None:
            return InputReading(_REGISTER, None, None, _REGISTER_SOURCE, status="missing")
        as_of, score = row
        return InputReading(_REGISTER, score, as_of, _REGISTER_SOURCE, f"register score {score:.0f}",
                            freshness_status(as_of, today, _REGISTER))

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchor = get_anchor(_GPR)
        register_weight = config.GEO_REGISTER_WEIGHT
        weights = {_GPR: 1.0 - register_weight, _REGISTER: register_weight}

        reading, gpr_value = self._gpr_reading(today, anchor)
        readings = [reading]
        if register_weight > 0:
            readings.append(self._register_reading(today))

        score, status = blend_inputs(readings, weights)
        if score is None:
            raise RuntimeError("no geopolitical input available: " + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        sentences = []
        if reading in used:
            sentences.append(
                "The Geopolitical Risk index counts newspaper coverage of geopolitical tensions, "
                "both threats and acts, across major newspapers each day. Its "
                f"{config.GPR_MEAN_DAYS}-day average was {gpr_value:.0f}, against a normal level "
                "set at the pre-2020 median.")
        if len(used) > 1:
            sentences.append(
                f"Blended with the stored disruption register score at {register_weight:.0%} weight.")
        metadata = {
            "source": "; ".join(r.source for r in used),
            "raw_value": " / ".join(r.raw_value for r in used),
            "raw_label": f"Geopolitical Risk index ({config.GPR_MEAN_DAYS}-day mean)",
            "description": " ".join(sentences),
            "calculation": (
                f"The {config.GPR_MEAN_DAYS}-day mean of the daily index is mapped on a log scale "
                "through its anchors (healthiest 5% of pre-2020 history = 100, pre-2020 median = 80, "
                "the record monthly GPR, October 2001 = 0)."
                + (f" Weights: GPR {weights[_GPR]:.0%}, disruption register {register_weight:.0%},"
                   " renormalized over the inputs available." if register_weight > 0 else "")),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    def fetch_history(self, days: int) -> pd.Series:
        """Daily GPR scores at the file's own dates, the last ``days`` calendar days.

        The file is the publication, so nothing is shifted by a lag and the series never runs
        past the file's last date. Days before the first usable 30-day mean stay NaN.
        The register has no history source, so it is not blended in here.
        """
        anchor = get_anchor(_GPR)
        try:
            mean, last = _gpr_mean()
        except Exception as exc:
            raise RuntimeError(f"no GPR history available: {exc}") from exc
        scores = pd.Series([_safe_score(v, anchor) for v in mean], index=mean.index)
        window = pd.date_range(end=pd.Timestamp(last), periods=days, freq="D")
        out = scores.reindex(window).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no GPR history available")
        return out.rename("geopolitical")
