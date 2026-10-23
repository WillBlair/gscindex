"""Offline tests for the Supply Chain category (NY Fed GSCPI alone, mapped through anchors)."""
import importlib.util
from datetime import date
from unittest import mock

import pandas as pd
import pytest

import config
from data.providers import supply_chain
from data.providers.supply_chain import SupplyChainProvider

TODAY = date(2026, 10, 22)

# Lower GSCPI is better: -1.0 -> 100, -0.36 (pre-2020 median) -> 80, 4.43 -> 0.
GSCPI_ANCHOR = {"series": "gscpi", "transform": "identity", "direction": "lower_better",
                "best": -1.0, "normal": -0.36, "worst": 4.43}
ANCHORS = {"inputs": {"gscpi": GSCPI_ANCHOR}}


def _gscpi(values, last="2026-09"):
    """Monthly GSCPI keyed by month end, like gscpi_client, ending at ``last``."""
    idx = pd.date_range(end=pd.Timestamp(last) + pd.offsets.MonthEnd(0), periods=len(values), freq="ME")
    return pd.Series(values, index=idx, dtype=float, name="GSCPI")


def _wei(value=2.5):
    return pd.Series([value - 0.1, value], index=pd.to_datetime(["2026-10-10", "2026-10-17"]))


@pytest.fixture(autouse=True)
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
    monkeypatch.setattr(supply_chain, "_today", lambda: TODAY)


def _run(fn, gscpi, wei=None, bdry=None):
    """Run ``fn`` with the three sources patched. A source passed as None fails."""
    def fetch_gscpi():
        if gscpi is None:
            raise RuntimeError("NY Fed CSV down")
        return gscpi

    def fetch_wei(series_id, *args, **kwargs):
        assert series_id == "WEI"
        if wei is None:
            raise RuntimeError("FRED down")
        return wei

    def last_quote(symbol):
        assert symbol == "BDRY"
        if bdry is None:
            raise ValueError("yfinance returned no data")
        return bdry

    with mock.patch.object(supply_chain, "fetch_gscpi_series", side_effect=fetch_gscpi), \
         mock.patch.object(supply_chain, "fetch_fred_series", side_effect=fetch_wei), \
         mock.patch.object(supply_chain.markets, "last_quote", side_effect=last_quote):
        return fn()


def _current(gscpi, wei=None, bdry=None):
    return _run(SupplyChainProvider().fetch_current, gscpi, wei, bdry)


def _history(gscpi, days=120):
    return _run(lambda: SupplyChainProvider().fetch_history(days), gscpi)


# ------------------------------------------------------------------ score


def test_supply_chain_anchor():
    median, _ = _current(_gscpi([0.1, 0.2, -0.36]))
    worst, _ = _current(_gscpi([0.1, 0.2, 4.43]))
    best, _ = _current(_gscpi([0.1, 0.2, -2.0]))
    assert median == 80.0
    assert worst == 0.0
    assert best == 100.0


def test_score_between_anchors_is_linear():
    score, _ = _current(_gscpi([0.0]))
    assert score == pytest.approx(80.0 * (4.43 - 0.0) / (4.43 + 0.36), abs=0.05)


def test_supply_chain_stale_flag():
    # July data (period end Jul 31) is 83 days old on TODAY: past the 75-day stale limit.
    _, stale = _current(_gscpi([0.1, 0.2], last="2026-07"))
    _, live = _current(_gscpi([0.1, 0.2], last="2026-09"))
    assert stale["is_stale"] is True
    assert stale["as_of"] == "2026-07-31"
    assert live["is_stale"] is False
    assert live["as_of"] == "2026-09-30"


def test_as_of_never_after_today():
    # A month still in progress has a period end in the future.
    _, meta = _current(_gscpi([0.1, 0.2], last="2026-10"))
    assert meta["as_of"] == TODAY.isoformat()


def test_reading_older_than_drop_window_raises():
    # April data ends Apr 30: 175 days old, past the 150-day drop limit.
    with pytest.raises(RuntimeError):
        _current(_gscpi([0.1, 0.2], last="2026-04"))


def test_latest_finite_month_is_used():
    series = _gscpi([0.5, float("nan")], last="2026-09")
    _, meta = _current(series)
    assert meta["as_of"] == "2026-08-31"


@pytest.mark.parametrize("bad", [None, pd.Series(dtype=float), _gscpi([float("nan"), float("inf")])])
def test_unusable_gscpi_raises(bad):
    with pytest.raises(RuntimeError):
        _current(bad)


