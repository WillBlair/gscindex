"""Offline tests for the IMF PortWatch chokepoint traffic module."""
from datetime import date
from unittest import mock

from data import portwatch


def test_compute_traffic_averages_and_orders_by_display_list():
    recent = [{"portid": "chokepoint6", "n_total": 4}, {"portid": "chokepoint6", "n_total": 2},
              {"portid": "chokepoint1", "n_total": 40}]
    baseline = [{"portid": "chokepoint6", "n_total": 100}, {"portid": "chokepoint6", "n_total": 50},
                {"portid": "chokepoint1", "n_total": 80}]
    out = portwatch.compute_traffic(recent, baseline, date(2026, 10, 18))
    names = [c["name"] for c in out["chokepoints"]]
    assert names == ["Hormuz", "Suez"]
    hormuz = out["chokepoints"][0]
    assert hormuz["recent_per_day"] == 3.0 and hormuz["normal_per_day"] == 75.0
    assert hormuz["pct_of_normal"] == 4
    assert out["as_of"] == "2026-10-18" and out["source"] == "IMF PortWatch"


def test_compute_traffic_skips_missing_or_zero_baselines():
    recent = [{"portid": "chokepoint2", "n_total": 5}, {"portid": "chokepoint5", "n_total": 5}]
    baseline = [{"portid": "chokepoint2", "n_total": 0}]
    assert portwatch.compute_traffic(recent, baseline, date(2026, 10, 18))["chokepoints"] == []


def test_fetch_failure_falls_back_to_stale_cache():
    stale = {"as_of": "2026-10-15", "chokepoints": [{"name": "Suez"}]}
    calls = []

    def fake_get_cached(key, ttl):
        calls.append(ttl)
        return None if ttl == portwatch._CACHE_TTL else stale

    with mock.patch.object(portwatch, "get_cached", side_effect=fake_get_cached), \
         mock.patch.object(portwatch.requests, "get", side_effect=RuntimeError("down")):
        assert portwatch.fetch_chokepoint_traffic() == stale
    assert calls == [portwatch._CACHE_TTL, portwatch._STALE_TTL]


def test_month_window_handles_december():
    assert portwatch._month_window(2023, 12) == (date(2023, 12, 1), date(2023, 12, 31))
