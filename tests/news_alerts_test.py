"""Offline tests for the display-only news alerts: Claude scores only new headlines, a
failed run keeps the last result flagged stale, topics match on word boundaries, and
VADER is gone. Nothing here calls Claude or the network."""

from __future__ import annotations

import pathlib
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from config import AI_CACHE_TTL_SECONDS, NEWS_AI_REFRESH_SECONDS, NEWS_MAX_ALERTS
from data import news_alerts

REPO = pathlib.Path(__file__).resolve().parents[1]


def _article(title, published="2026-10-22T10:00:00+00:00", description="Details."):
    return {"title": title, "description": description, "url": f"https://example.com/{abs(hash(title))}",
            "source": "Wire", "published": published}


def _cached_alert(title, published="2026-10-21T10:00:00+00:00", sentiment=-5.0):
    return {"timestamp": published, "severity": "high", "severity_label": "high", "title": title,
            "body": "Summary.", "category": "supply_chain", "sentiment": sentiment,
            "url": "https://example.com/c", "source": "Wire", "scored_by": "claude",
            "title_key": news_alerts.title_key(title)}


def _analysis(batch, severity=-5.0, relevant=True, category="supply_chain"):
    return {a["id"]: {"id": a["id"], "is_relevant": relevant, "category": category,
                      "severity_score": severity, "summary": f"Claude: {a['title']}", "reasoning": "r"}
            for a in batch}


@pytest.fixture
def env(monkeypatch):
    """Cache, RSS, web search and Claude all mocked; returns the mocks and a store."""
    store = {}
    monkeypatch.setattr(news_alerts, "get_cached", lambda key, ttl=None: store.get(key))
    monkeypatch.setattr(news_alerts, "set_cached", lambda key, data: store.__setitem__(key, data))
    rss = mock.Mock(return_value=[])
    web = mock.Mock(return_value=[])
    batch = mock.Mock(side_effect=lambda arts: (_analysis(arts), "• Briefing bullet."))
    report = mock.Mock(return_value="## Critical Disruptions\nReport.")
    monkeypatch.setattr(news_alerts, "fetch_rss_articles", rss)
    monkeypatch.setattr(news_alerts, "search_supply_chain_news", web)
    monkeypatch.setattr(news_alerts, "analyze_news_batch", batch)
    monkeypatch.setattr(news_alerts, "generate_full_report", report)
    monkeypatch.setattr(news_alerts.llm, "is_configured", lambda: True)
    return {"store": store, "rss": rss, "web": web, "batch": batch, "report": report}


def _seed(store, alerts, *, now=None, **fields):
    now = time.time() if now is None else now
    payload = {"alerts": alerts, "briefing": "• Cached briefing.", "full_report": "## Cached report",
               "ai_generated_at": now - 60, "alerts_scored_at": now - NEWS_AI_REFRESH_SECONDS - 1,
               "claude_ok_at": now - NEWS_AI_REFRESH_SECONDS - 1, "generated_at": now - 60,
               "stale": False, "scored_titles": []}
    payload.update(fields)
    store[news_alerts.NEWS_CACHE_KEY] = payload
    return payload


# --- topics ---------------------------------------------------------------------------------

def test_topic_word_boundaries():
    assert news_alerts.classify_topic("Annual report shows record sales") != "supply_chain"
    assert news_alerts.classify_topic("Warehouse automation") != "geopolitical"
    assert news_alerts.classify_topic("Heavy-duty trucks") != "tariffs"
    assert news_alerts.classify_topic("Port of Oakland congestion") == "supply_chain"


def test_topic_matches_plurals_and_site_categories():
    assert news_alerts.classify_topic("US raises tariffs on steel") == "tariffs"
    assert news_alerts.classify_topic("Ports of Los Angeles see record volumes") == "supply_chain"
    assert news_alerts.classify_topic("Houthi attacks in the Red Sea divert ships") == "chokepoints"
    assert news_alerts.classify_topic("Typhoon shuts Kaohsiung") == "physical"
    assert news_alerts.classify_topic("Airport opens a new lounge") == "other"


def test_topics_are_filter_keys():
    from components.layout import news_filter_options

    keys = {o["value"] for o in news_filter_options()}
    assert set(news_alerts._CATEGORY_KEYWORDS) <= keys
    from data.ai_analyst import ANALYSIS_SCHEMA

    enum = ANALYSIS_SCHEMA["properties"]["analysis"]["items"]["properties"]["category"]["enum"]
    assert set(enum) == keys - {"all"}


# --- incremental scoring --------------------------------------------------------------------

