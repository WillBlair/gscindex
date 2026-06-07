import unittest
from datetime import datetime, timedelta, timezone

from data.news_selection import (
    article_fingerprint,
    canonicalize_url,
    dedupe_articles,
    is_low_signal_article,
    parse_article_datetime,
    select_fresh_articles,
)


class NewsSelectionTests(unittest.TestCase):
    def test_canonicalize_url_removes_tracking_and_fragment(self):
        url = "https://example.com/story?utm_source=x&id=123#section"

        self.assertEqual(canonicalize_url(url), "https://example.com/story?id=123")

    def test_article_fingerprint_uses_canonical_url_when_present(self):
        first = {"title": "Port strike escalates", "url": "https://example.com/a?utm_campaign=x"}
        second = {"title": "Different title", "url": "https://example.com/a"}

        self.assertEqual(article_fingerprint(first), article_fingerprint(second))

    def test_parse_article_datetime_returns_aware_utc_datetime(self):
        parsed = parse_article_datetime("2026-06-07T12:30:00Z")

        self.assertIsNotNone(parsed)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.isoformat(), "2026-06-07T12:30:00+00:00")

    def test_dedupe_articles_removes_duplicate_urls_and_titles(self):
        articles = [
            {"title": "Port Strike Escalates", "url": "https://example.com/a", "published": "2026-06-07T12:00:00Z"},
            {"title": "Port strike escalates!", "url": "https://other.com/b", "published": "2026-06-07T13:00:00Z"},
            {"title": "Diesel prices fall", "url": "https://example.com/c", "published": "2026-06-07T14:00:00Z"},
        ]

        unique = dedupe_articles(articles)

        self.assertEqual([article["title"] for article in unique], ["Port Strike Escalates", "Diesel prices fall"])

    def test_select_fresh_articles_prefers_recent_and_diverse_sources(self):
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

        self.assertEqual([article["title"] for article in selected], ["Fresh logistics story", "Fresh weather story"])

    def test_select_fresh_articles_uses_fallback_window_when_needed(self):
        now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
        articles = [
            {
                "title": "Fallback trade story",
                "url": "https://example.com/fallback",
                "published": (now - timedelta(hours=48)).isoformat(),
                "source": "Trade Source",
                "source_group": "trade_policy",
            }
        ]

        selected = select_fresh_articles(articles, now=now, max_items=5, fresh_hours=36, fallback_hours=72)

        self.assertEqual([article["title"] for article in selected], ["Fallback trade story"])

    def test_low_signal_weather_and_disaster_items_are_excluded(self):
        now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
        low_signal = [
            {
                "title": "There are no tropical cyclones at this time.",
                "url": "https://example.com/no-cyclones",
                "published": now.isoformat(),
                "source": "NHC",
                "source_group": "weather_disasters",
            },
            {
                "title": "Atlantic Tropical Weather Outlook",
                "description": "Tropical cyclone formation is not expected during the next 7 days.",
                "url": "https://example.com/no-formation",
                "published": now.isoformat(),
                "source": "NHC",
                "source_group": "weather_disasters",
            },
            {
                "title": "Green earthquake (Magnitude 5.1M) in remote ocean",
                "url": "https://example.com/green-quake",
                "published": now.isoformat(),
                "source": "GDACS",
                "source_group": "weather_disasters",
            },
        ]
        useful = {
            "title": "Port closures reported after typhoon landfall",
            "url": "https://example.com/typhoon-port",
            "published": now.isoformat(),
            "source": "Official",
            "source_group": "weather_disasters",
        }

        self.assertTrue(all(is_low_signal_article(article) for article in low_signal))
        selected = select_fresh_articles([*low_signal, useful], now=now, max_items=5)

        self.assertEqual([article["title"] for article in selected], [useful["title"]])


if __name__ == "__main__":
    unittest.main()
