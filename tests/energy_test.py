"""Offline tests for the Energy category (Brent, NY Harbor ULSD, TTF)."""
import math
from datetime import date, timedelta
from unittest import mock

import pandas as pd
import pytest

import config
from data.providers import energy
from data.providers.energy import EnergyProvider, spike_penalty

TODAY = date(2026, 10, 22)
OFFICIAL = date(2026, 10, 20)
CPI = 300.0


def _anchor(best, normal, worst, key="x"):
    return {"series": key, "transform": "log_real", "direction": "lower_better",
            "best": math.log(best), "normal": math.log(normal), "worst": math.log(worst)}


ANCHORS = {
    "cpi_reference": {"series": "CPIAUCSL", "date": "2025-12-01", "value": CPI},
    "inputs": {
        "brent": _anchor(40, 65, 130),
        "ulsd": _anchor(1.2, 2.0, 5.0),
        "ttf": _anchor(4, 8, 40),
        "ttf_monthly": _anchor(4, 8, 40),
    },
}


def _daily(value_by_day, start=date(2025, 1, 1), end=OFFICIAL):
    days = pd.date_range(start, end, freq="D")
    return pd.Series([value_by_day(d.date()) for d in days], index=days, dtype=float)


def _monthly(value, start="2025-01-01", end="2026-09-01"):
    idx = pd.date_range(start, end, freq="MS")
    return pd.Series([value] * len(idx), index=idx, dtype=float)


def _score(x, best, normal, worst):
    """Hand-computed anchored score of price x (CPI ratio 1)."""
    lx, lb, ln, lw = map(math.log, (x, best, normal, worst))
    if lx <= lb:
        return 100.0
    if lx >= lw:
        return 0.0
    if lx <= ln:
        return 100 - 20 * (lx - lb) / (ln - lb)
    return 80 * (lw - lx) / (lw - ln)


BRENT_S = lambda p: _score(p, 40, 65, 130)
ULSD_S = lambda p: _score(p, 1.2, 2.0, 5.0)
TTF_S = lambda p: _score(p, 4, 8, 40)


class Env:
    """Patches every outside call of the provider."""

    def __init__(self, monkeypatch, brent=None, ulsd=None, ttf=None, cpi=None, wti=None,
                 scale=None, quotes=None):
        monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
        self.series = {
            "DCOILBRENTEU": brent if brent is not None else _daily(lambda d: 80.0),
            "DDFUELNYH": ulsd if ulsd is not None else _daily(lambda d: 2.5),
            "PNGASEUUSDM": ttf if ttf is not None else _monthly(10.0),
            "CPIAUCSL": cpi if cpi is not None else _monthly(CPI),
            "DCOILWTICO": wti if wti is not None else _daily(lambda d: 76.0),
        }
        monkeypatch.setattr(energy, "_today", lambda: TODAY)
        monkeypatch.setattr(energy, "_fred", self._fred)
        self.scale = mock.Mock(side_effect=scale or (lambda v, d, s: (v, d, "official")))
        monkeypatch.setattr(energy.markets, "scale_live", self.scale)
        self.quotes = quotes if quotes is not None else {}
        monkeypatch.setattr(energy.markets, "last_quote", self._quote)

    def _fred(self, series_id):
        value = self.series[series_id]
        if isinstance(value, Exception):
            raise value
        return value

    def _quote(self, symbol):
        if symbol not in self.quotes:
            raise ValueError(f"no data for {symbol}")
        return self.quotes[symbol]


def test_spike_penalty_bounds():
    assert spike_penalty(0.10) == 0
    assert spike_penalty(0.20) == 0
    assert spike_penalty(0.51) == pytest.approx(7.5)
    assert spike_penalty(0.82) == pytest.approx(15.0)
    assert spike_penalty(1.5) == 15.0
    assert spike_penalty(-0.4) == 0
    assert spike_penalty(float("nan")) == 0


def test_energy_uses_official_when_yahoo_stale(monkeypatch):
    # scale_live reports "official" (stale or rescaled quote), TTF live quotes fail.
    Env(monkeypatch, brent=_daily(lambda d: 100.0))
    score, meta = EnergyProvider().fetch_current()
    brent = meta["inputs"][0]
    assert brent["name"] == "brent" and "official" in brent["source"]
    assert brent["as_of"] == OFFICIAL.isoformat()
    expected = 0.35 * BRENT_S(100.0) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(10.0)
    assert score == pytest.approx(expected, abs=0.1)
    assert brent["score"] == pytest.approx(BRENT_S(100.0))


