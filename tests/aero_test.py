"""Offline tests for the four Aero sector categories."""
import math
from datetime import date
from unittest import mock

import pandas as pd
import pytest

import config
from data.providers import aero
from data.providers.readings import InputsExpired

TODAY = date(2026, 10, 22)

# Research anchors (docs/superpowers/research/2026-10-23-industry-artifacts/aero/proposed_anchors.json),
# keyed by the runtime input keys.
RESEARCH = {
    "aero_caputl": {"transform": "identity", "direction": "higher_better",
                    "best": 85.845, "normal": 73.8275, "worst": 46.7548},
    "aero_inv_ship": {"transform": "log", "direction": "lower_better",
                      "best": 1.246982, "normal": 1.554665, "worst": 2.7655},
    "ppi_ti_mill": {"transform": "identity", "direction": "lower_better",
                    "best": -14.105496, "normal": 0.369467, "worst": 98.737374},
    "ppi_ni_mill": {"transform": "identity", "direction": "lower_better",
                    "best": -16.299533, "normal": 1.264755, "worst": 70.588235},
    "ppi_ti_forge": {"transform": "identity", "direction": "lower_better",
                     "best": -7.343636, "normal": 0.0, "worst": 24.708146},
    "ppi_nonferrous_forge": {"transform": "identity", "direction": "lower_better",
                             "best": -2.836451, "normal": 0.545889, "worst": 10.248486},
    "ppi_steel_invest_cast": {"transform": "identity", "direction": "lower_better",
                              "best": -1.4573, "normal": 1.14166, "worst": 21.88781},
}

# Simple anchors for the unit tests: YoY % scores 80 at 0 and 0 at +50; the flow ratio scores
# 80 at 4.7 months, 100 at 3 and 0 at 10.
YOY_ANCHOR = {"transform": "identity", "direction": "lower_better", "best": -10.0, "normal": 0.0, "worst": 50.0}
FLOW_ANCHOR = {"transform": "log", "direction": "lower_better",
               "best": math.log(3.0), "normal": math.log(4.7), "worst": math.log(10.0)}
CAPUTL_ANCHOR = {"transform": "identity", "direction": "higher_better", "best": 85.0, "normal": 75.0, "worst": 45.0}
UNIT = {"aero_caputl": CAPUTL_ANCHOR, "aero_inv_ship": FLOW_ANCHOR,
        **{k: YOY_ANCHOR for k in RESEARCH if k.startswith("ppi_")}}

# FRED ids, as confirmed on FRED (series titles in the module docstring).
CAPUTL = "CAPUTLG3364T9S"
INVENTORY, SHIPMENTS = "ANAPTI", "ANAPVS"
TI_MILL, NI_MILL = "WPU102505", "WPU102504"
TI_FORGE, NF_FORGE, CAST = "PCU33211233211242", "PCU332112332112", "PCU3315123315120"


def _monthly(end, values):
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series([float(v) for v in values], index=idx, dtype=float)


def _yoy_levels(yoy_pct, end="2026-09-01", months=14):
    """Index at 100, with the last 12 months ``yoy_pct`` above the year before."""
    return _monthly(end, [100.0] * (months - 12) + [100.0 * (1 + yoy_pct / 100.0)] * 12)


def _yoy_inputs(**yoy):
    return {sid: _yoy_levels(v) for sid, v in yoy.items()}


@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": UNIT})
    monkeypatch.setattr(aero, "_today", lambda: TODAY)


def _run(fn, data):
    """Run ``fn`` with FRED serving ``data`` {series id: Series or Exception}; ids not in it fail."""
    def fred(series_id, lookback_days=None, **_):
        assert lookback_days == config.AERO_FRED_LOOKBACK_DAYS
        item = data.get(series_id, ValueError(f"no data for {series_id}"))
        if isinstance(item, Exception):
            raise item
        return item
    with mock.patch.object(aero, "fetch_fred_series", fred):
        return fn()


# ------------------------------------------------------------------ throughput

