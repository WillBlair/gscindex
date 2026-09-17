"""Regression checks for slow, oversized, and duplicate background jobs."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import threading
from unittest.mock import Mock

import pytest
import requests

from data.runtime import RefreshTasks, memory_usage
from data import rss_fetcher as rss


def test_timed_out_job_is_reused_across_refreshes_without_more_workers():
    tasks = RefreshTasks(max_workers=1)
    started, release = threading.Event(), threading.Event()
    calls = []

    def blocked():
        calls.append(threading.get_ident())
        started.set()
        release.wait(5)
        return "complete"

    try:
        original = tasks.submit_once("weather", blocked)
        assert started.wait(2)
        for _ in range(50):
            with pytest.raises(FutureTimeoutError):
                original.result(timeout=0)
            tasks.cancel_pending()
            assert tasks.submit_once("weather", blocked) is original
        assert len(calls) == 1
        release.set()
        assert original.result(timeout=2) == "complete"
        replacement = tasks.submit_once("weather", lambda: "refreshed")
        assert replacement is not original
        assert replacement.result(timeout=2) == "refreshed"
    finally:
        release.set()
        tasks.shutdown()


def test_pending_jobs_can_be_cancelled_and_retried():
    tasks = RefreshTasks(max_workers=1)
    started, release = threading.Event(), threading.Event()
    try:
        running = tasks.submit_once("busy", lambda: (started.set(), release.wait(5)))
        assert started.wait(2)
        queued = tasks.submit_once("queued", lambda: 1)
        tasks.cancel_pending()
        assert queued.cancelled() and not running.cancelled()
        release.set()
        running.result(timeout=2)
        assert tasks.submit_once("queued", lambda: 2).result(timeout=2) == 2
    finally:
        release.set()
        tasks.shutdown()


def response_with(chunks):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = iter(chunks)
    return response


def test_oversized_feed_is_rejected_before_xml_parsing_and_closed(monkeypatch):
    monkeypatch.setattr(rss, "MAX_FEED_BYTES", 10)
    response = response_with([b"123456", b"789012"])
    get = Mock(return_value=response)
    parse = Mock()
    monkeypatch.setattr(rss.requests, "get", get)
    monkeypatch.setattr(rss.feedparser, "parse", parse)
    assert rss.fetch_single_feed({"url": "https://example.com/feed"}) == []
    parse.assert_not_called()
    response.__exit__.assert_called_once()
    assert get.call_args.kwargs["stream"] is True
    assert get.call_args.kwargs["timeout"] == (3.05, 10)


def test_slow_trickle_feed_hits_total_download_budget(monkeypatch):
    response = response_with([b"one", b"two"])
    monkeypatch.setattr(rss.requests, "get", Mock(return_value=response))
    monkeypatch.setattr(rss.time, "monotonic", Mock(side_effect=[0, 1, 21]))
    with pytest.raises(TimeoutError):
        rss._download_feed("https://example.com/feed")
    response.__exit__.assert_called_once()


def test_network_timeout_preserves_other_news_sources(monkeypatch):
    monkeypatch.setattr(rss.requests, "get", Mock(side_effect=requests.Timeout("slow feed")))
    assert rss.fetch_single_feed({"url": "https://example.com/feed"}) == []


def test_concurrent_consumers_download_one_shared_snapshot(monkeypatch):
    cached = {}
    fetch = Mock(return_value=[
        {"title": "Port strike", "url": "https://example.com/1", "published": "2026-09-17", "description": "Shipping disruption"},
        {"title": "Canal closed", "url": "https://example.com/2", "published": "2026-09-16", "description": "Shipping disruption"},
    ])
    monkeypatch.setattr(rss, "NEWS_SOURCES", [{"name": "Feed"}])
    monkeypatch.setattr(rss, "fetch_single_feed", fetch)
    monkeypatch.setattr(rss, "get_cached", lambda key, ttl: cached.get(key))
    monkeypatch.setattr(rss, "set_cached", lambda key, value: cached.update({key: value}))
    with ThreadPoolExecutor(max_workers=4) as callers:
        results = list(callers.map(rss.fetch_rss_articles, [1, 2, 50, 100]))
    assert [len(result) for result in results] == [1, 2, 2, 2]
    assert fetch.call_count == 1


def test_memory_telemetry_is_safe_without_linux_proc():
    assert memory_usage()["threads"] >= 1
