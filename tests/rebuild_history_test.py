"""Offline tests for the history rebuild (scripts/rebuild_category_history.py).

Providers are fakes and the database is a throwaway SQLite file; nothing touches the network
or production.
"""
import csv
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import config
from data import database
from scripts import rebuild_category_history as rebuild

TODAY = date(2026, 10, 22)


class FakeProvider:
    def __init__(self, series_by_date: dict[date, float]):
        self.series_by_date = series_by_date
        self.asked_days = None

    def fetch_history(self, days: int) -> pd.Series:
        self.asked_days = days
        end = TODAY            # providers run to today; the rebuild must drop it
        index = pd.date_range(end=pd.Timestamp(end), periods=days, freq="D")
        return pd.Series([self.series_by_date.get(d.date(), np.nan) for d in index], index=index)


def _providers(overrides: dict[date, float] | None = None, missing: dict[str, set] | None = None):
    """Every weighted category at a constant 50 + offset, with optional per-category gaps."""
    out = {}
    for i, cat in enumerate(config.CATEGORY_WEIGHTS):
        gaps = (missing or {}).get(cat, set())
        values = {TODAY - timedelta(days=n): 50.0 + i for n in range(0, 200)
                  if (TODAY - timedelta(days=n)) not in gaps}
        out[cat] = FakeProvider(values)
    return out


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("sqlite", None))
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "scores.db"))
    database.init_db()
    return tmp_path / "scores.db"


def _all_rows(path):
    conn = sqlite3.connect(path)
    try:
        cats = conn.execute("SELECT date, category, score FROM daily_category_scores ORDER BY 1, 2").fetchall()
        comp = conn.execute("SELECT date, score FROM daily_scores ORDER BY 1").fetchall()
    finally:
        conn.close()
    return cats, comp


def _seed(path, cat_rows, comp_rows):
    conn = sqlite3.connect(path)
    with conn:
        conn.executemany("INSERT INTO daily_category_scores VALUES (?, ?, ?)", cat_rows)
        conn.executemany("INSERT INTO daily_scores VALUES (?, ?)", comp_rows)
    conn.close()


def test_rebuild_dry_run_writes_csv_and_no_db_writes(sqlite_db, tmp_path):
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    _seed(sqlite_db, [(yesterday, "energy", 10.0), ("2020-01-01", "energy", 33.0)], [(yesterday, 11.0)])
    before = _all_rows(sqlite_db)
    backups = tmp_path / "backups"

    result = rebuild.run(days=5, write=False, providers=_providers(), today=TODAY, backup_dir=backups)

    assert _all_rows(sqlite_db) == before                       # a dry run writes nothing
    csv_path = backups / f"rebuild_dryrun_{TODAY.isoformat()}.csv"
    assert result.csv_path == csv_path
    with open(csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == ["date", "category", "old", "new"]
    dates = {r["date"] for r in rows}
    assert dates == {(TODAY - timedelta(days=n)).isoformat() for n in range(1, 6)}   # ends yesterday
    energy = next(r for r in rows if r["date"] == yesterday and r["category"] == "energy")
    assert float(energy["old"]) == 10.0 and float(energy["new"]) == 52.0
    comp = next(r for r in rows if r["date"] == yesterday and r["category"] == "composite")
    assert float(comp["old"]) == 11.0 and comp["new"] != ""
    assert not list(backups.glob("category_scores_pre_v2_*"))   # no export without --write
    assert result.written == 0


def test_providers_asked_for_days_plus_30(sqlite_db, tmp_path):
    providers = _providers()
    rebuild.run(days=7, write=False, providers=providers, today=TODAY, backup_dir=tmp_path)
    assert {p.asked_days for p in providers.values()} == {37}


def test_composite_only_on_complete_dates(sqlite_db, tmp_path):
    gap_day = TODAY - timedelta(days=3)
    providers = _providers(missing={"physical": {gap_day}})
    result = rebuild.run(days=5, write=False, providers=providers, today=TODAY, backup_dir=tmp_path)

    assert gap_day not in result.composite
    assert len(result.composite) == 4
    expected = sum(w * (50.0 + i) for i, (cat, w) in enumerate(config.CATEGORY_WEIGHTS.items()))
    assert all(v == pytest.approx(expected) for v in result.composite.values())
    assert result.dates_without_composite == [gap_day]
    assert np.isnan(result.new["physical"][gap_day])


def test_provider_failure_leaves_category_missing_and_no_composite(sqlite_db, tmp_path):
    providers = _providers()

    def boom(days):
        raise RuntimeError("source down")
    providers["inputs"].fetch_history = boom
    result = rebuild.run(days=3, write=False, providers=providers, today=TODAY, backup_dir=tmp_path)
    assert result.composite == {}
    assert len(result.dates_without_composite) == 3


def test_write_exports_backup_then_upserts_without_deleting(sqlite_db, tmp_path):
    d1, d2 = TODAY - timedelta(days=1), TODAY - timedelta(days=2)
    gap = TODAY - timedelta(days=3)
    _seed(sqlite_db,
          [(d1.isoformat(), "energy", 10.0), (gap.isoformat(), "physical", 77.0),
           ("2020-01-01", "energy", 33.0), (d2.isoformat(), "geo_register", 61.0)],
          [(d1.isoformat(), 11.0), ("2020-01-01", 12.0)])
    providers = _providers(missing={"physical": {gap}})
    backups = tmp_path / "backups"

    result = rebuild.run(days=3, write=True, providers=providers, today=TODAY, backup_dir=backups)

    cats, comp = _all_rows(sqlite_db)
    by_key = {(d, c): s for d, c, s in cats}
    assert by_key[(d1.isoformat(), "energy")] == pytest.approx(52.0)         # overwritten
    assert by_key[(gap.isoformat(), "physical")] == 77.0                     # NaN new never overwrites
    assert by_key[("2020-01-01", "energy")] == 33.0                          # older rows untouched
    assert by_key[(d2.isoformat(), "geo_register")] == 61.0                  # register not touched
    assert all(np.isfinite(s) for _, _, s in cats) and all(np.isfinite(s) for _, s in comp)
    assert dict(comp)["2020-01-01"] == 12.0
    assert gap.isoformat() not in dict(comp)                                 # gap day: no composite row
    assert dict(comp)[d1.isoformat()] != 11.0

    backup = backups / f"category_scores_pre_v2_{TODAY.isoformat()}.csv"
    with open(backup, newline="") as fh:
        saved = list(csv.reader(fh))
    assert saved[0] == ["date", "category", "score"]
    saved_keys = {(r[0], r[1]): float(r[2]) for r in saved[1:]}
    assert saved_keys[(d1.isoformat(), "energy")] == 10.0                    # the OLD value
    assert saved_keys[(d1.isoformat(), "composite")] == 11.0
    assert ("2020-01-01", "energy") not in saved_keys                        # only rows it touches
    assert (d2.isoformat(), "geo_register") not in saved_keys
    assert result.written > 0


def test_rebuild_write_refuses_postgres_without_confirm(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("postgres", "postgresql://x/y"))
    monkeypatch.delenv("CONFIRM_PROD_REBUILD", raising=False)

    def no_connection():
        raise AssertionError("must not connect")
    monkeypatch.setattr(database, "get_connection", no_connection)
    monkeypatch.setattr(rebuild, "default_providers", lambda: pytest.fail("must not fetch"))

    with pytest.raises(rebuild.WriteRefused, match="CONFIRM_PROD_REBUILD"):
        rebuild.run(days=3, write=True, providers=_providers(), today=TODAY, backup_dir=tmp_path)
    assert rebuild.main(["--write", "--days", "3"]) != 0

    monkeypatch.setenv("CONFIRM_PROD_REBUILD", "yes")
    rebuild.check_write_allowed()           # the confirm variable lifts the refusal


def test_dry_run_on_postgres_is_allowed_without_confirm(monkeypatch):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("postgres", "postgresql://x/y"))
    monkeypatch.delenv("CONFIRM_PROD_REBUILD", raising=False)
    rebuild.check_write_allowed(write=False)


