import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import URLError

from data.ai_analyst import generate_newsletter_stories
import scripts.send_newsletter as newsletter

ARTICLES = [
    {"title": "Port strike in Antwerp", "description": "Dockers walk out for 48 hours.", "source": "Example",
     "url": "https://example.com/a", "source_group": "ports_shipping", "published": "2026-11-04"},
    {"title": "Carrier raises rates", "description": "A carrier adds a $500 surcharge.", "source": "Other",
     "url": "https://example.com/b", "source_group": "ports_shipping", "published": "2026-11-04"},
]
STORIES = [
    {"headline": "Antwerp dockers strike for two days", "summary": "Dockers walked out.", "source": "Example",
     "url": "https://example.com/a"},
    {"headline": "Carrier adds $500 surcharge", "summary": "A new surcharge.", "source": "Other",
     "url": "https://example.com/b"},
    {"headline": "Third story", "summary": "Third.", "source": "X", "url": "https://example.com/c"},
]
CATEGORIES = [
    {"key": "supply_chain", "label": "Supply Chain", "weight": 0.2, "today": 52.8, "change": 0.3, "status": ""},
    {"key": "chokepoints", "label": "Chokepoints", "weight": 0.15, "today": 28.3, "change": 0.0, "status": "stored"},
    {"key": "energy", "label": "Energy & Fuel", "weight": 0.15, "today": 32.5, "change": -2.4, "status": ""},
]
TIER = {"label": "Stressed", "color": "#FF8A3D"}


class NewsletterDigestTests(unittest.TestCase):
    def test_no_articles_means_no_stories(self):
        self.assertEqual(generate_newsletter_stories([]), [])

    def test_stories_take_links_from_the_articles_never_from_claude(self):
        reply = {"stories": [
            {"article_id": 1, "headline": "Carrier adds surcharge", "summary": "It adds $500."},
            {"article_id": 9, "headline": "Made up", "summary": "No such article."},
            {"article_id": 1, "headline": "Duplicate", "summary": "Same article again."},
        ]}
        seen = []
        with (
            patch("data.llm.is_configured", lambda: True),
            patch("data.llm.complete_json", lambda prompt, **k: seen.append(prompt) or reply),
        ):
            stories = generate_newsletter_stories(ARTICLES)
        self.assertEqual(stories, [{"headline": "Carrier adds surcharge", "summary": "It adds $500.",
                                    "source": "Other", "url": "https://example.com/b"}])
        self.assertIn("Do not mention the index or any score", seen[0])
        self.assertNotIn("credible", seen[0])

    def test_stories_fall_back_to_the_feed_when_claude_fails(self):
        def boom(*a, **k):
            raise RuntimeError("down")
        with patch("data.llm.is_configured", lambda: True), patch("data.llm.complete_json", boom):
            stories = generate_newsletter_stories(ARTICLES)
        self.assertEqual([s["headline"] for s in stories], ["Port strike in Antwerp", "Carrier raises rates"])
        self.assertEqual(stories[0]["url"], "https://example.com/a")

    def test_change_line_matches_the_readout(self):
        self.assertEqual(newsletter._change_text(None), "")
        self.assertEqual(newsletter._change_text(0.04), "No change since yesterday")
        self.assertEqual(newsletter._change_text(0.5), "+0.5 since yesterday")
        self.assertEqual(newsletter._change_text(-1.26), "\u22121.3 since yesterday")
        html = newsletter.generate_html_email(48.4, TIER, STORIES, "https://x", change=0.5)
        text = newsletter.generate_text_email(48.4, TIER, STORIES, "https://x", change=0.5)
        self.assertIn("+0.5 since yesterday", html)
        self.assertIn("+0.5 since yesterday", text)
        self.assertNotIn("since yesterday", newsletter.generate_html_email(48.4, TIER, STORIES, "https://x"))

    def test_biggest_move_is_by_effect_on_the_index(self):
        self.assertEqual(newsletter._biggest_move(CATEGORIES), "Biggest move: Energy & Fuel fell 2.4 to 32.5.")
        flat = [dict(c, change=0.0) for c in CATEGORIES]
        self.assertEqual(newsletter._biggest_move(flat), "No category moved since yesterday.")
        self.assertEqual(newsletter._biggest_move([dict(c, change=None) for c in CATEGORIES]), "")

    def test_subject_leads_with_the_top_story(self):
        self.assertEqual(newsletter.email_subject(48.5, TIER, -0.3, STORIES),
                         "Antwerp dockers strike for two days | Index 48.5 Stressed (\u22120.3)")
        self.assertEqual(newsletter.email_subject(48.5, TIER, None, []),
                         "Global Supply Chain Index: Index 48.5 Stressed")
        self.assertEqual(newsletter.email_preheader(STORIES), "Carrier adds $500 surcharge. Third story.")

    def test_email_order_is_briefing_then_index_then_chokepoints(self):
        choke = {"as_of": "2026-10-25", "items": [{"name": "Hormuz", "pct_of_normal": 3.0},
                                                  {"name": "Suez", "pct_of_normal": 56.0}]}
        html = newsletter.generate_html_email(48.5, TIER, STORIES, "https://gscindex.com/?utm_source=newsletter",
                                              "https://gscindex.com/unsubscribe?t=x", "PO Box 1",
                                              -0.3, CATEGORIES, choke)
        order = [html.index(s) for s in ("Today's briefing", "The index", "Chokepoint traffic", "OPEN THE DASHBOARD")]
        self.assertEqual(order, sorted(order))
        self.assertIn("(last stored)", html)
        self.assertIn("Sources: UN Global Platform; IMF PortWatch", html)
        self.assertIn("as of Oct 25", html)
        self.assertIn('href="https://example.com/a"', html)
        self.assertIn("https://gscindex.com/?utm_source=forward", html)
        self.assertIn("PO Box 1", html)
        text = newsletter.generate_text_email(48.5, TIER, STORIES, "https://gscindex.com", "", "", -0.3, CATEGORIES, choke)
        self.assertIn("Example: https://example.com/a", text)
        self.assertIn("Hormuz 3%", text)

    def test_build_stories_uses_today_cache(self):
        cached = {"stories": STORIES}
        with patch.object(newsletter, "get_cached", lambda key, ttl: cached):
            result = newsletter._build_daily_stories(fallback_briefing="fallback",
                                                     today=datetime(2026, 6, 7, tzinfo=timezone.utc))
        self.assertEqual(result, STORIES)

    def test_build_stories_falls_back_to_the_dashboard_briefing(self):
        def offline(max_items):
            raise URLError("offline")
        with (
            patch.object(newsletter, "get_cached", lambda key, ttl: None),
            patch.object(newsletter, "fetch_rss_articles", offline),
        ):
            result = newsletter._build_daily_stories(fallback_briefing="• One\n• Two",
                                                     today=datetime(2026, 6, 7, tzinfo=timezone.utc))
        self.assertEqual([s["summary"] for s in result], ["One", "Two"])

    def test_html_email_escapes_story_text_and_drops_unsafe_links(self):
        stories = [{"headline": "<b>x</b>", "summary": "<script>alert('x')</script>", "source": "S",
                    "url": "javascript:alert(1)"}]
        html = newsletter.generate_html_email(61.7, TIER, stories, "https://gscindex.com")
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("javascript:", html)

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
            patch.object(newsletter, "_build_daily_stories", lambda **kwargs: []),
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
