"""Offline tests for the Chokepoints category (IMF PortWatch daily transits)."""
import math
from datetime import date, timedelta
from unittest import mock

import numpy as np
import pandas as pd
import pytest

import config
from data import portwatch
from data.providers.chokepoints import ChokepointsProvider

# Tonnage shares over 2022-01..2023-10 (research out_weights.csv, `ton` column).
WEIGHTS = {
    "Hormuz": 0.13038920936378975,
    "RedSea": 0.10677210267252153,
    "Panama": 0.030380288917563975,
    "Malacca": 0.26463291785314635,
    "Taiwan": 0.18209587767649868,
    "Gibraltar": 0.13315592419901245,
    "Dover": 0.11591485710948354,
    "Bosporus": 0.03665882220798379,
}
ALL_NAMES = portwatch.CORRIDORS + ["BabM", "Suez", "Cape"]
PORT_NAMES = list(portwatch.PORTIDS)  # the ten series PortWatch publishes (no RedSea)

# Research ratio rows (docs/.../outputs/chokepoint_ratio_rows.json) and their k=3 score.
RESEARCH_ROWS = {
    "2026-10-18": (36.097, {
        "Hormuz": 0.038, "RedSea": 0.354, "Panama": 0.876, "Malacca": 0.983,
        "Taiwan": 1.052, "Gibraltar": 0.859, "Dover": 1.005, "Bosporus": 0.496}),
    "2026-03-20": (49.21, {
        "Hormuz": 0.025, "RedSea": 0.541, "Panama": 1.075, "Malacca": 1.042,
        "Taiwan": 1.008, "Gibraltar": 0.992, "Dover": 1.13, "Bosporus": 0.968}),
}


def _row(**overrides):
    row = {name: 1.0 for name in portwatch.CORRIDORS}
    row.update(overrides)
    return pd.Series(row)


def _baseline(value=100.0, names=PORT_NAMES):
    return {n: {str(m): value for m in range(1, 13)} for n in names}


def _daily(end, days, factors=None, base=100.0):
    """Daily frame in the shape fetch_chokepoint_daily returns, n_total = base * factor."""
    factors = factors or {}
    rows = []
    for i in range(days):
        d = pd.Timestamp(end - timedelta(days=days - 1 - i))
        for name in PORT_NAMES:
            rows.append({"date": d, "portid": portwatch.PORTIDS[name],
                         "n_total": base * factors.get(name, 1.0), "capacity": 1.0})
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def no_cache():
    with mock.patch.object(portwatch, "get_cached", return_value=None), \
         mock.patch.object(portwatch, "set_cached"):
        yield


@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {
        "chokepoint_weights": WEIGHTS, "chokepoint_baseline": _baseline()})


def test_corridors_and_portids():
    assert portwatch.CORRIDORS == ["Malacca", "Taiwan", "Gibraltar", "Hormuz",
                                   "Dover", "RedSea", "Bosporus", "Panama"]
    assert portwatch.PORTIDS["Dover"] == "chokepoint9"
    assert portwatch.PORTIDS["Bosporus"] == "chokepoint3"
    assert portwatch.PORTIDS["Hormuz"] == "chokepoint6"
    assert set(portwatch.PORTIDS) == {"Hormuz", "BabM", "Suez", "Panama", "Malacca",
                                      "Taiwan", "Gibraltar", "Dover", "Bosporus", "Cape"}


def test_score_all_normal_is_100():
    assert portwatch.chokepoint_score(_row(), WEIGHTS) == 100.0


def test_score_deadband():
    row = pd.Series({name: 0.9 for name in portwatch.CORRIDORS})
    assert portwatch.chokepoint_score(row, WEIGHTS) == pytest.approx(100.0)


def test_score_hormuz_closed():
    expected = 100 - 300 * 0.13038920936378975 * (1 - 0.04 / 0.9)
    score = portwatch.chokepoint_score(_row(Hormuz=0.04), WEIGHTS)
    assert score == pytest.approx(expected, abs=0.1)
    assert score == pytest.approx(62.6, abs=0.1)


def test_score_clips_to_zero_and_ignores_surplus():
    assert portwatch.chokepoint_score(_row(**{n: 0.0 for n in WEIGHTS}), WEIGHTS) == 0.0
    # Traffic above normal never lifts the score over 100 or offsets another corridor.
    assert portwatch.chokepoint_score(_row(Malacca=2.0, Hormuz=0.04), WEIGHTS) == pytest.approx(
        portwatch.chokepoint_score(_row(Hormuz=0.04), WEIGHTS))


def test_score_nan_corridor_gives_nan():
    assert math.isnan(portwatch.chokepoint_score(_row(Dover=np.nan), WEIGHTS))
    assert math.isnan(portwatch.chokepoint_score(_row().drop("Dover"), WEIGHTS))


@pytest.mark.parametrize("day", sorted(RESEARCH_ROWS))
def test_research_backtest_today(day):
    expected, ratios = RESEARCH_ROWS[day]
    assert portwatch.chokepoint_score(pd.Series(ratios), WEIGHTS) == pytest.approx(expected, abs=0.5)


