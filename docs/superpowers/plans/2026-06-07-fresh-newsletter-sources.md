# Fresh Newsletter Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard news layer and morning newsletter fresher, less repetitive, and better grounded in current public supply-chain risk sources.

**Architecture:** Split news ingestion into source configuration, article normalization, freshness selection, and newsletter briefing generation. The dashboard can keep using cached news for responsiveness, while the newsletter builds a daily digest from fresh selected articles and only reuses today's digest for retry safety.

**Tech Stack:** Python 3.11, `feedparser`, existing file cache helpers in `data/cache.py`, existing Gemini wrapper in `data/ai_analyst.py`, existing newsletter script in `scripts/send_newsletter.py`, focused `pytest` tests.

---

## File Structure

- Create `data/news_sources.py`: typed source definitions grouped by signal type, with official/public source URLs and per-source caps.
- Create `data/news_selection.py`: pure helpers for canonical URLs, article fingerprints, date parsing, dedupe, freshness filtering, and source diversity selection.
- Modify `data/rss_fetcher.py`: fetch from `NEWS_SOURCES`, tag every article with `source_group`, remove random shuffling, and return stable freshness-ranked articles.
- Modify `data/ai_analyst.py`: add a newsletter-specific briefing generator that uses article titles, descriptions, sources, groups, and score movement context.
- Modify `scripts/send_newsletter.py`: build or fetch a daily newsletter briefing instead of blindly reusing the dashboard briefing.
- Add `tests/test_news_selection.py`: unit tests for pure selection behavior.
- Add `tests/test_rss_fetcher.py`: parser-level tests with monkeypatched `feedparser.parse`.
- Add `tests/test_newsletter_digest.py`: tests for newsletter cache behavior and fallback handling.

## Initial Source Set

Use free/public feeds only. Avoid paid APIs and broad SEO aggregators.

```python
NEWS_SOURCES = [
    # Existing logistics trade sources
    {"name": "Supply Chain Dive", "url": "https://www.supplychaindive.com/feeds/news/", "group": "logistics_trade", "max_items": 8},
    {"name": "FreightWaves", "url": "https://www.freightwaves.com/feed", "group": "logistics_trade", "max_items": 8},
    {"name": "SupplyChainBrain", "url": "https://www.supplychainbrain.com/rss/articles", "group": "logistics_trade", "max_items": 6},
    {"name": "SupplyChainBrain Last Mile", "url": "https://www.supplychainbrain.com/rss/topic/296-last-mile-delivery", "group": "logistics_trade", "max_items": 4},
    {"name": "Logistics Management Transportation", "url": "https://www.logisticsmgmt.com/rss/topic/transportation_news", "group": "logistics_trade", "max_items": 6},
    {"name": "Logistics Management Ocean Freight", "url": "https://www.logisticsmgmt.com/rss/topic/ocean_freight", "group": "ports_shipping", "max_items": 6},
    {"name": "gCaptain", "url": "https://gcaptain.com/feed/", "group": "ports_shipping", "max_items": 6},
    {"name": "Splash 247", "url": "https://splash247.com/feed/", "group": "ports_shipping", "max_items": 6},
    {"name": "The Loadstar", "url": "https://theloadstar.com/feed/", "group": "ports_shipping", "max_items": 6},
    {"name": "Maritime Executive", "url": "https://www.maritime-executive.com/rss/news", "group": "ports_shipping", "max_items": 6},
    {"name": "Supply Chain Management Review", "url": "https://www.scmr.com/rss/resources", "group": "logistics_trade", "max_items": 4},
    {"name": "Logistics Viewpoints", "url": "https://logisticsviewpoints.com/feed/", "group": "logistics_trade", "max_items": 4},

    # Official/public risk sources
    {"name": "WTO News", "url": "http://www.wto.org/library/rss/latest_news_e.xml", "group": "trade_policy", "max_items": 5},
    {"name": "GDACS Disaster Alerts", "url": "https://www.gdacs.org/xml/rss.xml", "group": "weather_disasters", "max_items": 8},
    {"name": "NHC Atlantic Tropical Cyclones", "url": "https://www.nhc.noaa.gov/index-at.xml", "group": "weather_disasters", "max_items": 5},
    {"name": "NHC Eastern Pacific Tropical Cyclones", "url": "https://www.nhc.noaa.gov/index-ep.xml", "group": "weather_disasters", "max_items": 5},
    {"name": "NHC Atlantic Tropical Weather Outlook", "url": "https://www.nhc.noaa.gov/xml/TWOAT.xml", "group": "weather_disasters", "max_items": 3},
    {"name": "NHC Atlantic High Seas Forecast", "url": "https://www.nhc.noaa.gov/xml/HSFAT2.xml", "group": "weather_disasters", "max_items": 3},
]
```

