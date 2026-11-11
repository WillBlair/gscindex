"""Tests for the /history page and /history.csv (api/history.py)."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest
from flask import Flask

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
    assert 'id="ep-1"' in body and "X happened." in body and 'href="https://example.org/x"' in body
    assert "-36.0 over 90 days" in body and "All eight categories" in body
    assert all(config.CATEGORY_LABELS[c] in body for c in CATS)
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
    assert f"Excluded today: {config.CATEGORY_LABELS['energy']}" in body
    data = json.loads(re.search(r'id="hchart-data">(.*?)</script>', body, re.S).group(1))
    assert len(data["values"]) == 200


def test_an_episode_without_a_value_shows_a_dash_and_no_mark(monkeypatch):
    eps = EPISODES + [{"date": "2030-01-01", "label": "Later", "text": "", "source_url": ""}]
    body = client(monkeypatch, history(), snapshot(TODAY), eps).get("/history").get_data(as_text=True)
    assert 'id="ep-2"' in body and 'href="#ep-2"' not in body and "Six episodes" not in body and "Two episodes" in body


def test_csv_is_served_from_memory_with_a_one_hour_cache(monkeypatch):
    resp = client(monkeypatch, history(), snapshot(TODAY, score=41.0)).get("/history.csv")
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert resp.mimetype == "text/csv" and resp.headers["Cache-Control"] == "public, max-age=3600"
    assert 'filename="gscindex-history.csv"' in resp.headers["Content-Disposition"]
    assert lines[1].startswith("2019-01-11,60.00,") and len(lines) == 202 and lines[-1].startswith("2019-07-30,41.00,")


def test_the_routes_are_on_the_real_app():
    import app
    assert {"/history", "/history.csv"} <= {rule.rule for rule in app.server.url_map.iter_rules()}
