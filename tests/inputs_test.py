"""Offline tests for the Input Costs category (Fed prices paid, copper, aluminum)."""
import math
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd
import pytest

import config
from data.providers import inputs
from data.providers.inputs import InputsProvider
from data.providers.readings import InputReading, blend_inputs
from data.sources import fed_surveys
from data.sources.fed_surveys import prices_paid_composite

TODAY = date(2026, 10, 22)
CPI = 300.0

# Prices-paid composite is a z-score: 2.0 -> 40, 1.0 -> 60, 0 -> 80, 3.0 -> 20 (lower is better).
PP_ANCHOR = {"series": "prices_paid", "transform": "identity", "direction": "lower_better",
             "best": -2.0, "normal": 0.0, "worst": 4.0}


def _anchor(best, normal, worst):
    return {"series": "x", "transform": "log_real", "direction": "lower_better",
            "best": math.log(best), "normal": math.log(normal), "worst": math.log(worst)}


COPPER = _anchor(5000, 10000, 20000)
ALUMINUM = _anchor(1500, 3000, 6000)
STATS = {"philly": [40.0, 10.0], "empire": [30.0, 10.0], "dallas": [20.0, 10.0]}
ANCHORS = {
    "cpi_reference": {"series": "CPIAUCSL", "date": "2025-12-01", "value": CPI},
    "prices_paid_stats": STATS,
    "inputs": {"prices_paid": PP_ANCHOR, "copper": COPPER, "copper_monthly": COPPER,
               "aluminum": ALUMINUM, "aluminum_monthly": ALUMINUM},
}


def _score(x, best, normal, worst):
    lx, lb, ln, lw = map(math.log, (x, best, normal, worst))
    if lx <= lb:
        return 100.0
    if lx >= lw:
        return 0.0
    if lx <= ln:
        return 100 - 20 * (lx - lb) / (ln - lb)
    return 80 * (lw - lx) / (lw - ln)


def _monthly(value, start="2025-01-01", end="2026-09-01"):
    idx = pd.date_range(start, end, freq="MS")
    return pd.Series([value] * len(idx), index=idx, dtype=float)


def _surveys(z=2.0, start="2025-01-01", end="2026-09-01"):
    """Three surveys that each sit ``z`` sds above their own mean, so the composite is ``z``."""
    return {name: _monthly(mean + z * sd, start, end) for name, (mean, sd) in STATS.items()}


class Env:
    """Patches every outside call of the provider."""

    def __init__(self, monkeypatch, surveys=None, copper=None, aluminum=None, cpi=None,
                 delivery=None, scale=None):
        monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
        self.series = {
            "PCOPPUSDM": copper if copper is not None else _monthly(10000.0),
            "PALUMUSDM": aluminum if aluminum is not None else _monthly(3000.0),
            "CPIAUCSL": cpi if cpi is not None else _monthly(CPI),
        }
        self.surveys = surveys if surveys is not None else _surveys()
        self.delivery = delivery if delivery is not None else {"philly": _monthly(8.5), "empire": _monthly(19.8)}
        monkeypatch.setattr(inputs, "_today", lambda: TODAY)
        monkeypatch.setattr(inputs, "_fred", self._fred)
        monkeypatch.setattr(inputs.fed_surveys, "fetch_prices_paid", self._prices_paid)
        monkeypatch.setattr(inputs.fed_surveys, "fetch_delivery_times", self._delivery)
        self.scale = mock.Mock(side_effect=scale or (lambda v, d, s, unit_factor=1.0: (v, d, "official")))
        monkeypatch.setattr(inputs.markets, "scale_live", self.scale)

    def _fred(self, series_id):
        value = self.series[series_id]
        if isinstance(value, Exception):
            raise value
        return value

    def _prices_paid(self):
        if isinstance(self.surveys, Exception):
            raise self.surveys
        return self.surveys

    def _delivery(self):
        if isinstance(self.delivery, Exception):
            raise self.delivery
        return self.delivery


# ---------------------------------------------------------------------------- composite