Defer public HTML page scraping for USTR, Panama Canal, and Suez Canal until after this RSS pass is stable. Those sources matter, but they require source-specific parsing and should not be mixed into the RSS refactor.

---

### Task 1: Add Source Configuration

**Files:**
- Create: `data/news_sources.py`
- Test: `tests/test_news_sources.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_news_sources.py`:

```python
from data.news_sources import NEWS_SOURCES, SOURCE_GROUPS, get_sources_by_group


def test_news_sources_have_required_fields():
    for source in NEWS_SOURCES:
        assert source["name"]
        assert source["url"].startswith(("http://", "https://"))
        assert source["group"] in SOURCE_GROUPS
        assert isinstance(source["max_items"], int)
        assert source["max_items"] > 0


def test_source_groups_include_official_risk_buckets():
    assert {"logistics_trade", "ports_shipping", "trade_policy", "weather_disasters"}.issubset(SOURCE_GROUPS)


def test_get_sources_by_group_filters_without_mutating():
    logistics = get_sources_by_group("logistics_trade")

    assert logistics
    assert all(source["group"] == "logistics_trade" for source in logistics)
    assert logistics is not NEWS_SOURCES
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_news_sources.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'data.news_sources'`.

- [ ] **Step 3: Implement source configuration**

Create `data/news_sources.py`:

```python
"""Public news source configuration for supply-chain intelligence."""
from __future__ import annotations

from typing import TypedDict


class NewsSource(TypedDict):
    name: str
    url: str
    group: str
    max_items: int


SOURCE_GROUPS: set[str] = {
    "logistics_trade",
    "ports_shipping",
    "trade_policy",
    "weather_disasters",
}


NEWS_SOURCES: list[NewsSource] = [
    {"name": "Supply Chain Dive", "url": "https://www.supplychaindive.com/feeds/news/", "group": "logistics_trade", "max_items": 8},
    {"name": "FreightWaves", "url": "https://www.freightwaves.com/feed", "group": "logistics_trade", "max_items": 8},
    {"name": "SupplyChainBrain", "url": "https://www.supplychainbrain.com/rss/articles", "group": "logistics_trade", "max_items": 6},
    {"name": "SupplyChainBrain Last Mile", "url": "https://www.supplychainbrain.com/rss/topic/296-last-mile-delivery", "group": "logistics_trade", "max_items": 4},
    {"name": "Logistics Management Transportation", "url": "https://www.logisticsmgmt.com/rss/topic/transportation_news", "group": "logistics_trade", "max_items": 6},
    {"name": "Logistics Management Ocean Freight", "url": "https://www.logisticsmgmt.com/rss/topic/ocean_freight", "group": "ports_shipping", "max_items": 6},
    {"name": "gCaptain", "url": "https://gcaptain.com/feed/", "group": "ports_shipping", "max_items": 6},
    {"name": "Splash 247", "url": "https://splash247.com/feed/", "group": "ports_shipping", "max_items": 6},
    {"name": "The Loadstar", "url": "https://theloadstar.com/feed/", "group": "ports_shipping", "max_items": 6},
    {"name": "Maritime Executive", "url": "https://www.maritime-executive.com/rss/news", "group": "ports_shipping", "max_items": 6},
    {"name": "Supply Chain Management Review", "url": "https://www.scmr.com/rss/resources", "group": "logistics_trade", "max_items": 4},
    {"name": "Logistics Viewpoints", "url": "https://logisticsviewpoints.com/feed/", "group": "logistics_trade", "max_items": 4},
    {"name": "WTO News", "url": "http://www.wto.org/library/rss/latest_news_e.xml", "group": "trade_policy", "max_items": 5},
    {"name": "GDACS Disaster Alerts", "url": "https://www.gdacs.org/xml/rss.xml", "group": "weather_disasters", "max_items": 8},
    {"name": "NHC Atlantic Tropical Cyclones", "url": "https://www.nhc.noaa.gov/index-at.xml", "group": "weather_disasters", "max_items": 5},
    {"name": "NHC Eastern Pacific Tropical Cyclones", "url": "https://www.nhc.noaa.gov/index-ep.xml", "group": "weather_disasters", "max_items": 5},
    {"name": "NHC Atlantic Tropical Weather Outlook", "url": "https://www.nhc.noaa.gov/xml/TWOAT.xml", "group": "weather_disasters", "max_items": 3},
    {"name": "NHC Atlantic High Seas Forecast", "url": "https://www.nhc.noaa.gov/xml/HSFAT2.xml", "group": "weather_disasters", "max_items": 3},
]


def get_sources_by_group(group: str) -> list[NewsSource]:
    """Return configured sources for a source group."""
    return [source for source in NEWS_SOURCES if source["group"] == group]
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_news_sources.py -v
```

