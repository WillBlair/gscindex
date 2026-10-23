"""Offline tests for the Physical Disruption category (GDACS hazards, Gatun Lake, St. Louis)."""
from datetime import date, timedelta
from unittest import mock

import numpy as np
import pandas as pd
import pytest

import config
from data import database
from data.providers import physical
from data.providers.physical import PhysicalProvider
from data.sources import gdacs, waterways

TODAY = date(2026, 10, 22)

PORTS = [
    {"name": "Houston", "lat": 29.76, "lon": -95.37},
    {"name": "Rotterdam", "lat": 51.92, "lon": 4.48},
    {"name": "Shanghai", "lat": 31.23, "lon": 121.47},
]
SHARES = {"Houston": 0.05, "Rotterdam": 0.04, "Shanghai": 0.10}
RADIUS = {"TC": 450.0, "FL": 100.0, "EQ": 150.0, "VO": 50.0}

WATERWAY_ANCHORS = {"gatun_record_low": 78.0, "mississippi_record_low": -6.0,
                    "mississippi_threshold": 5.0}
ANCHORS = {"port_throughput_share": SHARES, "waterways": WATERWAY_ANCHORS}


@pytest.fixture(autouse=True)
def hazard_scale(monkeypatch):
    """The fixtures' shares and expected scores are worked out at a hazard scale of 1000."""
    monkeypatch.setattr(config, "HAZARD_SCALE", 1000.0)


def _event(kind="TC", alert="Red", lat=29.76, lon=-95.37, start="2026-10-20", end="2026-10-24", eid=1):
    return {"id": eid, "type": kind, "alert": alert, "lat": lat, "lon": lon,
            "name": f"{kind} {eid}", "from": start, "to": end}


# A trimmed real GDACS feature: the Red tropical cyclone CHAMPI-26 from the research sample.
RED_TC = {
    "type": "Feature", "bbox": [124.3, 21.9, 124.3, 21.9],
    "geometry": {"type": "Point", "coordinates": [124.3, 21.9]},
    "properties": {
        "eventtype": "TC", "eventid": 1001338, "episodeid": 34, "name": "Tropical Cyclone CHAMPI-26",
        "alertlevel": "Red", "fromdate": "2026-10-14T12:00:00", "todate": "2026-10-22T18:00:00",
    },
}


def _feature(kind="EQ", alert="Orange", lon=93.78, lat=32.38, eid=5, start="2026-10-22T14:33:40",
             end="2026-10-22T14:33:40"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"eventtype": kind, "eventid": eid, "name": f"{kind} event", "alertlevel": alert,
                           "fromdate": start, "todate": end}}


def _collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


# ------------------------------------------------------------------------------- hazard score

def test_hazard_red_typhoon_over_big_port():
    ports = [{"name": "Big", "lat": 22.0, "lon": 114.0}]
    event = _event("TC", "Red", lat=22.0, lon=114.0)
    score = gdacs.hazard_score([event], ports, {"Big": 0.05}, RADIUS)
    assert score == pytest.approx(50.0, abs=2.0)


def test_hazard_far_event_ignored():
    # About 2,000 km east of Houston.
    event = _event("TC", "Red", lat=29.76, lon=-74.0)
    assert gdacs.hazard_score([event], PORTS, SHARES, RADIUS) == 100.0


def test_hazard_orange_costs_half_of_red():
    red = gdacs.hazard_score([_event(alert="Red")], PORTS, SHARES, RADIUS)
    orange = gdacs.hazard_score([_event(alert="Orange")], PORTS, SHARES, RADIUS)
    assert (100 - orange) == pytest.approx((100 - red) / 2)


def test_hazard_radius_depends_on_event_type():
    # Houston is about 200 km from this point: inside a cyclone's 450 km, outside a flood's 100 km.
    lat = 29.76 + 200 / 111.2
    assert gdacs.hazard_score([_event("TC", lat=lat)], PORTS, SHARES, RADIUS) < 100.0
    assert gdacs.hazard_score([_event("FL", lat=lat)], PORTS, SHARES, RADIUS) == 100.0


def test_hazard_port_without_share_counts_zero():
    event = _event("TC", lat=51.92, lon=4.48)
    assert gdacs.hazard_score([event], PORTS, {"Houston": 0.05}, RADIUS) == 100.0


def test_hazard_sums_over_ports_and_events_and_clips_at_zero():
    ports = [{"name": "A", "lat": 10.0, "lon": 10.0}, {"name": "B", "lat": 10.5, "lon": 10.0}]
    shares = {"A": 0.03, "B": 0.02}
    one = gdacs.hazard_score([_event("TC", lat=10.0, lon=10.0)], ports, shares, RADIUS)
    assert one == pytest.approx(50.0)          # 1000 x (0.03 + 0.02) x 1.0
    two = gdacs.hazard_score([_event("TC", lat=10.0, lon=10.0, eid=1),
                              _event("TC", lat=10.0, lon=10.0, eid=2)], ports, shares, RADIUS)
    assert two == 0.0                          # 100 points would be below zero: clipped
    assert gdacs.hazard_score([], ports, shares, RADIUS) == 100.0