def test_prices_paid_composite_averages_available():
    idx = pd.to_datetime(["2026-07-01", "2026-08-01"])
    a = pd.Series([1.0, 1.0], index=idx)
    b = pd.Series([3.0, np.nan], index=idx)
    out = prices_paid_composite({"a": a, "b": b}, {"a": (0.0, 1.0), "b": (0.0, 1.0)})
    assert out["2026-07-01"] == pytest.approx(2.0)
    assert out["2026-08-01"] == pytest.approx(1.0)      # b missing: a's z alone


def test_prices_paid_composite_missing_month_in_one_survey():
    a = pd.Series([1.0, 1.0], index=pd.to_datetime(["2026-07-01", "2026-08-01"]))
    b = pd.Series([3.0], index=pd.to_datetime(["2026-07-01"]))
    out = prices_paid_composite({"a": a, "b": b}, {"a": (0.0, 1.0), "b": (0.0, 1.0)})
    assert out.to_dict() == {pd.Timestamp("2026-07-01"): 2.0, pd.Timestamp("2026-08-01"): 1.0}


def test_prices_paid_composite_z_scores_against_each_surveys_own_stats():
    idx = pd.to_datetime(["2026-07-01"])
    out = prices_paid_composite({"philly": pd.Series([60.0], index=idx), "empire": pd.Series([30.0], index=idx)},
                                {"philly": (40.0, 10.0), "empire": (30.0, 5.0)})
    assert out.iloc[0] == pytest.approx((2.0 + 0.0) / 2)


def test_prices_paid_composite_skips_unstatted_survey_and_rejects_bad_sd():
    idx = pd.to_datetime(["2026-07-01"])
    s = pd.Series([5.0], index=idx)
    out = prices_paid_composite({"a": s, "ghost": pd.Series([99.0], index=idx)}, {"a": (4.0, 1.0)})
    assert out.iloc[0] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        prices_paid_composite({"a": s}, {"a": (4.0, 0.0)})
    with pytest.raises(ValueError):
        prices_paid_composite({"a": s}, {"a": (4.0, float("nan"))})


def test_prices_paid_composite_empty_when_nothing_usable():
    assert prices_paid_composite({}, {}).empty


# ---------------------------------------------------------------------------- fed_surveys fetch

def _fake_fred(by_id):
    def fetch(series_id, lookback_days=None, **_):
        assert lookback_days == config.INPUTS_FRED_LOOKBACK_DAYS    # trimmed window, never full history
        value = by_id[series_id]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def test_fetch_prices_paid_reads_each_survey_from_fred():
    seen = _fake_fred({"PPCDFSA066MSFRBPHI": _monthly(40.0), "PPCDISA066MSFRBNY": _monthly(50.0),
                       "PRMSAMFRBDAL": _monthly(45.0)})
    with mock.patch.object(fed_surveys, "fetch_fred_series", side_effect=seen) as fred:
        out = fed_surveys.fetch_prices_paid()
    assert set(out) == {"philly", "empire", "dallas"}
    assert [c.args[0] for c in fred.call_args_list] == ["PPCDFSA066MSFRBPHI", "PPCDISA066MSFRBNY", "PRMSAMFRBDAL"]
    assert out["empire"].iloc[-1] == 50.0


def test_failed_survey_is_omitted_not_raised():
    seen = _fake_fred({"PPCDFSA066MSFRBPHI": RuntimeError("FRED down"), "PPCDISA066MSFRBNY": _monthly(50.0),
                       "PRMSAMFRBDAL": pd.Series(dtype=float)})        # empty payload counts as failed
    with mock.patch.object(fed_surveys, "fetch_fred_series", side_effect=seen):
        out = fed_surveys.fetch_prices_paid()
    assert list(out) == ["empire"]


def test_all_surveys_failing_returns_empty_not_raised():
    boom = RuntimeError("down")
    seen = _fake_fred({"PPCDFSA066MSFRBPHI": boom, "PPCDISA066MSFRBNY": boom, "PRMSAMFRBDAL": boom})
    with mock.patch.object(fed_surveys, "fetch_fred_series", side_effect=seen):
        assert fed_surveys.fetch_prices_paid() == {}


