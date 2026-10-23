"""Offline tests for the Freight Volume category (BTS TSIFRGHT + weekly STB rail volume)."""
import importlib
from datetime import date, timedelta
from unittest import mock

import pandas as pd
import pytest

import config
from data.providers import freight
from data.providers.freight import FreightProvider
from data.providers.readings import period_end
from data.sources import rail

TODAY = date(2026, 10, 22)
LAST_WEEK = date(2026, 10, 17)   # Saturday; the newest week the dataset holds on TODAY

# Identity transform on the YoY percent: 10 -> 100, 0 -> 80, -20 -> 0 (higher is better).
TSI_ANCHOR = {"series": "tsifrght", "transform": "identity", "direction": "higher_better",
              "best": 10.0, "normal": 0.0, "worst": -20.0}
RAIL_ANCHOR = {"series": "rail_volume", "transform": "identity", "direction": "higher_better",
               "best": 10.0, "normal": 0.0, "worst": -20.0}
ANCHORS = {"inputs": {"tsifrght": TSI_ANCHOR, "rail_volume": RAIL_ANCHOR}}


def _score(yoy):
    """Hand-computed score of a YoY percent under both test anchors."""
    if yoy >= 10:
        return 100.0
    if yoy >= 0:
        return 80.0 + 2.0 * yoy
    return max(0.0, 80.0 + 4.0 * yoy)


def _rail_flat_then_step(yoy_pct, weeks=70, end=LAST_WEEK):
    """Weekly totals of 100, except the last 4 weeks, which sit ``yoy_pct`` above: the latest
    4-week mean is up ``yoy_pct`` on the mean 52 weeks earlier."""
    idx = pd.date_range(end=pd.Timestamp(end), periods=weeks, freq="7D")
    values = [100.0] * (weeks - 4) + [100.0 * (1 + yoy_pct / 100.0)] * 4
    return pd.Series(values, index=idx, dtype=float)


def _tsi(yoy_pct=0.0, end="2026-08-01", months=30):
    """Monthly TSIFRGHT, first-of-month dated like FRED, with a constant YoY at the end."""
    idx = pd.date_range(end=end, periods=months, freq="MS")
    values = [100.0] * (months - 12) + [100.0 * (1 + yoy_pct / 100.0)] * 12
    return pd.Series(values, index=idx, dtype=float)


@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
    monkeypatch.setattr(freight, "_today", lambda: TODAY)


def _run(fn, tsi=None, weekly=None):
    """Run ``fn`` with both sources patched; a source passed as None fails."""
    def fred(series_id, lookback_days=None, **_):
        assert series_id == "TSIFRGHT"
        if tsi is None:
            raise RuntimeError("FRED down")
        return tsi

    def rail_fetch():
        if weekly is None:
            raise ValueError("rail payload empty")
        return weekly

    with mock.patch.object(freight, "fetch_fred_series", side_effect=fred), \
         mock.patch.object(freight.rail, "fetch_rail_weekly", side_effect=rail_fetch):
        return fn()


# ------------------------------------------------------------------------------ rail yoy

def test_rail_yoy():
    idx = pd.date_range("2025-01-04", periods=64, freq="7D")
    weekly = pd.Series([100.0] * 60 + [110.0] * 4, index=idx)
    assert rail.rail_yoy(weekly).iloc[-1] == pytest.approx(10.0)


def test_rail_yoy_uses_four_week_mean_against_52_weeks_earlier():
    idx = pd.date_range("2025-01-04", periods=70, freq="7D")
    values = [100.0] * 70
    values[-1] = 140.0                              # one spike week moves the 4-week mean to 110
    values[-56:-52] = [80.0, 100.0, 100.0, 120.0]   # the base window averages 100
    assert rail.rail_yoy(pd.Series(values, index=idx)).iloc[-1] == pytest.approx(10.0)


