"""Offline tests for the BOJ source and the three Semis categories."""
from datetime import date
from unittest import mock

import pandas as pd
import pytest

import config
from data.providers import semis
from data.providers.readings import InputsExpired
from data.sources import boj

TODAY = date(2026, 10, 22)

# Identity transform on YoY %: 30.2 at +31.3, 99.3 at -35.4 (lower is better).
BOJ_ANCHOR = {"series": "boj", "transform": "identity", "direction": "lower_better",
              "best": -36.3, "normal": -11.8, "worst": 57.4}
FAB_ANCHOR = {"series": "caputlg3344s", "transform": "identity", "direction": "lower_better",
              "best": 64.8, "normal": 80.1, "worst": 93.2}
ANCHORS = {"inputs": {"boj_memory": BOJ_ANCHOR, "boj_logic": BOJ_ANCHOR, "fab_util_3344": FAB_ANCHOR}}


def _payload(code="PRCG20_2500850005", dates=None, values=None, **overrides):
    """A BOJ getDataCode reply in the shape the API returns."""
    dates = dates if dates is not None else [202401, 202402, 202403]
    values = values if values is not None else [100.0, 101.5, None]
    body = {
        "STATUS": 200, "MESSAGEID": "M181000I", "MESSAGE": "Successfully completed",
        "PARAMETER": {"FORMAT": "JSON", "LANG": "EN", "DB": "PR01", "STARTDATE": "200001"},
        "NEXTPOSITION": None,
        "RESULTSET": [{"SERIES_CODE": code, "UNIT": "CY2020 average=100", "FREQUENCY": "MONTHLY",
                       "VALUES": {"SURVEY_DATES": dates, "VALUES": values}}],
    }
    body.update(overrides)
    return body


def _levels(end="2026-09-01", yoy_pct=0.0, months=30):
    """Monthly index at 100, with the last 12 months ``yoy_pct`` above the year before."""
    idx = pd.date_range(end=end, periods=months, freq="MS")
    return pd.Series([100.0] * (months - 12) + [100.0 * (1 + yoy_pct / 100.0)] * 12, index=idx, dtype=float)


@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
    monkeypatch.setattr(semis, "_today", lambda: TODAY)


def _with_boj(fn, series):
    """Run ``fn`` with BOJ returning ``series``; an Exception instance is raised instead."""
    def fetch(code):
        if isinstance(series, Exception):
            raise series
        return series
    with mock.patch.object(boj, "fetch_series", fetch):
        return fn()


def _with_fab(fn, series):
    def fred(series_id, lookback_days=None, **_):
        assert series_id == "CAPUTLG3344S"
        assert lookback_days == config.SEMIS_FRED_LOOKBACK_DAYS
        if isinstance(series, Exception):
            raise series
        return series
    with mock.patch.object(semis, "fetch_fred_series", fred):
        return fn()


# ------------------------------------------------------------------ BOJ source

@pytest.mark.parametrize("payload", [
    {"STATUS": 200, "RESULTSET": [{"SERIES_CODE": "C", "FREQUENCY": "MONTHLY"}]},          # no VALUES
    {"STATUS": 200, "RESULTSET": [{"SERIES_CODE": "C", "FREQUENCY": "MONTHLY", "VALUES": {}}]},
    {"STATUS": 400, "MESSAGEID": "M181005E", "MESSAGE": "Series code not found"},          # error body
    {"STATUS": 200, "RESULTSET": []},
    {"STATUS": 200},
    _payload(code="OTHER"),                                                                # wrong code
    _payload("C", dates=[], values=[]),                                                    # empty
    _payload("C", values=[None, None, None]),                                              # all null
    _payload("C", dates=[202401], values=[1.0, 2.0]),                                      # reshaped
    _payload("C", FREQUENCY="x") | {"RESULTSET": [{"SERIES_CODE": "C", "FREQUENCY": "QUARTERLY",
                                                   "VALUES": {"SURVEY_DATES": [20241], "VALUES": [1.0]}}]},
    _payload("C", NEXTPOSITION=61),                                                        # truncated
    ["not", "a", "dict"],
])
def test_boj_parse_reshaped_raises(payload):
    with pytest.raises(ValueError):
        boj.parse_series(payload, "C")


