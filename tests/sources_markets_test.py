"""Offline tests for guarded Yahoo live scaling and the full-history FRED fetch."""
from datetime import date
from unittest import mock

import pytest

from data.providers import fred_client
from data.sources import markets


def _scale(last, close, official_date=date(2026, 10, 20), **kw):
    with mock.patch.object(markets, "last_quote", **last), \
         mock.patch.object(markets, "close_on", **close):
        return markets.scale_live(100.0, official_date, "BZ=F", **kw)


def test_scale_live_applies_ratio():
    out = _scale({"return_value": (date(2026, 10, 22), 99.0)}, {"return_value": 90.0})
    assert out == (pytest.approx(110.0), date(2026, 10, 22), "live")


def test_scale_live_unit_factor_cancels_in_ratio():
    out = _scale({"return_value": (date(2026, 10, 22), 99.0)}, {"return_value": 90.0}, unit_factor=3.5)
    assert out[0] == pytest.approx(110.0) and out[2] == "live"


def test_scale_live_rejects_stale_quote():
    out = _scale({"return_value": (date(2026, 10, 19), 99.0)}, {"return_value": 90.0})
    assert out == (100.0, date(2026, 10, 20), "official")


def test_scale_live_rejects_wild_ratio():
    out = _scale({"return_value": (date(2026, 10, 22), 30.0)}, {"return_value": 10.0})
    assert out == (100.0, date(2026, 10, 20), "official")


def test_scale_live_rejects_missing_close():
    out = _scale({"return_value": (date(2026, 10, 22), 99.0)}, {"return_value": None})
    assert out == (100.0, date(2026, 10, 20), "official")


def test_scale_live_rejects_non_positive_or_non_finite_quotes():
    for last, close in [(0.0, 90.0), (99.0, 0.0), (float("nan"), 90.0), (99.0, float("inf"))]:
        out = _scale({"return_value": (date(2026, 10, 22), last)}, {"return_value": close})
        assert out[2] == "official"


def test_scale_live_survives_yfinance_error():
    out = _scale({"side_effect": RuntimeError("yahoo down")}, {"return_value": 90.0})
    assert out == (100.0, date(2026, 10, 20), "official")


def test_scale_live_survives_close_on_error():
    out = _scale({"return_value": (date(2026, 10, 22), 99.0)}, {"side_effect": ValueError("bad")})
    assert out == (100.0, date(2026, 10, 20), "official")


class _FakeTicker:
    def __init__(self, frame):
        self._frame = frame

    def history(self, **kwargs):
        return self._frame


def _frame(rows):
    import pandas as pd
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows])
    return pd.DataFrame({"Close": [c for _, c in rows]}, index=idx)


def test_last_quote_returns_latest_close():
    fake = _FakeTicker(_frame([("2026-10-20", 90.0), ("2026-10-21", 95.5)]))
    with mock.patch.object(markets, "_ticker", return_value=fake):
        assert markets.last_quote("BZ=F") == (date(2026, 10, 21), 95.5)


def test_last_quote_empty_raises():
    with mock.patch.object(markets, "_ticker", return_value=_FakeTicker(_frame([]))):
        with pytest.raises(ValueError):
            markets.last_quote("BZ=F")


def test_close_on_takes_latest_close_on_or_before_within_five_days():
    fake = _FakeTicker(_frame([("2026-10-14", 80.0), ("2026-10-16", 90.0), ("2026-10-21", 99.0)]))
    with mock.patch.object(markets, "_ticker", return_value=fake):
        assert markets.close_on("BZ=F", date(2026, 10, 18)) == 90.0
        assert markets.close_on("BZ=F", date(2026, 10, 16)) == 90.0
        assert markets.close_on("BZ=F", date(2026, 10, 12)) is None


def test_close_on_returns_none_when_no_data():
    with mock.patch.object(markets, "_ticker", return_value=_FakeTicker(_frame([]))):
        assert markets.close_on("BZ=F", date(2026, 10, 18)) is None


def _resp(text):
    r = mock.Mock()
    r.text = text
    r.raise_for_status = mock.Mock()
    return r


def test_fetch_fred_full_parses_dots():
    csv = "observation_date,X\n2020-01-01,1.5\n2020-02-01,.\n"
    with mock.patch.object(fred_client, "get_cached", return_value=None), \
         mock.patch.object(fred_client, "set_cached") as setc, \
         mock.patch.object(fred_client.requests, "get", return_value=_resp(csv)) as get:
        s = fred_client.fetch_fred_full("X")
    assert len(s) == 1 and s.iloc[0] == 1.5 and s.index[0].strftime("%Y-%m-%d") == "2020-01-01"
    assert get.call_args.args[0] == "https://fred.stlouisfed.org/graph/fredgraph.csv"
    assert get.call_args.kwargs["params"] == {"id": "X"}
    assert setc.call_args.args[0] == "fred_full_X_v1"


def test_fetch_fred_full_sorts_and_accepts_legacy_date_column():
    csv = "DATE,X\n2020-02-01,2.0\n2020-01-01,1.0\n"
    with mock.patch.object(fred_client, "get_cached", return_value=None), \
         mock.patch.object(fred_client, "set_cached"), \
         mock.patch.object(fred_client.requests, "get", return_value=_resp(csv)):
        s = fred_client.fetch_fred_full("X")
    assert s.tolist() == [1.0, 2.0] and s.index.is_monotonic_increasing


def test_fetch_fred_full_uses_cache():
    cached = {"dates": ["2020-01-01", "2020-02-01"], "values": [1.0, 2.0]}
    with mock.patch.object(fred_client, "get_cached", return_value=cached) as getc, \
         mock.patch.object(fred_client.requests, "get") as get:
        s = fred_client.fetch_fred_full("X", cache_ttl=123)
    get.assert_not_called()
    getc.assert_called_once_with("fred_full_X_v1", ttl=123)
    assert s.tolist() == [1.0, 2.0]


@pytest.mark.parametrize("csv", ["", "observation_date,Y\n2020-01-01,1\n", "observation_date,X\n2020-01-01,.\n"])
def test_fetch_fred_full_empty_or_reshaped_raises(csv):
    with mock.patch.object(fred_client, "get_cached", return_value=None), \
         mock.patch.object(fred_client, "set_cached") as setc, \
         mock.patch.object(fred_client.requests, "get", return_value=_resp(csv)):
        with pytest.raises(ValueError):
            fred_client.fetch_fred_full("X")
    setc.assert_not_called()