def test_throughput_higher_is_better(anchors):
    def run(level):
        return _run(aero.ThroughputProvider().fetch_current, {CAPUTL: _monthly("2026-09-01", [level] * 12)})[0]
    assert run(85.0) == 100.0 and run(75.0) == pytest.approx(80.0) and run(45.0) == 0.0
    assert run(80.0) > run(75.0) > run(60.0)


def test_throughput_metadata_contract(anchors):
    _, meta = _run(aero.ThroughputProvider().fetch_current, {CAPUTL: _monthly("2026-09-01", [73.8257] * 12)})
    assert {"source", "raw_value", "raw_label", "description", "calculation", "updated",
            "as_of", "is_stale", "inputs"} <= set(meta)
    assert meta["raw_value"] == "73.8% (Sep 2026)"
    assert meta["as_of"] == "2026-09-30" and meta["is_stale"] is False
    assert [i["name"] for i in meta["inputs"]] == ["aero_caputl"]
    assert CAPUTL in meta["source"]
    assert "—" not in meta["description"] and "—" not in meta["calculation"]


# ------------------------------------------------------------------ flow

def test_flow_ratio_and_direction(anchors):
    """Inventories 47 over a 3-month mean shipment of 10 is 4.7 months, the anchor's normal."""
    data = {INVENTORY: _monthly("2026-08-01", [47.0] * 3), SHIPMENTS: _monthly("2026-08-01", [10.0] * 3)}
    score, meta = _run(aero.FlowProvider().fetch_current, data)
    assert score == pytest.approx(80.0, abs=0.05)
    assert meta["raw_value"] == "4.7 months of shipments (Aug 2026)"
    assert meta["as_of"] == "2026-08-31"
    # the 3-month mean smooths shipments: [30, 0, 0] averages 10 just like [10, 10, 10]
    data[SHIPMENTS] = _monthly("2026-08-01", [30.0, 0.0, 0.0])
    assert _run(aero.FlowProvider().fetch_current, data)[0] == pytest.approx(80.0, abs=0.05)
    # more months of inventory per month of shipments is worse
    worse = {INVENTORY: _monthly("2026-08-01", [80.0] * 3), SHIPMENTS: _monthly("2026-08-01", [10.0] * 3)}
    assert _run(aero.FlowProvider().fetch_current, worse)[0] < 40.0


@pytest.mark.parametrize("shipments", [[0.0, 0.0, 0.0], [5.0, -5.0, 0.0], [float("nan")] * 3])
def test_flow_zero_shipments_is_missing(anchors, shipments):
    """A 3-month mean of shipments at or below zero must not blow up into an extreme score."""
    data = {INVENTORY: _monthly("2026-08-01", [47.0] * 3), SHIPMENTS: _monthly("2026-08-01", shipments)}
    with pytest.raises(RuntimeError) as err:
        _run(aero.FlowProvider().fetch_current, data)
    assert not isinstance(err.value, InputsExpired)


def test_flow_latest_month_unmeasurable_does_not_fall_back_to_an_older_month(anchors):
    shipments = _monthly("2026-08-01", [10.0] * 9 + [0.0, 0.0, 0.0])
    data = {INVENTORY: _monthly("2026-08-01", [47.0] * 12), SHIPMENTS: shipments}
    with pytest.raises(RuntimeError):
        _run(aero.FlowProvider().fetch_current, data)


def test_flow_needs_three_months_of_shipments_and_matching_months(anchors):
    data = {INVENTORY: _monthly("2026-08-01", [47.0] * 3), SHIPMENTS: _monthly("2026-08-01", [10.0, 10.0])}
    with pytest.raises(RuntimeError):                  # two months of shipments: no 3-month mean
        _run(aero.FlowProvider().fetch_current, data)
    # shipments run a month ahead of inventories: the latest month both have is used
    data = {INVENTORY: _monthly("2026-07-01", [47.0] * 3), SHIPMENTS: _monthly("2026-08-01", [10.0] * 4)}
    _, meta = _run(aero.FlowProvider().fetch_current, data)
    assert meta["as_of"] == "2026-07-31"


def test_flow_fetch_failure_counts_as_missing(anchors):
    with pytest.raises(RuntimeError):
        _run(aero.FlowProvider().fetch_current,
             {INVENTORY: ValueError("down"), SHIPMENTS: _monthly("2026-08-01", [10.0] * 3)})


