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


def test_non_finite_score_is_normalized_to_missing_in_metadata():
    from data.providers.readings import inputs_metadata
    for bad in (float("nan"), float("inf"), float("-inf")):
        r = InputReading("a", bad, date(2026, 10, 1), "x")
        assert r.score is None and r.status == "missing"
        entry = inputs_metadata([r])[0]
        assert entry["score"] is None and entry["status"] == "missing"
    ok = InputReading("a", 42.0, date(2026, 10, 1), "x")
    assert ok.score == 42.0 and ok.status == "live"
    stale = InputReading("a", 42.0, date(2026, 10, 1), "x", status="stale")
    assert stale.status == "stale"


# ------------------------------------------------------------ InputsExpired vs fetch failure

def _aged(name="a"):
    """A reading that returned data but is past its drop window (status from freshness)."""
    return InputReading(name, 70.0, date(2026, 1, 31), "x", status="missing")


def _failed(name="b"):
    return InputReading(name, None, None, "y", status="missing")


def test_no_inputs_error_is_expired_when_inputs_aged_out():
    from data.providers.readings import InputsExpired, no_inputs_error
    exc = no_inputs_error([_aged("a"), _aged("b")], "no input")
    assert isinstance(exc, InputsExpired) and isinstance(exc, RuntimeError)
    assert str(exc) == "no input"


def test_no_inputs_error_is_expired_when_the_inputs_with_data_aged_out():
    # One input failed to fetch, the only one that returned data is past its window.
    from data.providers.readings import InputsExpired, no_inputs_error
    assert isinstance(no_inputs_error([_aged("a"), _failed("b")], "m"), InputsExpired)


def test_no_inputs_error_is_plain_runtime_error_on_fetch_failures():
    from data.providers.readings import InputsExpired, no_inputs_error
    exc = no_inputs_error([_failed("a"), _failed("b")], "m")
    assert type(exc) is RuntimeError and not isinstance(exc, InputsExpired)
    # A non-finite value with a date is a parse failure, not an aged reading.
    nan = InputReading("a", float("nan"), date(2026, 10, 1), "x")
    assert not isinstance(no_inputs_error([nan], "m"), InputsExpired)
