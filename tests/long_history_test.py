"""Tests for the once-a-day long history loader (data/long_history.py)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import config
import data.long_history as lh
from tests.history_helpers import START, rows

D = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    lh.reset()
    disk = {}
    monkeypatch.setattr(lh.cache, "get_cached", lambda key, ttl=3600: disk.get(key))
    monkeypatch.setattr(lh.cache, "set_cached", lambda key, data: disk.__setitem__(key, data))
    yield disk
    lh.reset()


def reads(monkeypatch, result):
    calls = []

    def export(start, categories, strict=False):
        calls.append((start, tuple(categories), strict))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(lh.database, "export_category_rows", export)
    return calls


def test_reads_the_database_once_per_utc_day(monkeypatch):
    calls = reads(monkeypatch, rows(START, 5))
    assert lh.get() is None and lh.refresh_if_due(D) is True and lh.refresh_if_due(D) is True
    assert calls == [(date(2019, 1, 11), tuple(config.CATEGORY_WEIGHTS), True)]
    assert lh.refresh_if_due(D + timedelta(days=1)) is True and len(calls) == 2
    assert lh.get()["loaded_on"] == "2026-11-11"


def test_a_failed_or_empty_read_keeps_the_previous_history(monkeypatch):
    reads(monkeypatch, rows(START, 5))
    lh.refresh_if_due(D)
    reads(monkeypatch, RuntimeError("down"))
    assert lh.refresh_if_due(D + timedelta(days=1)) is False and lh.get()["loaded_on"] == "2026-11-10"
    reads(monkeypatch, [])
    assert lh.refresh_if_due(D + timedelta(days=1)) is False and lh.get()["loaded_on"] == "2026-11-10"
    reads(monkeypatch, rows(START, 6))
    assert lh.refresh_if_due(D + timedelta(days=1)) is True and len(lh.get()["dates"]) == 6


def test_todays_disk_copy_skips_the_database(monkeypatch):
    reads(monkeypatch, rows(START, 5))
    lh.refresh_if_due(D)
    lh.reset()
    calls = reads(monkeypatch, RuntimeError("must not be called"))
    assert lh.refresh_if_due(D) is True and calls == [] and len(lh.get()["dates"]) == 5


def test_prime_from_disk_shows_an_older_copy_until_the_next_load(monkeypatch):
    reads(monkeypatch, rows(START, 5))
    lh.refresh_if_due(D)
    lh.reset()
    calls = reads(monkeypatch, rows(START, 6))
    assert lh.prime_from_disk() is True and len(lh.get()["dates"]) == 5 and calls == []
    assert lh.refresh_if_due(D + timedelta(days=1)) is True and len(calls) == 1


def test_a_disk_copy_for_another_start_date_is_ignored(monkeypatch, store):
    store[config.HISTORY_CACHE_KEY] = {"loaded_on": "2026-11-10", "start": "2020-01-01",
                                       "dates": ["2020-01-01"], "scores": {}}
    assert lh.prime_from_disk() is False and lh.get() is None