def test_red_sea_takes_worse_of_bab_and_suez():
    daily = _daily(date(2026, 10, 18), 10, {"BabM": 0.5, "Suez": 0.8})
    daily = daily[daily.portid.isin([portwatch.PORTIDS["BabM"], portwatch.PORTIDS["Suez"]])]
    ratios = portwatch.corridor_ratios(daily, _baseline())
    last = ratios.iloc[-1]
    assert last["RedSea"] == pytest.approx(0.5)
    assert last["BabM"] == pytest.approx(0.5) and last["Suez"] == pytest.approx(0.8)
    assert list(ratios.columns) == ALL_NAMES
    assert ratios["Hormuz"].isna().all()


def test_ratio_is_seven_day_mean_over_same_month_baseline():
    # Hormuz drops from 100 to 50 transits per day on the last day only.
    daily = _daily(date(2026, 10, 18), 10)
    mask = (daily.portid == portwatch.PORTIDS["Hormuz"]) & (daily.date == pd.Timestamp("2026-10-18"))
    daily.loc[mask, "n_total"] = 50.0
    baseline = _baseline()
    baseline["Hormuz"]["10"] = 200.0  # a different month must not leak in
    baseline["Hormuz"]["9"] = 1.0
    ratios = portwatch.corridor_ratios(daily, baseline)
    # mean of last 7 days = (6*100 + 50) / 7 over the October baseline of 200.
    assert ratios.loc["2026-10-18", "Hormuz"] == pytest.approx((6 * 100 + 50) / 7 / 200.0)
    # Fewer than 7 observed days gives NaN, never a partial-window ratio.
    assert ratios.loc[:"2026-10-11", "Hormuz"].isna().all()


def test_ratio_missing_day_breaks_the_window():
    daily = _daily(date(2026, 10, 18), 12)
    daily = daily[~((daily.portid == portwatch.PORTIDS["Dover"]) & (daily.date == pd.Timestamp("2026-10-16")))]
    ratios = portwatch.corridor_ratios(daily, _baseline())
    assert math.isnan(ratios.loc["2026-10-18", "Dover"])
    assert ratios.loc["2026-10-18", "Malacca"] == pytest.approx(1.0)


def test_zero_or_missing_baseline_gives_nan_not_inf():
    baseline = _baseline()
    baseline["Panama"] = {str(m): 0.0 for m in range(1, 13)}
    del baseline["Taiwan"]
    ratios = portwatch.corridor_ratios(_daily(date(2026, 10, 18), 10), baseline)
    assert ratios["Panama"].isna().all() and ratios["Taiwan"].isna().all()


def test_fetch_chokepoint_daily_pages_and_shapes():
    ids = list(portwatch.PORTIDS.values())
    pages = [
        [{"date": "2026-10-17", "portid": ids[0], "n_total": 5, "capacity": 10},
         {"date": "2026-10-18", "portid": ids[0], "n_total": 6, "capacity": None}],
        [{"date": "2026-10-18", "portid": ids[1], "n_total": 7, "capacity": 12},
         {"date": "2026-10-18", "portid": "chokepoint99", "n_total": 1, "capacity": 1}],
        [],
    ]
    calls = []

    def fake_query(where, fields, order=None, count=2000, offset=0):
        calls.append((count, offset))
        return pages[len(calls) - 1]

    with mock.patch.object(portwatch, "_query", side_effect=fake_query), \
         mock.patch.object(portwatch, "_PAGE_SIZE", 2):
        df = portwatch.fetch_chokepoint_daily(date(2026, 10, 1))
    assert calls == [(2, 0), (2, 2), (2, 4)]
    assert list(df.columns) == ["date", "portid", "n_total", "capacity"]
    assert len(df) == 3  # unknown portid dropped
    assert df["date"].iloc[0] == pd.Timestamp("2026-10-17")
    assert df["n_total"].tolist() == [5, 6, 7]


def test_fetch_chokepoint_daily_cache_reused_only_if_it_covers_start():
    cached = {"start": "2026-09-01", "rows": [
        {"date": "2026-10-18", "portid": "chokepoint6", "n_total": 3, "capacity": 4}]}
    with mock.patch.object(portwatch, "get_cached", return_value=cached) as gc, \
         mock.patch.object(portwatch, "_query") as q:
        df = portwatch.fetch_chokepoint_daily(date(2026, 9, 15))
        assert gc.call_args.args[0] == "portwatch_daily_v1"
        assert gc.call_args.kwargs["ttl"] == 6 * 3600
        q.assert_not_called()
        assert len(df) == 1
        q.return_value = []
        portwatch.fetch_chokepoint_daily(date(2026, 8, 1))
        q.assert_called()


def test_empty_feature_list_raises(anchors):
    with mock.patch.object(portwatch, "_query", return_value=[]):
        with pytest.raises(RuntimeError):
            ChokepointsProvider().fetch_current()


def test_reshaped_payload_raises(anchors):
    rows = [{"day": "2026-10-18", "port": "chokepoint6", "count": 3}] * 5
    with mock.patch.object(portwatch, "_query", side_effect=[rows, []]):
        with pytest.raises(RuntimeError):
            ChokepointsProvider().fetch_current()


