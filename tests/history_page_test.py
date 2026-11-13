"""Tests for the /history page and /history.csv (api/history.py)."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

import pytest
from flask import Flask
from markupsafe import escape

import components.history_data as hd
import config
from api import history as history_page
from api.routes import get_limiter
from data import database, long_history
from data.providers.chokepoints import CREDIT
from tests.history_helpers import CATS, START, rows, snapshot

TODAY = date(2019, 7, 30)  # 200 stored days, then today
DAY, BASE = START + timedelta(days=95), START + timedelta(days=5)
EPISODES = [{"date": DAY.isoformat(), "label": "Test event", "text": "X happened.", "source_url": "https://example.org/x"}]
SECTOR_WORDS = [c for s in config.SECTORS.values() for c in s["weights"]] + ["Semis", "Aero", "Bank of Japan"]


def history():
    data = rows(START, 200, overrides={(DAY, c): 30.0 for c in CATS} | {(BASE, "energy"): 100.0})
    return hd.build_history(data, START, TODAY)


def client(monkeypatch, hist, snap, episodes=EPISODES):
    monkeypatch.setattr(config, "HISTORY_EPISODES", episodes)
    monkeypatch.setattr(long_history, "get", lambda: hist)
    monkeypatch.setattr(database, "get_connection", lambda: pytest.fail("database opened in a request"))
    app = Flask(__name__)
    history_page.register_history_routes(app, lambda: (snap, True), get_limiter(app))
    return app.test_client()


def test_page_shows_the_chart_numbers_and_episode_from_the_data(monkeypatch):
    body = client(monkeypatch, history(), snapshot(TODAY, score=41.0)).get("/history").get_data(as_text=True)
    assert "Global Supply Chain Index, daily since 11 January 2019" in body and '<path class="line"' in body
    assert "41.0" in body and "30.0" in body and "16 April 2019" in body and "66.0" in body and "16 January 2019" in body
    chart_part = body[body.index('class="hchart"'):body.index('id="hchart-readout"')]
    assert 'class="tip"' in chart_part and "Test event" in chart_part
    assert 'id="ep-1"' in body and "X happened." in body and 'href="https://example.org/x"' in body
    assert "-36.0 over 90 days" in body and "All eight categories" in body
    assert all(str(escape(config.CATEGORY_LABELS[c])) in body for c in CATS)
    assert "The index was Stable on 0 of the 1." in body
    assert CREDIT in body and "CC-BY-4.0" in body and 'href="/history.csv"' in body
    assert 'action="/history/signup"' in body and "Sign up free" in body
    assert not any(word in body for word in SECTOR_WORDS)


def test_page_without_history_says_it_is_loading(monkeypatch):
    for hist in (None, hd.build_history([], START, TODAY)):
        c = client(monkeypatch, hist, snapshot(TODAY))
        resp = c.get("/history")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200 and "History is loading. Reload in a minute." in body
        assert "<svg" not in body and 'id="episodes"' not in body and 'action="/history/signup"' in body
        assert c.get("/history.csv").status_code == 503


def test_page_without_a_snapshot_renders_the_stored_days(monkeypatch):
    resp = client(monkeypatch, history(), None).get("/history")
    assert resp.status_code == 200 and "<svg" in resp.get_data(as_text=True)


def test_an_exclusion_is_named_and_adds_no_live_point(monkeypatch):
    body = client(monkeypatch, history(), snapshot(TODAY, excluded=("energy",))).get("/history").get_data(as_text=True)
    assert f"Excluded today: {escape(config.CATEGORY_LABELS['energy'])}" in body
    data = json.loads(re.search(r'id="hchart-data">(.*?)</script>', body, re.S).group(1))
    assert len(data["values"]) == 200


def test_an_episode_without_a_value_shows_a_dash_and_no_mark(monkeypatch):
    eps = EPISODES + [{"date": "2030-01-01", "label": "Later", "text": "", "source_url": ""}]
    body = client(monkeypatch, history(), snapshot(TODAY), eps).get("/history").get_data(as_text=True)
    assert 'id="ep-2"' in body and 'href="#ep-2"' not in body and "Six episodes" not in body and "Two episodes" in body


def test_episode_text_is_escaped(monkeypatch):
    eps = [dict(EPISODES[0], text="A <b>bold</b> & risky claim.")]
    body = client(monkeypatch, history(), snapshot(TODAY), eps).get("/history").get_data(as_text=True)
    assert "<b>bold</b>" not in body and "&lt;b&gt;bold&lt;/b&gt; &amp; risky" in body


def test_csv_is_served_from_memory_with_a_one_hour_cache(monkeypatch):
    resp = client(monkeypatch, history(), snapshot(TODAY, score=41.0)).get("/history.csv")
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert resp.mimetype == "text/csv" and resp.headers["Cache-Control"] == "public, max-age=3600"
    assert 'filename="gscindex-history.csv"' in resp.headers["Content-Disposition"]
    assert lines[1].startswith("2019-01-11,60.00,") and len(lines) == 202 and lines[-1].startswith("2019-07-30,41.00,")


def test_the_routes_are_on_the_real_app():
    import app
    assert {"/history", "/history.csv", "/history/signup"} <= {rule.rule for rule in app.server.url_map.iter_rules()}


def signup(monkeypatch, result=None, **form):
    calls = []
    monkeypatch.setattr(database, "add_subscriber",
                        lambda email, source=None: calls.append((email, source)) or (result or {"success": True}))
    resp = client(monkeypatch, history(), snapshot(TODAY)).post("/history/signup", data=form)
    return resp, calls


def test_a_valid_email_is_stored_with_the_source_history(monkeypatch):
    resp, calls = signup(monkeypatch, email=" A@Example.com ")
    assert resp.status_code == 303 and resp.headers["Location"].endswith("/history?signup=ok#signup")
    assert calls == [("a@example.com", "history")]


def test_utm_tags_become_the_source_and_junk_does_not(monkeypatch):
    assert signup(monkeypatch, email="a@b.co", utm_source="reddit", utm_campaign="test1")[1] == [("a@b.co", "reddit/test1")]
    assert signup(monkeypatch, email="a@b.co", utm_source="<script>", utm_campaign="x y")[1] == [("a@b.co", "history")]


@pytest.mark.parametrize("form", [{}, {"email": "nope"}, {"email": "a" * 300 + "@b.co"}, {"email": "a@b.co, c@d.co"}])
def test_a_bad_or_missing_email_stores_nothing(monkeypatch, form):
    resp, calls = signup(monkeypatch, **form)
    assert resp.status_code == 303 and "signup=invalid#signup" in resp.headers["Location"] and calls == []


def test_opt_out_and_failure_get_their_own_lines(monkeypatch):
    assert "signup=optout" in signup(monkeypatch, database._OPTED_OUT_RESULT, email="a@b.co")[0].headers["Location"]
    assert "signup=error" in signup(monkeypatch, {"success": False, "message": "x"}, email="a@b.co")[0].headers["Location"]
    c = client(monkeypatch, history(), snapshot(TODAY))
    assert "You&#39;re subscribed to the daily briefing." in c.get("/history?signup=ok").get_data(as_text=True)
    assert "unsubscribed earlier" in c.get("/history?signup=optout").get_data(as_text=True)
    assert "alert(1)" not in c.get("/history?signup=<script>alert(1)</script>").get_data(as_text=True)


def test_the_form_carries_valid_utm_tags_only(monkeypatch):
    c = client(monkeypatch, history(), snapshot(TODAY))
    tagged = c.get("/history?utm_source=reddit&utm_campaign=test1").get_data(as_text=True)
    assert 'name="utm_source" value="reddit"' in tagged and 'name="utm_campaign" value="test1"' in tagged
    assert 'name="utm_source"' not in c.get("/history?utm_source=%3Cx%3E").get_data(as_text=True)


def test_signups_are_rate_limited_per_visitor(monkeypatch):
    monkeypatch.setattr(config, "HISTORY_SIGNUP_RATE_LIMIT", "2 per minute")
    monkeypatch.setattr(database, "add_subscriber", lambda email, source=None: {"success": True})
    c = client(monkeypatch, history(), snapshot(TODAY))
    codes = [c.post("/history/signup", data={"email": "a@b.co"}).status_code for _ in range(3)]
    assert codes == [303, 303, 429]


def test_every_episode_has_one_sentence_and_an_https_source():
    assert [e["date"] for e in config.HISTORY_EPISODES] == [
        "2020-04-15", "2021-03-29", "2021-12-15", "2024-02-15", "2025-04-15", "2026-03-20"]
    for episode in config.HISTORY_EPISODES:
        assert 40 <= len(episode["text"]) <= 240 and episode["text"].endswith(".")
        assert "—" not in episode["text"] and "–" not in episode["text"]
        assert episode["source_url"].startswith("https://")


def test_a_failing_signup_is_logged_without_the_email(monkeypatch, caplog):
    def boom(email, source=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(database, "add_subscriber", boom)
    with caplog.at_level(logging.ERROR):
        resp = client(monkeypatch, history(), snapshot(TODAY)).post("/history/signup", data={"email": "secret@example.com"})
    assert "signup=error" in resp.headers["Location"]
    assert "history signup failed" in caplog.text and "secret@example.com" not in caplog.text


def test_a_stale_snapshot_blanks_the_today_tile(monkeypatch):
    stale = snapshot(START + timedelta(days=2), score=41.0, excluded=("energy",))
    body = client(monkeypatch, history(), stale).get("/history").get_data(as_text=True)
    assert "Excluded today" not in body
    tile = re.search(r'<div class="lab">Today</div>\s*<div class="num"[^>]*>(.*?)</div>\s*<div class="sub">(.*?)</div>', body, re.S)
    assert tile.group(1) == "–" and tile.group(2) == ""
    assert "41.0" not in body


def test_the_how_it_was_made_dates_come_from_config(monkeypatch):
    body = client(monkeypatch, history(), snapshot(TODAY)).get("/history").get_data(as_text=True)
    assert ("Days from 23 July 2026 to 22 October 2026 were calculated on 23 October 2026." in body
            and "from 11 January 2019 to 22 July 2026 were calculated in" in body)
    monkeypatch.setattr(config, "HISTORY_BACKFILL_END_DATE", "2026-08-31")
    monkeypatch.setattr(config, "HISTORY_LIVE_FROM_DATE", "2026-11-02")
    body = client(monkeypatch, history(), snapshot(TODAY)).get("/history").get_data(as_text=True)
    assert "Days from 1 September 2026 to 1 November 2026 were calculated on 2 November 2026." in body


def test_a_filled_honeypot_stores_nothing_and_looks_like_success(monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        resp, calls = signup(monkeypatch, email="a@b.co", website="http://spam.example")
    assert "history signup ignored: honeypot field filled" in caplog.text
    assert "a@b.co" not in caplog.text
    assert resp.status_code == 303 and "signup=ok#signup" in resp.headers["Location"] and calls == []
    assert signup(monkeypatch, email="a@b.co", website="")[1] == [("a@b.co", "history")]


def test_the_form_has_a_hidden_honeypot_field(monkeypatch):
    body = client(monkeypatch, history(), snapshot(TODAY)).get("/history").get_data(as_text=True)
    tag = re.search(r'<input[^>]*name="website"[^>]*>', body).group(0)
    assert all(attr in tag for attr in ('tabindex="-1"', 'autocomplete="off"', 'aria-hidden="true"', 'type="text"'))


def test_only_the_loading_page_is_noindex(monkeypatch):
    marker = '<meta name="robots" content="noindex"'
    assert marker in client(monkeypatch, None, snapshot(TODAY)).get("/history").get_data(as_text=True)
    assert marker not in client(monkeypatch, history(), snapshot(TODAY)).get("/history").get_data(as_text=True)