def test_red_typhoon_358_km_from_kaohsiung_registers():
    """CHAMPI-26 on 2026-10-22: centre (22.7, 123.8), 358 km from Kaohsiung, Red."""
    kaohsiung = [{"name": "Kaohsiung", "lat": 22.62, "lon": 120.31}]
    champi = _event("TC", alert="Red", lat=22.7, lon=123.8)
    score = gdacs.hazard_score([champi], kaohsiung, {"Kaohsiung": 0.01}, config.HAZARD_RADIUS_KM)
    assert score == pytest.approx(100.0 - config.HAZARD_SCALE * 0.01)
    assert gdacs.hazard_score([champi], kaohsiung, {"Kaohsiung": 0.01}, {"TC": 300.0}) == 100.0


def test_hazard_ignores_unknown_type_or_alert():
    odd = [_event("DR", "Red", lat=29.76, lon=-95.37), _event("TC", "Green", lat=29.76, lon=-95.37)]
    assert gdacs.hazard_score(odd, PORTS, SHARES, RADIUS) == 100.0


def test_active_on_covers_inclusive_range():
    events = [_event(start="2026-10-20", end="2026-10-22", eid=1),
              _event(start="2026-10-23", end="2026-10-25", eid=2)]
    assert [e["id"] for e in gdacs.active_on(events, date(2026, 10, 22))] == [1]
    assert [e["id"] for e in gdacs.active_on(events, date(2026, 10, 20))] == [1]
    assert gdacs.active_on(events, date(2026, 10, 26)) == []


# ------------------------------------------------------------------------------- gdacs parsing

def test_parse_events_keeps_orange_and_red_with_expected_keys():
    green = _feature("EQ", "Green", eid=9)
    events = gdacs.parse_events(_collection(RED_TC, _feature("EQ", "Orange"), green))
    assert [e["alert"] for e in events] == ["Red", "Orange"]
    tc = events[0]
    assert (tc["type"], tc["lat"], tc["lon"]) == ("TC", 21.9, 124.3)
    assert tc["from"] == "2026-10-14" and tc["to"] == "2026-10-22"
    assert tc["name"] == "Tropical Cyclone CHAMPI-26" and tc["id"] == 1001338


def test_parse_events_skips_unusable_features():
    no_coords = _feature(eid=6)
    no_coords["geometry"] = {"type": "Point", "coordinates": []}
    bad_date = _feature(eid=7, start="not a date")
    drought = _feature("DR", "Orange", eid=8)
    events = gdacs.parse_events(_collection(no_coords, bad_date, drought, RED_TC))
    assert [e["id"] for e in events] == [1001338]


@pytest.mark.parametrize("payload", [
    {}, [], "oops", {"features": "x"}, {"type": "FeatureCollection"},
    {"type": "FeatureCollection", "features": []},
    {"type": "FeatureCollection", "features": [{"geometry": None}, 3]},
])
def test_parse_events_empty_or_reshaped_payload_raises(payload):
    with pytest.raises(ValueError):
        gdacs.parse_events(payload)


def test_parse_events_empty_allowed_for_short_window():
    assert gdacs.parse_events(_collection(), allow_empty=True) == []


# ------------------------------------------------------------------------------- gdacs fetch