Expected: PASS.

---

### Task 2: Add Article Selection Helpers

**Files:**
- Create: `data/news_selection.py`
- Test: `tests/test_news_selection.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_news_selection.py`:

```python
from datetime import datetime, timedelta, timezone

from data.news_selection import (
    article_fingerprint,
    canonicalize_url,
    dedupe_articles,
    parse_article_datetime,
    select_fresh_articles,
)


def test_canonicalize_url_removes_tracking_and_fragment():
    url = "https://example.com/story?utm_source=x&id=123#section"

    assert canonicalize_url(url) == "https://example.com/story?id=123"


def test_article_fingerprint_uses_canonical_url_when_present():
    first = {"title": "Port strike escalates", "url": "https://example.com/a?utm_campaign=x"}
    second = {"title": "Different title", "url": "https://example.com/a"}

    assert article_fingerprint(first) == article_fingerprint(second)


def test_parse_article_datetime_returns_aware_utc_datetime():
    parsed = parse_article_datetime("2026-06-07T12:30:00Z")

    assert parsed.tzinfo is not None
    assert parsed.isoformat() == "2026-06-07T12:30:00+00:00"


def test_dedupe_articles_removes_duplicate_urls_and_titles():
    articles = [
        {"title": "Port Strike Escalates", "url": "https://example.com/a", "published": "2026-06-07T12:00:00Z"},
        {"title": "Port strike escalates!", "url": "https://other.com/b", "published": "2026-06-07T13:00:00Z"},
        {"title": "Diesel prices fall", "url": "https://example.com/c", "published": "2026-06-07T14:00:00Z"},
    ]

    unique = dedupe_articles(articles)

    assert [article["title"] for article in unique] == ["Port Strike Escalates", "Diesel prices fall"]


def test_select_fresh_articles_prefers_recent_and_diverse_sources():
    now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    articles = [
        {
            "title": "Fresh logistics story",
            "url": "https://example.com/1",
            "published": (now - timedelta(hours=2)).isoformat(),
            "source": "A",
            "source_group": "logistics_trade",
        },
        {
            "title": "Fresh weather story",
            "url": "https://example.com/2",
            "published": (now - timedelta(hours=3)).isoformat(),
            "source": "B",
            "source_group": "weather_disasters",
        },
        {
            "title": "Old trade story",
            "url": "https://example.com/3",
            "published": (now - timedelta(days=6)).isoformat(),
            "source": "C",
            "source_group": "trade_policy",
        },
    ]

    selected = select_fresh_articles(articles, now=now, max_items=5, fresh_hours=36, fallback_hours=72)

    assert [article["title"] for article in selected] == ["Fresh logistics story", "Fresh weather story"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_news_selection.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'data.news_selection'`.

