"""Tests for the history page math (components/history_data.py)."""
from __future__ import annotations

import csv
from datetime import date, timedelta

import pytest

import config
import components.history_data as hd
from components import terminal_data
from data.providers.chokepoints import CREDIT
from tests.history_helpers import CATS, START, rows, snapshot

SECTOR_CATS = [c for s in config.SECTORS.values() for c in s["weights"]]


def test_build_history_keeps_the_eight_global_keys_from_the_start_date():
    data = rows(START - timedelta(days=3), 10, overrides={(START + timedelta(days=1), "energy"): float("nan")})
    data += [(START, "semis_memory_prices", 5.0), (START, "geo_register", 5.0)]
    h = hd.build_history(data, START, loaded_on=date(2026, 11, 10))
    assert h["dates"][0] == "2019-01-11" and len(h["dates"]) == 7 and h["loaded_on"] == "2026-11-10"
    assert set(h["scores"]) == set(CATS) and h["scores"]["energy"][1] is None
    assert hd.build_history(rows(START - timedelta(days=9), 5), START, START)["dates"] == []


def test_a_day_needs_all_eight_rows_and_matches_the_dashboard_sparkline():
    gap = START + timedelta(days=2)
    h = hd.build_history(rows(START, 5, missing={gap: {"physical"}}, overrides={(START, "energy"): 10.0}), START, START)
    index = hd.daily_index(h)
    assert index[2] is None and index[1] == pytest.approx(60.0) and index[0] == pytest.approx(52.5)
    snap = snapshot(START + timedelta(days=5)) | {"daily_history": {"dates": h["dates"], "scores": h["scores"]}}
    rounded = lambda values: [None if v is None else round(v, 6) for v in values]  # noqa: E731
    assert rounded(terminal_data.index_history(snap, "global", 6)[:-1]) == rounded(index)


def test_series_adds_the_live_point_only_without_an_exclusion():
    h = hd.build_history(rows(START, 5), START, START)
    today = START + timedelta(days=6)
    points = hd.series(h, snapshot(today, score=41.0))
    assert len(points) == 7 and points[-1] == (today, 41.0) and points[-2] == (today - timedelta(days=1), None)
    assert hd.series(h, snapshot(today, excluded=("energy",)))[-1][0] == today - timedelta(days=1)
    assert hd.series(h, None)[-1] == (START + timedelta(days=4), pytest.approx(60.0))


def test_a_stored_row_dated_today_never_replaces_the_live_value():
    today = START + timedelta(days=4)
    points = hd.series(hd.build_history(rows(START, 5), START, today), snapshot(today, score=41.0))
    assert [d for d, _ in points].count(today) == 1 and points[-1] == (today, 41.0)


def test_extremes_and_episode_rows_come_from_the_data():
    day, base = START + timedelta(days=95), START + timedelta(days=5)
    data = rows(START, 100, overrides={(day, c): 30.0 for c in CATS} | {(base, "energy"): 100.0})
    h = hd.build_history(data, START, START)
    ext = hd.extremes(hd.series(h, None))
    assert ext["low"] == (day, pytest.approx(30.0)) and ext["high"] == (base, pytest.approx(66.0))
    [row] = hd.episode_rows(h, [{"date": day.isoformat(), "label": "X", "text": "t", "source_url": "https://e.org"}], 90)
    assert row["n"] == 1 and row["date"] == day and row["index"] == pytest.approx(30.0)
    assert row["tier"]["label"] == "Critical" and row["change"] == pytest.approx(-36.0)
    energy = next(c for c in row["categories"] if c["cat"] == "energy")
    assert len(row["categories"]) == 8 and energy["score"] == 30.0 and energy["change"] == pytest.approx(-70.0)


def test_an_episode_on_a_gap_or_after_the_data_has_no_index():
    gap = START + timedelta(days=95)
    h = hd.build_history(rows(START, 100, missing={gap: {"freight"}}), START, START)
    blank = {"label": "A", "text": "", "source_url": ""}
    a, b = hd.episode_rows(h, [blank | {"date": gap.isoformat()}, blank | {"date": "2030-01-01"}], 90)
    assert a["index"] is None and a["tier"] is None and a["change"] is None
    assert next(c for c in a["categories"] if c["cat"] == "freight")["score"] is None
    assert b["index"] is None and all(c["score"] is None for c in b["categories"])


def test_csv_has_one_row_per_day_the_credit_and_empty_cells_for_gaps():
    gap = START + timedelta(days=1)
    h = hd.build_history(rows(START, 3, missing={gap: {"physical"}}), START, START)
    today = START + timedelta(days=3)
    lines = hd.history_csv(h, snapshot(today, score=41.0)).strip().splitlines()
    assert lines[0] == "date,index," + ",".join(CATS) + ",credit" and len(lines) == 5
    assert lines[1].startswith("2019-01-11,60.00,") and lines[4].startswith(f"{today.isoformat()},41.00,41.00,")
    cells = next(csv.reader([lines[2]]))
    assert cells[1] == "" and cells[2 + CATS.index("physical")] == "" and cells[-1] == CREDIT
    assert not any(key in "\n".join(lines) for key in SECTOR_CATS)