def _resp(payload, status=200, text=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = payload
    resp.text = text if text is not None else "{}"
    return resp


@pytest.fixture
def no_cache():
    with mock.patch.object(gdacs, "get_cached", return_value=None), \
         mock.patch.object(gdacs, "set_cached") as save:
        yield save


def test_gdacs_url_and_params(no_cache):
    with mock.patch.object(gdacs.requests, "get", return_value=_resp(_collection(RED_TC))) as get:
        gdacs.fetch_events(date(2026, 10, 1), TODAY, today=TODAY)
    assert get.call_args.args[0] == "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
    params = get.call_args.kwargs["params"]
    assert params["alertlevel"] == "Orange;Red"
    assert params["eventlist"] == "TC;FL;EQ;VO"
    assert params["todate"] == "2026-10-22"


def test_gdacs_chunks_are_at_most_six_months(no_cache):
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append((params["fromdate"], params["todate"]))
        return _resp(_collection(_feature(eid=len(calls))))

    with mock.patch.object(gdacs.requests, "get", side_effect=fake_get):
        events = gdacs.fetch_events(date(2025, 11, 15), TODAY, today=TODAY)
    assert calls == [("2025-07-01", "2025-12-31"), ("2026-01-01", "2026-06-30"), ("2026-07-01", "2026-10-22")]
    for start, end in calls:
        assert (date.fromisoformat(end) - date.fromisoformat(start)).days <= 184
    assert len(events) == 3


def test_gdacs_dedupes_events_across_chunks(no_cache):
    spanning = _feature("TC", "Red", eid=77, start="2026-06-25T00:00:00", end="2026-07-05T00:00:00")
    with mock.patch.object(gdacs.requests, "get", return_value=_resp(_collection(spanning))):
        events = gdacs.fetch_events(date(2026, 6, 20), date(2026, 7, 10), today=TODAY)
    assert [e["id"] for e in events] == [77]


def test_gdacs_cache_ttls_and_keys(no_cache):
    with mock.patch.object(gdacs.requests, "get", return_value=_resp(_collection(RED_TC))), \
         mock.patch.object(gdacs, "get_cached", return_value=None) as get_cached:
        gdacs.fetch_events(date(2026, 4, 1), TODAY, today=TODAY)
    ttls = {c.args[0]: c.kwargs.get("ttl") for c in get_cached.call_args_list}
    current = [k for k in ttls if k.startswith("gdacs_events_v1") and k.endswith("2026H2")]
    past = [k for k in ttls if k.endswith("2026H1")]
    assert ttls[current[0]] == 6 * 3600
    assert ttls[past[0]] == gdacs.PAST_CHUNK_TTL and gdacs.PAST_CHUNK_TTL > 6 * 3600
    assert all(k.startswith("gdacs_events_v1") for k in ttls)


def test_gdacs_uses_cached_chunk_without_a_request():
    cached = [_event(eid=3)]
    with mock.patch.object(gdacs, "get_cached", return_value=cached), \
         mock.patch.object(gdacs.requests, "get") as get:
        events = gdacs.fetch_events(date(2026, 10, 1), TODAY, today=TODAY)
    get.assert_not_called()
    assert events == cached


def test_gdacs_boundary_event_keeps_the_record_that_ends_later(no_cache):
    old = _feature("FL", "Red", eid=88, start="2026-06-20T00:00:00", end="2026-06-30T00:00:00")
    new = _feature("FL", "Red", eid=88, start="2026-06-20T00:00:00", end="2026-07-08T00:00:00")
    answers = iter([_resp(_collection(old)), _resp(_collection(new))])
    with mock.patch.object(gdacs.requests, "get", side_effect=lambda *a, **k: next(answers)):
        events = gdacs.fetch_events(date(2026, 6, 15), date(2026, 7, 10), today=TODAY)
    assert [e["to"] for e in events] == ["2026-07-08"]
    assert gdacs.active_on(events, date(2026, 7, 5)) == events
    # Same result when the chunks are merged in the opposite order of freshness.
    answers = iter([_resp(_collection(new)), _resp(_collection(old))])
    with mock.patch.object(gdacs.requests, "get", side_effect=lambda *a, **k: next(answers)):
        events = gdacs.fetch_events(date(2026, 6, 15), date(2026, 7, 10), today=TODAY)
    assert [e["to"] for e in events] == ["2026-07-08"]


def test_gdacs_empty_long_chunk_raises_and_is_not_cached(no_cache):
    with mock.patch.object(gdacs.requests, "get", return_value=_resp(_collection())):
        with pytest.raises(ValueError):
            gdacs.fetch_events(date(2026, 4, 1), TODAY, today=TODAY)
    no_cache.assert_not_called()


def test_gdacs_blank_body_for_a_short_chunk_is_no_events(no_cache):
    # GDACS answers a window with no events with an empty body, not an empty collection.
    resp = _resp(None, text="")
    resp.json.side_effect = ValueError("no json")
    with mock.patch.object(gdacs.requests, "get", return_value=resp):
        # Two days into a half-year the aligned chunk is short, so no events is believable.
        assert gdacs.fetch_events(date(2026, 7, 1), date(2026, 7, 2), today=date(2026, 7, 2)) == []


def test_gdacs_blank_body_result_is_cached(no_cache):
    resp = _resp(None, text="")
    resp.json.side_effect = ValueError("no json")
    today = date(2026, 7, 2)
    with mock.patch.object(gdacs.requests, "get", return_value=resp):
        gdacs.fetch_events(date(2026, 7, 1), date(2026, 7, 2), today=today)
    assert no_cache.call_args.args == ("gdacs_events_v1_2026H2", [])
    # The cached empty list is served without another request.
    with mock.patch.object(gdacs, "get_cached", return_value=[]), \
         mock.patch.object(gdacs.requests, "get") as get:
        assert gdacs.fetch_events(date(2026, 7, 1), date(2026, 7, 2), today=today) == []
    get.assert_not_called()


def test_gdacs_http_error_raises(no_cache):
    resp = _resp(None)
    resp.raise_for_status.side_effect = RuntimeError("503")
    with mock.patch.object(gdacs.requests, "get", return_value=resp):
        with pytest.raises(RuntimeError):
            gdacs.fetch_events(date(2026, 10, 1), TODAY, today=TODAY)


# ------------------------------------------------------------------------------- scores

def test_gatun_score():
    assert waterways.gatun_score(86.0, 78.0) == 100.0
    assert waterways.gatun_score(85.0, 78.0) == 100.0
    assert waterways.gatun_score(81.5, 78.0) == pytest.approx(50.0)
    assert waterways.gatun_score(78.0, 78.0) == 0.0
    assert waterways.gatun_score(70.0, 78.0) == 0.0


def test_river_score():
    assert waterways.river_score(9.0, 5.0, -6.0) == 100.0
    assert waterways.river_score(-0.5, 5.0, -6.0) == pytest.approx(50.0)
    assert waterways.river_score(-6.0, 5.0, -6.0) == 0.0
    assert waterways.river_score(-8.0, 5.0, -6.0) == 0.0


def test_scores_reject_degenerate_anchors_and_non_finite_input():
    with pytest.raises(ValueError):
        waterways.gatun_score(80.0, 85.0)            # record low not below the full-draft level
    with pytest.raises(ValueError):
        waterways.river_score(1.0, -6.0, -6.0)
    with pytest.raises(ValueError):
        waterways.gatun_score(float("nan"), 78.0)


# ------------------------------------------------------------------------------- waterways sources

GATUN_CSV = "DATE_LOG,GATUN_LAKE_LEVEL(FEET)\n2026-10-19,86.00\n2026-10-20,86.20\n2026-10-21,86.24\n"


def test_parse_gatun_csv():
    s = waterways.parse_gatun_csv(GATUN_CSV)
    assert s.index.tolist() == [pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20"),
                                pd.Timestamp("2026-10-21")]
    assert s.tolist() == [86.0, 86.2, 86.24]


@pytest.mark.parametrize("text", [
    "", "DATE_LOG,GATUN_LAKE_LEVEL(FEET)\n", "<html>maintenance</html>",
    "DATE,LEVEL\n2026-10-21,86.0\n",
    "DATE_LOG,GATUN_LAKE_LEVEL(FEET)\n2026-10-21,n/a\n",
    "DATE_LOG,GATUN_LAKE_LEVEL(FEET)\n2026-10-21,26.2\n",   # metres: outside the plausible feet range
])
def test_parse_gatun_csv_empty_or_reshaped_raises(text):
    with pytest.raises(ValueError):
        waterways.parse_gatun_csv(text)


def _usgs(values, code="00065", no_data="-999999.0"):
    return {"value": {"timeSeries": [{
        "variable": {"variableCode": [{"value": code}], "noDataValue": float(no_data)},
        "values": [{"value": [{"value": v, "qualifiers": ["P"], "dateTime": f"{d}T00:00:00.000"}
                              for d, v in values]}],
    }]}}


def test_parse_usgs_daily_gauge_height():
    payload = _usgs([("2026-10-20", "8.64"), ("2026-10-21", "8.30"), ("2026-10-22", "8.22")])
    s = waterways.parse_usgs_daily(payload)
    assert s.index[-1] == pd.Timestamp("2026-10-22")
    assert s.tolist() == [8.64, 8.30, 8.22]


def test_parse_usgs_drops_no_data_values():
    s = waterways.parse_usgs_daily(_usgs([("2026-10-20", "-999999"), ("2026-10-21", "8.3")]))
    assert s.tolist() == [8.3]


@pytest.mark.parametrize("payload", [
    {}, [], {"value": {}}, {"value": {"timeSeries": []}},
    _usgs([]), _usgs([("2026-10-21", "-999999")]), _usgs([("2026-10-21", "ice")]),
    _usgs([("2026-10-21", "171000")], code="00060"),     # discharge, not gauge height
    _usgs([("2026-10-21", "880")]),                       # inches or cm: outside the plausible feet range
])
def test_parse_usgs_empty_or_reshaped_raises(payload):
    with pytest.raises(ValueError):
        waterways.parse_usgs_daily(payload)


def test_kaub_parse():
    payload = {"shortname": "W", "unit": "cm",
               "currentMeasurement": {"timestamp": "2026-10-23T04:00:00+02:00", "value": 27.0}}
    assert waterways.parse_kaub(payload) == (date(2026, 10, 23), 27.0)


def test_kaub_missing_unit_raises():
    with pytest.raises(ValueError):
        waterways.parse_kaub({"currentMeasurement": {"timestamp": "2026-10-23T04:00:00+02:00",
                                                     "value": 27.0}})


@pytest.mark.parametrize("payload", [
    {}, [], {"currentMeasurement": None}, {"currentMeasurement": {"timestamp": "x", "value": 1}},
    {"currentMeasurement": {"timestamp": "2026-10-23T04:00:00+02:00", "value": None}},
    {"currentMeasurement": {"timestamp": "2026-10-23T04:00:00+02:00", "value": "high"}},
    {"unit": "m", "currentMeasurement": {"timestamp": "2026-10-23T04:00:00+02:00", "value": 0.27}},
])
def test_kaub_empty_or_reshaped_raises(payload):
    with pytest.raises(ValueError):
        waterways.parse_kaub(payload)


@pytest.fixture
def no_wcache():
    with mock.patch.object(waterways, "get_cached", return_value=None), \
         mock.patch.object(waterways, "set_cached") as save:
        yield save


def test_fetch_gatun_url_and_cache(no_wcache):
    resp = mock.Mock(text=GATUN_CSV)
    resp.raise_for_status = mock.Mock()
    with mock.patch.object(waterways.requests, "get", return_value=resp) as get:
        s = waterways.fetch_gatun()
    assert get.call_args.args[0] == ("https://evtms-rpts.pancanal.com/eng/h2o/"
                                     "Download_Gatun_Lake_Water_Level_History.csv")
    assert s.iloc[-1] == 86.24
    assert no_wcache.call_args.args[0] == "gatun_levels_v1"


def test_fetch_gatun_bad_payload_not_cached(no_wcache):
    resp = mock.Mock(text="<html></html>")
    resp.raise_for_status = mock.Mock()
    with mock.patch.object(waterways.requests, "get", return_value=resp):
        with pytest.raises(ValueError):
            waterways.fetch_gatun()
    no_wcache.assert_not_called()


def test_fetch_mississippi_url_params_and_no_stat_code(no_wcache):
    payload = _usgs([("2026-10-21", "8.30"), ("2026-10-22", "8.22")])
    with mock.patch.object(waterways.requests, "get", return_value=_resp(payload)) as get:
        s = waterways.fetch_mississippi_stl(start=date(2026, 10, 1))
    assert get.call_args.args[0] == "https://waterservices.usgs.gov/nwis/dv/"
    params = get.call_args.kwargs["params"]
    assert params["sites"] == "07010000" and params["parameterCd"] == "00065"
    assert params["startDT"] == "2026-10-01" and params["format"] == "json"
    # St. Louis publishes daily gauge height under its own statistic code, so none is requested.
    assert "statCd" not in params
    assert s.iloc[-1] == 8.22


def test_fetch_kaub_latest_url():
    payload = {"unit": "cm", "currentMeasurement": {"timestamp": "2026-10-23T04:00:00+02:00", "value": 27.0}}
    with mock.patch.object(waterways.requests, "get", return_value=_resp(payload)) as get:
        assert waterways.fetch_kaub_latest() == (date(2026, 10, 23), 27.0)
    assert get.call_args.args[0] == ("https://www.pegelonline.wsv.de/webservices/rest-api/v2/"
                                     "stations/KAUB/W.json")
    assert get.call_args.kwargs["params"] == {"includeCurrentMeasurement": "true"}


# ------------------------------------------------------------------------------- database

@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("sqlite", None))
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "gauges.db"))
    database.init_db()
    return database.SQLITE_PATH


