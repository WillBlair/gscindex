"""Offline tests for the Geopolitical category (Caldara-Iacoviello GPR and the register hook)."""
import io
import math
import sqlite3
from datetime import date, timedelta
from unittest import mock

import pandas as pd
import pytest

import config
import data.database as database
from data.providers import geopolitical
from data.providers.geopolitical import GeopoliticalProvider
from data.sources import gpr

TODAY = date(2026, 10, 22)
LAST = date(2026, 10, 19)   # last day in the synthetic file, three days before TODAY

GPR_ANCHOR = {"series": "gpr", "transform": "log", "direction": "lower_better",
              "best": math.log(70), "normal": math.log(95), "worst": math.log(400)}
ANCHORS = {"inputs": {"gpr": GPR_ANCHOR}}


def _level_for(score):
    """GPR level that the log anchor maps to ``score`` (between normal and worst)."""
    lw, ln = GPR_ANCHOR["worst"], GPR_ANCHOR["normal"]
    return math.exp(lw - score / 80.0 * (lw - ln))


def _daily(values, last=LAST):
    index = pd.date_range(end=pd.Timestamp(last), periods=len(values), freq="D")
    return pd.Series(values, index=index, name="GPRD", dtype=float)


def _dta_bytes(frame):
    buf = io.BytesIO()
    frame.to_stata(buf, write_index=False)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def no_cache():
    with mock.patch.object(gpr, "get_cached", return_value=None), \
         mock.patch.object(gpr, "set_cached"):
        yield


@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
    monkeypatch.setattr(geopolitical, "_today", lambda: TODAY)


def _with_gpr(monkeypatch, series):
    monkeypatch.setattr(gpr, "fetch_gpr_daily", lambda: series)


def _with_register(monkeypatch, row):
    monkeypatch.setattr(geopolitical, "get_last_category_score", lambda category: row)


# ------------------------------------------------------------------------- parsing

def test_gpr_reshaped_file_raises():
    with pytest.raises(ValueError, match="GPRD"):
        gpr.parse_gpr_daily(pd.DataFrame({"date": ["2026-10-19"], "GPR_RENAMED": [100.0]}))
    with pytest.raises(ValueError, match="date"):
        gpr.parse_gpr_daily(pd.DataFrame({"DAY": [20261019], "GPRD": [100.0]}))
    with pytest.raises(ValueError, match="GPR"):
        gpr.parse_gpr_monthly(pd.DataFrame({"month": ["2026-09-01"], "GPR_RENAMED": [100.0]}))
    with pytest.raises(ValueError, match="month"):
        gpr.parse_gpr_monthly(pd.DataFrame({"GPR": [100.0]}))


def test_parse_gpr_daily_sorts_dedupes_and_drops_unusable_rows():
    frame = pd.DataFrame({
        "date": ["2026-10-19", "2026-10-17", "2026-10-18", "2026-10-18", "2026-10-16", None],
        "GPRD": [130.0, 110.0, 120.0, 125.0, float("nan"), 99.0],
    })
    s = gpr.parse_gpr_daily(frame)
    assert list(s.index) == [pd.Timestamp("2026-10-17"), pd.Timestamp("2026-10-18"),
                             pd.Timestamp("2026-10-19")]
    assert list(s) == [110.0, 125.0, 130.0]     # the later duplicate wins


def test_parse_gpr_daily_with_no_usable_rows_raises():
    with pytest.raises(ValueError, match="no usable"):
        gpr.parse_gpr_daily(pd.DataFrame({"date": ["2026-10-19"], "GPRD": [float("nan")]}))


def test_parse_gpr_monthly():
    frame = pd.DataFrame({"month": ["2026-08-01", "2026-07-01", "2026-09-01"],
                          "GPR": [125.5, 167.5, 146.25]})
    s = gpr.parse_gpr_monthly(frame)
    assert list(s.index) == [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01"),
                             pd.Timestamp("2026-09-01")]
    assert list(s) == [167.5, 125.5, 146.25]


# ----------------------------------------------------------------------- fetching

def _response(content):
    resp = mock.Mock()
    resp.content = content
    resp.raise_for_status = mock.Mock()
    return resp


def test_fetch_gpr_daily_reads_the_stata_file_and_caches_it():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-10-18", "2026-10-19"]),
                          "GPRD": [120.0, 130.0]})
    with mock.patch.object(gpr.requests, "get", return_value=_response(_dta_bytes(frame))) as get, \
         mock.patch.object(gpr, "set_cached") as put:
        s = gpr.fetch_gpr_daily()
    assert get.call_args.args[0] == gpr.DAILY_URL
    assert list(s) == [120.0, 130.0] and s.index[-1] == pd.Timestamp("2026-10-19")
    key, packed = put.call_args.args
    assert key == "gpr_daily_v1"
    assert packed == {"dates": ["2026-10-18", "2026-10-19"], "values": [120.0, 130.0]}