def test_upsert_helpers_skip_non_finite(sqlite_db):
    d = date(2026, 10, 1)
    assert database.upsert_scores_for_dates([(d, "energy", float("nan")), (d, "freight", 40.0)]) == 1
    assert database.upsert_composite_for_dates([(d, float("inf"))]) == 0
    cats, comp = _all_rows(sqlite_db)
    assert cats == [(d.isoformat(), "freight", 40.0)] and comp == []
    assert database.export_category_rows(d, ["freight", "composite"]) == [(d, "freight", 40.0)]


# ---------------------------------------------------------------- backtest helpers

def test_backtest_widens_fred_windows_and_restores_them_after_an_error():
    from scripts import backtest_composite as bt
    before = {n: getattr(config, n) for n in bt.FRED_WINDOWS}
    with pytest.raises(RuntimeError):
        with bt.widened_fred_windows():
            assert all(getattr(config, n) == bt.WIDE_FRED_DAYS for n in bt.FRED_WINDOWS)
            raise RuntimeError("boom")
    assert {n: getattr(config, n) for n in bt.FRED_WINDOWS} == before


def test_backtest_composites_full_only_when_all_eight_and_renormalized_otherwise():
    from scripts import backtest_composite as bt
    scores = {cat: 60.0 for cat in config.CATEGORY_WEIGHTS}
    full, available, n = bt.composites(scores)
    assert full == pytest.approx(60.0) and available == pytest.approx(60.0) and n == 8

    scores["chokepoints"] = None
    scores["physical"] = 100.0
    full, available, n = bt.composites(scores)
    assert full is None and n == 7
    weights = config.CATEGORY_WEIGHTS
    kept = {c: w for c, w in weights.items() if c != "chokepoints"}
    expected = sum(w * (100.0 if c == "physical" else 60.0) for c, w in kept.items()) / sum(kept.values())
    assert available == pytest.approx(expected)
    assert bt.composites({c: None for c in weights}) == (None, None, 0)


def test_backtest_lookup_is_none_without_a_measurement():
    from scripts import backtest_composite as bt
    s = pd.Series([1.0, np.nan], index=pd.to_datetime(["2020-04-15", "2020-04-16"]))
    assert bt.lookup(s, date(2020, 4, 15)) == 1.0
    assert bt.lookup(s, date(2020, 4, 16)) is None
    assert bt.lookup(s, date(2008, 7, 15)) is None
    assert bt.lookup(None, date(2008, 7, 15)) is None