def test_gauge_readings_upsert_round_trip(sqlite_db):
    database.upsert_gauge_reading(date(2026, 10, 23), "kaub", 27.0)
    database.upsert_gauge_reading(date(2026, 10, 23), "kaub", 29.0)      # same key: replaced
    database.upsert_gauge_reading(date(2026, 10, 24), "kaub", 31.0)
    conn = database.get_connection()
    rows = conn.execute("SELECT date, gauge, value FROM gauge_readings ORDER BY date").fetchall()
    conn.close()
    assert rows == [("2026-10-23", "kaub", 29.0), ("2026-10-24", "kaub", 31.0)]


def test_gauge_readings_primary_key_is_date_and_gauge(sqlite_db):
    database.upsert_gauge_reading(date(2026, 10, 23), "kaub", 27.0)
    database.upsert_gauge_reading(date(2026, 10, 23), "other", 5.0)
    conn = database.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM gauge_readings").fetchone()[0]
    conn.close()
    assert count == 2


def test_gauge_upsert_is_a_no_op_without_a_database(monkeypatch):
    monkeypatch.setattr(database, "get_connection", lambda: None)
    database.upsert_gauge_reading(date(2026, 10, 23), "kaub", 27.0)       # does not raise


# ------------------------------------------------------------------------------- provider