def test_fetch_gpr_daily_uses_cache_without_network():
    packed = {"dates": ["2026-10-18", "2026-10-19"], "values": [120.0, 130.0]}
    with mock.patch.object(gpr, "get_cached", return_value=packed) as cached, \
         mock.patch.object(gpr.requests, "get") as get:
        s = gpr.fetch_gpr_daily()
    get.assert_not_called()
    assert cached.call_args.kwargs["ttl"] == 12 * 3600
    assert list(s) == [120.0, 130.0]


def test_fetch_gpr_monthly_reads_the_stata_file_and_caches_it():
    frame = pd.DataFrame({"month": pd.to_datetime(["2026-08-01", "2026-09-01"]),
                          "GPR": [125.5, 146.25]})
    with mock.patch.object(gpr.requests, "get", return_value=_response(_dta_bytes(frame))) as get, \
         mock.patch.object(gpr, "set_cached") as put:
        s = gpr.fetch_gpr_monthly()
    assert get.call_args.args[0] == gpr.MONTHLY_URL
    assert list(s) == [125.5, 146.25]
    assert put.call_args.args[0] == "gpr_monthly_v1"


def test_fetch_gpr_reshaped_file_raises_and_is_not_cached():
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-10-19"]), "OTHER": [1.0]})
    with mock.patch.object(gpr.requests, "get", return_value=_response(_dta_bytes(frame))), \
         mock.patch.object(gpr, "set_cached") as put:
        with pytest.raises(ValueError):
            gpr.fetch_gpr_daily()
    put.assert_not_called()


def test_fetch_gpr_non_stata_body_raises_value_error():
    with mock.patch.object(gpr.requests, "get", return_value=_response(b"<html>moved</html>")):
        with pytest.raises(ValueError):
            gpr.fetch_gpr_daily()


# ------------------------------------------------------------------------ provider