def test_rail_yoy_needs_a_full_year_of_weeks():
    idx = pd.date_range("2026-01-03", periods=30, freq="7D")
    assert rail.rail_yoy(pd.Series([100.0] * 30, index=idx)).dropna().empty


def test_rail_yoy_missing_week_gives_no_value():
    full = pd.date_range("2025-01-04", periods=80, freq="7D")
    yoy = rail.rail_yoy(pd.Series(100.0, index=full).drop(full[10]))
    # The gap blanks the 4-week means that contain it (weeks 10 to 13), and so the YoY readings
    # that use them as a base 52 weeks later (weeks 62 to 65); the rest are measurable.
    assert yoy[full[62:66]].isna().all()
    assert yoy[full[61]] == pytest.approx(0.0) and yoy[full[66]] == pytest.approx(0.0)
    assert yoy.iloc[-1] == pytest.approx(0.0)


# --------------------------------------------------------------------------- rail source

def _row(day, commodity, carloads):
    return {"date": f"{day}T00:00:00.000", "commodity": commodity, "carloads": str(carloads)}


def _rows(days=("2026-10-10", "2026-10-17")):
    rows = []
    for d in days:
        rows += [_row(d, "Coal", 58000), _row(d, "Containers", 300000),
                 _row(d, "Trailers", 9000), _row(d, "Grain", 29000)]
    return rows