@pytest.fixture
def anchors(monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", ANCHORS)
    monkeypatch.setattr(physical, "_today", lambda: TODAY)
    monkeypatch.setattr(physical, "MAJOR_PORTS", [(p["name"], p["lat"], p["lon"], []) for p in PORTS])


def _gatun_series(level=86.0, last=TODAY - timedelta(days=1), days=40):
    return pd.Series(level, index=pd.date_range(end=pd.Timestamp(last), periods=days, freq="D"))


def _river_series(stage=9.0, last=TODAY, days=40):
    return pd.Series(stage, index=pd.date_range(end=pd.Timestamp(last), periods=days, freq="D"))


def _run(fn, events=None, gatun=None, river=None, kaub=(date(2026, 10, 22), 27.0), upsert=None,
         kaub_marker=None, kaub_cache=None):
    """Run ``fn`` with every source patched; a source passed as None fails.

    ``kaub_marker`` is what the Kaub throttle cache returns (None: due); ``kaub_cache``
    receives the marker writes.
    """
    def fail(name):
        def _raise(*a, **k):
            raise ValueError(f"{name} unavailable")
        return _raise

    def returning(value):
        return lambda *a, **k: value

    upsert = upsert if upsert is not None else mock.Mock()
    with mock.patch.object(physical.gdacs, "fetch_events",
                           side_effect=returning(events) if events is not None else fail("gdacs")), \
         mock.patch.object(physical.waterways, "fetch_gatun",
                           side_effect=returning(gatun) if gatun is not None else fail("gatun")), \
         mock.patch.object(physical.waterways, "fetch_mississippi_stl",
                           side_effect=returning(river) if river is not None else fail("stl")), \
         mock.patch.object(physical.waterways, "fetch_kaub_latest",
                           side_effect=returning(kaub) if kaub is not None else fail("kaub")), \
         mock.patch.object(physical.database, "upsert_gauge_reading", upsert), \
         mock.patch.object(physical, "get_cached", return_value=kaub_marker), \
         mock.patch.object(physical, "set_cached", kaub_cache if kaub_cache is not None else mock.Mock()):
        return fn()


def test_physical_all_clear_scores_100(anchors):
    score, meta = _run(PhysicalProvider().fetch_current, events=[_event(lat=0, lon=-30)],
                       gatun=_gatun_series(86.0), river=_river_series(9.0))
    assert score == 100.0
    assert meta["is_stale"] is False and meta["as_of"] == "2026-10-21"    # the Gatun file ends yesterday
    assert [i["name"] for i in meta["inputs"]] == ["hazards", "gatun", "mississippi"]
    assert all(i["status"] == "live" for i in meta["inputs"])


def test_physical_blends_with_config_weights(anchors):
    # Red typhoon over Houston: share 0.05 -> hazards 50. Gatun 81.5 (record low 78) -> 50.
    # St. Louis 9.0 above the threshold -> 100. 0.5 x 50 + 0.25 x 50 + 0.25 x 100 = 62.5.
    score, _ = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")],
                    gatun=_gatun_series(81.5), river=_river_series(9.0))
    assert score == pytest.approx(62.5, abs=0.1)