- [ ] **Step 3: Implement article selection helpers**

Create `data/news_selection.py`:

```python
"""Freshness and diversity helpers for news article selection."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def canonicalize_url(url: str) -> str:
    """Normalize URLs so tracking params do not defeat dedupe."""
    if not url:
        return ""

    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_PARAMS and not key.startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def _normalized_title(title: str) -> str:
    tokens = [token for token in _TITLE_TOKEN_RE.split(title.lower()) if token]
    return " ".join(tokens[:14])


def article_fingerprint(article: dict) -> str:
    """Return a stable identifier for an article."""
    canonical_url = canonicalize_url(str(article.get("url", "")))
    basis = canonical_url or _normalized_title(str(article.get("title", "")))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def parse_article_datetime(value: object) -> datetime | None:
    """Parse common feed date formats into timezone-aware UTC datetimes."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dedupe_articles(articles: list[dict]) -> list[dict]:
    """Remove duplicate URLs and near-identical titles while preserving order."""
    seen_fingerprints: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict] = []

    for article in articles:
        fingerprint = article_fingerprint(article)
        title_key = _normalized_title(str(article.get("title", "")))
        if fingerprint in seen_fingerprints or title_key in seen_titles:
            continue
        seen_fingerprints.add(fingerprint)
        if title_key:
            seen_titles.add(title_key)
        enriched = dict(article)
        enriched["fingerprint"] = fingerprint
        unique.append(enriched)

    return unique


def select_fresh_articles(
    articles: list[dict],
    *,
    now: datetime | None = None,
    max_items: int = 30,
    fresh_hours: int = 36,
    fallback_hours: int = 72,
    per_source_limit: int = 4,
    per_group_limit: int = 10,
) -> list[dict]:
    """Select recent articles with source and group diversity caps."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)

    fresh: list[tuple[datetime, dict]] = []
    fallback: list[tuple[datetime, dict]] = []
    for article in dedupe_articles(articles):
        published_at = parse_article_datetime(article.get("published"))
        if not published_at:
            continue
        age_hours = (reference - published_at).total_seconds() / 3600
        enriched = dict(article)
        enriched["published_at"] = published_at.isoformat()
        if 0 <= age_hours <= fresh_hours:
            fresh.append((published_at, enriched))
        elif fresh_hours < age_hours <= fallback_hours:
            fallback.append((published_at, enriched))

    ranked = sorted(fresh, key=lambda item: item[0], reverse=True)
    if len(ranked) < max_items:
        ranked.extend(sorted(fallback, key=lambda item: item[0], reverse=True))

    selected: list[dict] = []
    source_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for _published_at, article in ranked:
        source = str(article.get("source", "Unknown"))
        group = str(article.get("source_group", "unknown"))
        if source_counts.get(source, 0) >= per_source_limit:
            continue
        if group_counts.get(group, 0) >= per_group_limit:
            continue
        selected.append(article)
        source_counts[source] = source_counts.get(source, 0) + 1
        group_counts[group] = group_counts.get(group, 0) + 1
        if len(selected) >= max_items:
            break

    return selected
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_news_selection.py -v
```

Expected: PASS.

---

### Task 3: Refactor RSS Fetcher Around Sources and Freshness

**Files:**
- Modify: `data/rss_fetcher.py`
- Test: `tests/test_rss_fetcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rss_fetcher.py`:

```python
from types import SimpleNamespace

from data.news_sources import NewsSource
from data.rss_fetcher import fetch_single_feed, fetch_rss_articles


def _entry(title, link, published="2026-06-07T12:00:00Z", summary="Summary"):
    return {
        "title": title,
        "link": link,
        "published": published,
        "summary": summary,
    }


def test_fetch_single_feed_tags_source_group(monkeypatch):
    source: NewsSource = {
        "name": "Test Feed",
        "url": "https://example.com/feed",
        "group": "trade_policy",
        "max_items": 2,
    }

    def fake_parse(url):
        assert url == source["url"]
        return SimpleNamespace(
            bozo=False,
            feed={"title": "Ignored Feed Title"},
            entries=[_entry("Tariff update", "https://example.com/a")],
        )

    monkeypatch.setattr("data.rss_fetcher.feedparser.parse", fake_parse)

    articles = fetch_single_feed(source)

    assert articles == [
        {
            "title": "Tariff update",
            "description": "Summary",
            "url": "https://example.com/a",
            "source": "Test Feed",
            "source_group": "trade_policy",
            "published": "2026-06-07T12:00:00Z",
            "is_rss": True,
        }
    ]


def test_fetch_rss_articles_is_stable_and_deduped(monkeypatch):
    sources = [
        {"name": "A", "url": "https://example.com/a.xml", "group": "logistics_trade", "max_items": 4},
        {"name": "B", "url": "https://example.com/b.xml", "group": "weather_disasters", "max_items": 4},
    ]

    def fake_fetch(source):
        if source["name"] == "A":
            return [
                {
                    "title": "Older item",
                    "description": "old",
                    "url": "https://example.com/old",
                    "source": "A",
                    "source_group": "logistics_trade",
                    "published": "2026-06-06T12:00:00Z",
                    "is_rss": True,
                }
            ]
        return [
            {
                "title": "Newer item",
                "description": "new",
                "url": "https://example.com/new?utm_source=x",
                "source": "B",
                "source_group": "weather_disasters",
                "published": "2026-06-07T12:00:00Z",
                "is_rss": True,
            },
            {
                "title": "Newer item!",
                "description": "duplicate",
                "url": "https://other.com/duplicate",
                "source": "B",
                "source_group": "weather_disasters",
                "published": "2026-06-07T13:00:00Z",
                "is_rss": True,
            },
        ]

    monkeypatch.setattr("data.rss_fetcher.NEWS_SOURCES", sources)
    monkeypatch.setattr("data.rss_fetcher.fetch_single_feed", fake_fetch)

    articles = fetch_rss_articles(max_items=10)

    assert [article["title"] for article in articles] == ["Newer item", "Older item"]
```

- [ ] **Step 2: Run test to verify it fails against current implementation**

Run:

```bash
pytest tests/test_rss_fetcher.py -v
```

Expected: FAIL because `fetch_single_feed` currently accepts a URL string and does not tag `source_group`.

- [ ] **Step 3: Update `data/rss_fetcher.py`**

Replace the module with this implementation:

