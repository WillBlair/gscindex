"""Sector indexes in the aggregator: Semis and Aero beside the global composite, fully isolated.

Uses the aggregator_v2 harness: every provider, the side jobs, the weather map and the database
are mocked. Nothing touches the network or a real database.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import timedelta

import pytest

import config
from config import CATEGORY_WEIGHTS, SECTORS
from data import aggregator
from aggregator_v2_test import _ExpiredProvider, _Provider, _SCORES, _today, harness  # noqa: F401

_SECTOR_SCORES = {
    "semis_memory_prices": 0.0, "semis_logic_prices": 66.0, "semis_fab_utilization": 85.0,
    "aero_throughput": 80.0, "aero_flow": 76.0, "aero_mill_prices": 74.0, "aero_forge_cast": 37.0,
}
_SECTOR_CATS = set(_SECTOR_SCORES)
_OLD_KEYS = (
    "chip_fab_util", "chip_memory_prices", "chip_lead_times", "chip_wafer_prices",
    "aero_metals", "aero_orders", "aero_production", "aero_ppi",
)
_GLOBAL_KEYS = ("composite", "degraded", "disruptions", "fallback_categories",
                "excluded_categories", "stale_categories")


def _providers(*, scores=None, errors=(), expired=()):
    """The 8 global providers (healthy) plus the 7 sector providers."""
    scores = {**_SECTOR_SCORES, **(scores or {})}
    out = [_Provider(c) for c in CATEGORY_WEIGHTS]
    for cat, score in scores.items():
        if cat in expired:
            out.append(_ExpiredProvider(cat))
        else:
            out.append(_Provider(cat, score=score, error="HTTP 503" if cat in errors else None))
    return out


def _disruptions(data):
    """Disruptions in a fixed order (providers finish in any order)."""
    return sorted(data["disruptions"], key=lambda d: d["event"])


def _global_view(data):
    return {key: _disruptions(data) if key == "disruptions" else data[key] for key in _GLOBAL_KEYS}


def test_sector_categories_have_their_own_timeout_and_drop_window():
    for cat in _SECTOR_CATS:
        assert aggregator._provider_timeout(cat) == config.SECTOR_PROVIDER_TIMEOUT_SECONDS
        assert aggregator._drop_after_days(cat) == config.SECTOR_DROP_AFTER_DAYS
    assert aggregator._drop_after_days("energy") == config.CATEGORY_DROP_AFTER_DAYS["energy"]
    assert aggregator._provider_timeout("energy") == config.PROVIDER_TIMEOUT_SECONDS


def test_sector_outage_leaves_global_untouched(harness):
    run, recorded = harness
    reference = run(_providers())
    ref_record = recorded["record"][-1]

    # Every sector category fails; one serves a stored fallback, the rest are excluded.
    stored = (_today() - timedelta(days=3), 55.0)
    data = run(_providers(errors=_SECTOR_CATS),
               last=lambda cat: stored if cat == "aero_flow" else None)

    assert _global_view(data) == _global_view(reference)
    assert data["degraded"] is False
    assert data["composite"] == pytest.approx(sum(CATEGORY_WEIGHTS[c] * _SCORES[c] for c in CATEGORY_WEIGHTS))
    for key in ("fallback_categories", "excluded_categories", "stale_categories"):
        assert not set(data[key]) & _SECTOR_CATS
    # The global composite stored for the day is unchanged and the snapshot is still saved.
    assert recorded["record"][-1][0] == pytest.approx(ref_record[0])
    assert recorded["snapshot"] == 2

    semis, aero = data["sectors"]["semiconductor"], data["sectors"]["aerospace"]
    assert semis["degraded"] is True and aero["degraded"] is True
    assert semis["index"] is None and semis["tier"] is None and semis["coverage"] == 0
    assert semis["excluded_categories"] == sorted(SECTORS["semiconductor"]["weights"])
    assert aero["fallback_categories"] == ["aero_flow"]
    assert aero["stale_categories"] == ["aero_flow"]
    assert aero["coverage"] == 1 and aero["index"] is None


def test_sector_below_70_not_in_disruptions(harness):
    run, _ = harness
    reference = run(_providers())
    data = run(_providers(scores={cat: 12.0 for cat in _SECTOR_CATS}))
    assert _disruptions(data) == _disruptions(reference)
    for item in data["disruptions"]:
        assert not set(item["categories"]) & _SECTOR_CATS
    # The global categories below 70 still are listed.
    assert {c for d in data["disruptions"] for c in d["categories"]} == {
        c for c, s in _SCORES.items() if s < config.DISRUPTION_SCORE_THRESHOLD}


def test_sector_index_mean_and_coverage(harness):
    run, recorded = harness
    data = run(_providers())
    semis = data["sectors"]["semiconductor"]
    assert semis["index"] == pytest.approx((0.0 + 66.0 + 85.0) / 3)
    assert semis["coverage"] == 3
    assert semis["tier"] == "Stressed"
    assert semis["degraded"] is False
    assert semis["excluded_categories"] == semis["fallback_categories"] == semis["stale_categories"] == []
    assert data["sectors"]["aerospace"]["index"] == pytest.approx((80 + 76 + 74 + 37) / 4)
    assert set(data["sectors"]) == set(SECTORS)
    for block in data["sectors"].values():
        assert set(block) == {"index", "tier", "coverage", "degraded", "stale_categories",
                              "excluded_categories", "fallback_categories"}
    # Sector categories are in current_scores / metadata / history for the UI, and their
    # measured values are recorded beside the global ones.
    for cat, score in _SECTOR_SCORES.items():
        assert data["current_scores"][cat] == score
        assert data["category_metadata"][cat]["score"] == round(score, 1)
        assert data["category_history"][cat].iloc[-1] == score
    assert recorded["record"][-1][1] == {**_SCORES, **_SECTOR_SCORES}

    # 3 of 4 Aero categories: mean of the three present.
    data = run(_providers(errors={"aero_forge_cast"}))
    aero = data["sectors"]["aerospace"]
    assert aero["index"] == pytest.approx((80 + 76 + 74) / 3)
    assert aero["tier"] == "Stable"
    assert aero["coverage"] == 3
    assert aero["excluded_categories"] == ["aero_forge_cast"]
    assert aero["degraded"] is True
    assert "aero_forge_cast" not in data["current_scores"]

    # 2 of 4: below the coverage minimum, no index.
    data = run(_providers(errors={"aero_forge_cast", "aero_flow"}))
    aero = data["sectors"]["aerospace"]
    assert aero["index"] is None and aero["tier"] is None
    assert aero["coverage"] == 2
    assert aero["excluded_categories"] == ["aero_flow", "aero_forge_cast"]
    # Semis at 2 of 3 still has an index.
    data = run(_providers(errors={"semis_memory_prices"}))
    assert data["sectors"]["semiconductor"]["index"] == pytest.approx((66.0 + 85.0) / 2)


def test_sector_stored_fallback_and_expiry(harness):
    run, recorded = harness
    limit = config.SECTOR_DROP_AFTER_DAYS

    # Fetch failure: the last stored score inside the drop window counts, flagged.
    lookups = []

    def last(cat):
        lookups.append(cat)
        return (_today() - timedelta(days=limit - 1), 58.0)

    data = run(_providers(errors={"aero_flow"}, expired={"aero_mill_prices"}), last=last)
    aero = data["sectors"]["aerospace"]
    assert data["current_scores"]["aero_flow"] == 58.0
    meta = data["category_metadata"]["aero_flow"]
    assert meta["is_fallback"] is True and meta["is_stale"] is True
    assert f"{limit} days old" in meta["calculation"]
    assert aero["fallback_categories"] == ["aero_flow"]
    assert aero["stale_categories"] == ["aero_flow"]
    # Expired inputs: excluded at once, storage never consulted.
    assert "aero_mill_prices" not in lookups
    assert "aero_mill_prices" not in data["current_scores"]
    assert aero["excluded_categories"] == ["aero_mill_prices"]
    assert "drop window" in data["category_metadata"]["aero_mill_prices"]["description"]
    assert aero["coverage"] == 3
    assert aero["index"] == pytest.approx((80 + 58 + 37) / 3)
    assert aero["degraded"] is True
    # Global lists untouched; the stored fallback is never recorded as a measurement.
    assert data["degraded"] is False
    assert data["fallback_categories"] == data["stale_categories"] == data["excluded_categories"] == []
    _, scores = recorded["record"][-1]
    assert "aero_flow" not in scores and "aero_mill_prices" not in scores
    assert scores["aero_throughput"] == 80.0
    assert data["category_history"]["aero_flow"].isna().all()

    # At the drop limit the stored score is too old: excluded.
    data = run(_providers(errors={"aero_flow"}),
               last=lambda cat: (_today() - timedelta(days=limit), 58.0))
    assert "aero_flow" not in data["current_scores"]
    assert data["sectors"]["aerospace"]["excluded_categories"] == ["aero_flow"]
    assert data["sectors"]["aerospace"]["fallback_categories"] == []
    assert "150 days" in data["category_metadata"]["aero_flow"]["description"]


def test_no_old_industry_keys(harness):
    run, _ = harness
    assert importlib.util.find_spec("data.providers.silicon_analysts") is None
    assert importlib.util.find_spec("data.providers.aerospace") is None
    assert not hasattr(config, "INDUSTRY_PROVIDER_CACHE_TTL")
    categories = {p.category for p in aggregator._PROVIDERS}
    assert categories == set(CATEGORY_WEIGHTS) | _SECTOR_CATS
    assert len(aggregator._PROVIDERS) == len(categories)

    # Old rows still in the database are never read into the snapshot.
    day = _today().isoformat()
    daily = {"dates": [day], "scores": {"energy": [23.3], "aero_throughput": [80.0],
                                         **{k: [50.0] for k in _OLD_KEYS}}}
    data = run(_providers(), daily=daily)
    assert set(data["daily_history"]["scores"]) == {"energy", "aero_throughput"}
    for section in ("current_scores", "category_metadata", "category_history"):
        assert not set(data[section]) & set(_OLD_KEYS), section


def _old_snapshot(data: dict) -> dict:
    """A JSON round trip of a snapshot saved before project 3: old industry keys, no sectors."""
    from data.cache import dashboard_to_safe_dict

    raw = json.loads(json.dumps(dashboard_to_safe_dict(data), default=str))
    raw.pop("sectors", None)
    for cat in _SECTOR_CATS:
        for section in ("current_scores", "category_metadata", "category_history"):
            raw[section].pop(cat, None)
    for key in _OLD_KEYS:
        raw["current_scores"][key] = 50.0
        raw["category_metadata"][key] = {"source": "Silicon Analysts", "is_fallback": True}
        raw["category_history"][key] = raw["category_history"]["energy"]
        raw["daily_history"]["scores"][key] = [50.0] * len(raw["daily_history"]["dates"])
    raw["fallback_categories"] = list(_OLD_KEYS)
    raw["degraded"] = True
    raw["disruptions"] = raw["disruptions"] + [
        {"event": "Fab Utilization — Critical", "region": "Global", "impact_score": 60.0,
         "categories": ["chip_fab_util"], "started": "Ongoing", "status": "Active"},
        {"event": "Aero Metals — Stressed", "region": "Global", "impact_score": 45.0,
         "categories": ["aero_metals", "energy"], "started": "Ongoing", "status": "Monitoring"},
    ]
    return raw


def test_old_snapshot_startup_ok(harness, monkeypatch):
    run, _ = harness
    day = _today().isoformat()
    data = run(_providers(), daily={"dates": [day], "scores": {"energy": [23.3]}})
    import app as application
    from data.cache import dashboard_to_safe_dict, reconstruct_dashboard_state

    # A v2 global snapshot without the sector keys is current.
    v2 = json.loads(json.dumps(dashboard_to_safe_dict(data), default=str))
    v2.pop("sectors")
    for cat in _SECTOR_CATS:
        v2["current_scores"].pop(cat)
    assert application._has_current_categories(v2) is True

    # An old snapshot loads, with the retired industry keys stripped everywhere.
    global_disruptions = _disruptions(data)
    assert global_disruptions and data["degraded"] is False
    raw = application._migrate_keys(_old_snapshot(data))
    assert application._has_current_categories(raw) is True
    for section in ("current_scores", "category_metadata", "category_history"):
        assert not set(raw[section]) & set(_OLD_KEYS), section
    assert not set(raw["daily_history"]["scores"]) & set(_OLD_KEYS)
    assert not set(raw["fallback_categories"]) & set(_OLD_KEYS)
    # Their disruptions go too, and degraded follows the remaining global lists.
    assert _disruptions(raw) == global_disruptions
    assert raw["degraded"] is False
    state = reconstruct_dashboard_state(raw)

    # The page renders from it.
    monkeypatch.setattr(application, "_DATA_CACHE", state)
    monkeypatch.setattr("data.cache.get_cached_dashboard", lambda: None)
    assert application.app.layout() is not None


def test_hung_sector_jobs_never_delay_global_providers(harness, monkeypatch):
    """Sector providers run on their own pool: hung sector jobs that outlive their deadline
    never hold a worker a global provider needs, in the same cycle or the next."""
    import threading
    import time

    from data.runtime import RefreshTasks

    run, _ = harness
    monkeypatch.setattr(config, "SECTOR_PROVIDER_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(config, "PROVIDER_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(config, "PROVIDER_TIMEOUT_OVERRIDES", {})
    release = threading.Event()
    providers = [_Provider(c) for c in CATEGORY_WEIGHTS] + [
        _Provider(c, score=s, block=release) for c, s in _SECTOR_SCORES.items()]
    tasks, sector_tasks = RefreshTasks(max_workers=3), RefreshTasks(max_workers=2)
    try:
        for cycle in (1, 2):
            started = time.monotonic()
            data = run(providers, tasks=tasks, sector_tasks=sector_tasks)
            elapsed = time.monotonic() - started
            assert elapsed < 2.0, cycle
            assert set(CATEGORY_WEIGHTS) <= set(data["current_scores"]), cycle
            assert data["excluded_categories"] == [] and data["degraded"] is False, cycle
            assert not set(data["provider_errors"]) & set(CATEGORY_WEIGHTS), cycle
            for block in data["sectors"].values():
                assert block["index"] is None and block["coverage"] == 0
            assert data["provider_errors"]["aero_flow"] == "Provider timed out"
    finally:
        release.set()
        tasks.shutdown()
        sector_tasks.shutdown()


def test_boj_category_on_stored_fallback_keeps_the_boj_credit(harness):
    """A BOJ category serving its stored score still shows a BOJ-derived score, so its
    description carries config.BOJ_CREDIT. Non-BOJ categories do not get it."""
    from data.providers.semis import BOJ_CATEGORIES

    run, _ = harness
    stored = (_today() - timedelta(days=3), 41.0)
    data = run(_providers(errors={"semis_memory_prices", "semis_fab_utilization", "aero_flow"}),
               last=lambda cat: stored)
    assert BOJ_CATEGORIES == {"semis_memory_prices", "semis_logic_prices"}
    memory = data["category_metadata"]["semis_memory_prices"]
    assert memory["is_fallback"] is True and data["current_scores"]["semis_memory_prices"] == 41.0
    assert memory["description"].startswith("The live source failed this cycle: HTTP 503")
    assert memory["description"].endswith(config.BOJ_CREDIT)
    for cat in ("semis_fab_utilization", "aero_flow"):
        meta = data["category_metadata"][cat]
        assert meta["is_fallback"] is True and config.BOJ_CREDIT not in meta["description"]


def test_hung_sector_job_does_not_delay_global_collection(harness, monkeypatch):
    """Global provider futures are collected first, on the global deadlines alone; a sector job
    that hangs to its (longer) sector deadline is collected afterwards."""
    import threading
    import time

    from data.runtime import RefreshTasks

    run, _ = harness
    monkeypatch.setattr(config, "PROVIDER_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(config, "PROVIDER_TIMEOUT_OVERRIDES", {})
    monkeypatch.setattr(config, "SECTOR_PROVIDER_TIMEOUT_SECONDS", 1.5)
    release = threading.Event()
    providers = [_Provider(c, block=release if c == "energy" else None) for c in CATEGORY_WEIGHTS] + [
        _Provider(c, score=s, block=release if c == "aero_flow" else None) for c, s in _SECTOR_SCORES.items()]

    collected = []
    real_collect = aggregator._collect_provider_results

    def spy(future_to_provider, started):
        out = real_collect(future_to_provider, started)
        collected.append(({p.category for p in future_to_provider.values()}, time.monotonic()))
        return out
    monkeypatch.setattr(aggregator, "_collect_provider_results", spy)

    tasks, sector_tasks = RefreshTasks(max_workers=3), RefreshTasks(max_workers=2)
    try:
        t0 = time.monotonic()
        data = run(providers, tasks=tasks, sector_tasks=sector_tasks)
    finally:
        release.set()
        tasks.shutdown()
        sector_tasks.shutdown()

    (first_cats, first_done), (second_cats, second_done) = collected
    assert first_cats == set(CATEGORY_WEIGHTS) and second_cats == _SECTOR_CATS
    assert first_done - t0 < 1.0                       # global deadline 0.3 s, not the 1.5 s sector one
    assert second_done - t0 >= 1.4                     # the hung sector job ran to its own deadline
    assert data["excluded_categories"] == ["energy"]   # the hung global job timed out at its deadline
    assert data["provider_errors"]["energy"] == data["provider_errors"]["aero_flow"] == "Provider timed out"
    expected = sum(CATEGORY_WEIGHTS[c] * _SCORES[c] for c in CATEGORY_WEIGHTS if c != "energy") / (
        1 - CATEGORY_WEIGHTS["energy"])
    assert data["composite"] == pytest.approx(expected)
    assert data["sectors"]["aerospace"]["excluded_categories"] == ["aero_flow"]