def test_survey_non_finite_values_are_dropped():
    bad = _monthly(40.0)
    bad.iloc[-1] = np.inf
    seen = _fake_fred({"PPCDFSA066MSFRBPHI": bad, "PPCDISA066MSFRBNY": _monthly(50.0),
                       "PRMSAMFRBDAL": pd.Series([np.nan, np.nan], index=pd.to_datetime(["2026-08-01", "2026-09-01"]))})
    with mock.patch.object(fed_surveys, "fetch_fred_series", side_effect=seen):
        out = fed_surveys.fetch_prices_paid()
    assert "dallas" not in out
    assert out["philly"].index[-1] == pd.Timestamp("2026-08-01")


def test_fetch_delivery_times_omits_failures():
    seen = _fake_fred({"DTCDFSA066MSFRBPHI": _monthly(8.5), "DTCDISA066MSFRBNY": ValueError("down")})
    with mock.patch.object(fed_surveys, "fetch_fred_series", side_effect=seen):
        out = fed_surveys.fetch_delivery_times()
    assert list(out) == ["philly"]


# ---------------------------------------------------------------------------- provider

def test_inputs_blend():
    readings = [InputReading("prices_paid", 20.0, TODAY, "pp"), InputReading("copper", 40.0, TODAY, "cu"),
                InputReading("aluminum", 60.0, TODAY, "al")]
    assert blend_inputs(readings, config.INPUT_WEIGHTS) == (35.0, "live")


def test_input_weights_config():
    assert config.INPUT_WEIGHTS == {"prices_paid": 0.5, "copper": 0.25, "aluminum": 0.25}
    assert config.CATEGORY_LABELS["inputs"] == "Input Costs"
    assert config.CATEGORY_COLORS["inputs"] not in [v for k, v in config.CATEGORY_COLORS.items() if k != "inputs"]
    assert InputsProvider.category == "inputs"


def test_inputs_provider_blends_anchored_inputs(monkeypatch):
    Env(monkeypatch)
    score, meta = InputsProvider().fetch_current()
    # composite z = 2.0 -> 40; copper 10000 -> 80; aluminum 3000 -> 80
    assert score == pytest.approx(0.5 * 40 + 0.25 * 80 + 0.25 * 80, abs=0.05)
    by = {i["name"]: i for i in meta["inputs"]}
    assert set(by) == {"prices_paid", "copper_monthly", "aluminum_monthly"}   # official, so _monthly
    assert by["prices_paid"]["score"] == pytest.approx(40.0)
    assert by["prices_paid"]["as_of"] == "2026-09-30"


def test_metal_prices_are_deflated_and_logged(monkeypatch):
    # CPI is 20% above the reference, so a 12000 nominal copper price is 10000 real -> 80.
    Env(monkeypatch, copper=_monthly(12000.0), cpi=_monthly(CPI * 1.2))
    _, meta = InputsProvider().fetch_current()
    by = {i["name"]: i for i in meta["inputs"]}
    assert by["copper_monthly"]["score"] == pytest.approx(80.0, abs=0.01)


def test_copper_live_scaled_with_unit_factor_and_official_period_end(monkeypatch):
    def scale(value, official_date, symbol, unit_factor=1.0):
        return (value * 1.2, TODAY, "live") if symbol in ("HG=F", "ALI=F") else (value, official_date, "official")
    env = Env(monkeypatch, scale=scale)
    _, meta = InputsProvider().fetch_current()
    calls = {c.args[2]: c for c in env.scale.call_args_list}
    assert calls["HG=F"].args[:2] == (10000.0, date(2026, 9, 30))     # official value, month's period end
    assert calls["HG=F"].kwargs["unit_factor"] == pytest.approx(2204.62)
    assert calls["ALI=F"].kwargs.get("unit_factor", 1.0) == 1.0
    by = {i["name"]: i for i in meta["inputs"]}
    assert set(by) == {"prices_paid", "copper", "aluminum"}
    assert by["copper"]["as_of"] == TODAY.isoformat() and by["copper"]["status"] == "live"
    assert by["copper"]["score"] == pytest.approx(_score(12000, 5000, 10000, 20000))
    assert by["aluminum"]["score"] == pytest.approx(_score(3600, 1500, 3000, 6000))
    assert "HG=F" in by["copper"]["source"] and "PCOPPUSDM" in by["copper"]["source"]


