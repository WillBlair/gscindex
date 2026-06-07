import unittest
from types import SimpleNamespace
from unittest.mock import patch

from data.news_sources import NewsSource
from data.rss_fetcher import fetch_rss_articles, fetch_single_feed


def _entry(title, link, published="2026-06-07T12:00:00Z", summary="Summary"):
    return {
        "title": title,
        "link": link,
        "published": published,
        "summary": summary,
    }


class RssFetcherTests(unittest.TestCase):
    def test_fetch_single_feed_tags_source_group(self):
        source: NewsSource = {
            "name": "Test Feed",
            "url": "https://example.com/feed",
            "group": "trade_policy",
            "max_items": 2,
        }

        def fake_parse(url):
            self.assertEqual(url, source["url"])
            return SimpleNamespace(
                bozo=False,
                feed={"title": "Ignored Feed Title"},
                entries=[_entry("Tariff update", "https://example.com/a")],
            )

        with patch("data.rss_fetcher.feedparser.parse", fake_parse):
            articles = fetch_single_feed(source)

        self.assertEqual(
            articles,
            [
                {
                    "title": "Tariff update",
                    "description": "Summary",
                    "url": "https://example.com/a",
                    "source": "Test Feed",
                    "source_group": "trade_policy",
                    "published": "2026-06-07T12:00:00Z",
                    "is_rss": True,
                }
            ],
        )

    def test_fetch_rss_articles_is_stable_and_deduped(self):
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

        with (
            patch("data.rss_fetcher.NEWS_SOURCES", sources, create=True),
            patch("data.rss_fetcher.fetch_single_feed", fake_fetch),
        ):
            articles = fetch_rss_articles(max_items=10)

        self.assertEqual([article["title"] for article in articles], ["Newer item", "Older item"])


if __name__ == "__main__":
    unittest.main()