def _resp(payload, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = payload
    return resp


@pytest.fixture
def no_cache():
    with mock.patch.object(rail, "get_cached", return_value=None), \
         mock.patch.object(rail, "set_cached") as save:
        yield save


def test_parse_rail_rows_adds_carloads_and_intermodal_per_week():
    s = rail.parse_rail_rows(_rows())
    assert s.index.tolist() == [pd.Timestamp("2026-10-10"), pd.Timestamp("2026-10-17")]
    assert s.tolist() == [396000.0, 396000.0]


def test_parse_rail_rows_sums_railroads_with_duplicate_commodity_rows():
    rows = _rows(("2026-10-17",)) + [_row("2026-10-17", "Coal", 2000)]
    assert rail.parse_rail_rows(rows).iloc[0] == 398000.0


def test_parse_rail_rows_skips_unparseable_amounts():
    rows = _rows(("2026-10-17",)) + [_row("2026-10-17", "Coal", "null"), {"date": "bad", "commodity": "Coal",
                                                                          "carloads": "5"}]
    assert rail.parse_rail_rows(rows).iloc[0] == 396000.0


@pytest.mark.parametrize("payload", [
    [],
    {"error": True, "message": "Query coordinator error"},
    "not json rows",
    [{"day": "2026-10-17", "kind": "Coal", "n": "5"}],                                  # renamed columns
    [_row("2026-10-17", "Coal", 5), _row("2026-10-17", "Grain", 6)],                    # no intermodal
    [_row("2026-10-17", "Containers", "x")],                                            # nothing numeric
])
def test_rail_empty_payload_raises(payload):
    with pytest.raises(ValueError):
        rail.parse_rail_rows(payload)


def test_fetch_rail_weekly_empty_response_raises_and_is_not_cached(no_cache):
    with mock.patch.object(rail.requests, "get", return_value=_resp([])):
        with pytest.raises(ValueError):
            rail.fetch_rail_weekly()
    no_cache.assert_not_called()


def test_fetch_rail_weekly_queries_originated_by_date_and_commodity_and_caches(no_cache):
    with mock.patch.object(rail.requests, "get", return_value=_resp(_rows())) as get:
        s = rail.fetch_rail_weekly()
    assert get.call_args.args[0] == "https://agtransport.usda.gov/resource/tb7q-kn5i.json"
    params = get.call_args.kwargs["params"]
    assert params["$where"] == "type='Originated'"
    assert params["$group"] == "date,commodity"
    assert "sum(carloads)" in params["$select"]
    assert s.tolist() == [396000.0, 396000.0]
    assert no_cache.call_args.args[0] == "stb_rail_weekly_v1"


def test_fetch_rail_weekly_uses_cache():
    cached = {"dates": ["2026-10-10", "2026-10-17"], "values": [500.0, 510.0]}
    with mock.patch.object(rail, "get_cached", return_value=cached) as get, \
         mock.patch.object(rail.requests, "get") as http:
        s = rail.fetch_rail_weekly()
    http.assert_not_called()
    assert get.call_args.args[0] == "stb_rail_weekly_v1"
    assert get.call_args.kwargs["ttl"] == 12 * 3600
    assert s.tolist() == [500.0, 510.0]


# ------------------------------------------------------------------------------ provider

def test_freight_config_and_label():
    assert config.FREIGHT_WEIGHTS == {"tsifrght": 0.5, "rail_volume": 0.5}
    assert FreightProvider.category == "freight"
    assert config.CATEGORY_LABELS["freight"] == "Freight Volume"
    assert not hasattr(config, "FREIGHT_PROXY_WEIGHT")
    assert not hasattr(config, "FREIGHT_YOY_BASELINE")
    assert not hasattr(config, "FREIGHT_YOY_SLOPE")


def test_iyt_proxy_module_removed():
    with pytest.raises(ImportError):
        importlib.import_module("data.providers.transport_equity_proxy")


def test_freight_blends_tsifrght_and_rail_equally(anchors):
    # TSIFRGHT +5% -> 90; rail -10% -> 40
    score, meta = _run(FreightProvider().fetch_current, tsi=_tsi(5.0), weekly=_rail_flat_then_step(-10.0))
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tsifrght"]["score"] == pytest.approx(_score(5.0))
    assert inputs["rail_volume"]["score"] == pytest.approx(_score(-10.0))
    assert score == pytest.approx(0.5 * 90 + 0.5 * 40, abs=0.1)
    assert meta["is_stale"] is False


def test_freight_metadata_shape_and_dates(anchors):
    score, meta = _run(FreightProvider().fetch_current, tsi=_tsi(2.0), weekly=_rail_flat_then_step(4.0))
    for key in ("source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"):
        assert key in meta
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tsifrght"]["as_of"] == "2026-08-31"        # period end of August
    assert inputs["rail_volume"]["as_of"] == LAST_WEEK.isoformat()
    assert meta["as_of"] == "2026-08-31"                       # oldest used input
    assert inputs["tsifrght"]["status"] == inputs["rail_volume"]["status"] == "live"
    assert "+2.0%" in meta["raw_value"] and "+4.0%" in meta["raw_value"]


def test_freight_description_says_volume_not_congestion(anchors):
    _, meta = _run(FreightProvider().fetch_current, tsi=_tsi(2.0), weekly=_rail_flat_then_step(4.0))
    text = meta["description"].lower()
    assert "goods" in text and "moving" in text
    assert "contraction" in text
    assert "not a congestion or cost" in text
    assert "iyt" not in (meta["source"] + meta["calculation"] + text).lower()


def test_freight_tsifrght_yoy_pairs_each_month_with_the_same_month_a_year_earlier(anchors):
    tsi = _tsi(0.0)
    tsi[tsi.index[-1]] = 110.0                                 # Aug 2026 only: +10% vs Aug 2025
    _, meta = _run(FreightProvider().fetch_current, tsi=tsi, weekly=_rail_flat_then_step(0.0))
    assert {i["name"]: i for i in meta["inputs"]}["tsifrght"]["score"] == pytest.approx(100.0)


def test_freight_uses_rail_when_tsifrght_too_old(anchors):
    # The last print is February; its period end is 236 days before TODAY, past the 200-day drop.
    tsi = _tsi(5.0, end="2026-02-01")
    assert (TODAY - period_end(tsi.index[-1].date(), "M")).days > config.FRESHNESS["tsifrght"][1]
    score, meta = _run(FreightProvider().fetch_current, tsi=tsi, weekly=_rail_flat_then_step(-10.0))
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tsifrght"]["status"] == "missing"
    assert inputs["rail_volume"]["status"] == "live"
    assert score == pytest.approx(_score(-10.0), abs=0.1)
    assert meta["is_stale"] is False


def test_freight_stale_tsifrght_flags_stale(anchors, monkeypatch):
    monkeypatch.setattr(freight, "_today", lambda: date(2027, 1, 5))     # 127 days after Aug 31
    weekly = _rail_flat_then_step(0.0, end=date(2027, 1, 2))
    _, meta = _run(FreightProvider().fetch_current, tsi=_tsi(0.0), weekly=weekly)
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tsifrght"]["status"] == "stale"
    assert inputs["rail_volume"]["status"] == "live"
    assert meta["is_stale"] is True


def test_freight_uses_tsifrght_when_rail_fails(anchors):
    score, meta = _run(FreightProvider().fetch_current, tsi=_tsi(5.0), weekly=None)
    assert {i["name"]: i for i in meta["inputs"]}["rail_volume"]["status"] == "missing"
    assert score == pytest.approx(_score(5.0), abs=0.1)


def test_freight_rail_empty_payload_counts_as_missing(anchors):
    with mock.patch.object(rail.requests, "get", return_value=_resp([])), \
         mock.patch.object(rail, "get_cached", return_value=None), \
         mock.patch.object(freight, "fetch_fred_series", return_value=_tsi(5.0)):
        score, meta = FreightProvider().fetch_current()
    assert {i["name"]: i for i in meta["inputs"]}["rail_volume"]["status"] == "missing"
    assert score == pytest.approx(_score(5.0), abs=0.1)


def test_freight_all_inputs_missing_raises(anchors):
    with pytest.raises(RuntimeError):
        _run(FreightProvider().fetch_current, tsi=None, weekly=None)


def test_freight_missing_anchor_raises(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {"tsifrght": TSI_ANCHOR}})
    monkeypatch.setattr(freight, "_today", lambda: TODAY)
    with pytest.raises(RuntimeError, match="no anchor for rail_volume"):
        _run(FreightProvider().fetch_current, tsi=_tsi(), weekly=_rail_flat_then_step(0.0))


