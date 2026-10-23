from datetime import date
from data.providers.readings import InputReading, period_end, freshness_status, blend_inputs

def test_period_end_monthly_is_last_day():
    assert period_end(date(2026, 8, 1), "M") == date(2026, 8, 31)

def test_monthly_freshness_counts_from_period_end(monkeypatch):
    import config
    monkeypatch.setitem(config.FRESHNESS, "gscpi", (75, 150))
    as_of = period_end(date(2026, 8, 1), "M")
    assert freshness_status(as_of, date(2026, 10, 22), "gscpi") == "live"
    assert freshness_status(as_of, date(2026, 11, 20), "gscpi") == "stale"
    assert freshness_status(as_of, date(2027, 2, 1), "gscpi") == "missing"
    assert freshness_status(None, date(2026, 10, 22), "gscpi") == "missing"

def test_blend_renormalizes_and_propagates_stale():
    w = {"a": 0.6, "b": 0.4}
    a = InputReading("a", 50.0, date(2026, 10, 1), "x")
    assert blend_inputs([a, InputReading("b", None, None, "y", status="missing")], w) == (50.0, "live")
    b = InputReading("b", 100.0, date(2026, 9, 1), "y", status="stale")
    assert blend_inputs([a, b], w) == (70.0, "stale")
    assert blend_inputs([InputReading("a", None, None, "x", status="missing")], w) == (None, "missing")

def test_non_finite_score_counts_as_missing():
    w = {"a": 1.0, "b": 1.0}
    nan = InputReading("a", float("nan"), date(2026, 10, 1), "x")
    assert blend_inputs([nan], {"a": 1.0}) == (None, "missing")
    inf = InputReading("a", float("inf"), date(2026, 10, 1), "x")
    ok = InputReading("b", 60.0, date(2026, 10, 1), "y")
    assert blend_inputs([inf, ok], w) == (60.0, "live")