def test_physical_missing_gauges_uses_hazards_only(anchors):
    score, meta = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")])
    assert score == pytest.approx(50.0, abs=0.1)
    statuses = {i["name"]: i["status"] for i in meta["inputs"]}
    assert statuses == {"hazards": "live", "gatun": "missing", "mississippi": "missing"}


def test_physical_missing_hazards_uses_gauges(anchors):
    score, meta = _run(PhysicalProvider().fetch_current, gatun=_gatun_series(81.5), river=_river_series(9.0))
    assert score == pytest.approx(75.0, abs=0.1)         # (0.25 x 50 + 0.25 x 100) / 0.5
    assert {i["name"]: i["status"] for i in meta["inputs"]}["hazards"] == "missing"


def test_physical_all_inputs_missing_raises(anchors):
    with pytest.raises(RuntimeError):
        _run(PhysicalProvider().fetch_current)


def test_physical_asks_gdacs_relative_to_its_own_utc_today(anchors):
    with mock.patch.object(physical.gdacs, "fetch_events", return_value=[]) as fetch:
        PhysicalProvider()._hazards_reading(TODAY, SHARES)
    assert fetch.call_args.kwargs["today"] == TODAY
    assert fetch.call_args.args == (TODAY - timedelta(days=config.HAZARD_LOOKBACK_DAYS), TODAY)


def test_physical_events_not_covering_today_are_ignored(anchors):
    old = _event("TC", "Red", start="2026-09-01", end="2026-09-10")
    score, _ = _run(PhysicalProvider().fetch_current, events=[old])
    assert score == 100.0


