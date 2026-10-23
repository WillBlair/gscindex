"""Aggregator v2: eight weighted categories, explicit stale / fallback / exclusion, stored composite.

Every provider, the news / market / port / register jobs, the weather map fetch and the
database writes are mocked. Nothing touches the network or a real database.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd
import pytest

import config
from config import CATEGORY_WEIGHTS
from data import aggregator, cache, database, status
from data.runtime import RefreshTasks
from scoring.engine import renormalized_weights

_SCORES = {
    "supply_chain": 52.5, "chokepoints": 36.1, "energy": 23.3, "tariffs": 46.2,
    "geopolitical": 49.3, "freight": 77.2, "inputs": 41.9, "physical": 82.8,
}


class _SyncTasks:
    """Runs each job inline so results are ready before the aggregator collects them."""

    def submit_once(self, key, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:  # the aggregator sees the exception via future.result()
            future.set_exception(exc)
        return future

    def cancel_pending(self, keep=()):
        pass


class _Provider:
    def __init__(self, category, score=None, history=None, error=None, block=None):
        self.category = category
        self.score = _SCORES.get(category, 70.0) if score is None else score
        self.history = history
        self.error = error
        self.block = block

    def fetch_current(self):
        if self.block is not None:
            self.block.wait(5)
        if self.error:
            raise RuntimeError(self.error)
        today = datetime.now(timezone.utc).date().isoformat()
        return self.score, {
            "source": "test", "raw_value": "1", "raw_label": "x", "description": "d",
            "calculation": "c", "updated": today, "as_of": today, "is_stale": False, "inputs": [],
        }

    def fetch_history(self, days):
        if self.error:
            raise RuntimeError(self.error)
        return self.history if self.history is not None else pd.Series(dtype=float)


class _Weather:
    def fetch_batch_port_weather(self, coords):
        return {}


@pytest.fixture
def harness(monkeypatch):
    """Patch everything aggregate_data touches; returns (run, recorded)."""
    recorded = {"record": [], "snapshot": 0}

    def run(providers=None, *, last=None, register=None, news=None, tasks=None, daily=None,
            sector_tasks=None):
        monkeypatch.setattr(aggregator, "_FETCH_TASKS", tasks or _SyncTasks())
        monkeypatch.setattr(aggregator, "_SECTOR_TASKS", sector_tasks or _SyncTasks())
        monkeypatch.setattr(
            aggregator, "_PROVIDERS",
            providers if providers is not None else [_Provider(c) for c in CATEGORY_WEIGHTS])
        monkeypatch.setattr(aggregator, "_WEATHER", _Weather())
        monkeypatch.setattr(
            aggregator, "fetch_supply_chain_news",
            news or mock.Mock(side_effect=RuntimeError("off")))
        monkeypatch.setattr(aggregator, "scoring_label", lambda: "Claude (stale)")
        monkeypatch.setattr(aggregator, "_fetch_market_data", lambda: {})
        monkeypatch.setattr(aggregator, "generate_port_summaries", lambda: {})
        monkeypatch.setattr(aggregator, "fetch_chokepoint_traffic", lambda: None)
        monkeypatch.setattr(aggregator, "run_register_cycle", register or (lambda: None))
        monkeypatch.setattr(database, "get_last_category_score",
                            last or (lambda cat: None))
        monkeypatch.setattr(database, "get_daily_category_scores",
                            lambda days: daily or {"dates": [], "scores": {}})
        monkeypatch.setattr(
            database, "record_daily_scores",
            lambda composite, scores: recorded["record"].append((composite, dict(scores))))

        def _save(payload):
            recorded["snapshot"] += 1
            return True

        monkeypatch.setattr(database, "save_dashboard_snapshot", _save)
        monkeypatch.setattr(cache, "set_cached_dashboard", lambda data: None)
        monkeypatch.setattr(cache, "get_cached", lambda key, ttl=3600: None)
        monkeypatch.setattr(cache, "set_cached", lambda key, data: None)
        monkeypatch.setattr(status, "set_status", lambda message: None)
        return aggregator.aggregate_data()

    return run, recorded


def _today():
    return datetime.now(timezone.utc).date()


# -- config ----------------------------------------------------------------------------------

def test_weights_sum_and_profiles():
    assert CATEGORY_WEIGHTS == {
        "supply_chain": .20, "chokepoints": .15, "energy": .15, "tariffs": .15,
        "geopolitical": .10, "freight": .10, "inputs": .10, "physical": .05,
    }
    # Tabs: Global is the composite; Semis and Aero are the separate sector indexes.
    assert config.TABS == ("global", "semiconductor", "aerospace")
    assert config.DEFAULT_TAB == "global"
    assert set(config.TABS[1:]) == set(config.SECTORS)
    for key, sector in config.SECTORS.items():
        assert sum(sector["weights"].values()) == pytest.approx(1.0, abs=1e-9), key
        assert not set(sector["weights"]) & set(CATEGORY_WEIGHTS)
    assert config.CATEGORY_LABELS["chokepoints"] == "Chokepoints"
    assert "chokepoints" in config.CATEGORY_COLORS
    for removed in ("DEFAULT_FALLBACK_SCORES", "PORT_DISRUPTION_WEIGHT", "INDUSTRY_PROFILES",
                    "DEFAULT_PROFILE", "INDUSTRY_BASELINE_SHARE"):
        assert not hasattr(config, removed)


def test_renormalized_weights():
    present = set(CATEGORY_WEIGHTS) - {"physical"}
    weights = renormalized_weights(CATEGORY_WEIGHTS, present)
    assert set(weights) == present
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert weights["supply_chain"] == pytest.approx(0.20 / 0.95)
    assert renormalized_weights(CATEGORY_WEIGHTS, set(CATEGORY_WEIGHTS)) == CATEGORY_WEIGHTS
    with pytest.raises(ValueError):
        renormalized_weights(CATEGORY_WEIGHTS, set())


# -- aggregate_data ----------------------------------------------------------------------------

def test_all_present_composite_and_records(harness):
    run, recorded = harness
    data = run()
    expected = sum(CATEGORY_WEIGHTS[c] * _SCORES[c] for c in CATEGORY_WEIGHTS)
    assert data["composite"] == pytest.approx(expected)
    assert set(data["current_scores"]) == set(CATEGORY_WEIGHTS)
    assert data["excluded_categories"] == []
    assert data["stale_categories"] == []
    assert data["fallback_categories"] == []
    assert data["degraded"] is False
    assert recorded["record"] == [(pytest.approx(expected), _SCORES)]
    assert recorded["snapshot"] == 1


def test_failed_provider_uses_recent_stored_score(harness):
    run, recorded = harness
    providers = [_Provider(c, error="down" if c == "energy" else None) for c in CATEGORY_WEIGHTS]
    stored_day = _today() - timedelta(days=2)
    data = run(providers, last=lambda cat: (stored_day, 61.0) if cat == "energy" else None)

    assert data["current_scores"]["energy"] == 61.0
    assert "energy" in data["fallback_categories"]
    assert "energy" in data["stale_categories"]
    assert data["excluded_categories"] == []
    assert data["degraded"] is True
    meta = data["category_metadata"]["energy"]
    assert meta["is_fallback"] is True and meta["is_stale"] is True
    # as_of is the data date, which a stored fallback does not know; stored_on is the row date.
    assert meta["as_of"] is None
    assert meta["stored_on"] == stored_day.isoformat()
    assert "Last stored reading" in meta["source"]
    for key in ("source", "raw_value", "raw_label", "calculation", "updated", "inputs"):
        assert key in meta
    # The stored fallback is never written back as a measurement; failed history stays NaN.
    composite, scores = recorded["record"][0]
    assert "energy" not in scores
    assert composite == pytest.approx(data["composite"])
    assert data["category_history"]["energy"].isna().all()
    # A weighted category on a fallback keeps the snapshot out of the database.
    assert recorded["snapshot"] == 0
    expected = sum(CATEGORY_WEIGHTS[c] * (61.0 if c == "energy" else _SCORES[c])
                   for c in CATEGORY_WEIGHTS)
    assert data["composite"] == pytest.approx(expected)


def test_failed_provider_excluded_when_too_old(harness):
    run, recorded = harness
    providers = [_Provider(c, error="down" if c == "physical" else None) for c in CATEGORY_WEIGHTS]
    old_day = _today() - timedelta(days=400)
    data = run(providers, last=lambda cat: (old_day, 90.0))

    assert data["excluded_categories"] == ["physical"]
    assert "physical" not in data["current_scores"]
    assert "physical" not in data["fallback_categories"]
    assert data["degraded"] is True
    weights = renormalized_weights(CATEGORY_WEIGHTS, set(CATEGORY_WEIGHTS) - {"physical"})
    expected = sum(w * _SCORES[c] for c, w in weights.items())
    assert data["composite"] == pytest.approx(expected)
    composite, scores = recorded["record"][0]
    assert composite is None
    assert "physical" not in scores and scores["energy"] == _SCORES["energy"]
    assert recorded["snapshot"] == 0
    assert data["category_history"]["physical"].isna().all()


def test_no_stored_score_excludes_category(harness):
    run, _ = harness
    providers = [_Provider(c, error="down" if c == "chokepoints" else None)
                 for c in CATEGORY_WEIGHTS]
    data = run(providers)
    assert data["excluded_categories"] == ["chokepoints"]
    assert 0.0 < data["composite"] < 100.0


def test_stored_score_at_drop_limit_is_excluded(harness):
    run, _ = harness
    providers = [_Provider(c, error="down" if c == "physical" else None) for c in CATEGORY_WEIGHTS]
    limit = config.CATEGORY_DROP_AFTER_DAYS["physical"]
    data = run(providers, last=lambda cat: (_today() - timedelta(days=limit), 90.0))
    assert data["excluded_categories"] == ["physical"]
    data = run(providers, last=lambda cat: (_today() - timedelta(days=limit - 1), 90.0))
    assert data["excluded_categories"] == []
    assert data["current_scores"]["physical"] == 90.0


class _ExpiredProvider(_Provider):
    """Every input returned data, all of it past its drop window."""

    def fetch_current(self):
        from data.providers.readings import InputsExpired
        raise InputsExpired("GSCPI for April 2026 is past its freshness drop window")


def test_inputs_expired_is_excluded_not_served_from_storage(harness):
    run, recorded = harness
    providers = [(_ExpiredProvider if c == "supply_chain" else _Provider)(c) for c in CATEGORY_WEIGHTS]
    lookups = []

    def last(cat):
        lookups.append(cat)
        return (_today() - timedelta(days=1), 70.0)       # a fresh-dated row exists

    data = run(providers, last=last)
    assert data["excluded_categories"] == ["supply_chain"]
    assert "supply_chain" not in data["current_scores"]
    assert "supply_chain" not in data["fallback_categories"]
    assert "supply_chain" not in lookups                  # storage is never consulted
    meta = data["category_metadata"]["supply_chain"]
    assert meta["is_fallback"] is False and meta["as_of"] is None
    assert "drop window" in meta["description"]
    assert "Last stored reading" not in meta["source"]
    weights = renormalized_weights(CATEGORY_WEIGHTS, set(CATEGORY_WEIGHTS) - {"supply_chain"})
    assert data["composite"] == pytest.approx(sum(w * _SCORES[c] for c, w in weights.items()))
    assert "supply_chain" not in recorded["record"][0][1]


def test_fetch_failure_still_uses_stored_fallback(harness):
    run, _ = harness
    providers = [_Provider(c, error="HTTP 503" if c == "supply_chain" else None) for c in CATEGORY_WEIGHTS]
    data = run(providers, last=lambda cat: (_today() - timedelta(days=1), 70.0))
    assert data["excluded_categories"] == []
    assert data["current_scores"]["supply_chain"] == 70.0
    assert "supply_chain" in data["fallback_categories"]


def test_non_finite_score_goes_through_fallback_path(harness):
    run, _ = harness
    providers = [_Provider(c, score=float("nan") if c == "tariffs" else None)
                 for c in CATEGORY_WEIGHTS]
    data = run(providers)
    assert data["excluded_categories"] == ["tariffs"]
    assert "tariffs" not in data["current_scores"]


def test_stale_provider_listed_in_stale_categories(harness):
    run, _ = harness

    class _StaleProvider(_Provider):
        def fetch_current(self):
            score, meta = super().fetch_current()
            meta["is_stale"] = True
            return score, meta

    providers = [(_StaleProvider if c == "supply_chain" else _Provider)(c) for c in CATEGORY_WEIGHTS]
    data = run(providers)
    assert data["stale_categories"] == ["supply_chain"]
    assert data["fallback_categories"] == []
    assert data["degraded"] is False


def test_no_score_explanation_key(harness):
    run, _ = harness
    data = run()
    assert "score_explanation" not in data


def test_disruptions_use_one_impact_scale(harness):
    run, _ = harness
    news = mock.Mock(return_value=(
        [{"title": "Strait closed", "severity": "high", "sentiment": -7.5, "category": "energy"},
         {"title": "Unscored story", "severity": None, "sentiment": None, "category": "other"}],
        "", "",
    ))
    data = run(news=news)
    by_event = {d["event"]: d for d in data["disruptions"]}
    energy = next(d for d in data["disruptions"] if d["categories"] == ["energy"]
                  and d["event"] != "Strait closed")
    assert energy["impact_score"] == pytest.approx(100 - _SCORES["energy"])
    assert by_event["Strait closed"]["impact_score"] == pytest.approx(75.0)
    assert "Unscored story" not in by_event
    assert data["news_scoring"] == "Claude (stale)"
    # News never overrides the geopolitical category.
    assert data["current_scores"]["geopolitical"] == _SCORES["geopolitical"]


def test_register_recorded_when_ready(harness):
    run, recorded = harness
    data = run(register=lambda: 42.0)
    _, scores = recorded["record"][0]
    assert scores["geo_register"] == 42.0
    assert "geo_register" not in data["current_scores"]


def test_slow_register_never_delays_the_composite(harness):
    run, recorded = harness
    release = threading.Event()

    def slow_register():
        release.wait(10)
        return 42.0

    tasks = RefreshTasks(max_workers=3)
    try:
        started = datetime.now()
        data = run(register=slow_register, tasks=tasks)
        elapsed = (datetime.now() - started).total_seconds()
    finally:
        release.set()
        tasks.shutdown()
    assert elapsed < 5
    assert data["composite"] > 0
    _, scores = recorded["record"][0]
    assert "geo_register" not in scores


def test_timed_out_provider_uses_fallback_path(harness, monkeypatch):
    run, _ = harness
    monkeypatch.setattr(config, "PROVIDER_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(config, "PROVIDER_TIMEOUT_OVERRIDES", {})
    release = threading.Event()
    providers = [_Provider(c, block=release if c == "freight" else None) for c in CATEGORY_WEIGHTS]
    tasks = RefreshTasks(max_workers=3)
    stored_day = _today() - timedelta(days=3)
    try:
        data = run(providers, tasks=tasks,
                   last=lambda cat: (stored_day, 64.0) if cat == "freight" else None)
    finally:
        release.set()
        tasks.shutdown()
    assert data["current_scores"]["freight"] == 64.0
    assert "freight" in data["fallback_categories"]
    assert data["provider_errors"]["freight"] == "Provider timed out"


def test_provider_timeouts_come_from_config():
    assert config.PROVIDER_TIMEOUT_SECONDS == 45
    assert config.PROVIDER_TIMEOUT_OVERRIDES["physical"] >= 150
    assert config.PROVIDER_TIMEOUT_OVERRIDES["freight"] >= 150
    assert aggregator._provider_timeout("physical") == config.PROVIDER_TIMEOUT_OVERRIDES["physical"]
    assert aggregator._provider_timeout("energy") == 45


def test_weather_is_map_only():
    assert all(p.category != "weather" for p in aggregator._PROVIDERS)
    sector_categories = {c for s in config.SECTORS.values() for c in s["weights"]}
    assert {p.category for p in aggregator._PROVIDERS} == set(CATEGORY_WEIGHTS) | sector_categories


# -- history alignment ---------------------------------------------------------------------------

def test_history_points_after_today_are_dropped():
    dates = pd.date_range("2026-10-01", "2026-10-22", freq="D")
    hist = pd.Series(
        [60.0, 99.0, 70.0],
        index=pd.to_datetime(["2026-10-10", "2026-10-26", "2026-10-15"]),
    )
    aligned = aggregator._align_history_to_dates(hist, dates, 75.0)
    assert aligned.index.max() == pd.Timestamp("2026-10-22")
    assert 99.0 not in aligned.values
    assert aligned.loc["2026-10-21"] == 70.0
    assert aligned.iloc[-1] == 75.0
    assert aligned.loc[:"2026-10-09"].isna().all()


# -- record_daily_scores ---------------------------------------------------------------------------

def test_record_daily_scores_skips_composite_when_none(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("sqlite", None))
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "scores.db"))
    monkeypatch.setattr(database, "_daily_scores_written_hour", None)
    database.init_db()

    assert database.record_daily_scores(None, {"energy": 23.3, "geo_register": 61.0}) is True
    conn = sqlite3.connect(database.SQLITE_PATH)
    try:
        assert conn.execute("SELECT COUNT(*) FROM daily_scores").fetchone()[0] == 0
        rows = dict(conn.execute("SELECT category, score FROM daily_category_scores").fetchall())
    finally:
        conn.close()
    assert rows == {"energy": 23.3, "geo_register": 61.0}


# -- consumers of the snapshot composite (kept from crashing until Tasks 16-17) ---------------------

def test_snapshot_composite_prefers_stored_value_and_never_raises():
    from scoring.engine import snapshot_composite

    assert snapshot_composite({"composite": 47.3, "current_scores": {"energy": 1.0}}) == 47.3
    assert snapshot_composite({"composite": None, "current_scores": _SCORES}) is None
    full = sum(CATEGORY_WEIGHTS[c] * _SCORES[c] for c in CATEGORY_WEIGHTS)
    assert snapshot_composite({"current_scores": _SCORES}) == pytest.approx(full)
    # An old snapshot (weather, no chokepoints / inputs / physical) gives None, not ValueError.
    assert snapshot_composite({"current_scores": {"weather": 80.0, "energy": 50.0}}) is None


def test_latest_api_survives_a_missing_category(monkeypatch):
    from flask import Flask

    from api.routes import api_bp

    app = Flask(__name__)
    app.register_blueprint(api_bp)
    scores = {c: s for c, s in _SCORES.items() if c != "physical"}
    monkeypatch.setattr(cache, "get_cached_dashboard", lambda: {
        "current_scores": scores, "composite": 45.0, "excluded_categories": ["physical"],
    })
    body = app.test_client().get("/api/v1/latest").get_json()
    assert body["composite_index"] == 45.0
    monkeypatch.setattr(cache, "get_cached_dashboard", lambda: {"current_scores": scores})
    response = app.test_client().get("/api/v1/latest")
    assert response.status_code == 200
    assert response.get_json()["composite_index"] is None
