"""Tests for the stored daily history that feeds the Terminal redesign."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

import config
import data.database as database
from components import terminal_data as td


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


# --- Terminal view math (no database; snapshots are built by hand) ----------

BASELINE = config.INDUSTRY_PROFILES["baseline"]["weights"]


def _snapshot(profile_key="baseline", with_history=True):
    """Two stored days (yesterday and today) for every category in every profile."""
    cats = {c for p in config.INDUSTRY_PROFILES.values() for c in p["weights"]}
    snap = {
        "last_updated_utc": "2026-10-22T20:04:45Z",
        "current_scores": {c: 70.0 + i for i, c in enumerate(sorted(cats))},
        "category_metadata": {
            c: {
                "source": f"{c} source", "raw_value": 1.5, "raw_label": "raw",
                "updated": "2026-10-22", "description": "desc", "calculation": "calc",
            }
            for c in cats
        },
        "fallback_categories": [],
    }
    if with_history:
        dates = [(date(2026, 10, 22) - timedelta(days=n)).isoformat() for n in range(91, -1, -1)]
        scores = {}
        for i, c in enumerate(sorted(cats)):
            series = [None] * len(dates)
            series[-2] = 60.0 + i  # yesterday
            series[-1] = None      # today is read before the hourly write
            series[-3] = 55.0 + i
            scores[c] = series
        snap["daily_history"] = {"dates": dates, "scores": scores}
    return snap


def test_index_row_equals_weighted_rows():
    snap = _snapshot()
    rows = td.category_rows(snap, "baseline")
    summary = td.index_summary(snap, "baseline")

    assert summary["today"] == pytest.approx(sum(r["weight"] * r["today"] for r in rows))
    assert summary["yday"] == pytest.approx(sum(r["weight"] * r["yday"] for r in rows))
    assert summary["change"] == pytest.approx(summary["today"] - summary["yday"])
    assert summary["tier"] == td.tier_for(summary["today"])
    assert [r["weight"] for r in rows] == sorted((r["weight"] for r in rows), reverse=True)
    for r in rows:
        assert r["change"] == pytest.approx(r["today"] - r["yday"])
        assert r["effect"] == pytest.approx(r["change"] * r["weight"])
        assert r["label"] == config.CATEGORY_LABELS[r["cat"]]
        assert r["source"] == f"{r['cat']} source"
        assert r["raw_value"] == 1.5 and r["calculation"] == "calc"


def test_missing_yesterday_blanks_row_and_index_change():
    snap = _snapshot()
    snap["daily_history"]["scores"]["tariffs"][-2] = None

    rows = {r["cat"]: r for r in td.category_rows(snap, "baseline")}
    assert rows["tariffs"]["yday"] is None
    assert rows["tariffs"]["change"] is None
    assert rows["tariffs"]["effect"] is None
    assert rows["tariffs"]["today"] == snap["current_scores"]["tariffs"]
    for cat, row in rows.items():
        if cat != "tariffs":
            assert isinstance(row["yday"], float)
            assert isinstance(row["change"], float)
            assert isinstance(row["effect"], float)

    summary = td.index_summary(snap, "baseline")
    assert summary["yday"] is None
    assert summary["change"] is None
    assert isinstance(summary["today"], float)


def test_profiles_use_their_own_weights():
    snap = _snapshot()
    rows = td.category_rows(snap, "semiconductor")
    expected = config.INDUSTRY_PROFILES["semiconductor"]["weights"]
    assert {r["cat"]: r["weight"] for r in rows} == expected


def test_snapshot_without_daily_history_renders_dashes():
    snap = _snapshot(with_history=False)
    rows = td.category_rows(snap, "baseline")
    assert rows
    for r in rows:
        assert r["yday"] is None and r["change"] is None and r["effect"] is None
        assert r["history"] == [None] * 29 + [r["today"]]
    summary = td.index_summary(snap, "baseline")
    assert summary["yday"] is None and summary["change"] is None
    assert td.index_history(snap, "baseline", 7) == [None] * 6 + [summary["today"]]


def test_fallback_flag():
    snap = _snapshot()
    snap["fallback_categories"] = ["energy"]
    rows = {r["cat"]: r for r in td.category_rows(snap, "baseline")}
    assert rows["energy"]["is_fallback"] is True
    assert rows["weather"]["is_fallback"] is False


def test_tier_colors_are_ui_only():
    assert td.tier_for(85)["color"] == "#35D07F"
    assert config.HEALTH_TIERS[0]["color"] == "#3d9b6e"
    assert td.tier_for(85)["label"] == "Healthy"
    assert td.tier_for(79.9)["label"] == "Stable"
    assert td.tier_for(60)["label"] == "Stable"
    assert td.tier_for(59.9)["label"] == "Stressed"
    assert td.tier_for(40)["label"] == "Stressed"
    assert td.tier_for(12)["label"] == "Critical"
    assert td.tier_for(12)["color"] == "#FF4D5E"


def test_today_is_always_live_and_yesterday_is_utc_date_minus_one():
    snap = _snapshot()
    # Stale axis: history ends two days before the snapshot date; yesterday is a gap.
    snap["daily_history"]["dates"] = [
        (date(2026, 10, 20) - timedelta(days=n)).isoformat() for n in range(91, -1, -1)
    ]
    for series in snap["daily_history"]["scores"].values():
        series[-1] = 33.0  # 2026-10-20
    rows = td.category_rows(snap, "baseline")
    assert all(r["yday"] is None for r in rows)
    assert all(r["history"][-1] == r["today"] for r in rows)


def _march_snapshot(last_updated, stored_days=range(1, 17)):
    """Stored value for every category on 2026-03-DD is DD (far from the real date)."""
    snap = _snapshot(with_history=False)
    snap["last_updated_utc"] = last_updated
    days = list(stored_days)
    snap["daily_history"] = {
        "dates": [f"2026-03-{d:02d}" for d in days],
        "scores": {c: [float(d) for d in days] for c in snap["current_scores"]},
    }
    return snap


@pytest.mark.parametrize(
    "last_updated, expected_yday",
    [
        ("2026-03-14T20:04:45Z", 13.0),            # Z suffix
        ("2026-03-14T23:30:00-07:00", 14.0),       # UTC date is already the 15th
        ("2026-03-14T01:30:00+05:00", 12.0),       # UTC date is still the 13th
        ("2026-03-14T20:04:45", 13.0),             # naive timestamp is treated as UTC
        ("2026-03-14T20:04:45.123456+00:00", 13.0),
    ],
)
def test_utc_date_comes_from_last_updated_utc_not_local_clock(last_updated, expected_yday):
    rows = td.category_rows(_march_snapshot(last_updated), "baseline")
    assert all(r["yday"] == expected_yday for r in rows)
    # Today's own point is live, and yesterday's stored point sits just before it.
    assert all(r["history"][-1] == r["today"] for r in rows)
    assert all(r["history"][-2] == expected_yday for r in rows)


def test_utc_date_without_stored_predecessor_gives_none():
    # 01:30+05:00 on the 14th is the 13th in UTC; only the 13th is stored, not the 12th.
    snap = _march_snapshot("2026-03-14T01:30:00+05:00", stored_days=[13])
    assert all(r["yday"] is None for r in td.category_rows(snap, "baseline"))
    assert td.index_summary(snap, "baseline")["yday"] is None
    # Local-date reading (14th) would have found the 13th; UTC reading must not.
    snap = _march_snapshot("2026-03-14T23:30:00-07:00", stored_days=[13])
    assert all(r["yday"] is None for r in td.category_rows(snap, "baseline"))


def test_row_history_uses_stored_days_and_live_today():
    snap = _snapshot()
    rows = {r["cat"]: r for r in td.category_rows(snap, "baseline")}
    hist = rows["weather"]["history"]
    assert len(hist) == 30
    assert hist[-1] == snap["current_scores"]["weather"]
    assert hist[-2] == snap["daily_history"]["scores"]["weather"][-2]
    assert hist[-3] == snap["daily_history"]["scores"]["weather"][-3]
    assert hist[0] is None


def test_index_history_needs_every_category_and_ends_live():
    snap = _snapshot()
    summary = td.index_summary(snap, "baseline")
    for days in (7, 30, 90):
        hist = td.index_history(snap, "baseline", days)
        assert len(hist) == days
        assert hist[-1] == pytest.approx(summary["today"])
    hist = td.index_history(snap, "baseline", 7)
    assert hist[-2] == pytest.approx(summary["yday"])
    assert hist[-3] == pytest.approx(
        sum(w * snap["daily_history"]["scores"][c][-3] for c, w in BASELINE.items())
    )
    assert hist[0] is None

    snap["daily_history"]["scores"]["energy"][-3] = None
    assert td.index_history(snap, "baseline", 7)[-3] is None
    assert td.index_history(snap, "baseline", 7)[-2] == pytest.approx(summary["yday"])