def test_all_null_transits_raise(anchors):
    rows = [{"date": "2026-10-18", "portid": "chokepoint6", "n_total": None, "capacity": None}] * 5
    with mock.patch.object(portwatch, "_query", side_effect=[rows, []]):
        with pytest.raises(RuntimeError):
            ChokepointsProvider().fetch_current()


@pytest.mark.parametrize("weights,baseline", [
    (None, _baseline()), (WEIGHTS, None), ({}, _baseline()), (WEIGHTS, {})])
def test_missing_anchor_raises(monkeypatch, weights, baseline):
    anchors = {}
    if weights is not None:
        anchors["chokepoint_weights"] = weights
    if baseline is not None:
        anchors["chokepoint_baseline"] = baseline
    monkeypatch.setattr(config, "SCORE_ANCHORS", anchors)
    with mock.patch.object(portwatch, "fetch_chokepoint_daily") as fetch:
        with pytest.raises(RuntimeError, match="no anchor for chokepoint_flow"):
            ChokepointsProvider().fetch_current()
        fetch.assert_not_called()


def _provider_with(daily, today=date(2026, 10, 22)):
    return mock.patch.object(portwatch, "fetch_chokepoint_daily", return_value=daily), \
        mock.patch("data.providers.chokepoints._today", return_value=today)


def test_fetch_current_score_and_metadata(anchors):
    factors = {"Hormuz": 0.04, "BabM": 0.35, "Suez": 0.6, "Bosporus": 0.5, "Cape": 1.8}
    a, b = _provider_with(_daily(date(2026, 10, 18), 20, factors))
    with a, b:
        score, meta = ChokepointsProvider().fetch_current()
    expected = portwatch.chokepoint_score(
        pd.Series({**{n: 1.0 for n in portwatch.CORRIDORS},
                   "Hormuz": 0.04, "RedSea": 0.35, "Bosporus": 0.5}), WEIGHTS)
    assert score == pytest.approx(expected, abs=0.05)
    assert meta["as_of"] == "2026-10-18"
    assert meta["is_stale"] is False
    assert meta["raw_value"].startswith("Hormuz 4% · Red Sea 35% · Bosporus 50%")
    assert meta["source"] == "IMF PortWatch"
    assert "Sources: UN Global Platform; IMF PortWatch" in meta["description"]
    assert "Cape of Good Hope" in meta["description"] and "180%" in meta["description"]
    for key in ("raw_label", "calculation", "updated"):
        assert meta[key]
    assert [i["name"] for i in meta["inputs"]] == ["chokepoint_flow"]
    assert meta["inputs"][0]["as_of"] == "2026-10-18" and meta["inputs"][0]["status"] == "live"
    assert meta["inputs"][0]["score"] == pytest.approx(score)


def test_fetch_current_flags_stale_input(anchors):
    a, b = _provider_with(_daily(date(2026, 10, 18), 20), today=date(2026, 11, 10))  # 23 days old
    with a, b:
        score, meta = ChokepointsProvider().fetch_current()
    assert score == 100.0 and meta["is_stale"] is True
    assert meta["inputs"][0]["status"] == "stale"


def test_fetch_current_dropped_when_too_old(anchors):
    a, b = _provider_with(_daily(date(2026, 10, 18), 20), today=date(2026, 12, 15))  # 58 days old
    with a, b, pytest.raises(RuntimeError):
        ChokepointsProvider().fetch_current()


def test_fetch_current_uses_last_complete_day(anchors):
    daily = _daily(date(2026, 10, 18), 20)
    # The newest day only has one corridor reported so far.
    partial = daily[(daily.date < pd.Timestamp("2026-10-18")) | (daily.portid == "chokepoint6")]
    a, b = _provider_with(partial)
    with a, b:
        _, meta = ChokepointsProvider().fetch_current()
    assert meta["as_of"] == "2026-10-17"


def test_fetch_history_dates_by_publication_lag(anchors):
    daily = _daily(date(2026, 10, 18), 30)
    daily.loc[(daily.portid == "chokepoint6") & (daily.date >= pd.Timestamp("2026-10-10")), "n_total"] = 4.0
    a, b = _provider_with(daily)
    with a, b:
        hist = ChokepointsProvider().fetch_history(10)
    lag = config.PUBLICATION_LAG_DAYS["chokepoint_flow"]
    assert isinstance(hist.index, pd.DatetimeIndex)
    assert hist.index.max() == pd.Timestamp(date(2026, 10, 18) + timedelta(days=lag))
    assert hist.notna().all()
    assert hist.index.is_monotonic_increasing
    # Only days with a full 7-day window and every corridor reported are included.
    assert hist.index.min() >= pd.Timestamp("2026-10-22") - pd.Timedelta(days=10)
    assert hist.iloc[0] == pytest.approx(100.0) and hist.iloc[-1] < 100.0


def test_fetch_history_empty_raises(anchors):
    a, b = _provider_with(pd.DataFrame(columns=["date", "portid", "n_total", "capacity"]))
    with a, b, pytest.raises(RuntimeError):
        ChokepointsProvider().fetch_history(30)
