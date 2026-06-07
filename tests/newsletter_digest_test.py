import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from data.ai_analyst import generate_newsletter_briefing
import scripts.send_newsletter as newsletter


class NewsletterDigestTests(unittest.TestCase):
    def test_generate_newsletter_briefing_returns_fallback_without_articles(self):
        result = generate_newsletter_briefing([], score=72.4, tier_label="Stable", score_delta=None)

        self.assertIn("No fresh public-source supply chain articles", result)
        self.assertIn("72.4/100", result)

    def test_build_newsletter_briefing_uses_today_cache(self):
        cached = {"briefing": "• Cached morning briefing"}

        with patch.object(newsletter, "get_cached", lambda key, ttl: cached):
            result = newsletter._build_daily_newsletter_briefing(
                current_scores={"weather": 80},
                score=72.4,
                tier={"label": "Stable"},
                fallback_briefing="fallback",
                today=datetime(2026, 6, 7, tzinfo=timezone.utc),
            )

        self.assertEqual(result, "• Cached morning briefing")

    def test_build_newsletter_briefing_generates_from_fresh_articles(self):
        article = {
            "title": "Fresh port story",
            "description": "A port disruption changed overnight.",
            "url": "https://example.com/a",
            "source": "Example",
            "source_group": "ports_shipping",
            "published": "2026-06-07T10:00:00+00:00",
        }

        with (
            patch.object(newsletter, "get_cached", lambda key, ttl: None),
            patch.object(newsletter, "set_cached", lambda key, data: None),
            patch.object(newsletter, "fetch_rss_articles", lambda max_items: [article]),
            patch.object(
                newsletter,
                "select_fresh_articles",
                lambda articles, now, max_items, fresh_hours, fallback_hours: articles,
            ),
            patch.object(
                newsletter,
                "generate_newsletter_briefing",
                lambda articles, score, tier_label, score_delta: "• Fresh generated briefing",
            ),
        ):
            result = newsletter._build_daily_newsletter_briefing(
                current_scores={"weather": 80},
                score=72.4,
                tier={"label": "Stable"},
                fallback_briefing="fallback",
                today=datetime(2026, 6, 7, tzinfo=timezone.utc),
            )

        self.assertEqual(result, "• Fresh generated briefing")

    def test_text_email_uses_real_newlines(self):
        text = newsletter.generate_text_email(
            61.7,
            {"label": "Stable"},
            "• First item\n• Second item",
            "https://gscindex.com",
        )

        self.assertIn("GLOBAL SUPPLY CHAIN INDEX - DAILY BRIEFING\nDate:", text)
        self.assertNotIn("\\nDate:", text)
        self.assertIn("- First item\n- Second item", text)

    def test_html_email_escapes_briefing_lines(self):
        html = newsletter.generate_html_email(
            61.7,
            {"label": "Stable", "color": "#fff"},
            "• <script>alert('x')</script>",
            "https://gscindex.com",
        )

        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert", html)


if __name__ == "__main__":
    unittest.main()