def test_physical_waterway_reading_dates_and_staleness(anchors):
    gatun = _gatun_series(86.0, last=TODAY - timedelta(days=5))     # stale after 3 days
    river = _river_series(9.0, last=TODAY - timedelta(days=12))     # dropped after 9 days
    _, meta = _run(PhysicalProvider().fetch_current, events=[_event(lat=0, lon=-30)],
                   gatun=gatun, river=river)
    by_name = {i["name"]: i for i in meta["inputs"]}
    assert by_name["gatun"]["status"] == "stale" and by_name["gatun"]["as_of"] == "2026-10-17"
    assert by_name["mississippi"]["status"] == "missing"
    assert meta["is_stale"] is True
    assert meta["as_of"] == "2026-10-17"          # oldest input used


def test_physical_non_finite_latest_waterway_value_is_missing(anchors):
    gatun = _gatun_series(86.0)
    gatun.iloc[-1] = np.nan
    score, meta = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")], gatun=gatun)
    by_name = {i["name"]: i for i in meta["inputs"]}
    # The latest finite reading is the day before; it is still used.
    assert by_name["gatun"]["as_of"] == "2026-10-20"
    only_nan = pd.Series([np.nan], index=pd.DatetimeIndex([TODAY]))
    _, meta = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")], gatun=only_nan)
    assert {i["name"]: i["status"] for i in meta["inputs"]}["gatun"] == "missing"


def test_physical_metadata_contract(anchors):
    _, meta = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")],
                   gatun=_gatun_series(86.0), river=_river_series(9.0))
    for key in ("source", "raw_value", "raw_label", "description", "calculation", "updated",
                "as_of", "is_stale", "inputs"):
        assert key in meta
    assert "GDACS" in meta["source"] and "Gatun" in meta["source"]
    assert "St. Louis" in meta["source"]


def test_physical_raw_label_matches_the_inputs_used(anchors):
    _, meta = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")])
    assert meta["raw_label"] == "Active hazard alerts"
    assert len(meta["raw_value"].split(" / ")) == len(meta["raw_label"].split("; ")) == 1
    _, meta = _run(PhysicalProvider().fetch_current, gatun=_gatun_series(86.0), river=_river_series(9.0))
    assert meta["raw_label"] == "Gatun Lake level (ft); St. Louis stage (ft)"
    assert len(meta["raw_value"].split(" / ")) == 2
    _, meta = _run(PhysicalProvider().fetch_current, events=[_event(lat=0, lon=-30)],
                   gatun=_gatun_series(86.0), river=_river_series(9.0))
    assert meta["raw_label"] == "Active hazard alerts; Gatun Lake level (ft); St. Louis stage (ft)"


def test_physical_upserts_kaub_when_due_and_never_scores_it(anchors):
    upsert = mock.Mock()
    score, meta = _run(PhysicalProvider().fetch_current, events=[_event(lat=0, lon=-30)],
                       gatun=_gatun_series(86.0), river=_river_series(9.0),
                       kaub=(date(2026, 10, 22), 27.0), upsert=upsert)
    upsert.assert_called_once_with(date(2026, 10, 22), "kaub", 27.0)
    assert "kaub" not in [i["name"] for i in meta["inputs"]]
    assert score == 100.0


def test_physical_kaub_failure_is_swallowed(anchors):
    score, _ = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")], kaub=None)
    assert score == pytest.approx(50.0, abs=0.1)
    boom = mock.Mock(side_effect=RuntimeError("db down"))
    score, _ = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")], upsert=boom)
    assert score == pytest.approx(50.0, abs=0.1)


@pytest.mark.parametrize("missing", ["port_throughput_share", "waterways"])
def test_physical_missing_anchor_raises_clear_error(anchors, monkeypatch, missing):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {k: v for k, v in ANCHORS.items() if k != missing})
    with pytest.raises(RuntimeError, match=f"no anchor for {missing}"):
        _run(PhysicalProvider().fetch_current, events=[], gatun=_gatun_series(), river=_river_series())


def test_physical_missing_waterway_key_raises_clear_error(anchors, monkeypatch):
    partial = {"gatun_record_low": 78.0}
    monkeypatch.setattr(config, "SCORE_ANCHORS", {**ANCHORS, "waterways": partial})
    with pytest.raises(RuntimeError, match="no anchor for waterways"):
        _run(PhysicalProvider().fetch_current, events=[])


def test_physical_port_missing_from_shares_counts_zero(anchors, monkeypatch):
    monkeypatch.setattr(config, "SCORE_ANCHORS", {**ANCHORS, "port_throughput_share": {"Rotterdam": 0.04}})
    score, _ = _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")])   # Houston: no share
    assert score == 100.0


def test_physical_category_constants(monkeypatch):
    monkeypatch.undo()
    assert PhysicalProvider.category == "physical"
    assert config.CATEGORY_LABELS["physical"] == "Physical Disruption"
    assert config.PHYSICAL_WEIGHTS == {"hazards": 0.5, "gatun": 0.25, "mississippi": 0.25}
    assert config.GATUN_FULL_DRAFT_FT == 85.0
    assert config.HAZARD_RADIUS_KM == {"TC": 450, "FL": 100, "EQ": 150, "VO": 50}
    assert config.HAZARD_LEVEL_POINTS == {"Orange": 0.5, "Red": 1.0} and config.HAZARD_SCALE == 5000.0
    colors = list(config.CATEGORY_COLORS.values())
    assert config.CATEGORY_COLORS["physical"] and len(colors) == len(set(colors))