def test_energy_live_leg_is_scored_and_labelled(monkeypatch):
    env = Env(monkeypatch, scale=lambda v, d, s: (v * 1.1, TODAY, "live") if s == "BZ=F" else (v, d, "official"))
    score, meta = EnergyProvider().fetch_current()
    env.scale.assert_any_call(80.0, OFFICIAL, "BZ=F")
    env.scale.assert_any_call(2.5, OFFICIAL, "HO=F")
    brent = meta["inputs"][0]
    assert "live" in brent["source"] and "BZ=F" in brent["source"]
    assert brent["as_of"] == TODAY.isoformat()
    assert brent["score"] == pytest.approx(BRENT_S(88.0))


def test_energy_ttf_falls_back_to_monthly(monkeypatch):
    Env(monkeypatch)  # no TTF=F quote, so the live attempt fails
    score, meta = EnergyProvider().fetch_current()
    ttf = meta["inputs"][2]
    assert ttf["name"] == "ttf_monthly"
    assert ttf["as_of"] == "2026-09-30"
    assert "monthly" in ttf["source"]
    assert ttf["score"] == pytest.approx(TTF_S(10.0))


def test_energy_ttf_live_converted_to_usd_per_mmbtu(monkeypatch):
    quotes = {"TTF=F": (date(2026, 10, 21), 30.0), "EURUSD=X": (TODAY, 1.10)}
    Env(monkeypatch, quotes=quotes)
    score, meta = EnergyProvider().fetch_current()
    ttf = meta["inputs"][2]
    assert ttf["name"] == "ttf" and "TTF=F" in ttf["source"] and "live" in ttf["source"]
    assert ttf["as_of"] == "2026-10-21"
    assert ttf["score"] == pytest.approx(TTF_S(30.0 * 1.10 / 3.412))


@pytest.mark.parametrize("quotes", [
    {"TTF=F": (date(2026, 10, 21), 30.0)},                                   # no EURUSD
    {"EURUSD=X": (TODAY, 1.10)},                                             # no TTF
    {"TTF=F": (date(2026, 10, 10), 30.0), "EURUSD=X": (TODAY, 1.10)},        # stale TTF quote
    {"TTF=F": (TODAY, 30.0), "EURUSD=X": (date(2026, 10, 10), 1.10)},        # stale FX quote
    {"TTF=F": (TODAY, 300.0), "EURUSD=X": (TODAY, 1.10)},                    # unit change: 97 vs 10
    {"TTF=F": (TODAY, float("nan")), "EURUSD=X": (TODAY, 1.10)},
])
def test_energy_ttf_live_rejected_uses_monthly(monkeypatch, quotes):
    Env(monkeypatch, quotes=quotes)
    _, meta = EnergyProvider().fetch_current()
    assert meta["inputs"][2]["name"] == "ttf_monthly"


def test_energy_spike_penalty_is_weighted_and_subtracted(monkeypatch):
    # Brent real price +51% over 91 days (penalty 7.5 pts) at weight 0.35; others flat.
    now = OFFICIAL
    ref = now - timedelta(days=91)
    brent = _daily(lambda d: 60.0 if d <= ref else 90.6)
    Env(monkeypatch, brent=brent)
    score, _ = EnergyProvider().fetch_current()
    blend = 0.35 * BRENT_S(90.6) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(10.0)
    assert score == pytest.approx(blend - 0.35 * 7.5, abs=0.1)


def test_energy_spike_uses_real_prices(monkeypatch):
    # Nominal Brent +40% but CPI also +25%: real change is +12%, below the 20% threshold.
    ref = OFFICIAL - timedelta(days=91)
    brent = _daily(lambda d: 70.0 if d <= ref else 98.0)
    cpi = pd.Series([240.0 if d < pd.Timestamp(ref) else 300.0 for d in pd.date_range("2025-01-01", "2026-09-01", freq="MS")],
                    index=pd.date_range("2025-01-01", "2026-09-01", freq="MS"))
    Env(monkeypatch, brent=brent, cpi=cpi)
    score, _ = EnergyProvider().fetch_current()
    blend = 0.35 * BRENT_S(98.0) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(10.0)
    assert score == pytest.approx(blend, abs=0.1)


def test_energy_weights_renormalize_over_available_legs(monkeypatch):
    Env(monkeypatch, ulsd=ValueError("FRED down"))
    score, meta = EnergyProvider().fetch_current()
    expected = (0.35 * BRENT_S(80.0) + 0.25 * TTF_S(10.0)) / 0.60
    assert score == pytest.approx(expected, abs=0.1)
    assert meta["inputs"][1]["status"] == "missing"