def test_incremental_scoring_only_sends_new_titles(env):
    _seed(env["store"], [_cached_alert("Port strike in Rotterdam"), _cached_alert("Suez canal delays")])
    env["rss"].return_value = [_article("Port strike in Rotterdam"), _article("Diesel prices jump"),
                               _article("New tariffs on Chinese steel")]

    alerts, briefing, report = news_alerts.fetch_supply_chain_news()

    sent = env["batch"].call_args.args[0]
    assert sorted(a["title"] for a in sent) == ["Diesel prices jump", "New tariffs on Chinese steel"]
    assert len(alerts) == 4
    assert env["web"].call_count == 0          # web search runs on the daily full run only
    assert env["report"].call_count == 0       # report and briefing too
    assert briefing == "• Cached briefing." and report == "## Cached report"
    payload = env["store"][news_alerts.NEWS_CACHE_KEY]
    assert payload["stale"] is False
    assert payload["alerts_scored_at"] == pytest.approx(time.time(), abs=5)


def test_titles_claude_rejected_are_not_resent(env):
    _seed(env["store"], [])
    env["rss"].return_value = [_article("Diesel prices jump")]
    env["batch"].side_effect = lambda arts: (_analysis(arts, relevant=False), "")
    news_alerts.fetch_supply_chain_news()
    payload = env["store"][news_alerts.NEWS_CACHE_KEY]
    payload["alerts_scored_at"] = time.time() - NEWS_AI_REFRESH_SECONDS - 1
    env["batch"].reset_mock()

    news_alerts.fetch_supply_chain_news()

    assert env["batch"].call_count == 0


def test_not_due_returns_cache_without_fetching(env):
    now = time.time()
    _seed(env["store"], [_cached_alert("Port strike in Rotterdam")], now=now, alerts_scored_at=now - 60)

    alerts, _, _ = news_alerts.fetch_supply_chain_news()

    assert [a["title"] for a in alerts] == ["Port strike in Rotterdam"]
    assert env["rss"].call_count == 0 and env["batch"].call_count == 0


def test_full_run_adds_web_search_and_regenerates_briefing_and_report(env):
    now = time.time()
    _seed(env["store"], [_cached_alert("Port strike in Rotterdam")], now=now,
          ai_generated_at=now - AI_CACHE_TTL_SECONDS - 1)
    env["rss"].return_value = [_article("Diesel prices jump")]
    env["web"].return_value = [_article("Hormuz traffic halted (web)")]

    alerts, briefing, report = news_alerts.fetch_supply_chain_news()

    assert env["web"].call_count == 1
    assert {a["title"] for a in env["batch"].call_args.args[0]} == {"Diesel prices jump", "Hormuz traffic halted (web)"}
    assert briefing == "• Briefing bullet."
    assert report == "## Critical Disruptions\nReport."
    payload = env["store"][news_alerts.NEWS_CACHE_KEY]
    assert payload["ai_generated_at"] == pytest.approx(now, abs=5)


def test_keeps_newest_alerts_only(env):
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    cached = [_cached_alert(f"Old story {i}", published=(start + timedelta(days=i)).isoformat())
              for i in range(NEWS_MAX_ALERTS)]
    _seed(env["store"], cached)
    env["rss"].return_value = [_article("Fresh port strike", published="2026-10-22T09:00:00+00:00")]

    alerts, _, _ = news_alerts.fetch_supply_chain_news()

    assert len(alerts) == NEWS_MAX_ALERTS
    assert alerts[0]["title"] == "Fresh port strike"
    assert "Old story 0" not in {a["title"] for a in alerts}


def test_claude_failure_keeps_cached_alerts_flagged_stale(env):
    now = time.time()
    cached = [_cached_alert("Port strike in Rotterdam"), _cached_alert("Suez canal delays")]
    _seed(env["store"], cached, now=now)
    env["rss"].return_value = [_article("Diesel prices jump")]
    env["batch"].side_effect = None
    env["batch"].return_value = ({}, "")

    alerts, briefing, _ = news_alerts.fetch_supply_chain_news()

    assert [a["title"] for a in alerts] == ["Port strike in Rotterdam", "Suez canal delays"]
    assert all(a["severity"] == "high" for a in alerts)
    payload = env["store"][news_alerts.NEWS_CACHE_KEY]
    assert payload["stale"] is True
    assert news_alerts.scoring_label(payload) == "Claude (stale)"
    # Retried after AI_FAILURE_RETRY_SECONDS, not every cycle and not a full 6 hours later.
    from config import AI_FAILURE_RETRY_SECONDS
    assert payload["alerts_scored_at"] == pytest.approx(
        now - NEWS_AI_REFRESH_SECONDS + AI_FAILURE_RETRY_SECONDS, abs=5)
    assert payload["claude_ok_at"] < now - 60