def test_official_metal_is_labelled_monthly_with_period_end_age(monkeypatch):
    Env(monkeypatch)
    _, meta = InputsProvider().fetch_current()
    by = {i["name"]: i for i in meta["inputs"]}
    assert by["copper_monthly"]["as_of"] == "2026-09-30"
    assert by["copper_monthly"]["status"] == "live"     # 22 days from period end, within 75
    assert "official" in by["copper_monthly"]["source"]


def test_latest_month_uses_whichever_surveys_have_it(monkeypatch):
    surveys = _surveys(z=2.0)
    surveys["philly"] = pd.concat([surveys["philly"], pd.Series([40.0 + 4 * 10.0], index=[pd.Timestamp("2026-10-01")])])
    Env(monkeypatch, surveys=surveys)
    _, meta = InputsProvider().fetch_current()
    pp = [i for i in meta["inputs"] if i["name"] == "prices_paid"][0]
    assert pp["as_of"] == "2026-10-31"                  # Philly alone reports October: z = 4.0
    assert pp["score"] == pytest.approx(0.0)


def test_survey_missing_leaves_the_others(monkeypatch):
    surveys = _surveys()
    del surveys["dallas"], surveys["philly"]
    Env(monkeypatch, surveys=surveys)
    _, meta = InputsProvider().fetch_current()
    assert [i for i in meta["inputs"] if i["name"] == "prices_paid"][0]["score"] == pytest.approx(40.0)
    assert "Empire" in meta["description"] or "empire" in meta["source"].lower()


def test_all_surveys_missing_blends_metals_only(monkeypatch):
    Env(monkeypatch, surveys={})
    score, meta = InputsProvider().fetch_current()
    assert score == pytest.approx(80.0, abs=0.05)
    assert [i for i in meta["inputs"] if i["name"] == "prices_paid"][0]["status"] == "missing"


def test_surveys_fetch_error_counts_as_missing_not_neutral(monkeypatch):
    Env(monkeypatch, surveys=RuntimeError("boom"))
    score, _ = InputsProvider().fetch_current()
    assert score == pytest.approx(80.0, abs=0.05)


def test_everything_missing_raises_never_neutral(monkeypatch):
    err = ValueError("down")
    Env(monkeypatch, surveys={}, copper=err, aluminum=err)
    with pytest.raises(RuntimeError):
        InputsProvider().fetch_current()


def test_cpi_failure_drops_metals_but_not_prices_paid(monkeypatch):
    Env(monkeypatch, cpi=ValueError("CPI down"))
    score, meta = InputsProvider().fetch_current()
    assert score == pytest.approx(40.0)
    statuses = {i["name"]: i["status"] for i in meta["inputs"]}
    assert statuses["copper_monthly"] == "missing" and statuses["aluminum_monthly"] == "missing"


def test_one_metal_failing_renormalizes(monkeypatch):
    Env(monkeypatch, aluminum=ValueError("down"))
    score, _ = InputsProvider().fetch_current()
    assert score == pytest.approx((0.5 * 40 + 0.25 * 80) / 0.75, abs=0.05)


def test_stale_prices_paid_is_flagged_and_old_one_dropped(monkeypatch):
    Env(monkeypatch, surveys=_surveys(end="2026-06-01"))        # as_of 06-30: 114 days, stale (60/150)
    _, meta = InputsProvider().fetch_current()
    assert meta["is_stale"] is True
    Env(monkeypatch, surveys=_surveys(end="2026-04-01"))        # as_of 04-30: 175 days, dropped
    score, meta = InputsProvider().fetch_current()
    assert score == pytest.approx(80.0, abs=0.05)
    assert [i for i in meta["inputs"] if i["name"] == "prices_paid"][0]["status"] == "missing"


def test_non_finite_metal_price_is_missing(monkeypatch):
    bad = _monthly(10000.0)
    bad.iloc[-1] = np.nan
    Env(monkeypatch, copper=bad)
    _, meta = InputsProvider().fetch_current()
    by = {i["name"]: i for i in meta["inputs"]}
    assert by["copper_monthly"]["as_of"] == "2026-08-31"        # NaN month dropped, August used


