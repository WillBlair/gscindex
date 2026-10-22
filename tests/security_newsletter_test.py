"""Tests for unsubscribe links, admin auth, and newsletter safeguards."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from flask import Flask


class UnsubscribeTokenTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"NEWSLETTER_SECRET": "s3cret"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_round_trip(self):
        from data.unsubscribe import make_token, verify_token

        self.assertEqual(verify_token(make_token("A@Example.com")), "a@example.com")

    def test_forged_or_garbled_tokens_rejected(self):
        from data.unsubscribe import make_token, verify_token

        good = make_token("a@example.com")
        other_email = make_token("b@example.com").split(".")[0]
        self.assertIsNone(verify_token(f"{other_email}.{good.split('.')[1]}"))
        self.assertIsNone(verify_token("not-a-token"))
        self.assertIsNone(verify_token(""))


class UnsubscribeRouteTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"NEWSLETTER_SECRET": "s3cret"})
        self.env.start()
        from api.newsletter import newsletter_bp

        app = Flask(__name__)
        app.register_blueprint(newsletter_bp)
        self.client = app.test_client()

    def tearDown(self):
        self.env.stop()

    def test_get_does_not_unsubscribe(self):
        from data.unsubscribe import make_token

        with mock.patch("api.newsletter.unsubscribe_user") as unsub:
            resp = self.client.get(f"/unsubscribe?t={make_token('a@example.com')}")
        self.assertEqual(resp.status_code, 200)
        unsub.assert_not_called()

    def test_post_unsubscribes(self):
        from data.unsubscribe import make_token

        with mock.patch("api.newsletter.unsubscribe_user", return_value=True) as unsub:
            resp = self.client.post(f"/unsubscribe?t={make_token('a@example.com')}")
        self.assertEqual(resp.status_code, 200)
        unsub.assert_called_once_with("a@example.com")

    def test_bad_token_is_rejected(self):
        with mock.patch("api.newsletter.unsubscribe_user") as unsub:
            resp = self.client.post("/unsubscribe?t=bogus")
        self.assertEqual(resp.status_code, 400)
        unsub.assert_not_called()


class AdminAuthTests(unittest.TestCase):
    def _check(self, headers):
        from api.admin import verify_admin

        app = Flask(__name__)
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "tok"}), \
             app.test_request_context("/", headers=headers):
            return verify_admin()

    def test_bearer_header_required(self):
        self.assertTrue(self._check({"Authorization": "Bearer tok"}))
        self.assertFalse(self._check({"Authorization": "Bearer nope"}))
        self.assertFalse(self._check({}))

    def test_query_string_token_not_accepted(self):
        from api.admin import verify_admin

        app = Flask(__name__)
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "tok"}), \
             app.test_request_context("/?token=tok"):
            self.assertFalse(verify_admin())


class NewsletterEmailTests(unittest.TestCase):
    def test_footer_has_unsubscribe_and_address(self):
        from scripts.send_newsletter import generate_html_email, generate_text_email

        tier = {"label": "Stable", "color": "#fff"}
        html = generate_html_email(70.0, tier, "• a", "https://x", "https://x/unsubscribe?t=1", "1 Main St")
        text = generate_text_email(70.0, tier, "• a", "https://x", "https://x/unsubscribe?t=1", "1 Main St")
        for body in (html, text):
            self.assertIn("unsubscribe?t=1", body)
            self.assertIn("1 Main St", body)

    def test_mask_email(self):
        from scripts.send_newsletter import _mask_email

        self.assertEqual(_mask_email("william@example.com"), "wi***@example.com")


if __name__ == "__main__":
    unittest.main()