def test_boj_parse_monthly_index():
    series = boj.parse_series(_payload(), "PRCG20_2500850005")
    assert list(series.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")]  # null month dropped
    assert list(series) == [100.0, 101.5]
    assert series.dtype == float


def test_boj_fetch_caches_good_reply_and_not_a_bad_one():
    store = {}
    code = "PRCG20_2500850005"
    good = mock.Mock(status_code=200)
    good.json.return_value = _payload(code)
    bad = mock.Mock(status_code=200)
    bad.json.return_value = {"STATUS": 400, "MESSAGE": "bad"}
    with mock.patch.object(boj, "get_cached", lambda k, ttl: store.get(k)), \
            mock.patch.object(boj, "set_cached", lambda k, v: store.__setitem__(k, v)), \
            mock.patch.object(boj.requests, "get", return_value=bad) as get:
        with pytest.raises(ValueError):
            boj.fetch_series(code)
        assert store == {}
        get.return_value = good
        first = boj.fetch_series(code)
        second = boj.fetch_series(code)          # served from the cache
    assert get.call_count == 2
    assert list(store) == [f"boj_{code}_v1"]
    pd.testing.assert_series_equal(first, second)
    assert get.call_args.kwargs["params"]["code"] == code
    assert get.call_args.args[0] == boj.API_URL


# ------------------------------------------------------------------ memory and logic

@pytest.mark.parametrize("yoy, expected", [(31.3, 30.2), (-35.4, 99.3)])
@pytest.mark.parametrize("provider", [semis.MemoryPricesProvider, semis.LogicPricesProvider])
def test_memory_yoy_and_anchor(anchors, provider, yoy, expected):
    score, meta = _with_boj(provider().fetch_current, _levels(yoy_pct=yoy))
    assert score == pytest.approx(expected, abs=0.05)
    assert "YoY" in meta["raw_value"] and "Sep 2026" in meta["raw_value"]


def test_boj_categories_carry_the_credit_and_metadata_contract(anchors):
    for provider in (semis.MemoryPricesProvider, semis.LogicPricesProvider):
        _, meta = _with_boj(provider().fetch_current, _levels(yoy_pct=5))
        assert config.BOJ_CREDIT in meta["description"]
        assert {"source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"} <= set(meta)
        assert meta["as_of"] == "2026-09-30"
        assert meta["is_stale"] is False
        assert [i["name"] for i in meta["inputs"]] == [provider.input_key]
        assert "—" not in meta["description"]


def test_provider_categories_match_sector_keys():
    keys = set(config.SECTORS["semiconductor"]["weights"])
    assert {semis.MemoryPricesProvider.category, semis.LogicPricesProvider.category,
            semis.FabUtilizationProvider.category} == keys


def test_yoy_compares_by_date_not_position(anchors):
    levels = _levels(yoy_pct=31.3)
    levels = levels.drop(levels.index[-5])      # a missing month must not shift the comparison
    score, _ = _with_boj(semis.MemoryPricesProvider().fetch_current, levels)
    assert score == pytest.approx(30.2, abs=0.05)


def test_zero_or_missing_base_counts_as_missing(anchors):
    levels = _levels(yoy_pct=10)
    levels.iloc[:18] = 0.0                      # every year-earlier base is zero
    with pytest.raises(RuntimeError):
        _with_boj(semis.MemoryPricesProvider().fetch_current, levels)


def test_month_in_progress_is_as_of_today(anchors):
    _, meta = _with_boj(semis.MemoryPricesProvider().fetch_current, _levels(end="2026-10-01", yoy_pct=5))
    assert meta["as_of"] == TODAY.isoformat()


def test_stale_input_is_flagged(anchors, monkeypatch):
    monkeypatch.setattr(semis, "_today", lambda: date(2027, 1, 10))   # 102 days after 2026-09-30
    _, meta = _with_boj(semis.MemoryPricesProvider().fetch_current, _levels(yoy_pct=5))
    assert meta["is_stale"] is True and meta["inputs"][0]["status"] == "stale"


def test_aged_out_input_raises_inputs_expired(anchors, monkeypatch):
    monkeypatch.setattr(semis, "_today", lambda: date(2027, 3, 1))    # 152 days after 2026-09-30
    with pytest.raises(InputsExpired):
        _with_boj(semis.MemoryPricesProvider().fetch_current, _levels(yoy_pct=5))


# ------------------------------------------------------------------ fab utilization

def test_fab_util_lower_is_better(anchors):
    def run(level):
        idx = pd.date_range(end="2026-09-01", periods=12, freq="MS")
        return _with_fab(semis.FabUtilizationProvider().fetch_current,
                         pd.Series([level] * 12, index=idx, dtype=float))[0]
    low, normal, high = run(70.0), run(80.1), run(90.0)
    assert low > normal > high
    assert normal == pytest.approx(80.0, abs=0.05)
    assert run(64.8) == 100.0 and run(93.2) == 0.0


def test_fab_util_description_says_weak_demand_is_not_separated(anchors):
    idx = pd.date_range(end="2026-09-01", periods=12, freq="MS")
    _, meta = _with_fab(semis.FabUtilizationProvider().fetch_current,
                        pd.Series([75.0] * 12, index=idx, dtype=float))
    assert "weak demand is not separated out" in meta["description"]


def test_fab_util_metadata_has_no_boj_credit(anchors):
    idx = pd.date_range(end="2026-09-01", periods=12, freq="MS")
    _, meta = _with_fab(semis.FabUtilizationProvider().fetch_current,
                        pd.Series([75.0] * 12, index=idx, dtype=float))
    assert config.BOJ_CREDIT not in meta["description"]
    assert meta["raw_value"] == "75.0% (Sep 2026)"
    assert meta["as_of"] == "2026-09-30"


# ------------------------------------------------------------------ missing inputs

@pytest.mark.parametrize("failure", [
    ValueError("BOJ status 400"),
    boj.requests.ConnectionError("down"),
    pd.Series([], dtype=float),
    pd.Series([float("nan"), float("inf")], index=pd.date_range("2026-08-01", periods=2, freq="MS")),
])
def test_semis_empty_payload_counts_missing_and_raises(anchors, failure):
    for provider in (semis.MemoryPricesProvider, semis.LogicPricesProvider):
        with pytest.raises(RuntimeError) as err:
            _with_boj(provider().fetch_current, failure)
        assert not isinstance(err.value, InputsExpired)
    with pytest.raises(RuntimeError):
        _with_fab(semis.FabUtilizationProvider().fetch_current, failure)


def test_reshaped_boj_reply_never_scores(anchors):
    """A 200 reply that parses to nothing reaches the provider as a ValueError from the source."""
    response = mock.Mock(status_code=200)
    response.json.return_value = _payload(code="WRONG")
    with mock.patch.object(boj, "get_cached", lambda k, ttl: None), \
            mock.patch.object(boj, "set_cached"), mock.patch.object(boj.requests, "get", return_value=response):
        with pytest.raises(RuntimeError):
            semis.MemoryPricesProvider().fetch_current()


def test_missing_anchor_is_a_runtime_error(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for boj_memory"):
        _with_boj(semis.MemoryPricesProvider().fetch_current, _levels())


# ------------------------------------------------------------------ history

def test_history_is_dated_by_publication_lag_and_drops_after_window(anchors):
    levels = _levels(end="2026-03-01", yoy_pct=10)            # last month: March 2026
    history = _with_boj(lambda: semis.MemoryPricesProvider().fetch_history(400), levels)
    period_end_ts = pd.Timestamp("2026-03-31")
    public = period_end_ts + pd.Timedelta(days=config.PUBLICATION_LAG_DAYS["boj_cgpi"])
    assert history.name == "semis_memory_prices"
    assert history.index[-1] == pd.Timestamp(TODAY)
    # March at +10% YoY scores 80 * (57.4 - 10) / (57.4 + 11.8) = 54.8 from its publication date.
    assert history[public] == pytest.approx(54.8, abs=0.05)
    assert pd.notna(history[period_end_ts + pd.Timedelta(days=config.FRESHNESS["boj_memory"][1])])
    assert pd.isna(history[period_end_ts + pd.Timedelta(days=config.FRESHNESS["boj_memory"][1] + 1)])
    # nothing is filled before the first measurable year-over-year month becomes public
    first_yoy = _levels(end="2026-03-01", yoy_pct=10).index[12]
    assert history.loc[:first_yoy].isna().all()


def test_history_all_missing_raises(anchors):
    with pytest.raises((RuntimeError, ValueError)):
        _with_boj(lambda: semis.MemoryPricesProvider().fetch_history(90), ValueError("down"))


def test_history_beyond_every_window_raises(anchors, monkeypatch):
    monkeypatch.setattr(semis, "_today", lambda: date(2028, 1, 1))
    with pytest.raises(RuntimeError):
        _with_boj(lambda: semis.MemoryPricesProvider().fetch_history(90), _levels(yoy_pct=5))


def test_fab_history_uses_g17_lag(anchors):
    idx = pd.date_range(end="2026-08-01", periods=12, freq="MS")
    series = pd.Series([70.0] * 11 + [90.0], index=idx, dtype=float)      # August jumps to 90
    history = _with_fab(lambda: semis.FabUtilizationProvider().fetch_history(90), series)
    public = pd.Timestamp("2026-08-31") + pd.Timedelta(days=config.PUBLICATION_LAG_DAYS["g17"])
    before, after = history[public - pd.Timedelta(days=1)], history[public]
    assert before == pytest.approx(100 - 20 * (70.0 - 64.8) / (80.1 - 64.8), abs=0.05)   # July's 70% still stands
    assert after == pytest.approx(80 * (93.2 - 90.0) / (93.2 - 80.1), abs=0.05)


# ------------------------------------------------------------------ config

def test_sectors_config_weights():
    for sector in config.SECTORS.values():
        assert sum(sector["weights"].values()) == pytest.approx(1.0)
    semi = config.SECTORS["semiconductor"]
    assert set(semi["weights"]) == {"semis_memory_prices", "semis_logic_prices", "semis_fab_utilization"}
    assert all(w == pytest.approx(1 / 3) for w in semi["weights"].values())
    assert semi["min_categories"] == 2 and semi["label"] == "Semis" and semi["title"] == "Semiconductor"
    aero = config.SECTORS["aerospace"]
    assert set(aero["weights"]) == {"aero_throughput", "aero_flow", "aero_mill_prices", "aero_forge_cast"}
    assert all(w == pytest.approx(0.25) for w in aero["weights"].values())
    assert aero["min_categories"] == 3 and aero["label"] == "Aero"


def test_sector_config_entries():
    for key in ("boj_memory", "boj_logic", "fab_util_3344"):
        assert config.FRESHNESS[key] == (75, 150)
        assert key in config.INPUT_LABELS
    assert config.PUBLICATION_LAG_DAYS["boj_cgpi"] == 12 and config.PUBLICATION_LAG_DAYS["g17"] == 16
    assert config.SECTOR_DROP_AFTER_DAYS == 150
    for cat in config.SECTORS["semiconductor"]["weights"]:
        assert cat in config.CATEGORY_LABELS and cat in config.CATEGORY_COLORS
    assert config.BOJ_CREDIT == ("This service uses the API provided by the 'Bank of Japan Time-Series "
                                 "Data Search.' The Bank of Japan does not guarantee the content of the service.")
    assert config.SECTOR_PROVIDER_TIMEOUT_SECONDS > 0 and config.SEMIS_FRED_LOOKBACK_DAYS >= 3 * 365