# ------------------------------------------------------------------ prices

def test_mill_prices_mean_of_inputs(anchors):
    # titanium +10% scores 64, nickel +20% scores 48
    score, meta = _run(aero.MillPricesProvider().fetch_current, _yoy_inputs(**{TI_MILL: 10.0, NI_MILL: 20.0}))
    assert score == pytest.approx(56.0, abs=0.05)
    assert [i["name"] for i in meta["inputs"]] == ["ppi_ti_mill", "ppi_ni_mill"]
    assert [i["score"] for i in meta["inputs"]] == [pytest.approx(64.0), pytest.approx(48.0)]
    assert "YoY" in meta["raw_value"] and "Sep 2026" in meta["raw_value"]
    assert meta["as_of"] == "2026-09-30"


def test_forge_cast_mean_of_three_inputs(anchors):
    score, meta = _run(aero.ForgeCastProvider().fetch_current,
                       _yoy_inputs(**{TI_FORGE: 0.0, NF_FORGE: 10.0, CAST: 20.0}))
    assert score == pytest.approx((80.0 + 64.0 + 48.0) / 3, abs=0.05)
    assert [i["name"] for i in meta["inputs"]] == ["ppi_ti_forge", "ppi_nonferrous_forge", "ppi_steel_invest_cast"]


def test_forge_cast_one_input_missing_renormalizes(anchors):
    data = _yoy_inputs(**{TI_FORGE: 0.0, NF_FORGE: 10.0})
    data[CAST] = ValueError("BLS down")
    score, meta = _run(aero.ForgeCastProvider().fetch_current, data)
    assert score == pytest.approx((80.0 + 64.0) / 2, abs=0.05)
    status = {i["name"]: i["status"] for i in meta["inputs"]}
    assert status == {"ppi_ti_forge": "live", "ppi_nonferrous_forge": "live", "ppi_steel_invest_cast": "missing"}
    assert meta["is_stale"] is False


def test_price_input_without_a_year_earlier_base_is_missing(anchors):
    short = _monthly("2026-09-01", [100.0] * 12)                    # no month a year earlier
    data = {TI_MILL: _yoy_levels(10.0), NI_MILL: short}
    score, meta = _run(aero.MillPricesProvider().fetch_current, data)
    assert score == pytest.approx(64.0, abs=0.05)
    assert meta["inputs"][1]["status"] == "missing"


def test_price_yoy_compares_by_date_not_position(anchors):
    levels = _yoy_levels(10.0).drop(pd.Timestamp("2026-05-01"))
    score, _ = _run(aero.MillPricesProvider().fetch_current, {TI_MILL: levels, NI_MILL: levels})
    assert score == pytest.approx(64.0, abs=0.05)


def test_all_inputs_missing_raises_not_a_neutral_score(anchors):
    for provider in (aero.MillPricesProvider, aero.ForgeCastProvider, aero.ThroughputProvider):
        with pytest.raises(RuntimeError) as err:
            _run(provider().fetch_current, {})
        assert not isinstance(err.value, InputsExpired)


def test_stale_and_aged_out_inputs(anchors, monkeypatch):
    data = _yoy_inputs(**{TI_MILL: 5.0, NI_MILL: 5.0})
    monkeypatch.setattr(aero, "_today", lambda: date(2027, 1, 10))        # 102 days after 2026-09-30
    _, meta = _run(aero.MillPricesProvider().fetch_current, data)
    assert meta["is_stale"] is True and {i["status"] for i in meta["inputs"]} == {"stale"}
    monkeypatch.setattr(aero, "_today", lambda: date(2027, 3, 1))         # 152 days after
    with pytest.raises(InputsExpired):
        _run(aero.MillPricesProvider().fetch_current, data)


def test_month_in_progress_is_as_of_today(anchors):
    levels = _yoy_levels(5.0, end="2026-10-01")
    _, meta = _run(aero.MillPricesProvider().fetch_current, {TI_MILL: levels, NI_MILL: levels})
    assert meta["as_of"] == TODAY.isoformat()


