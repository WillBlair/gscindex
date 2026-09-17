
"""RSS fetcher for public supply-chain intelligence feeds."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser
import requests

from data.cache import get_cached, set_cached
from data.runtime import serialized
from data.news_selection import dedupe_articles, is_low_signal_article, parse_article_datetime
from data.news_sources import NEWS_SOURCES, NewsSource

logger = logging.getLogger(__name__)

# Compatibility for any older diagnostics importing the raw URL list.
FEED_URLS = [source["url"] for source in NEWS_SOURCES]
MAX_FEED_BYTES = 2 * 1024 * 1024
FEED_DEADLINE_SECONDS = 20
RSS_CACHE_KEY = "rss_articles_bounded_v1"


def _download_feed(url: str) -> bytes:
    """Limit decoded size and network waits before parsing untrusted XML."""
    started = time.monotonic()
    with requests.get(url, stream=True, timeout=(3.05, 10),
                      headers={"User-Agent": "GSCIndex/1.0 RSS reader"}) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(chunk_size=16 * 1024):
            if time.monotonic() - started > FEED_DEADLINE_SECONDS:
                raise TimeoutError("RSS download exceeded its time budget")
            if len(content) + len(chunk) > MAX_FEED_BYTES:
                raise ValueError("RSS feed exceeds the 2 MB size limit")
            content.extend(chunk)
        return bytes(content)


def parse_pub_date(entry) -> str:
    """Robustly extract and normalize publication date."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()

    raw_date = entry.get("published", "") or entry.get("updated", "") or entry.get("pubDate", "")
    if not raw_date:
        return datetime.now(timezone.utc).isoformat()
    return str(raw_date)


def fetch_single_feed(source: NewsSource) -> list[dict]:
    """Fetch and normalize a single RSS feed."""
    articles: list[dict] = []
    try:
        feed = feedparser.parse(_download_feed(source["url"]),
                                response_headers={"content-location": source["url"], "content-type": "application/xml"})
        if feed.bozo:
            logger.warning("RSS parse warning for %s: %s", source["url"], feed.bozo_exception)

        for entry in feed.entries[: source["max_items"]]:
            title = str(entry.get("title", "No Title")).strip()[:500]
            link = str(entry.get("link", "#")).strip()[:2048]
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
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


@serialized
def _fetch_rss_snapshot() -> list[dict]:
    """Share a five-minute snapshot across news, tariff, and port consumers."""
    cached = get_cached(RSS_CACHE_KEY, ttl=300)
    if cached is not None:
        return cached
    all_articles: list[dict] = []

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="RSS") as executor:
        future_to_source = {executor.submit(fetch_single_feed, source): source for source in NEWS_SOURCES}
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            try:
                all_articles.extend(future.result())
            except Exception as exc:
                logger.error("RSS worker failed for %s: %s", source["name"], exc)

    signal_articles = [article for article in all_articles if not is_low_signal_article(article)]
    unique_articles = dedupe_articles(signal_articles)
    unique_articles.sort(key=_sort_key, reverse=True)

    logger.info("Fetched %d unique articles from RSS feeds.", len(unique_articles))
    result = unique_articles[:200]
    set_cached(RSS_CACHE_KEY, result)
    return result


def fetch_rss_articles(max_items: int = 60) -> list[dict]:
    """Return an independently sized view of the shared RSS snapshot."""
    return _fetch_rss_snapshot()[:max(0, max_items)]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    items = fetch_rss_articles()
    for item in items[:5]:
        group = item.get("source_group", "news").replace("_", " ")
        print(f"- [{item['source']} | {group}] {item['title']}")
