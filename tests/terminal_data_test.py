"""Tests for the stored daily history that feeds the Terminal redesign."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

import data.database as database


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Point the database layer at a throwaway SQLite file (never production)."""
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("sqlite", None))
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "terminal.db"))
    database.init_db()
    return database.SQLITE_PATH


def _insert(path, day, category, score):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO daily_category_scores (date, category, score) VALUES (?, ?, ?)",
        (day.isoformat(), category, score),
    )
    conn.commit()
    conn.close()


def test_daily_scores_align_and_mark_missing_days(sqlite_db):
    today = date.today()
    _insert(sqlite_db, today - timedelta(days=2), "energy", 61.5)
    _insert(sqlite_db, today, "energy", 64.0)

    result = database.get_daily_category_scores(91)

    series = result["scores"]["energy"]
    assert len(result["dates"]) == len(series)
    assert result["dates"] == sorted(result["dates"])
    assert result["dates"][-1] == today.isoformat()
    assert series[-3] == 61.5
    assert series[-2] is None
    assert series[-1] == 64.0


def test_daily_scores_empty_without_db(monkeypatch):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("none", None))

    assert database.get_daily_category_scores(91) == {"dates": [], "scores": {}}