def test_freight_non_finite_tsifrght_counts_as_missing(anchors):
    zeros = pd.Series(0.0, index=_tsi().index)                  # 0 / 0: no YoY is finite
    score, meta = _run(FreightProvider().fetch_current, tsi=zeros, weekly=_rail_flat_then_step(-10.0))
    assert {i["name"]: i for i in meta["inputs"]}["tsifrght"]["status"] == "missing"
    assert score == pytest.approx(_score(-10.0), abs=0.1)


# ------------------------------------------------------------------------------- history

def test_freight_history_dates_tsifrght_by_publication_lag(anchors):
    tsi = _tsi(0.0)                                            # YoY 0 -> 80 through Aug
    tsi[pd.Timestamp("2026-07-01")] = 105.0                    # Jul +5% -> 90; Aug (0%) published later
    tsi[pd.Timestamp("2026-08-01")] = 100.0
    hist = _run(lambda: FreightProvider().fetch_history(120), tsi=tsi, weekly=None)
    assert hist.name == "freight"
    assert hist.index[-1] == pd.Timestamp(TODAY)
    assert config.PUBLICATION_LAG_DAYS["tsifrght"] == 80
    jul_public = pd.Timestamp("2026-07-31") + pd.Timedelta(days=80)      # 2026-10-19
    assert hist[jul_public - pd.Timedelta(days=1)] == pytest.approx(80.0, abs=0.1)    # June's print stands
    assert hist[jul_public] == pytest.approx(90.0, abs=0.1)                           # July published
    # August is published 2026-11-19, after today
    assert hist[pd.Timestamp(TODAY)] == pytest.approx(90.0, abs=0.1)


