"""Offline tests for the Trade & Tariffs category (customs burden + Trade Policy Uncertainty)."""
import importlib.util
import io
import math
from datetime import date, timedelta
from unittest import mock

import openpyxl
import pandas as pd
import pytest

import config
from data.providers import tariffs
from data.providers.tariffs import TariffsProvider
from data.sources import tpu, treasury

TODAY = date(2026, 10, 22)
CUSTOMS_NAME = "DHS - Customs Duties, Taxes, and Fees"

BURDEN_ANCHOR = {"series": "tariff_burden", "transform": "identity", "direction": "lower_better",
                 "best": 1.0, "normal": 2.0, "worst": 10.0}
TPU_ANCHOR = {"series": "tpu", "transform": "log", "direction": "lower_better",
              "best": math.log(20), "normal": math.log(50), "worst": math.log(500)}
ANCHORS = {"inputs": {"tariff_burden": BURDEN_ANCHOR, "tpu": TPU_ANCHOR}}


def _tpu_value_for(score):
    """Daily TPU level that the log anchor maps to ``score`` (between normal and worst)."""
    lw, ln = TPU_ANCHOR["worst"], TPU_ANCHOR["normal"]
    return math.exp(lw - score / 80.0 * (lw - ln))


def _row(day, amt, catg=treasury.CUSTOMS_CATEGORIES[0], typ="Deposits"):
    return {"record_date": day, "transaction_catg": catg, "transaction_type": typ,
            "transaction_today_amt": str(amt), "account_type": "Federal Reserve Account"}


@pytest.fixture(autouse=True)
def no_cache():
    with mock.patch.object(treasury, "get_cached", return_value=None), \
         mock.patch.object(treasury, "set_cached"), \
         mock.patch.object(tpu, "get_cached", return_value=None), \
         mock.patch.object(tpu, "set_cached"):
        yield


# ---------------------------------------------------------------------------- treasury

def test_monthly_customs_sums_deposits_only():
    rows = [
        _row("2005-10-03", 127),
        _row("2005-10-04", 133),
        _row("2005-10-04", 999, typ="Withdrawals"),            # not a deposit
        _row("2005-10-05", 500, catg="Federal Reserve Earnings"),  # not a customs category
        _row("2005-10-06", "null"),                             # unparseable amount is skipped
        _row("2005-11-01", 90, catg=treasury.CUSTOMS_CATEGORIES[2]),
    ]
    s = treasury.monthly_customs_from_rows(rows)
    assert s.to_dict() == {pd.Timestamp("2005-10-01"): 260.0, pd.Timestamp("2005-11-01"): 90.0}