def test_stale_claude_result_is_dropped_after_seven_days(env):
    from config import NEWS_CACHE_MAX_AGE_SECONDS

    now = time.time()
    _seed(env["store"], [_cached_alert("Port strike in Rotterdam")], now=now,
          claude_ok_at=now - NEWS_CACHE_MAX_AGE_SECONDS - 1, stale=True)
    env["rss"].return_value = [_article("Diesel prices jump")]
    env["batch"].side_effect = None
    env["batch"].return_value = ({}, "")

    alerts, _, _ = news_alerts.fetch_supply_chain_news()

    assert [a["title"] for a in alerts] == ["Diesel prices jump"]
    assert alerts[0]["severity"] is None


def test_no_key_headlines_are_unscored(env, monkeypatch):
    monkeypatch.setattr(news_alerts.llm, "is_configured", lambda: False)
    env["rss"].return_value = [_article("Port of Oakland congestion"), _article("Diesel prices jump")]

    alerts, briefing, report = news_alerts.fetch_supply_chain_news()

    assert env["batch"].call_count == 0
    assert len(alerts) == 2
    for alert in alerts:
        assert alert["severity"] is None and alert["sentiment"] is None
        assert alert["severity_label"] == "unscored"
    assert {a["category"] for a in alerts} == {"supply_chain", "energy"}
    assert briefing.strip() and report.strip()
    assert news_alerts.scoring_label(env["store"][news_alerts.NEWS_CACHE_KEY]) == "Unscored"


def test_no_articles_and_no_cache_raises(env):
    with pytest.raises(RuntimeError):
        news_alerts.fetch_supply_chain_news()


def test_returns_three_tuple_of_display_data(env):
    env["rss"].return_value = [_article("Diesel prices jump")]
    result = news_alerts.fetch_supply_chain_news()
    assert isinstance(result, tuple) and len(result) == 3
    alerts, briefing, report = result
    alert = alerts[0]
    for key in ("timestamp", "severity", "title", "body", "category", "sentiment", "url", "source", "scored_by"):
        assert key in alert
    assert alert["sentiment"] == -5.0 and alert["scored_by"] == "claude"


# --- UI with unscored alerts ----------------------------------------------------------------

def test_unscored_alerts_render_and_sort_last():
    from components import terminal as term
    from components.workspace import select_news

    alerts = [
        {"title": "Unscored story", "severity": None, "severity_label": "unscored", "sentiment": None,
         "category": "other", "timestamp": "2026-10-22T12:00:00Z", "source": "Wire", "url": "https://a.example"},
        {"title": "Low story", "severity": "low", "sentiment": -0.5, "category": "energy",
         "timestamp": "2026-10-21T10:00:00Z", "source": "Wire", "url": "https://b.example"},
        {"title": "High story", "severity": "high", "sentiment": -7.0, "category": "chokepoints",
         "timestamp": "2026-10-20T10:00:00Z", "source": "Wire", "url": "https://c.example"},
    ]
    table = term.build_headlines(alerts)
    rows = table.children[1].children
    titles = [str(row.children[2].children.children) for row in rows]
    assert titles == ["High story", "Low story", "Unscored story"]
    assert rows[2].children[0].children != "LOW"
    assert [a["title"] for a in select_news(alerts, severity="high")] == ["High story"]
    assert len(select_news(alerts)) == 3


def test_fallback_briefing_handles_unscored_alerts():
    text = news_alerts._build_fallback_briefing(
        [{"title": "Unscored story", "category": "other", "sentiment": None, "source": "Wire"}])
    assert "Unscored story" in text


def test_map_skips_unscored_alerts():
    from data.aggregator import _match_news_to_ports

    alerts = [{"title": "Rotterdam port strike", "body": "", "sentiment": None, "severity": None}]
    assert _match_news_to_ports(alerts) == {}


# --- VADER ----------------------------------------------------------------------------------

def test_no_vader_dependency():
    sources = [p for d in ("data", "api", "components", "scoring", "scripts") for p in (REPO / d).rglob("*.py")]
    sources += [REPO / "app.py", REPO / "config.py"]
    offenders = [str(p) for p in sources
                 if any(t in p.read_text(encoding="utf-8").lower() for t in ("vadersentiment", "sentimentintensityanalyzer"))]
    assert offenders == []
    assert "vader" not in (REPO / "requirements.txt").read_text().lower()


def test_cache_key_bumped():
    from config import NEWS_BRIEFING_CACHE_KEY

    assert NEWS_BRIEFING_CACHE_KEY == "newsapi_briefing_v19"