def test_missing_anchor_is_a_runtime_error(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for gscpi"):
        _current(_gscpi([0.1]))


# ------------------------------------------------------------------ metadata and hover context


def test_metadata_contract():
    score, meta = _current(_gscpi([0.1, -0.36]), wei=_wei(), bdry=(date(2026, 10, 21), 11.52))
    for key in ("source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"):
        assert key in meta
    assert [i["name"] for i in meta["inputs"]] == ["gscpi"]
    assert meta["inputs"][0]["score"] == score


def test_hover_shows_gscpi_and_unscored_context():
    _, meta = _current(_gscpi([0.1, -0.36]), wei=_wei(2.5), bdry=(date(2026, 10, 21), 11.52))
    assert "GSCPI -0.36" in meta["raw_value"]
    assert "WEI +2.50 (context, not scored)" in meta["raw_value"]
    assert "BDRY $11.52 (context, not scored)" in meta["raw_value"]
    assert "not scored" in meta["description"]
    assert "Baltic Dry Index" in meta["description"]


def test_context_never_changes_the_score():
    gscpi = _gscpi([0.1, 0.8])
    with_context, _ = _current(gscpi, wei=_wei(9.0), bdry=(date(2026, 10, 21), 3.0))
    other_context, _ = _current(gscpi, wei=_wei(-9.0), bdry=(date(2026, 10, 21), 90.0))
    without, _ = _current(gscpi)
    assert with_context == other_context == without


def test_context_failures_do_not_fail_the_provider():
    score, meta = _current(_gscpi([0.1, 0.8]), wei=None, bdry=None)
    assert 0.0 < score < 100.0
    assert meta["raw_value"] == "GSCPI +0.80 (Sep 2026)"
    assert "WEI" not in meta["raw_value"] and "BDRY" not in meta["raw_value"]


def test_non_finite_context_is_left_out():
    wei = pd.Series([float("nan")], index=pd.to_datetime(["2026-10-17"]))
    _, meta = _current(_gscpi([0.1, 0.8]), wei=wei, bdry=(date(2026, 10, 21), float("nan")))
    assert "WEI" not in meta["raw_value"] and "BDRY" not in meta["raw_value"]


def test_freight_rate_proxy_module_is_gone():
    assert importlib.util.find_spec("data.providers.freight_rate_proxy") is None


# ------------------------------------------------------------------ history


def test_history_dates_each_month_by_publication_and_carries_it():
    # Aug (-1.0 -> 100) is public Aug 31 + 5 = Sep 5; Sep (4.43 -> 0) on Sep 30 + 5 = Oct 5.
    hist = _history(_gscpi([-1.0, 4.43], last="2026-09"), days=60)
    assert hist.name == "supply_chain"
    assert len(hist) == 60
    assert hist.index[-1] == pd.Timestamp(TODAY)
    assert pd.isna(hist[pd.Timestamp("2026-09-04")])
    assert hist[pd.Timestamp("2026-09-05")] == 100.0
    assert hist[pd.Timestamp("2026-10-04")] == 100.0
    assert hist[pd.Timestamp("2026-10-05")] == 0.0
    assert hist[pd.Timestamp(TODAY)] == 0.0


def test_history_leading_days_stay_nan():
    hist = _history(_gscpi([-0.36], last="2026-09"), days=90)
    assert hist[: pd.Timestamp("2026-10-04")].isna().all()
    assert hist[pd.Timestamp("2026-10-05"):].eq(80.0).all()


def test_history_drops_a_reading_past_the_drop_window():
    # Only July data: public Aug 5, carried while at most 150 days past Jul 31 (through Dec 28).
    hist = _history(_gscpi([-0.36], last="2026-07"), days=120)
    assert hist[pd.Timestamp(TODAY)] == 80.0
    with mock.patch.object(supply_chain, "_today", return_value=date(2027, 1, 5)):
        later = _run(lambda: SupplyChainProvider().fetch_history(10), _gscpi([-0.36], last="2026-07"))
    assert later[pd.Timestamp("2026-12-28")] == 80.0
    assert later[pd.Timestamp("2026-12-29"):].isna().all()


def test_history_non_finite_month_is_a_gap_not_a_carry():
    hist = _history(_gscpi([-1.0, float("nan")], last="2026-09"), days=60)
    assert hist[pd.Timestamp("2026-10-04")] == 100.0
    assert pd.isna(hist[pd.Timestamp("2026-10-05")])


def test_history_raises_when_there_is_nothing():
    with pytest.raises(RuntimeError):
        _history(None)
    with pytest.raises(RuntimeError):
        _history(pd.Series(dtype=float))


def test_history_missing_anchor_raises(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for gscpi"):
        _history(_gscpi([0.1]))
