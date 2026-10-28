"""robots.txt, sitemap.xml, the share card and the share/analytics tags (api/share.py)."""
from __future__ import annotations

import io

import pytest
from flask import Flask
from PIL import Image

import config
from api import share

SECTOR_CATS = {c for s in config.SECTORS.values() for c in s["weights"]}
PAGE = "<html><head><title>x</title></head><body><p>page</p></body></html>"


def _snapshot(today_score=46.5, yday_score=48.0):
    cats = list(config.CATEGORY_WEIGHTS) + sorted(SECTOR_CATS)
    scores = {c: today_score for c in config.CATEGORY_WEIGHTS} | {c: 50.0 for c in SECTOR_CATS}
    return {
        "last_updated_utc": "2026-10-28T16:49:06Z",
        "current_scores": scores,
        "category_metadata": {c: {"source": "test"} for c in cats},
        "daily_history": {
            "dates": ["2026-10-27", "2026-10-28"],
            "scores": {c: [yday_score if c in config.CATEGORY_WEIGHTS else 50.0, None] for c in cats},
        },
        "excluded_categories": [],
        "sectors": {key: {"index": 50.0, "coverage": len(spec["weights"]), "degraded": False}
                    for key, spec in config.SECTORS.items()},
    }


@pytest.fixture(autouse=True)
def _clear_card_cache():
    share._CARD_CACHE.clear()


def _client(data):
    app = Flask(__name__)
    for path in ("/", "/docs", "/unsubscribe"):
        app.add_url_rule(path, path, lambda: PAGE)
    share.register_share_routes(app, lambda: (data, True))
    return app.test_client()


def test_robots_is_plain_text_and_names_the_sitemap():
    resp = _client(None).get("/robots.txt")
    assert resp.status_code == 200 and resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "Disallow: /unsubscribe" in body and "Disallow: /api/v1/admin/" in body
    assert f"Sitemap: {config.SITE_URL}/sitemap.xml" in body


def test_sitemap_lists_the_public_pages():
    resp = _client(None).get("/sitemap.xml")
    assert resp.mimetype == "application/xml"
    body = resp.get_data(as_text=True)
    for path in config.SITEMAP_PATHS:
        assert f"<loc>{config.SITE_URL}{path}</loc>" in body


def test_card_is_a_1200x630_png_and_cached_per_snapshot(monkeypatch):
    data = _snapshot()
    resp = _client(data).get("/og.png")
    assert resp.status_code == 200 and resp.mimetype == "image/png"
    assert Image.open(io.BytesIO(resp.data)).size == share.CARD_SIZE
    calls = []
    monkeypatch.setattr(share, "render_card", lambda d: calls.append(d) or b"png")
    share.card_png(data)
    assert calls == []          # same snapshot time: cached bytes, no redraw


def test_card_renders_without_data():
    resp = _client(None).get("/og.png")
    assert Image.open(io.BytesIO(resp.data)).size == share.CARD_SIZE


def test_home_page_gets_share_tags_with_todays_score():
    html = _client(_snapshot()).get("/").get_data(as_text=True)
    assert 'property="og:title" content="Global Supply Chain Index: 46.5 (Stressed)"' in html
    assert f'content="{config.SITE_URL}/og.png?v=202610281649"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert "Semis 50.0" in html and "Aero 50.0" in html
    assert html.index("og:title") < html.index("</head>")


def test_card_numbers_match_the_readout():
    numbers = share.card_numbers(_snapshot(46.5, 48.0))
    assert numbers["global"]["today"] == pytest.approx(46.5)
    assert numbers["global"]["change"] == pytest.approx(-1.5)


def test_docs_keeps_its_own_title_and_no_snapshot_falls_back():
    html = _client(None).get("/docs").get_data(as_text=True)
    assert 'content="Methodology | Global Supply Chain Index"' in html
    html = _client(None).get("/").get_data(as_text=True)
    assert 'property="og:title" content="Global Supply Chain Index"' in html


def test_no_analytics_without_a_token(monkeypatch):
    monkeypatch.setattr(share, "CF_ANALYTICS_TOKEN", "")
    html = _client(_snapshot()).get("/").get_data(as_text=True)
    assert "cloudflareinsights" not in html


def test_analytics_on_public_pages_only(monkeypatch):
    monkeypatch.setattr(share, "CF_ANALYTICS_TOKEN", "abcdef0123456789abcdef0123456789")
    client = _client(_snapshot())
    assert "cloudflareinsights" in client.get("/").get_data(as_text=True)
    assert "cloudflareinsights" in client.get("/docs").get_data(as_text=True)
    unsub = client.get("/unsubscribe").get_data(as_text=True)
    assert "cloudflareinsights" not in unsub and "og:title" not in unsub


def test_malformed_token_is_ignored():
    assert share.analytics_tag("abc\"><script>") == ""
    assert share.analytics_tag("") == ""
