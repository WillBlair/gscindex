import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import URLError

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
                current_scores={"supply_chain": 80},
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
                current_scores={"supply_chain": 80},
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

    # A snapshot whose Physical category was excluded: the composite is the stored one
    # (weights renormalized over the seven present categories), never recomputed.
    EXCLUDED_SNAPSHOT = {
        "current_scores": {"supply_chain": 52.5, "chokepoints": 36.1, "energy": 23.3, "tariffs": 46.2,
                           "geopolitical": 49.3, "freight": 77.2, "inputs": 41.9},
        "composite": 45.5,
        "excluded_categories": ["physical"],
        "degraded": True,
        "briefing": "• Hormuz transits remain low",
    }

    def test_local_fallback_uses_stored_composite_with_an_excluded_category(self):
        def offline(*args, **kwargs):
            raise URLError("offline")

        with (
            patch.object(newsletter, "urlopen", offline),
            patch("data.cache.get_cached_dashboard", lambda: dict(self.EXCLUDED_SNAPSHOT)),
        ):
            data = newsletter._fetch_dashboard_data("https://gscindex.com", "tok")

        self.assertEqual(data["composite_index"], 45.5)
        self.assertNotIn("physical", data["current_scores"])

    def _run_main(self, data):
        sent = []
        env = {"WEBSITE_URL": "https://gscindex.com", "RECIPIENT_EMAIL": "", "NEWSLETTER_POSTAL_ADDRESS": "1 Main St"}
        with (
            patch.object(sys, "argv", ["send_newsletter.py", "--dry-run"]),
            patch.dict(os.environ, env),
            patch.object(newsletter, "load_environment", lambda: None),
            patch("data.database.init_db", lambda: None),
            patch.object(newsletter, "_fetch_dashboard_data", lambda url, token: data),
            patch.object(newsletter, "_build_daily_newsletter_briefing",
                         lambda **kwargs: kwargs["fallback_briefing"]),
            patch("data.database.get_active_subscribers", lambda: ["a@example.com"]),
            patch("data.database.get_db_type", lambda: "sqlite"),
            patch("data.database.get_sent_today", lambda day: set()),
            patch.object(newsletter, "generate_text_email",
                         lambda score, tier, *a, **k: sent.append((score, tier["label"])) or ""),
            patch.object(newsletter, "generate_html_email", lambda *a, **k: ""),
            patch("builtins.print", lambda *a, **k: None),
        ):
            newsletter.main()
        return sent

    def test_main_sends_the_stored_composite_with_an_excluded_category(self):
        data = {
            "current_scores": self.EXCLUDED_SNAPSHOT["current_scores"],
            "briefing": "• Hormuz transits remain low",
            "composite_index": 45.5,
        }
        self.assertEqual(self._run_main(data), [(45.5, "Stressed")])

    def test_main_skips_without_a_composite(self):
        data = {
            "current_scores": self.EXCLUDED_SNAPSHOT["current_scores"],
            "briefing": "• Hormuz transits remain low",
            "composite_index": None,
        }
        with self.assertLogs("Newsletter", level="ERROR") as logs:
            self.assertEqual(self._run_main(data), [])
        self.assertIn("No composite available", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