def test_missing_anchor_is_a_runtime_error(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for aero_caputl"):
        _run(aero.ThroughputProvider().fetch_current, {CAPUTL: _monthly("2026-09-01", [74.0] * 12)})


# ------------------------------------------------------------------ reference

def test_aero_reference_today(monkeypatch):
    """The research run's latest values reproduce its category scores (80.0 / 76.2 / 74.3 / 37.3)."""
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": RESEARCH})
    monkeypatch.setattr(aero, "_today", lambda: TODAY)

    def ppi(year_ago, latest):
        return _monthly("2026-09-01", [year_ago] + [latest] * 12)   # Sep 2025 .. Sep 2026

    data = {
        CAPUTL: _monthly("2026-09-01", [73.8257] * 12),
        INVENTORY: _monthly("2026-08-01", [84930, 85599, 86527]),          # Jun-Aug 2026
        SHIPMENTS: _monthly("2026-08-01", [17713, 17794, 16267]),
        TI_MILL: ppi(233.418, 236.159),
        NI_MILL: ppi(211.608, 234.023),
        TI_FORGE: ppi(182.105, 199.290),
        NF_FORGE: ppi(199.914, 222.779),
        CAST: ppi(356.832, 377.178),
    }
    scores = {p.category: _run(p().fetch_current, data)[0]
              for p in (aero.ThroughputProvider, aero.FlowProvider, aero.MillPricesProvider, aero.ForgeCastProvider)}
    assert scores["aero_throughput"] == pytest.approx(80.0, abs=0.5)
    assert scores["aero_flow"] == pytest.approx(76.2, abs=0.5)
    assert scores["aero_mill_prices"] == pytest.approx(74.3, abs=0.5)
    assert scores["aero_forge_cast"] == pytest.approx(37.3, abs=0.5)


# ------------------------------------------------------------------ history

def test_history_is_dated_by_each_sources_lag(anchors):
    caputl = _monthly("2026-08-01", [75.0] * 11 + [45.0])               # August collapses to 0
    hist = _run(lambda: aero.ThroughputProvider().fetch_history(120), {CAPUTL: caputl})
    public = pd.Timestamp("2026-08-31") + pd.Timedelta(days=config.PUBLICATION_LAG_DAYS["g17"])
    assert hist.name == "aero_throughput" and hist.index[-1] == pd.Timestamp(TODAY)
    assert hist[public - pd.Timedelta(days=1)] == pytest.approx(80.0, abs=0.05)
    assert hist[public] == 0.0

    flow = _run(lambda: aero.FlowProvider().fetch_history(120),
                {INVENTORY: _monthly("2026-08-01", [47.0] * 11 + [100.0]),
                 SHIPMENTS: _monthly("2026-08-01", [10.0] * 12)})
    public = pd.Timestamp("2026-08-31") + pd.Timedelta(days=config.PUBLICATION_LAG_DAYS["census_m3"])
    assert flow[public - pd.Timedelta(days=1)] == pytest.approx(80.0, abs=0.05)
    assert flow[public] == 0.0

    levels = pd.concat([_yoy_levels(0.0, end="2026-07-01"),
                        _monthly("2026-08-01", [160.0])])               # August +60% YoY scores 0
    prices = _run(lambda: aero.MillPricesProvider().fetch_history(120), {TI_MILL: levels, NI_MILL: levels})
    public = pd.Timestamp("2026-08-31") + pd.Timedelta(days=config.PUBLICATION_LAG_DAYS["bls_ppi"])
    assert prices[public - pd.Timedelta(days=1)] == pytest.approx(80.0, abs=0.05)
    assert prices[public] == 0.0


def test_history_drops_after_window_and_leaves_gaps_before_first_value(anchors):
    levels = _yoy_levels(10.0, end="2026-03-01")
    hist = _run(lambda: aero.MillPricesProvider().fetch_history(400), {TI_MILL: levels, NI_MILL: levels})
    drop = config.FRESHNESS["ppi_ti_mill"][1]
    last_ok = pd.Timestamp("2026-03-31") + pd.Timedelta(days=drop)
    assert pd.notna(hist[last_ok]) and pd.isna(hist[last_ok + pd.Timedelta(days=1)])
    first_yoy = levels.index[12]                 # first month with a year-earlier base
    assert hist.loc[:first_yoy].isna().all()


def test_history_averages_the_inputs_present(anchors):
    ti = _yoy_levels(10.0, end="2026-09-01")                              # scores 64
    ni = _yoy_levels(20.0, end="2026-09-01", months=14)[-13:]             # only one year-earlier month
    hist = _run(lambda: aero.MillPricesProvider().fetch_history(30), {TI_MILL: ti, NI_MILL: ni})
    assert hist.iloc[-1] == pytest.approx(56.0, abs=0.05)
    only_ti = _run(lambda: aero.MillPricesProvider().fetch_history(30),
                   {TI_MILL: ti, NI_MILL: ValueError("down")})
    assert only_ti.iloc[-1] == pytest.approx(64.0, abs=0.05)


def test_flow_history_skips_unmeasurable_months(anchors):
    """August's 3-month mean of shipments is exactly 0, so August has no value and its public date
    carries July's score unchanged. A division blow-up would score August 0 or 100 instead."""
    shipments = _monthly("2026-08-01", [10.0] * 10 + [-5.0, -5.0])     # Jun 10; Jul mean 5; Aug mean 0
    data = {INVENTORY: _monthly("2026-08-01", [47.0] * 12), SHIPMENTS: shipments}
    hist = _run(lambda: aero.FlowProvider().fetch_history(90), data)
    lag = pd.Timedelta(days=config.PUBLICATION_LAG_DAYS["census_m3"])
    june, july, august = (pd.Timestamp(d) + lag for d in ("2026-06-30", "2026-07-31", "2026-08-31"))
    july_score = 80.0 * (math.log(10.0) - math.log(47.0 / 5.0)) / (math.log(10.0) - math.log(4.7))
    assert hist[june] == pytest.approx(80.0, abs=0.05)                  # mean 10: ratio 4.7, the anchor's normal
    assert hist[july] == pytest.approx(july_score, abs=0.05) and 0.0 < july_score < 10.0
    assert (hist.loc[august:] == hist[july]).all()                      # carried, not a new value
    assert not hist.loc[august:].isin([0.0, 100.0]).any()


def test_history_all_missing_raises(anchors):
    for provider in (aero.ThroughputProvider, aero.FlowProvider, aero.MillPricesProvider, aero.ForgeCastProvider):
        with pytest.raises(RuntimeError):
            _run(lambda: provider().fetch_history(90), {})


def test_history_beyond_every_window_raises(anchors, monkeypatch):
    monkeypatch.setattr(aero, "_today", lambda: date(2028, 1, 1))
    with pytest.raises(RuntimeError):
        _run(lambda: aero.ThroughputProvider().fetch_history(90), {CAPUTL: _monthly("2026-09-01", [74.0] * 12)})


# ------------------------------------------------------------------ config

def test_provider_categories_match_sector_keys():
    providers = (aero.ThroughputProvider, aero.FlowProvider, aero.MillPricesProvider, aero.ForgeCastProvider)
    assert {p.category for p in providers} == set(config.SECTORS["aerospace"]["weights"])


def test_aero_config_entries():
    keys = ["aero_caputl", "aero_inv_ship", "ppi_ti_mill", "ppi_ni_mill", "ppi_ti_forge",
            "ppi_nonferrous_forge", "ppi_steel_invest_cast"]
    for key in keys:
        assert config.FRESHNESS[key] == (75, 150) and key in config.INPUT_LABELS
    assert config.PUBLICATION_LAG_DAYS["census_m3"] == 35 and config.PUBLICATION_LAG_DAYS["bls_ppi"] == 15
    assert config.AERO_FRED_LOOKBACK_DAYS >= 3 * 365
    for cat in config.SECTORS["aerospace"]["weights"]:
        assert cat in config.CATEGORY_LABELS and cat in config.CATEGORY_COLORS
    colors = list(config.CATEGORY_COLORS.values())
    assert len(colors) == len(set(colors))
    for provider in (aero.ThroughputProvider, aero.FlowProvider, aero.MillPricesProvider, aero.ForgeCastProvider):
        assert [s.key for s in provider.inputs] and all(s.key in keys for s in provider.inputs)