def test_geo_ignores_register_at_zero_weight(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    _with_gpr(monkeypatch, _daily([_level_for(60)] * 40))
    register = mock.Mock(return_value=(TODAY, 40.0))
    monkeypatch.setattr(geopolitical, "get_last_category_score", register)

    score, meta = GeopoliticalProvider().fetch_current()

    assert score == 60.0
    register.assert_not_called()
    assert [i["name"] for i in meta["inputs"]] == ["gpr"]


def test_geo_blends_register_when_enabled(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.5)
    _with_gpr(monkeypatch, _daily([_level_for(60)] * 40))
    _with_register(monkeypatch, (TODAY, 40.0))

    score, meta = GeopoliticalProvider().fetch_current()

    assert score == 50.0
    by_name = {i["name"]: i for i in meta["inputs"]}
    assert set(by_name) == {"gpr", "geo_register"}
    assert by_name["geo_register"]["as_of"] == TODAY.isoformat()
    assert by_name["geo_register"]["status"] == "live"
    assert meta["as_of"] == LAST.isoformat()    # the oldest input used


def test_geo_register_without_stored_score_falls_back_to_gpr(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.5)
    _with_gpr(monkeypatch, _daily([_level_for(60)] * 40))
    _with_register(monkeypatch, None)

    score, meta = GeopoliticalProvider().fetch_current()

    assert score == 60.0
    assert {i["name"]: i["status"] for i in meta["inputs"]} == {"gpr": "live", "geo_register": "missing"}


def test_geo_register_freshness_is_checked_against_its_row_date(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.5)
    _with_gpr(monkeypatch, _daily([_level_for(60)] * 40))
    _with_register(monkeypatch, (TODAY - timedelta(days=5), 40.0))      # stale after 3 days
    score, meta = GeopoliticalProvider().fetch_current()
    assert score == 50.0 and meta["is_stale"] is True

    _with_register(monkeypatch, (TODAY - timedelta(days=12), 40.0))     # dropped after 9 days
    score, meta = GeopoliticalProvider().fetch_current()
    assert score == 60.0 and meta["is_stale"] is False


def test_geo_register_database_error_is_a_missing_input(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.5)
    _with_gpr(monkeypatch, _daily([_level_for(60)] * 40))
    monkeypatch.setattr(geopolitical, "get_last_category_score",
                        mock.Mock(side_effect=RuntimeError("db down")))
    score, _ = GeopoliticalProvider().fetch_current()
    assert score == 60.0


def test_geo_metadata_contract(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    _with_gpr(monkeypatch, _daily([146.4] * 40))

    score, meta = GeopoliticalProvider().fetch_current()

    assert {"source", "raw_value", "raw_label", "description", "calculation", "updated",
            "as_of", "is_stale", "inputs"} <= set(meta)
    assert meta["source"] == "Caldara–Iacoviello GPR (daily)"
    assert meta["raw_value"] == "GPR 30-day mean 146"
    assert "newspaper" in meta["description"] and "pre-2020 median" in meta["description"]
    assert "log" in meta["calculation"] and "anchor" in meta["calculation"]
    assert meta["as_of"] == LAST.isoformat()
    assert meta["is_stale"] is False        # 3 days old against a 14-day stale window
    assert 0.0 <= score <= 100.0


def test_geo_uses_the_30_day_mean_of_the_last_rows(anchors, monkeypatch):
    values = [500.0] * 10 + [_level_for(60)] * 30
    _with_gpr(monkeypatch, _daily(values))
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    score, _ = GeopoliticalProvider().fetch_current()
    assert score == 60.0


def test_geo_needs_twenty_observations(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    _with_gpr(monkeypatch, _daily([100.0] * 19))
    with pytest.raises(RuntimeError):
        GeopoliticalProvider().fetch_current()
    _with_gpr(monkeypatch, _daily([100.0] * 20))
    score, _ = GeopoliticalProvider().fetch_current()
    assert 0.0 <= score <= 100.0


def test_geo_stale_gpr_is_flagged_and_old_gpr_raises(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    _with_gpr(monkeypatch, _daily([100.0] * 40, last=TODAY - timedelta(days=20)))
    _, meta = GeopoliticalProvider().fetch_current()
    assert meta["is_stale"] is True

    _with_gpr(monkeypatch, _daily([100.0] * 40, last=TODAY - timedelta(days=60)))
    with pytest.raises(RuntimeError):
        GeopoliticalProvider().fetch_current()


def test_geo_source_failure_raises_runtime_error_never_a_constant(anchors, monkeypatch):
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    monkeypatch.setattr(gpr, "fetch_gpr_daily", mock.Mock(side_effect=OSError("offline")))
    with pytest.raises(RuntimeError):
        GeopoliticalProvider().fetch_current()


def test_geo_missing_anchor_raises(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    monkeypatch.setattr(geopolitical, "_today", lambda: TODAY)
    monkeypatch.setattr(config, "GEO_REGISTER_WEIGHT", 0.0)
    _with_gpr(monkeypatch, _daily([100.0] * 40))
    with pytest.raises(RuntimeError, match="no anchor for gpr"):
        GeopoliticalProvider().fetch_current()


# ------------------------------------------------------------------------- history

def test_geo_history_is_dated_by_the_file_and_never_extends_past_it(anchors, monkeypatch):
    values = [_level_for(60)] * 20 + [_level_for(40)] * 20
    _with_gpr(monkeypatch, _daily(values))

    hist = GeopoliticalProvider().fetch_history(10)

    assert len(hist) == 10
    assert hist.index[-1] == pd.Timestamp(LAST)      # not TODAY
    assert hist.index[0] == pd.Timestamp(LAST) - pd.Timedelta(days=9)
    assert hist.name == "geopolitical"
    assert hist.notna().all()
    assert 0.0 <= hist.min() and hist.max() <= 100.0


def test_geo_history_keeps_leading_gaps(anchors, monkeypatch):
    _with_gpr(monkeypatch, _daily([_level_for(60)] * 25))     # 25 rows; the mean starts at row 20

    hist = GeopoliticalProvider().fetch_history(30)

    assert len(hist) == 30
    assert hist.iloc[:5].isna().all()        # before the file starts
    assert hist.iloc[5:24].isna().all()      # fewer than 20 observations behind the mean
    assert hist.iloc[24:].notna().all()      # rows 20 to 25 of the file
    assert hist.iloc[-1] == 60.0


def test_geo_history_without_a_source_raises(anchors, monkeypatch):
    monkeypatch.setattr(gpr, "fetch_gpr_daily", mock.Mock(side_effect=OSError("offline")))
    with pytest.raises(RuntimeError):
        GeopoliticalProvider().fetch_history(30)


# ------------------------------------------------------------- get_last_category_score

@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Point the database layer at a throwaway SQLite file (never production)."""
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("sqlite", None))
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "geo.db"))
    database.init_db()
    return database.SQLITE_PATH


def _insert(path, day, category, score):
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO daily_category_scores (date, category, score) VALUES (?, ?, ?)",
                 (day.isoformat(), category, score))
    conn.commit()
    conn.close()


def test_last_category_score_returns_newest_row_for_the_category(sqlite_db):
    _insert(sqlite_db, date(2026, 10, 18), "geo_register", 70.0)
    _insert(sqlite_db, date(2026, 10, 20), "geo_register", 42.5)
    _insert(sqlite_db, date(2026, 10, 21), "energy", 90.0)

    assert database.get_last_category_score("geo_register") == (date(2026, 10, 20), 42.5)


def test_last_category_score_is_none_without_rows(sqlite_db):
    assert database.get_last_category_score("geo_register") is None


def test_last_category_score_is_none_without_a_database(monkeypatch):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("none", None))
    assert database.get_last_category_score("geo_register") is None


def test_last_category_score_postgres_uses_percent_placeholders(monkeypatch):
    cursor = mock.Mock()
    cursor.fetchone.return_value = (date(2026, 10, 20), 42.5)
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("postgres", "postgresql://x"))
    monkeypatch.setattr(database, "get_connection", lambda: conn)

    assert database.get_last_category_score("geo_register") == (date(2026, 10, 20), 42.5)
    sql, params = cursor.execute.call_args.args
    assert "%s" in sql and "?" not in sql and params == ("geo_register",)
    conn.close.assert_called_once()