```python
"""RSS fetcher for public supply-chain intelligence feeds."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import feedparser

from data.news_selection import dedupe_articles, parse_article_datetime
from data.news_sources import NEWS_SOURCES, NewsSource

logger = logging.getLogger(__name__)


def parse_pub_date(entry) -> str:
    """Robustly extract and normalize publication date."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6]).isoformat()

    raw_date = entry.get("published", "") or entry.get("updated", "") or entry.get("pubDate", "")
    if not raw_date:
        return datetime.utcnow().isoformat()
    return str(raw_date)


def fetch_single_feed(source: NewsSource) -> list[dict]:
    """Fetch and normalize a single RSS feed."""
    articles: list[dict] = []
    try:
        feed = feedparser.parse(source["url"])
        if feed.bozo:
            logger.warning("RSS parse warning for %s: %s", source["url"], feed.bozo_exception)

        for entry in feed.entries[: source["max_items"]]:
            title = str(entry.get("title", "No Title")).strip()
            link = str(entry.get("link", "#")).strip()
            description = str(entry.get("summary", "") or entry.get("description", "")).strip()
            articles.append(
                {
                    "title": title,
                    "description": description[:800],
                    "url": link,
                    "source": source["name"],
                    "source_group": source["group"],
                    "published": parse_pub_date(entry),
                    "is_rss": True,
                }
            )
    except Exception as exc:
        logger.error("Failed to fetch RSS %s: %s", source["url"], exc)

    return articles


def _sort_key(article: dict) -> datetime:
    parsed = parse_article_datetime(article.get("published"))
    return parsed or datetime.min


def fetch_rss_articles(max_items: int = 60) -> list[dict]:
    """Fetch configured RSS feeds and return deduped, newest-first articles."""
    all_articles: list[dict] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_source = {executor.submit(fetch_single_feed, source): source for source in NEWS_SOURCES}
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            try:
                all_articles.extend(future.result())
            except Exception as exc:
                logger.error("RSS worker failed for %s: %s", source["name"], exc)

    unique_articles = dedupe_articles(all_articles)
    unique_articles.sort(key=_sort_key, reverse=True)

    logger.info("Fetched %d unique articles from RSS feeds.", len(unique_articles))
    return unique_articles[:max_items]
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_news_sources.py tests/test_news_selection.py tests/test_rss_fetcher.py -v
```

Expected: PASS.

---

### Task 4: Add Newsletter-Specific Briefing Generation

**Files:**
- Modify: `data/ai_analyst.py`
- Test: `tests/test_newsletter_digest.py`

- [ ] **Step 1: Write failing test for prompt construction fallback**

Create `tests/test_newsletter_digest.py` with the first test:

```python
from data.ai_analyst import generate_newsletter_briefing


def test_generate_newsletter_briefing_returns_fallback_without_articles():
    result = generate_newsletter_briefing([], score=72.4, tier_label="Stable", score_delta=None)

    assert "No fresh public-source supply chain articles" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_newsletter_digest.py -v
```

Expected: FAIL because `generate_newsletter_briefing` does not exist.

- [ ] **Step 3: Add newsletter briefing function**

Append to `data/ai_analyst.py` after `generate_briefing`:

```python
def generate_newsletter_briefing(
    articles: list[dict],
    *,
    score: float,
    tier_label: str,
    score_delta: float | None,
) -> str:
    """Generate a morning newsletter briefing from selected fresh articles."""
    if not articles:
        return (
            "• No fresh public-source supply chain articles cleared the relevance filter this morning; "
            f"the index is {score:.1f}/100 ({tier_label}) based on current market, weather, freight, and policy signals."
        )

    if not api_key:
        top = articles[:4]
        bullets = []
        for article in top:
            bullets.append(
                "• "
                f"{article.get('title', 'Supply chain update')} "
                f"({article.get('source', 'public source')}, {article.get('source_group', 'news').replace('_', ' ')})."
            )
        return "\n".join(bullets)

    delta_text = "unchanged"
    if score_delta is not None:
        sign = "+" if score_delta >= 0 else ""
        delta_text = f"{sign}{score_delta:.1f} points versus the previous recorded score"

    model = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        generation_config=BRIEFING_CONFIG,
    )

    prompt_lines = [
        "You are writing the morning email for the Global Supply Chain Index.",
        f"Current score: {score:.1f}/100 ({tier_label}); movement: {delta_text}.",
        "Use ONLY the public-source articles below.",
        "Write 4 bullets, each one sentence, plain text, each starting with '•'.",
        "The bullets must cover: what changed overnight, top logistics risk, market/policy signal, and why the score is credible.",
        "Mention source names naturally when useful. Do not invent facts, numbers, or disruptions.",
        "Avoid generic phrases like 'monitoring remains active' unless there is no fresh signal.",
        "",
        "Fresh articles:",
    ]
    for article in articles[:20]:
        prompt_lines.append(
            "- "
            f"[{article.get('source_group', 'news')}] "
            f"{article.get('title', 'Untitled')} "
            f"({article.get('source', 'public source')}, {article.get('published', 'unknown date')}): "
            f"{str(article.get('description', ''))[:220]}"
        )

    try:
        response = model.generate_content("\n".join(prompt_lines))
        return response.text.strip()
    except Exception as exc:
        logger.error("Newsletter briefing generation failed: %s", exc)
        return generate_newsletter_briefing([], score=score, tier_label=tier_label, score_delta=score_delta)
```