def test_monthly_customs_complete_only_drops_open_month():
    rows = [_row("2026-08-31", 100), _row("2026-09-01", 50), _row("2026-09-30", 70),
            _row("2026-10-01", 30), _row("2026-10-21", 5)]
    s = treasury.monthly_customs_from_rows(rows, complete_only=True)
    assert s.index.tolist() == [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")]
    assert s.tolist() == [100.0, 120.0]


def test_monthly_customs_complete_only_needs_a_later_month_record():
    # A record in the following month is what proves the month is closed.
    s = treasury.monthly_customs_from_rows([_row("2026-09-01", 50), _row("2026-09-30", 70)],
                                           complete_only=True)
    assert s.empty


def _page(rows, pages=1):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = {"data": rows, "meta": {"total-pages": pages}}
    return resp


def test_fetch_customs_monthly_pages_each_category_and_caches():
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        catg = params["filter"].split("transaction_catg:eq:")[1].split(",transaction_type")[0]
        number = int(params["page[number]"])
        if catg == treasury.CUSTOMS_CATEGORIES[0]:
            return _page([_row(f"2026-0{number}-15", 10, catg=catg)], pages=2)
        if catg == treasury.CUSTOMS_CATEGORIES[1]:
            return _page([_row("2026-04-15", 20, catg=catg)])
        return _page([_row("2026-05-15", 30, catg=catg)])

    with mock.patch.object(treasury.requests, "get", side_effect=fake_get) as get, \
         mock.patch.object(treasury, "set_cached") as save:
        s = treasury.fetch_customs_monthly()
    assert get.call_args.args[0].endswith("/accounting/dts/deposits_withdrawals_operating_cash")
    assert len(calls) == 4  # two pages for the first category, one each for the other two
    assert all("transaction_type:eq:Deposits" in c["filter"] for c in calls)
    assert {c["filter"].split("transaction_catg:eq:")[1].split(",transaction_type")[0] for c in calls} \
        == set(treasury.CUSTOMS_CATEGORIES)
    # May is the newest month with a record, so it is still open and dropped.
    assert s.to_dict() == {pd.Timestamp("2026-01-01"): 10.0, pd.Timestamp("2026-02-01"): 10.0,
                           pd.Timestamp("2026-04-01"): 20.0}
    assert save.call_args.args[0] == "dts_customs_v1"


def test_fetch_customs_monthly_empty_raises_and_is_not_cached():
    with mock.patch.object(treasury.requests, "get", return_value=_page([])), \
         mock.patch.object(treasury, "set_cached") as save:
        with pytest.raises(ValueError):
            treasury.fetch_customs_monthly()
    save.assert_not_called()


def test_fetch_customs_monthly_uses_cache():
    cached = {"dates": ["2026-07-01", "2026-08-01"], "values": [100.0, 120.0]}
    with mock.patch.object(treasury, "get_cached", return_value=cached) as get, \
         mock.patch.object(treasury.requests, "get") as http:
        s = treasury.fetch_customs_monthly()
    http.assert_not_called()
    assert get.call_args.args[0] == "dts_customs_v1"
    assert get.call_args.kwargs["ttl"] == 12 * 3600
    assert s.tolist() == [100.0, 120.0]


def test_tariff_burden_ratio():
    # Customs of Jul-Sep pair with imports of Jun-Aug: deposits are shifted back one month.
    customs = pd.Series([10.0, 20.0, 30.0], index=pd.date_range("2026-07-01", periods=3, freq="MS"))
    imports = pd.Series([1000.0] * 3, index=pd.date_range("2026-06-01", periods=3, freq="MS"))
    burden = treasury.tariff_burden_series(customs, imports)
    assert burden.dropna().tolist() == [2.0]               # 100 * (10 + 20 + 30) / 3000
    assert burden.index[-1] == pd.Timestamp("2026-08-01")  # indexed by the import month m


def test_tariff_burden_flat_ratio():
    idx = pd.date_range("2026-06-01", periods=4, freq="MS")
    customs = pd.Series([10.0] * 4, index=idx)
    imports = pd.Series([1000.0] * 4, index=idx)
    burden = treasury.tariff_burden_series(customs, imports)
    assert burden.dropna().tolist() == [1.0]               # only Aug has imports for Jun-Aug and customs Jul-Sep
    assert burden.index[-1] == pd.Timestamp("2026-08-01")


def test_tariff_burden_pairs_next_month_deposits_with_imports():
    # A one-month spike in deposits shows up one month earlier than the deposit month.
    idx = pd.date_range("2026-01-01", periods=8, freq="MS")
    customs = pd.Series([10.0] * 8, index=idx)
    customs[pd.Timestamp("2026-06-01")] = 40.0             # June deposits belong to May entries
    imports = pd.Series([1000.0] * 8, index=idx)
    burden = treasury.tariff_burden_series(customs, imports)
    assert burden[pd.Timestamp("2026-04-01")] == pytest.approx(1.0)   # deposits Mar-May
    assert burden[pd.Timestamp("2026-05-01")] == pytest.approx(100 * 60 / 3000)  # deposits Apr-Jun


def test_tariff_burden_latest_month_needs_next_month_deposits():
    # DTS through Sep 21 (September still open): Sep is dropped, so August cannot be scored.
    rows = [_row(f"2026-{m:02d}-15", 10) for m in range(3, 10)] + [_row("2026-09-21", 5)]
    customs = treasury.monthly_customs_from_rows(rows, complete_only=True)
    assert customs.index[-1] == pd.Timestamp("2026-08-01")
    imports = pd.Series([1000.0] * 7, index=pd.date_range("2026-03-01", periods=7, freq="MS"))
    burden = treasury.tariff_burden_series(customs, imports)
    assert burden.index[-1] == pd.Timestamp("2026-07-01")


def test_tariff_burden_gap_month_gives_no_value():
    idx = pd.date_range("2026-01-01", periods=8, freq="MS")
    customs = pd.Series([10.0] * 8, index=idx).drop(pd.Timestamp("2026-04-01"))
    imports = pd.Series([1000.0] * 8, index=idx)
    burden = treasury.tariff_burden_series(customs, imports)
    # Missing April deposits belong to March; windows ending Mar, Apr and May contain it.
    assert burden.index.tolist() == [pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-01")]


# ---------------------------------------------------------------------------- tpu

def _xlsx(sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, header, rows in sheets:
        ws = wb.create_sheet(name)
        ws.append(header)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


DAILY = ("TPU_DAILY", ["DATE", "TPUD_index"],
         [[pd.Timestamp("2026-10-17"), 94.5], [pd.Timestamp("2026-10-18"), 273.7]])
MONTHLY = ("TPU_MONTHLY", ["DATE", "TPU"], [[pd.Timestamp("2026-09-01"), 260.7]])


def test_parse_tpu_xlsx_reads_both_sheets():
    daily, monthly = tpu.parse_tpu_xlsx(_xlsx([DAILY, MONTHLY]))
    assert daily.tolist() == [94.5, 273.7]
    assert daily.index[-1] == pd.Timestamp("2026-10-18")
    assert monthly.tolist() == [260.7]


def test_parse_tpu_xlsx_accepts_a_path(tmp_path):
    path = tmp_path / "tpu.xlsx"
    path.write_bytes(_xlsx([DAILY, MONTHLY]))
    daily, _ = tpu.parse_tpu_xlsx(path)
    assert len(daily) == 2


def test_tpu_missing_sheet_raises():
    with pytest.raises(ValueError):
        tpu.parse_tpu_xlsx(_xlsx([MONTHLY]))


def test_tpu_renamed_column_raises():
    daily = ("TPU_DAILY", ["DATE", "TPUD_renamed"], [[pd.Timestamp("2026-10-17"), 94.5]])
    with pytest.raises(ValueError):
        tpu.parse_tpu_xlsx(_xlsx([daily, MONTHLY]))


def test_tpu_empty_sheet_raises():
    daily = ("TPU_DAILY", ["DATE", "TPUD_index"], [])
    with pytest.raises(ValueError):
        tpu.parse_tpu_xlsx(_xlsx([daily, MONTHLY]))


def test_tpu_not_a_workbook_raises_value_error():
    with pytest.raises(ValueError):
        tpu.parse_tpu_xlsx(b"<html>Service unavailable</html>")


def _http(content, status_ok=True):
    resp = mock.Mock(content=content)
    if status_ok:
        resp.raise_for_status = mock.Mock()
    else:
        resp.raise_for_status.side_effect = RuntimeError("503")
    return resp


def test_fetch_tpu_downloads_parses_and_caches():
    with mock.patch.object(tpu.requests, "get", return_value=_http(_xlsx([DAILY, MONTHLY]))) as get, \
         mock.patch.object(tpu, "set_cached") as save:
        daily, monthly = tpu.fetch_tpu()
    assert get.call_args.args[0] == "https://www.matteoiacoviello.com/tpu_files/tpu_web_latest.xlsx"
    assert daily.tolist() == [94.5, 273.7] and monthly.tolist() == [260.7]
    assert save.call_args.args[0] == "tpu_v1"


def test_fetch_tpu_reshaped_file_raises_and_is_not_cached():
    with mock.patch.object(tpu.requests, "get", return_value=_http(_xlsx([MONTHLY]))), \
         mock.patch.object(tpu, "set_cached") as save:
        with pytest.raises(ValueError):
            tpu.fetch_tpu()
    save.assert_not_called()


def test_fetch_tpu_uses_cache():
    cached = {"daily": {"dates": ["2026-10-18"], "values": [273.7]},
              "monthly": {"dates": ["2026-09-01"], "values": [260.7]}}
    with mock.patch.object(tpu, "get_cached", return_value=cached) as get, \
         mock.patch.object(tpu.requests, "get") as http:
        daily, monthly = tpu.fetch_tpu()
    http.assert_not_called()
    assert get.call_args.kwargs["ttl"] == 12 * 3600
    assert daily.tolist() == [273.7] and monthly.tolist() == [260.7]


# ---------------------------------------------------------------------------- provider

def _months(end="2026-08-01", start="2025-01-01"):
    return pd.date_range(start, end, freq="MS")


def _customs(pct=6.0, end="2026-09-01"):
    idx = _months(end)
    return pd.Series([pct * 10.0] * len(idx), index=idx)      # $M; imports below are 1000


def _imports(end="2026-08-01"):
    idx = _months(end)
    return pd.Series([1000.0] * len(idx), index=idx)


def _tpu_daily(level, end="2026-10-19", start="2026-01-01"):
    idx = pd.date_range(start, end, freq="D")
    return pd.Series([level] * len(idx), index=idx)


def _fred(imports=None, eputrade=None):
    def fake(series_id, lookback_days=None, **kw):
        if series_id == "BOPGIMP":
            if imports is None:
                raise RuntimeError("FRED down")
            return imports
        if series_id == "EPUTRADE":
            if eputrade is None:
                raise RuntimeError("FRED down")
            return eputrade
        raise AssertionError(series_id)
    return fake


@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
    monkeypatch.setattr(tariffs, "_today", lambda: TODAY)


def _run(fn, customs=None, imports=None, tpu_daily=None, eputrade=None):
    """Run ``fn`` with the three sources patched; a source passed as None fails."""
    def dts():
        if customs is None:
            raise RuntimeError("DTS down")
        return customs

    def tpu_file():
        if tpu_daily is None:
            raise ValueError("TPU sheet missing")
        return tpu_daily, tpu_daily

    with mock.patch.object(tariffs, "fetch_fred_series", side_effect=_fred(imports, eputrade)), \
         mock.patch.object(tariffs.treasury, "fetch_customs_monthly", side_effect=dts), \
         mock.patch.object(tariffs.tpu, "fetch_tpu", side_effect=tpu_file):
        return fn()


def test_tariffs_config_weights():
    assert config.TARIFF_WEIGHTS == {"tariff_burden": 0.6, "tpu": 0.4}
    assert TariffsProvider.category == "tariffs"


def test_tariffs_blend_weights(anchors):
    # burden 6% -> 80 * (10 - 6) / (10 - 2) = 40; TPU level chosen to score 70
    score, meta = _run(TariffsProvider().fetch_current, customs=_customs(6.0), imports=_imports(),
                       tpu_daily=_tpu_daily(_tpu_value_for(70)))
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tariff_burden"]["score"] == pytest.approx(40.0)
    assert inputs["tpu"]["score"] == pytest.approx(70.0)
    assert score == 52.0


def test_tariffs_metadata_shape_and_dates(anchors):
    score, meta = _run(TariffsProvider().fetch_current, customs=_customs(), imports=_imports(),
                       tpu_daily=_tpu_daily(100.0),
                       eputrade=pd.Series([88.0, 120.5], index=pd.to_datetime(["2026-08-01", "2026-09-01"])))
    for key in ("source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"):
        assert key in meta
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tariff_burden"]["as_of"] == "2026-08-31"      # period end of the latest month
    assert inputs["tpu"]["as_of"] == "2026-10-19"                # last daily date in the file
    assert meta["as_of"] == "2026-08-31"                         # oldest input
    assert meta["is_stale"] is False
    assert "gross of IEEPA refunds" in meta["description"]
    assert "120.5" in meta["description"] and "EPUTRADE" in meta["description"]
    assert "6.00%" in meta["raw_value"]


def test_tariffs_uses_30_day_mean_of_daily_index(anchors):
    idx = pd.date_range("2026-08-01", "2026-10-19", freq="D")
    values = [50.0] * (len(idx) - 30) + [200.0] * 30
    daily = pd.Series(values, index=idx)
    _, meta = _run(TariffsProvider().fetch_current, customs=_customs(), imports=_imports(), tpu_daily=daily)
    tpu_input = {i["name"]: i for i in meta["inputs"]}["tpu"]
    assert tpu_input["raw_value"].startswith("200.0")
    expected = (math.log(500) - math.log(200)) / (math.log(500) - math.log(50)) * 80
    assert tpu_input["score"] == pytest.approx(expected)


def test_tariffs_eputrade_failure_does_not_fail_provider(anchors):
    score, meta = _run(TariffsProvider().fetch_current, customs=_customs(), imports=_imports(),
                       tpu_daily=_tpu_daily(100.0), eputrade=None)
    assert isinstance(score, float)
    assert "EPUTRADE" not in meta["description"]


def test_tariffs_one_input_missing_uses_the_other(anchors):
    score, meta = _run(TariffsProvider().fetch_current, customs=_customs(6.0), imports=_imports(),
                       tpu_daily=None)
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tpu"]["status"] == "missing"
    assert score == 40.0


def test_tariffs_reshaped_tpu_file_counts_as_missing(anchors):
    # A 200 whose workbook lost the TPU_DAILY sheet must drop the input, never score it.
    with mock.patch.object(tpu.requests, "get", return_value=_http(_xlsx([MONTHLY]))), \
         mock.patch.object(tariffs, "fetch_fred_series", side_effect=_fred(_imports())), \
         mock.patch.object(tariffs.treasury, "fetch_customs_monthly", return_value=_customs(6.0)):
        score, meta = TariffsProvider().fetch_current()
    assert {i["name"]: i for i in meta["inputs"]}["tpu"]["status"] == "missing"
    assert score == 40.0


def test_tariffs_empty_dts_payload_counts_as_missing(anchors):
    page = _page([])
    with mock.patch.object(treasury.requests, "get", return_value=page), \
         mock.patch.object(tariffs, "fetch_fred_series", side_effect=_fred(_imports())), \
         mock.patch.object(tariffs.tpu, "fetch_tpu", return_value=(_tpu_daily(100.0),) * 2):
        score, meta = TariffsProvider().fetch_current()
    assert {i["name"]: i for i in meta["inputs"]}["tariff_burden"]["status"] == "missing"
    assert score == pytest.approx(_tpu_score_at(100.0), abs=0.1)


def test_tariffs_all_inputs_missing_raises(anchors):
    with pytest.raises(RuntimeError):
        _run(TariffsProvider().fetch_current, customs=None, imports=None, tpu_daily=None)


def test_tariffs_missing_anchor_raises(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {"tariff_burden": BURDEN_ANCHOR}})
    monkeypatch.setattr(tariffs, "_today", lambda: TODAY)
    with pytest.raises(RuntimeError, match="no anchor for tpu"):
        _run(TariffsProvider().fetch_current, customs=_customs(), imports=_imports(),
             tpu_daily=_tpu_daily(100.0))


def test_tariffs_stale_burden_flags_stale(anchors, monkeypatch):
    monkeypatch.setattr(tariffs, "_today", lambda: date(2026, 11, 16))  # 77 days after Aug 31
    _, meta = _run(TariffsProvider().fetch_current, customs=_customs(), imports=_imports(),
                   tpu_daily=_tpu_daily(100.0, end="2026-11-14"))
    inputs = {i["name"]: i for i in meta["inputs"]}
    assert inputs["tariff_burden"]["status"] == "stale"
    assert inputs["tpu"]["status"] == "live"
    assert meta["is_stale"] is True


def test_tariffs_burden_dropped_after_freshness_window(anchors, monkeypatch):
    monkeypatch.setattr(tariffs, "_today", lambda: date(2027, 2, 15))   # 168 days after Aug 31
    score, meta = _run(TariffsProvider().fetch_current, customs=_customs(), imports=_imports(),
                       tpu_daily=_tpu_daily(100.0, end="2027-02-14"))
    assert {i["name"]: i for i in meta["inputs"]}["tariff_burden"]["status"] == "missing"
    assert score == pytest.approx({i["name"]: i for i in meta["inputs"]}["tpu"]["score"], abs=0.1)


def test_tariffs_history_dates_burden_by_publication_lag(anchors):
    customs = _customs(6.0)
    customs[pd.Timestamp("2026-07-01")] = 120.0            # July deposits 12%; burden for Jun, Jul, Aug = 8%
    daily = _tpu_daily(_tpu_value_for(70), start="2026-01-01", end="2026-10-19")
    hist = _run(lambda: TariffsProvider().fetch_history(120), customs=customs,
                imports=_imports(), tpu_daily=daily)
    assert hist.name == "tariffs"
    assert hist.index[-1] == pd.Timestamp(TODAY)
    assert (config.PUBLICATION_LAG_DAYS["dts"], config.PUBLICATION_LAG_DAYS["bopgimp"]) == (1, 35)
    # June's burden (deposits May-Jul) is public at max(Jul 31 + 1, Jun 30 + 35) = Aug 4;
    # until then May's 6% reading (score 40) stands.
    assert hist[pd.Timestamp("2026-08-03")] == pytest.approx(0.6 * 40 + 0.4 * 70, abs=0.1)
    assert hist[pd.Timestamp("2026-08-04")] == pytest.approx(0.6 * 20 + 0.4 * 70, abs=0.1)


def test_tariffs_history_leaves_unobserved_days_nan(anchors):
    # Customs complete through April, imports through April: the last burden is March (public
    # May 5) and drops 150 days after Mar 31, on Aug 28. The TPU 30-day mean needs 20
    # observations, so it first exists Sep 29 for a file starting Sep 10.
    daily = _tpu_daily(_tpu_value_for(70), start="2026-09-10", end="2026-10-19")
    hist = _run(lambda: TariffsProvider().fetch_history(120), customs=_customs(6.0, end="2026-04-01"),
                imports=_imports("2026-04-01"), tpu_daily=daily)
    assert hist[pd.Timestamp("2026-06-25")] == pytest.approx(40.0, abs=0.1)
    assert hist[pd.Timestamp("2026-08-28")] == pytest.approx(40.0, abs=0.1)
    assert hist["2026-08-29":"2026-09-28"].isna().all()
    assert hist[pd.Timestamp("2026-09-29")] == pytest.approx(70.0, abs=0.1)
    assert hist[pd.Timestamp(TODAY)] == pytest.approx(70.0, abs=0.1)


def test_tariffs_history_tpu_dated_by_its_own_days(anchors):
    idx = pd.date_range("2026-01-01", "2026-10-19", freq="D")
    daily = pd.Series([50.0] * 280 + [300.0] * (len(idx) - 280), index=idx)
    hist = _run(lambda: TariffsProvider().fetch_history(30), customs=None, imports=None, tpu_daily=daily)
    mean30 = daily.rolling(30, min_periods=20).mean()
    for day in ("2026-10-05", "2026-10-15", "2026-10-19"):
        assert hist[pd.Timestamp(day)] == pytest.approx(_tpu_score_at(mean30[pd.Timestamp(day)]), abs=0.1)


def test_tariffs_history_tpu_carries_last_value_to_today(anchors):
    idx = pd.date_range("2026-08-01", "2026-10-19", freq="D")          # the file ends 3 days before TODAY
    daily = pd.Series(_tpu_value_for(70), index=idx)
    hist = _run(lambda: TariffsProvider().fetch_history(10), customs=None, imports=None, tpu_daily=daily)
    assert hist.index[-1] == pd.Timestamp(TODAY)
    last = hist[pd.Timestamp("2026-10-19")]
    assert last == pytest.approx(70.0, abs=0.1)
    for day in ("2026-10-20", "2026-10-21", "2026-10-22"):
        assert hist[pd.Timestamp(day)] == last


def test_tariffs_history_tpu_tail_is_nan_past_the_drop_limit(anchors):
    drop = config.FRESHNESS["tpu"][1]
    end = TODAY - timedelta(days=drop + 1)                              # the file ends drop+1 days before TODAY
    idx = pd.date_range(end - timedelta(days=60), end, freq="D")
    daily = pd.Series(_tpu_value_for(70), index=idx)
    hist = _run(lambda: TariffsProvider().fetch_history(10), customs=None, imports=None, tpu_daily=daily)
    assert hist.index[-1] == pd.Timestamp(TODAY)
    assert math.isnan(hist[pd.Timestamp(TODAY)])
    assert hist[pd.Timestamp(TODAY) - pd.Timedelta(days=1)] == pytest.approx(70.0, abs=0.1)


def _tpu_score_at(level):
    from scoring.anchors import score_raw
    return score_raw(level, TPU_ANCHOR)


def test_tariffs_history_all_missing_raises(anchors):
    with pytest.raises(RuntimeError):
        _run(lambda: TariffsProvider().fetch_history(30), customs=None, imports=None, tpu_daily=None)


def test_nowcast_module_removed():
    assert importlib.util.find_spec("data.providers.tariff_news_nowcast") is None


def test_tariffs_fetch_failures_are_not_inputs_expired(anchors):
    from data.providers.readings import InputsExpired
    with pytest.raises(RuntimeError) as failure:
        _run(TariffsProvider().fetch_current, customs=None, imports=None, tpu_daily=None)
    assert not isinstance(failure.value, InputsExpired)


def test_tariff_burden_is_live_until_the_next_print_is_due():
    # BOPGIMP for August lands about Oct 5 (35 days after month end); September's lands about
    # Nov 4. A healthy source is about 65 days old just before the next print: still live.
    from data.providers.readings import freshness_status
    assert config.FRESHNESS["tariff_burden"] == (75, 150)
    august_end = date(2026, 8, 31)
    assert freshness_status(august_end, date(2026, 11, 4), "tariff_burden") == "live"
    assert freshness_status(august_end, date(2026, 11, 15), "tariff_burden") == "stale"
