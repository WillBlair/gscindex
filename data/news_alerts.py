"""
News Alerts (display only)
==========================
Supply chain headlines for the Headlines pane, the briefing, the /report page and the map's
news penalty. News feeds no category score (Geopolitical is the GPR index).

Claude scores headlines incrementally: every ``NEWS_AI_REFRESH_SECONDS`` the RSS feeds are
read and only headlines Claude has not judged yet are sent to ``analyze_news_batch``; earlier
severities and summaries are kept, and the newest ``NEWS_MAX_ALERTS`` alerts stay. The daily
full run (``AI_CACHE_TTL_SECONDS``) adds Claude web search and regenerates the briefing and
the full report. Between Claude runs the feeds are re-read every ``NEWS_RSS_REFRESH_SECONDS``
and new headlines join the cached alerts unscored (no Claude call); the next scoring run
scores them, even if they have left the feeds by then.

A failed Claude call keeps the cached alerts, flags the payload ``stale`` and retries after
``AI_FAILURE_RETRY_SECONDS``. A Claude result older than ``NEWS_CACHE_MAX_AGE_SECONDS`` is
dropped. With no API key, headlines are shown without a severity (``severity=None``,
``severity_label="unscored"``).

Topic tags use word-boundary keyword matching, so "port" does not match "report", "war" does
not match "warehouse" and "duty" does not match "heavy-duty".
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

from config import (
    AI_CACHE_TTL_SECONDS,
    AI_FAILURE_RETRY_SECONDS,
    AI_SEVERITY_MAX,
    CATEGORY_WEIGHTS,
    NEWS_AI_MAX_ARTICLES,
    NEWS_AI_REFRESH_SECONDS,
    NEWS_BRIEFING_CACHE_KEY,
    NEWS_BRIEFING_MAX_ALERTS,
    NEWS_CACHE_MAX_AGE_SECONDS,
    NEWS_MAX_ALERTS,
    NEWS_RSS_REFRESH_SECONDS,
)
from data import llm
from data.ai_analyst import analyze_news_batch, generate_briefing, generate_full_report
from data.cache import get_cached, set_cached
from data.news_selection import _normalized_title, parse_article_datetime
from data.rss_fetcher import fetch_rss_articles
from data.runtime import serialized
from data.web_news import merge_articles, search_supply_chain_news

logger = logging.getLogger(__name__)

NEWS_CACHE_KEY = NEWS_BRIEFING_CACHE_KEY
UNSCORED = "unscored"
OTHER_TOPIC = "other"


def _clamp_severity(value) -> float:
    """Model severities are documented as -10..+10; never trust the range."""
    try:
        sev = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-AI_SEVERITY_MAX, min(AI_SEVERITY_MAX, sev))


def _score_to_severity(score: float) -> str:
    """Map severity score to label."""
    if score <= -4: return "high"
    if score <= -1.5: return "medium"
    return "low"


def _numeric_sentiment(alert: dict) -> float:
    """The Claude severity, or 0 for an unscored headline (sorts as neutral)."""
    value = alert.get("sentiment")
    return float(value) if isinstance(value, (int, float)) else 0.0


def title_key(title) -> str:
    """Normalized title used to recognise a headline Claude has already judged."""
    return _normalized_title(str(title or ""))


# ---------------------------------------------------------------------------
# Topic classification keywords, keyed by the site's category keys (the headline
# topic filter). The FIRST matching category wins, most specific first; a headline
# matching none is tagged "other".
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "physical":      {"hurricane", "typhoon", "storm", "flood", "drought", "cyclone", "tornado", "wildfire", "earthquake"},
    "chokepoints":   {"red sea", "suez canal", "panama canal", "malacca strait", "strait of malacca", "strait of hormuz",
                      "bab el-mandeb", "bosporus", "dardanelles", "cape of good hope"},
    "supply_chain":  {"port", "congestion", "container terminal", "vessel queue", "berth", "dock worker", "longshoreman",
                      "dwell time", "inventory", "inventories", "shortage", "surplus", "consumer demand", "retail sales",
                      "stockpile", "backlog", "pmi"},
    "energy":        {"oil", "crude", "gas price", "fuel", "opec", "petroleum", "brent", "lng", "refinery", "refineries",
                      "pipeline", "energy cost", "diesel"},
    "tariffs":       {"tariff", "trade war", "duty", "duties", "import ban", "export ban", "sanctions", "trade deal", "cbam",
                      "trade policy", "customs"},
    "inputs":        {"copper", "aluminum", "aluminium", "steel price", "metal price", "raw material"},
    "freight":       {"freight rate", "container rate", "shipping cost", "blank sailing", "feu", "teu", "carrier", "maersk",
                      "hapag", "cosco"},
    "geopolitical":  {"war", "conflict", "missile", "blockade", "military", "coup", "protest", "unrest", "territory", "houthi"},
}

# Word boundaries, with two adjustments: a keyword may take a plural "s", and a hyphen
# before it blocks the match (so "duty" does not match "heavy-duty").
_TOPIC_PATTERNS: dict[str, re.Pattern] = {
    category: re.compile(
        r"(?<![\w-])(?:" + "|".join(map(re.escape, sorted(kws, key=len, reverse=True))) + r")s?\b"
    )
    for category, kws in _CATEGORY_KEYWORDS.items()
}


def classify_topic(text: str) -> str:
    """Topic tag for a headline: the first category whose keywords match on word boundaries."""
    lowered = str(text or "").lower()
    for category, pattern in _TOPIC_PATTERNS.items():
        if pattern.search(lowered):
            return category
    return OTHER_TOPIC


# Terms that indicate an article is clearly NOT about supply chains.
# If any of these appear in the title or body, the article is skipped
# before it is scored or matched to a port.
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


def _build_fallback_briefing(alerts: list[dict]) -> str:
    """Build a deterministic 3-bullet briefing when AI output is unavailable."""
    if not alerts:
        return (
            "• Live supply chain feeds are online, but no material disruptions were detected in the latest cycle.\n"
            "• No new headlines cleared the relevance filter in this cycle.\n"
            "• Monitoring remains active for weather, trade policy, and geopolitical events that could shift risk quickly."
        )

    # Most severe first, one headline per category so the three bullets
    # cover different risks instead of repeating one template.
    ranked = sorted(alerts, key=_numeric_sentiment)
    top: list[dict] = []
    seen: set[str] = set()
    for alert in ranked:
        category = str(alert.get("category", OTHER_TOPIC))
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


_FALLBACK_REPORT = (
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


# ---------------------------------------------------------------------------
# Cached payload
# ---------------------------------------------------------------------------

def cached_payload() -> dict | None:
    """The cached news payload (alerts, briefing, full_report, timestamps), if usable."""
    cached = get_cached(NEWS_CACHE_KEY, ttl=NEWS_CACHE_MAX_AGE_SECONDS)
    return cached if isinstance(cached, dict) else None


def scoring_label(payload: dict | None = None) -> str:
    """How the alerts in a payload (default: the cached one) were scored, for the UI."""
    payload = cached_payload() if payload is None else payload
    alerts = (payload or {}).get("alerts") or []
    if not any(a.get("scored_by") == "claude" for a in alerts):
        return "Unscored"
    return "Claude (stale)" if payload.get("stale") else "Claude"


def _due(payload: dict, field: str, interval: float, now: float) -> bool:
    """True when the run timed by ``payload[field]`` is older than ``interval``."""
    stamp = payload.get(field)
    return not isinstance(stamp, (int, float)) or now - float(stamp) > interval


def _published_sort_key(alert: dict) -> datetime:
    parsed = parse_article_datetime(alert.get("timestamp"))
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


def _merge_alerts(old: list[dict], new: list[dict]) -> list[dict]:
    """New alerts replace old ones with the same title key; newest NEWS_MAX_ALERTS kept."""
    replaced = {a["title_key"] for a in new}
    merged = new + [a for a in old if a.get("title_key") not in replaced]
    merged.sort(key=_published_sort_key, reverse=True)
    return merged[:NEWS_MAX_ALERTS]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def _candidates(articles: list[dict]) -> list[dict]:
    """Relevant articles with a title key, deduplicated by that key, feed order kept."""
    seen: set[str] = set()
    out: list[dict] = []
    for art in articles:
        title = str(art.get("title") or "").strip()
        description = str(art.get("description") or "").strip()
        key = title_key(title)
        if not key or key in seen or _is_irrelevant_article(f"{title} {description}".lower()):
            continue
        seen.add(key)
        out.append({
            "title": title, "description": description, "url": art.get("url") or "#",
            "source": art.get("source") or "Industry News",
            "published": art.get("published") or datetime.now(timezone.utc).isoformat(),
            "key": key,
        })
    return out


def _unscored_alert(c: dict) -> dict:
    description = c["description"]
    return {
        "timestamp": c["published"],
        "severity": None,
        "severity_label": UNSCORED,
        "title": c["title"],
        "body": (description[:240] + "...") if len(description) > 240 else description,
        "category": classify_topic(f"{c['title']} {description}"),
        "sentiment": None,
        "url": c["url"],
        "source": c["source"],
        "scored_by": None,
        "title_key": c["key"],
    }


def _alert_candidate(alert: dict) -> dict:
    """A cached alert back in candidate form, so Claude can score it after it left the feeds."""
    return {
        "title": str(alert.get("title") or ""), "description": str(alert.get("body") or ""),
        "url": alert.get("url") or "#", "source": alert.get("source") or "Industry News",
        "published": alert.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "key": alert["title_key"],
    }


def _claude_alert(c: dict, analysis: dict) -> dict:
    severity = _clamp_severity(analysis.get("severity_score", 0.0))
    label = _score_to_severity(severity)
    category = analysis.get("category")
    if category not in CATEGORY_WEIGHTS:
        category = classify_topic(f"{c['title']} {c['description']}")
    return {
        "timestamp": c["published"],
        "severity": label,
        "severity_label": label,
        "title": c["title"],
        "body": analysis.get("summary") or c["description"],
        "category": category,
        "sentiment": severity,
        "url": c["url"],
        "source": c["source"],
        "scored_by": "claude",
        "title_key": c["key"],
    }


def _briefing_inputs(alerts: list[dict]) -> list[dict]:
    """The top NEWS_BRIEFING_MAX_ALERTS alerts, most severe first then newest, as headline text."""
    newest_first = sorted(alerts, key=_published_sort_key, reverse=True)
    ranked = sorted(newest_first, key=_numeric_sentiment)  # stable: recency kept within a severity
    out = []
    for a in ranked[:NEWS_BRIEFING_MAX_ALERTS]:
        body = str(a.get("body") or "").strip()
        out.append({"title": f"{a.get('title', '')} - {body}" if body else str(a.get("title", ""))})
    return out


def _as_tuple(payload: dict) -> tuple[list[dict], str, str]:
    return payload.get("alerts") or [], payload.get("briefing") or "", payload.get("full_report") or ""


def _refresh(cached: dict, *, full: bool, now: float) -> dict:
    """One news update: score new headlines, merge, and (on the full run) rebuild the narrative."""
    articles = fetch_rss_articles(max_items=50)
    if full:
        # Web search runs only on the daily full run. Its articles go first so they are
        # inside the Claude window; RSS follows.
        articles = merge_articles(search_supply_chain_news(), articles)
    candidates = _candidates(articles)

    old_alerts = list(cached.get("alerts") or [])
    judged = set(cached.get("scored_titles") or [])
    claude_ok_at = cached.get("claude_ok_at")
    if not isinstance(claude_ok_at, (int, float)) or now - claude_ok_at > NEWS_CACHE_MAX_AGE_SECONDS:
        # The last Claude result stays up, flagged stale, for at most NEWS_CACHE_MAX_AGE_SECONDS.
        old_alerts = [a for a in old_alerts if a.get("scored_by") != "claude"]
        judged = set()
        claude_ok_at = None

    if not candidates and not old_alerts:
        # No articles is an outage, not "no news": the previous payload (if any) stays.
        raise RuntimeError("No RSS articles available from any feed")

    judged |= {a["title_key"] for a in old_alerts if a.get("scored_by") == "claude"}
    # Unscored alerts the hourly RSS refresh added that have since left the feeds.
    feed_keys = {c["key"] for c in candidates}
    pending = [_alert_candidate(a) for a in old_alerts
               if a.get("scored_by") != "claude" and a.get("title_key") and a["title_key"] not in feed_keys]
    to_score = [c for c in candidates + pending if c["key"] not in judged][:NEWS_AI_MAX_ARTICLES]

    configured = llm.is_configured()
    scoring_ok = True
    if not configured:
        present = {a.get("title_key") for a in old_alerts}
        alerts = _merge_alerts(old_alerts, [_unscored_alert(c) for c in candidates if c["key"] not in present])
    elif not to_score:
        alerts = old_alerts
        claude_ok_at = now
    else:
        batch = [{"id": i, "title": c["title"], "description": c["description"]} for i, c in enumerate(to_score)]
        results, _ = analyze_news_batch(batch)  # its briefing covers only the new items
        if results:
            logger.info("Claude scored %d new headlines", len(results))
            scored = [_claude_alert(c, results[i]) for i, c in enumerate(to_score)
                      if i in results and results[i].get("is_relevant", False)]
            rejected = {c["key"] for i, c in enumerate(to_score)
                        if i in results and not results[i].get("is_relevant", False)}
            judged |= {c["key"] for i, c in enumerate(to_score) if i in results}
            alerts = _merge_alerts([a for a in old_alerts if a.get("title_key") not in rejected], scored)
            claude_ok_at = now
        else:
            scoring_ok = False
            logger.warning("Claude news scoring failed; keeping %d cached alerts (stale).", len(old_alerts))
            if any(a.get("scored_by") == "claude" for a in old_alerts):
                alerts = old_alerts
            else:  # nothing Claude-scored to keep: show the headlines unscored
                present = {a.get("title_key") for a in old_alerts}
                alerts = _merge_alerts(old_alerts, [_unscored_alert(c) for c in candidates
                                                    if c["key"] not in present])

    candidate_keys = feed_keys | {c["key"] for c in pending}
    payload = dict(cached)
    payload.update({
        "alerts": alerts,
        "stale": configured and not scoring_ok,
        "claude_ok_at": claude_ok_at,
        # Titles Claude judged (relevant or not) that are still in the feeds, so they are
        # never re-sent; titles that have left the feeds drop out.
        "scored_titles": sorted(judged & candidate_keys),
        # A failed call retries after AI_FAILURE_RETRY_SECONDS instead of waiting a full
        # interval (or retrying every cycle).
        "alerts_scored_at": now if scoring_ok else now - NEWS_AI_REFRESH_SECONDS + AI_FAILURE_RETRY_SECONDS,
        "rss_refreshed_at": now,
    })

    if full:
        # The narrative is rebuilt from the merged alerts, not just this run's new headlines.
        # After a failed scoring call the paid report and briefing calls are skipped; the
        # cached ones stay and the whole full run retries after AI_FAILURE_RETRY_SECONDS.
        report = briefing = ""
        if configured and scoring_ok:
            report = (generate_full_report(candidates[:50]) or "").strip()
            briefing = (generate_briefing(_briefing_inputs(alerts)) or "").strip() if alerts else ""
        if not configured or (scoring_ok and not alerts):
            briefing = _build_fallback_briefing(alerts)
        full_ok = not configured or (scoring_ok and bool(report) and bool(briefing))
        payload["briefing"] = briefing or payload.get("briefing") or _build_fallback_briefing(alerts)
        if report:
            payload["full_report"], payload["generated_at"] = report, now
        elif not (payload.get("full_report") or "").strip():
            payload["full_report"], payload["generated_at"] = _FALLBACK_REPORT, now
        payload["ai_generated_at"] = now if full_ok else now - AI_CACHE_TTL_SECONDS + AI_FAILURE_RETRY_SECONDS
    elif not (payload.get("briefing") or "").strip():
        payload["briefing"] = _build_fallback_briefing(alerts)
    return payload


def _append_rss(cached: dict, now: float) -> dict:
    """Hourly: new RSS headlines join the cached alerts unscored. No Claude call.

    A headline already shown, or one Claude judged not relevant, is skipped (normalized title
    key). A feed failure keeps the cached alerts.
    """
    payload = dict(cached)
    payload["rss_refreshed_at"] = now
    try:
        candidates = _candidates(fetch_rss_articles(max_items=50))
    except Exception as exc:
        logger.warning("Hourly RSS refresh failed; keeping the cached alerts: %s", exc)
        return payload
    old_alerts = list(cached.get("alerts") or [])
    known = {a.get("title_key") for a in old_alerts} | set(cached.get("scored_titles") or [])
    new = [_unscored_alert(c) for c in candidates if c["key"] not in known]
    if new:
        logger.info("Hourly RSS refresh added %d unscored headlines", len(new))
        payload["alerts"] = _merge_alerts(old_alerts, new)
    return payload


@serialized
def fetch_supply_chain_news() -> tuple[list[dict], str, str]:
    """Headlines, briefing and full report for display. No score.

    Returns the cached payload until an incremental (``NEWS_AI_REFRESH_SECONDS``) or full
    (``AI_CACHE_TTL_SECONDS``) run is due, then updates and caches it. In between, every
    ``NEWS_RSS_REFRESH_SECONDS`` new RSS headlines are appended unscored. Raises
    ``RuntimeError`` when there are no articles and nothing cached.
    """
    now = time.time()
    cached = cached_payload() or {}
    full = _due(cached, "ai_generated_at", AI_CACHE_TTL_SECONDS, now)
    if full or _due(cached, "alerts_scored_at", NEWS_AI_REFRESH_SECONDS, now):
        payload = _refresh(cached, full=full, now=now)
    elif _due(cached, "rss_refreshed_at", NEWS_RSS_REFRESH_SECONDS, now):
        payload = _append_rss(cached, now)
    else:
        return _as_tuple(cached)
    set_cached(NEWS_CACHE_KEY, payload)
    return _as_tuple(payload)