- [ ] **Step 4: Run test**

Run:

```bash
pytest tests/test_newsletter_digest.py -v
```

Expected: PASS.

---

### Task 5: Build Daily Newsletter Digest in the Sender

**Files:**
- Modify: `scripts/send_newsletter.py`
- Test: `tests/test_newsletter_digest.py`

- [ ] **Step 1: Add tests for daily cache and freshness selection**

Append to `tests/test_newsletter_digest.py`:

```python
from datetime import datetime, timezone

import scripts.send_newsletter as newsletter


def test_build_newsletter_briefing_uses_today_cache(monkeypatch):
    cached = {"briefing": "• Cached morning briefing"}

    monkeypatch.setattr(newsletter, "get_cached", lambda key, ttl: cached)

    result = newsletter._build_daily_newsletter_briefing(
        current_scores={"weather": 80},
        score=72.4,
        tier={"label": "Stable"},
        fallback_briefing="fallback",
        today=datetime(2026, 6, 7, tzinfo=timezone.utc),
    )

    assert result == "• Cached morning briefing"


def test_build_newsletter_briefing_generates_from_fresh_articles(monkeypatch):
    monkeypatch.setattr(newsletter, "get_cached", lambda key, ttl: None)
    monkeypatch.setattr(newsletter, "set_cached", lambda key, data: None)
    monkeypatch.setattr(
        newsletter,
        "fetch_rss_articles",
        lambda max_items: [
            {
                "title": "Fresh port story",
                "description": "A port disruption changed overnight.",
                "url": "https://example.com/a",
                "source": "Example",
                "source_group": "ports_shipping",
                "published": "2026-06-07T10:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        newsletter,
        "select_fresh_articles",
        lambda articles, now, max_items, fresh_hours, fallback_hours: articles,
    )
    monkeypatch.setattr(
        newsletter,
        "generate_newsletter_briefing",
        lambda articles, score, tier_label, score_delta: "• Fresh generated briefing",
    )

    result = newsletter._build_daily_newsletter_briefing(
        current_scores={"weather": 80},
        score=72.4,
        tier={"label": "Stable"},
        fallback_briefing="fallback",
        today=datetime(2026, 6, 7, tzinfo=timezone.utc),
    )

    assert result == "• Fresh generated briefing"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_newsletter_digest.py -v
```

Expected: FAIL because `_build_daily_newsletter_briefing`, `get_cached`, `set_cached`, `fetch_rss_articles`, `select_fresh_articles`, and `generate_newsletter_briefing` are not imported in `scripts/send_newsletter.py`.

- [ ] **Step 3: Modify newsletter sender imports and helper**

In `scripts/send_newsletter.py`, add these imports after `from config import COLORS`:

```python
from data.ai_analyst import generate_newsletter_briefing
from data.cache import get_cached, set_cached
from data.news_selection import select_fresh_articles
from data.rss_fetcher import fetch_rss_articles
```

Add this helper before `generate_html_email`:

```python
def _daily_newsletter_cache_key(today: datetime) -> str:
    """Cache key scoped to one newsletter date so SMTP retries reuse the same text."""
    return f"newsletter_briefing_{today.strftime('%Y_%m_%d')}"


def _build_daily_newsletter_briefing(
    *,
    current_scores: dict,
    score: float,
    tier: dict,
    fallback_briefing: str,
    today: datetime | None = None,
) -> str:
    """Build a fresh morning briefing from public sources, with same-day retry cache."""
    run_date = today or datetime.now(timezone.utc)
    cache_key = _daily_newsletter_cache_key(run_date)
    cached = get_cached(cache_key, ttl=36 * 3600)
    if cached and cached.get("briefing"):
        return str(cached["briefing"])

    try:
        articles = fetch_rss_articles(max_items=80)
        selected = select_fresh_articles(
            articles,
            now=run_date,
            max_items=24,
            fresh_hours=36,
            fallback_hours=72,
        )
        briefing = generate_newsletter_briefing(
            selected,
            score=score,
            tier_label=str(tier.get("label", "Unknown")),
            score_delta=None,
        )
        set_cached(
            cache_key,
            {
                "briefing": briefing,
                "article_count": len(selected),
                "article_fingerprints": [article.get("fingerprint") for article in selected],
            },
        )
        return briefing
    except Exception as exc:
        logger.warning("Fresh newsletter briefing failed; using dashboard briefing: %s", exc)
        return fallback_briefing
```

Also change the datetime import near the top:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Use the fresh briefing in `main()`**

After calculating `tier`, replace:

```python
logger.info(f"Dashboard score: {score:.1f} ({tier.get('label')})")

html_content = generate_html_email(score, tier, briefing, website_url)
text_content = generate_text_email(score, tier, briefing, website_url)
```

with:

```python
logger.info(f"Dashboard score: {score:.1f} ({tier.get('label')})")
briefing = _build_daily_newsletter_briefing(
    current_scores=current_scores,
    score=float(score),
    tier=tier,
    fallback_briefing=briefing,
)

html_content = generate_html_email(score, tier, briefing, website_url)
text_content = generate_text_email(score, tier, briefing, website_url)
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_newsletter_digest.py -v
```

Expected: PASS.

---

### Task 6: Verify Live Feed Health Without Sending Email

**Files:**
- No code changes unless a configured source fails consistently.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
pytest tests/test_news_sources.py tests/test_news_selection.py tests/test_rss_fetcher.py tests/test_newsletter_digest.py -v
```

Expected: PASS.

- [ ] **Step 2: Run RSS fetcher manually**

Run:

```bash
python -m data.rss_fetcher
```

Expected: prints at least 5 article titles and logs a nonzero unique article count. If one source fails but most succeed, keep the source if it is a transient parse warning; remove or fix it if it fails every run.

- [ ] **Step 3: Run newsletter dry run**

Run:

```bash
python scripts/send_newsletter.py --dry-run
```

Expected: script does not send SMTP, text output includes a current score and fresh briefing bullets. The bullets should not be the old dashboard briefing unless live public-source fetch failed.

---

### Task 7: Deployment Notes

**Files:**
- Modify: deployment environment only if needed.

- [ ] **Step 1: Keep existing Gemini cache**

Do not change `GEMINI_CACHE_TTL_SECONDS` for the dashboard in this pass. The newsletter gets its own daily cache key, so dashboard responsiveness stays intact.

- [ ] **Step 2: Confirm cron timing**

Ensure Render Cron runs after the web service has had time to boot and refresh once. If the web service boots around the same time as the cron, schedule newsletter delivery at least 10 minutes later.

- [ ] **Step 3: Monitor first three sends**

For the first three morning sends, check:

```text
1. Did the newsletter use today's daily cache key?
2. How many selected fresh articles were included?
3. Did source groups include at least two buckets?
4. Did the email avoid repeating yesterday's exact bullets?
```

If source diversity is weak, lower `per_group_limit` in `select_fresh_articles()` from `10` to `7`.

---

## Self-Review

- Spec coverage: The plan adds public/free sources, source grouping, deterministic feed normalization, recency selection, dedupe, and a newsletter-specific daily cache.
- Placeholder scan: No implementation step relies on "add later" for the first RSS pass. USTR/Panama/Suez HTML parsing is intentionally excluded from this first implementation and called out as a later source-specific parser task.
- Type consistency: Article dictionaries consistently use `title`, `description`, `url`, `source`, `source_group`, `published`, optional `published_at`, and optional `fingerprint`.