def test_freight_history_dates_rail_by_publication_lag(anchors):
    weekly = _rail_flat_then_step(10.0)    # latest YoY +10 (score 100); the week before +2.5 (score 85)
    yoy = rail.rail_yoy(weekly)
    hist = _run(lambda: FreightProvider().fetch_history(60), tsi=None, weekly=weekly)
    assert config.PUBLICATION_LAG_DAYS["rail_volume"] == 5
    last = pd.Timestamp(LAST_WEEK)
    avail = last + pd.Timedelta(days=5)                        # 2026-10-22 == TODAY
    prev = last - pd.Timedelta(days=7)
    assert hist[avail] == pytest.approx(_score(yoy[last]), abs=0.1)
    assert hist[avail - pd.Timedelta(days=1)] == pytest.approx(_score(yoy[prev]), abs=0.1)


def test_freight_history_leaves_unobserved_days_nan(anchors):
    # Rail YoY exists from week 56 of the file; before its publication nothing is known.
    weekly = _rail_flat_then_step(0.0, weeks=60)
    hist = _run(lambda: FreightProvider().fetch_history(400), tsi=None, weekly=weekly)
    first = weekly.index[55] + pd.Timedelta(days=5)
    assert hist[:first - pd.Timedelta(days=1)].isna().all()
    assert hist[first] == pytest.approx(80.0, abs=0.1)
    assert not pd.isna(hist[pd.Timestamp(TODAY)])


def test_freight_history_drops_values_after_the_freshness_window(anchors, monkeypatch):
    monkeypatch.setattr(freight, "_today", lambda: LAST_WEEK + timedelta(days=60))
    hist = _run(lambda: FreightProvider().fetch_history(30), tsi=None, weekly=_rail_flat_then_step(0.0))
    drop = config.FRESHNESS["rail_volume"][1]
    assert hist[pd.Timestamp(LAST_WEEK) + pd.Timedelta(days=drop)] == pytest.approx(80.0, abs=0.1)
    assert pd.isna(hist[pd.Timestamp(LAST_WEEK) + pd.Timedelta(days=drop + 1)])


def test_freight_history_blends_available_inputs(anchors):
    hist = _run(lambda: FreightProvider().fetch_history(30), tsi=_tsi(5.0), weekly=_rail_flat_then_step(-10.0))
    # Both are published for the last days: TSIFRGHT Aug (public Nov 19) is not, so July's +5%
    # (public Oct 19) and rail's -10% (public Oct 22) blend 50/50.
    assert hist[pd.Timestamp(TODAY)] == pytest.approx(0.5 * _score(5.0) + 0.5 * _score(-10.0), abs=0.1)


def test_freight_history_all_missing_raises(anchors):
    with pytest.raises(RuntimeError):
        _run(lambda: FreightProvider().fetch_history(30), tsi=None, weekly=None)


def test_freight_aged_out_raises_inputs_expired(anchors):
    from data.providers.readings import InputsExpired
    old_tsi = _tsi(5.0, end="2026-02-01")                                  # past 200 days
    old_rail = _rail_flat_then_step(0.0, end=TODAY - timedelta(days=60))   # past 45 days
    with pytest.raises(InputsExpired):
        _run(FreightProvider().fetch_current, tsi=old_tsi, weekly=old_rail)
    # Rail failed to fetch; the only input that returned data aged out.
    with pytest.raises(InputsExpired):
        _run(FreightProvider().fetch_current, tsi=old_tsi, weekly=None)


def test_freight_fetch_failures_are_not_inputs_expired(anchors):
    from data.providers.readings import InputsExpired
    with pytest.raises(RuntimeError) as failure:
        _run(FreightProvider().fetch_current, tsi=None, weekly=None)
    assert not isinstance(failure.value, InputsExpired)
