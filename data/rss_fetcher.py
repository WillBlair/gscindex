
"""RSS fetcher for public supply-chain intelligence feeds."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser

from data.news_selection import dedupe_articles, is_low_signal_article, parse_article_datetime
from data.news_sources import NEWS_SOURCES, NewsSource

logger = logging.getLogger(__name__)

# Compatibility for any older diagnostics importing the raw URL list.
FEED_URLS = [source["url"] for source in NEWS_SOURCES]


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
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


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

    signal_articles = [article for article in all_articles if not is_low_signal_article(article)]
    unique_articles = dedupe_articles(signal_articles)
    unique_articles.sort(key=_sort_key, reverse=True)

    logger.info("Fetched %d unique articles from RSS feeds.", len(unique_articles))
    return unique_articles[:max_items]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    items = fetch_rss_articles()
    for item in items[:5]:
        group = item.get("source_group", "news").replace("_", " ")
        print(f"- [{item['source']} | {group}] {item['title']}")