def test_energy_stale_official_leg_is_dropped(monkeypatch):
    # Last ULSD print 40 days old: past the 30-day drop limit.
    Env(monkeypatch, ulsd=_daily(lambda d: 2.5, end=TODAY - timedelta(days=40)))
    _, meta = EnergyProvider().fetch_current()
    assert meta["inputs"][1]["status"] == "missing"


def test_energy_all_legs_missing_raises(monkeypatch):
    err = ValueError("down")
    Env(monkeypatch, brent=err, ulsd=err, ttf=err)
    with pytest.raises(RuntimeError):
        EnergyProvider().fetch_current()


def test_energy_missing_anchor_raises(monkeypatch):
    Env(monkeypatch)
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"cpi_reference": ANCHORS["cpi_reference"], "inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for brent"):
        EnergyProvider().fetch_current()


def test_energy_context_failure_does_not_fail_provider(monkeypatch):
    Env(monkeypatch, wti=ValueError("down"))
    score, meta = EnergyProvider().fetch_current()
    assert math.isfinite(score) and "WTI" not in meta["description"]


def test_energy_metadata_contract_and_context(monkeypatch):
    Env(monkeypatch)
    _, meta = EnergyProvider().fetch_current()
    for key in ("source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"):
        assert key in meta
    assert meta["as_of"] == "2026-09-30"           # oldest used input: the monthly TTF value
    assert meta["is_stale"] is False
    assert "WTI" in meta["description"] and "$4.00" in meta["description"]  # 80 - 76
    assert "crack" in meta["description"]
    assert "BZ=F" in meta["source"] and "HO=F" in meta["source"]


def test_energy_never_scores_wti_futures(monkeypatch):
    env = Env(monkeypatch)
    EnergyProvider().fetch_current()
    assert "CL=F" not in [c.args[2] for c in env.scale.call_args_list]


def test_history_recomputes_daily_from_official_series(monkeypatch):
    env = Env(monkeypatch)
    hist = EnergyProvider().fetch_history(120)
    env.scale.assert_not_called()                  # no live values in history
    assert isinstance(hist.index, pd.DatetimeIndex)
    expected = 0.35 * BRENT_S(80.0) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(10.0)
    assert hist.iloc[-1] == pytest.approx(expected, abs=0.1)
    assert hist.index.max() <= pd.Timestamp(TODAY)
    assert len(hist) <= 121


def test_history_includes_spike_and_leaves_gaps_before_data(monkeypatch):
    # Brent starts 2026-03-01 and doubles on 2026-08-01: ~91 days later the window still sees +100%.
    brent = _daily(lambda d: 100.0 if d >= date(2026, 8, 1) else 50.0, start=date(2026, 3, 1))
    Env(monkeypatch, brent=brent)
    hist = EnergyProvider().fetch_history(700)
    day = pd.Timestamp("2026-08-15")               # 14 days after the jump
    spiked = 0.35 * BRENT_S(100.0) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(10.0) - 0.35 * 15.0
    assert hist[day] == pytest.approx(spiked, abs=0.1)
    # Before Brent starts, scores renormalize over ULSD and TTF (TTF from Jan 2025 is published
    # 2025-03-07, so ULSD alone covers earlier days) and dates before any data are NaN.
    early = hist[pd.Timestamp("2025-12-01")]
    assert early == pytest.approx((0.40 * ULSD_S(2.5) + 0.25 * TTF_S(10.0)) / 0.65, abs=0.1)
    ulsd_only = hist[pd.Timestamp("2025-02-01")]
    assert ulsd_only == pytest.approx(ULSD_S(2.5), abs=0.1)
    assert hist[:pd.Timestamp("2024-12-31")].isna().all()


def test_history_all_missing_raises(monkeypatch):
    err = ValueError("down")
    Env(monkeypatch, brent=err, ulsd=err, ttf=err)
    with pytest.raises(RuntimeError):
        EnergyProvider().fetch_history(90)


def _monthly_with(**by_month):
    """Monthly TTF of 10.0 with overrides keyed 'YYYY_MM'."""
    series = _monthly(10.0)
    for key, value in by_month.items():
        series[pd.Timestamp(key.replace("_", "-") + "-01")] = value
    return series