# ------------------------------------------------------------------------------- history

def test_physical_history_daily_scores_at_actual_dates(anchors):
    events = [_event("TC", "Red", start="2026-10-10", end="2026-10-12")]
    gatun = _gatun_series(86.0, last=TODAY - timedelta(days=1), days=8)       # starts 2026-10-15
    series = _run(lambda: PhysicalProvider().fetch_history(30), events=events, gatun=gatun)
    assert series.index[-1] == pd.Timestamp(TODAY) and len(series) == 30
    # Hazard-only days: the Red cyclone is active 10-10..10-12 (score 50), clear before and after.
    assert series[pd.Timestamp("2026-10-11")] == pytest.approx(50.0, abs=0.1)
    assert series[pd.Timestamp("2026-10-13")] == pytest.approx(100.0)
    assert series[pd.Timestamp("2026-10-20")] == pytest.approx(100.0)
    assert series.name == "physical"


def test_physical_history_keeps_leading_gap_without_hazards(anchors):
    gatun = _gatun_series(86.0, last=TODAY - timedelta(days=1), days=8)
    series = _run(lambda: PhysicalProvider().fetch_history(30), gatun=gatun)
    assert series[:pd.Timestamp("2026-10-13")].isna().all()          # before the first gauge reading
    assert series[pd.Timestamp("2026-10-16")] == 100.0


def test_physical_history_blends_with_weights(anchors):
    events = [_event("TC", "Red", start="2026-10-20", end="2026-10-22")]
    series = _run(lambda: PhysicalProvider().fetch_history(10), events=events,
                  gatun=_gatun_series(81.5, days=40), river=_river_series(9.0))
    assert series[pd.Timestamp("2026-10-21")] == pytest.approx(62.5, abs=0.1)


def test_physical_history_all_missing_raises(anchors):
    with pytest.raises(RuntimeError):
        _run(lambda: PhysicalProvider().fetch_history(30))


def test_physical_aged_out_gauges_raise_inputs_expired(anchors):
    from data.providers.readings import InputsExpired
    old = TODAY - timedelta(days=20)                                   # past the 9-day drop
    with pytest.raises(InputsExpired):
        _run(PhysicalProvider().fetch_current, gatun=_gatun_series(86.0, last=old),
             river=_river_series(9.0, last=old))


def test_physical_fetch_failures_are_not_inputs_expired(anchors):
    from data.providers.readings import InputsExpired
    with pytest.raises(RuntimeError) as failure:
        _run(PhysicalProvider().fetch_current)
    assert not isinstance(failure.value, InputsExpired)


def test_physical_stores_kaub_at_most_once_per_hour(anchors):
    upsert, marker_writes = mock.Mock(), mock.Mock()
    fetch_kaub = mock.Mock(return_value=(date(2026, 10, 22), 27.0))
    with mock.patch.object(physical.waterways, "fetch_kaub_latest", fetch_kaub), \
         mock.patch.object(physical.database, "upsert_gauge_reading", upsert), \
         mock.patch.object(physical, "set_cached", marker_writes), \
         mock.patch.object(physical, "get_cached", return_value=None) as get_marker:
        PhysicalProvider()._store_kaub()
    assert get_marker.call_args.args == ("kaub_stored_v1",)
    assert get_marker.call_args.kwargs["ttl"] == config.KAUB_STORE_INTERVAL_SECONDS == 3600
    upsert.assert_called_once_with(date(2026, 10, 22), "kaub", 27.0)
    assert marker_writes.call_args.args[0] == "kaub_stored_v1"

    # Within the hour the marker is fresh: no fetch, no database write.
    fetch_kaub.reset_mock(); upsert.reset_mock()
    with mock.patch.object(physical.waterways, "fetch_kaub_latest", fetch_kaub), \
         mock.patch.object(physical.database, "upsert_gauge_reading", upsert), \
         mock.patch.object(physical, "set_cached", mock.Mock()), \
         mock.patch.object(physical, "get_cached", return_value={"day": "2026-10-22"}):
        PhysicalProvider()._store_kaub()
    fetch_kaub.assert_not_called()
    upsert.assert_not_called()


def test_physical_failed_kaub_attempt_also_waits_an_hour(anchors):
    marker_writes = mock.Mock()
    _run(PhysicalProvider().fetch_current, events=[_event("TC", "Red")], kaub=None, kaub_cache=marker_writes)
    assert marker_writes.call_args.args[0] == "kaub_stored_v1"