def test_missing_anchor_raises_clear_error(monkeypatch):
    Env(monkeypatch)
    monkeypatch.setattr(config, "SCORE_ANCHORS", {**ANCHORS, "inputs": {"prices_paid": PP_ANCHOR}})
    with pytest.raises(RuntimeError, match="no anchor for copper"):
        InputsProvider().fetch_current()


def test_missing_prices_paid_stats_raises_clear_error(monkeypatch):
    Env(monkeypatch)
    monkeypatch.setattr(config, "SCORE_ANCHORS", {k: v for k, v in ANCHORS.items() if k != "prices_paid_stats"})
    with pytest.raises(RuntimeError, match="no anchor for prices_paid_stats"):
        InputsProvider().fetch_current()


def test_delivery_times_are_context_only(monkeypatch):
    Env(monkeypatch)
    score, meta = InputsProvider().fetch_current()
    assert "supplier delivery" in meta["description"].lower()
    assert "8.5" in meta["description"] and "19.8" in meta["description"]
    assert {i["name"] for i in meta["inputs"]} == {"prices_paid", "copper_monthly", "aluminum_monthly"}
    assert score == pytest.approx(60.0, abs=0.05)               # delivery times never enter the score


def test_delivery_times_failure_does_not_fail_provider(monkeypatch):
    Env(monkeypatch, delivery=ValueError("down"))
    score, meta = InputsProvider().fetch_current()
    assert score == pytest.approx(60.0, abs=0.05)
    assert "supplier delivery" not in meta["description"].lower()


def test_metadata_contract(monkeypatch):
    Env(monkeypatch)
    _, meta = InputsProvider().fetch_current()
    for key in ("source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"):
        assert key in meta
    assert meta["as_of"] == "2026-09-30" and meta["is_stale"] is False
    assert "PPCDFSA066MSFRBPHI" in meta["source"] and "PRMSAMFRBDAL" in meta["source"]


# ---------------------------------------------------------------------------- history

def test_history_recomputes_monthly_inputs_by_publication_date(monkeypatch):
    env = Env(monkeypatch)
    hist = InputsProvider().fetch_history(700)
    env.scale.assert_not_called()                                # no live values in history
    assert isinstance(hist.index, pd.DatetimeIndex) and hist.index.max() <= pd.Timestamp(TODAY)
    assert hist[pd.Timestamp(TODAY)] == pytest.approx(60.0, abs=0.1)
    # Surveys start Jan 2025 (public 2025-01-31, no lag); metals start Jan 2025 + 35 days = 2025-03-07.
    assert hist[pd.Timestamp("2025-02-15")] == pytest.approx(40.0, abs=0.1)
    assert hist[pd.Timestamp("2025-03-10")] == pytest.approx(60.0, abs=0.1)
    assert hist[:pd.Timestamp("2025-01-30")].isna().all()        # never backfilled


def test_history_tracks_changes_and_drops_after_window(monkeypatch):
    # Surveys end in March: public 03-31, dropped 150 days after the period ends, so gone by TODAY.
    Env(monkeypatch, surveys=_surveys(end="2026-03-01"))
    hist = InputsProvider().fetch_history(700)
    assert hist[pd.Timestamp("2026-08-01")] == pytest.approx(0.5 * 40 + 0.25 * 80 + 0.25 * 80, abs=0.1)
    assert hist[pd.Timestamp("2026-08-29")] == pytest.approx(80.0, abs=0.1)   # surveys dropped, metals only
    assert hist[pd.Timestamp(TODAY)] == pytest.approx(80.0, abs=0.1)


def test_history_all_missing_raises(monkeypatch):
    err = ValueError("down")
    Env(monkeypatch, surveys={}, copper=err, aluminum=err)
    with pytest.raises(RuntimeError):
        InputsProvider().fetch_history(90)


def test_history_survives_cpi_failure_with_prices_paid_only(monkeypatch):
    Env(monkeypatch, cpi=ValueError("down"))
    assert InputsProvider().fetch_history(90)[pd.Timestamp(TODAY)] == pytest.approx(40.0, abs=0.1)