def test_ttf_monthly_spike_compares_with_three_months_earlier(monkeypatch):
    # Sep 7.6 against Jun 5.0 is +52% (Jul/Aug are 7.0, so a two-month reference would see +9%).
    ttf = _monthly_with(**{"2026_06": 5.0, "2026_07": 7.0, "2026_08": 7.0, "2026_09": 7.6})
    Env(monkeypatch, ttf=ttf)
    score, meta = EnergyProvider().fetch_current()
    assert meta["inputs"][2]["name"] == "ttf_monthly"
    penalty = spike_penalty(7.6 / 5.0 - 1)
    assert penalty == pytest.approx(7.742, abs=0.01)
    blend = 0.35 * BRENT_S(80.0) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(7.6)
    assert score == pytest.approx(blend - 0.25 * penalty, abs=0.1)


def test_ttf_monthly_spike_matches_history_dating(monkeypatch):
    # Once September is published (2026-11-04), the history's last point applies the same
    # Sep-vs-Jun comparison as the current value.
    ttf = _monthly_with(**{"2026_06": 5.0, "2026_07": 7.0, "2026_08": 7.0, "2026_09": 7.6})
    Env(monkeypatch, ttf=ttf)
    monkeypatch.setattr(energy, "_today", lambda: date(2026, 11, 10))
    score, _ = EnergyProvider().fetch_current()
    hist = EnergyProvider().fetch_history(60)
    assert hist.iloc[-1] == pytest.approx(score, abs=0.1)


def test_live_ttf_spike_uses_official_value_on_or_before_91_days_back(monkeypatch):
    # Live as_of 2026-10-21, so the reference is the July 2026 average (6.0): +61%.
    ttf = _monthly_with(**{"2026_06": 3.0, "2026_07": 6.0})
    quotes = {"TTF=F": (date(2026, 10, 21), 30.0), "EURUSD=X": (TODAY, 1.10)}
    Env(monkeypatch, ttf=ttf, quotes=quotes)
    score, meta = EnergyProvider().fetch_current()
    live = 30.0 * 1.10 / 3.412
    assert meta["inputs"][2]["name"] == "ttf"
    penalty = spike_penalty(live / 6.0 - 1)
    assert penalty == pytest.approx(9.97, abs=0.01)
    blend = 0.35 * BRENT_S(80.0) + 0.40 * ULSD_S(2.5) + 0.25 * TTF_S(live)
    assert score == pytest.approx(blend - 0.25 * penalty, abs=0.1)


def test_runtime_fred_fetch_is_trimmed_not_full_history(monkeypatch):
    fetch = mock.Mock(return_value=pd.Series([1.0], index=pd.DatetimeIndex(["2026-10-01"])))
    monkeypatch.setattr(energy, "fetch_fred_series", fetch)
    energy._fred("DCOILBRENTEU")
    fetch.assert_called_once_with("DCOILBRENTEU", lookback_days=config.ENERGY_FRED_LOOKBACK_DAYS)
    assert config.ENERGY_FRED_LOOKBACK_DAYS <= 4 * 365
    assert not hasattr(energy, "fetch_fred_full")


@pytest.mark.parametrize("entry", [
    {"series": "CPIAUCSL", "value": CPI},                           # date missing: used to be a bare KeyError
    {"series": "CPIAUCSL", "date": "2025-12-01"},
    {"series": "CPIAUCSL", "date": "", "value": CPI},
])
def test_energy_cpi_reference_missing_or_malformed_raises_runtime_error(monkeypatch, entry):
    Env(monkeypatch)
    monkeypatch.setattr(config, "SCORE_ANCHORS", {**ANCHORS, "cpi_reference": entry})
    with pytest.raises(RuntimeError, match="no anchor for cpi_reference"):
        EnergyProvider().fetch_current()
    with pytest.raises(RuntimeError, match="no anchor for cpi_reference"):
        EnergyProvider().fetch_history(90)


def test_energy_fetch_failures_are_not_inputs_expired(monkeypatch):
    from data.providers.readings import InputsExpired
    err = ValueError("down")
    Env(monkeypatch, brent=err, ulsd=err, ttf=err)
    with pytest.raises(RuntimeError) as failure:
        EnergyProvider().fetch_current()
    assert not isinstance(failure.value, InputsExpired)


def test_energy_aged_out_legs_raise_inputs_expired(monkeypatch):
    from data.providers.readings import InputsExpired
    old_end = TODAY - timedelta(days=60)                    # daily drop is 30 days
    Env(monkeypatch, brent=_daily(lambda d: 80.0, end=old_end), ulsd=_daily(lambda d: 2.5, end=old_end),
        ttf=_monthly(10.0, end="2026-03-01"))                     # monthly drop is 150 days
    with pytest.raises(InputsExpired):
        EnergyProvider().fetch_current()
