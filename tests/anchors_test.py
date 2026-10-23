import math, pytest
from scoring.anchors import anchored_score, transform_value, score_raw, get_anchor

LB = {"transform": "identity", "direction": "lower_better", "best": 0, "normal": 10, "worst": 110}
HB = {"transform": "identity", "direction": "higher_better", "best": 10, "normal": 5, "worst": -5}

@pytest.mark.parametrize("x,expected", [(0, 100), (-5, 100), (5, 90), (10, 80), (60, 40), (110, 0), (200, 0)])
def test_lower_better_piecewise(x, expected):
    assert anchored_score(x, LB) == pytest.approx(expected)

@pytest.mark.parametrize("x,expected", [(10, 100), (7.5, 90), (5, 80), (0, 40), (-5, 0)])
def test_higher_better_piecewise(x, expected):
    assert anchored_score(x, HB) == pytest.approx(expected)

def test_log_transform_midpoint():
    a = {"transform": "log", "direction": "lower_better",
         "best": math.log(50), "normal": math.log(100), "worst": math.log(1000)}
    assert score_raw(100, a) == pytest.approx(80)
    assert score_raw(math.sqrt(100 * 1000), a) == pytest.approx(40)

def test_log_real_uses_cpi_ratio():
    assert transform_value(50, "log_real", cpi_ratio=2.0) == pytest.approx(math.log(100))

def test_non_monotone_anchor_raises():
    with pytest.raises(ValueError):
        anchored_score(1, {"direction": "lower_better", "best": 10, "normal": 5, "worst": 20})

def test_missing_anchor_raises_runtime_error(monkeypatch):
    import config
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for gscpi"):
        get_anchor("gscpi")

def test_anchor_file_missing_or_invalid_loads_empty(tmp_path):
    import config
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    notdict = tmp_path / "list.json"
    notdict.write_text("[1, 2]")
    assert config._load_score_anchors(str(tmp_path / "absent.json")) == {}
    assert config._load_score_anchors(str(bad)) == {}
    assert config._load_score_anchors(str(notdict)) == {}

def test_non_finite_x_raises():
    anchor = {"direction": "lower_better", "best": 0, "normal": 5, "worst": 20}
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            anchored_score(bad, anchor)


# --- past-record marker --------------------------------------------------------------------

def _past_record_anchors(monkeypatch):
    import config
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {
        "boj_memory": {"transform": "identity", "direction": "lower_better", "best": -36.3,
                       "normal": -11.8, "worst": 57.417894,
                       "worst_basis": "worst monthly mean through 2025-12: 2025-12"},
        "aero_inv_ship": {"transform": "log", "direction": "lower_better", "best": 1.25,
                          "normal": 1.55, "worst": 2.7655,
                          "worst_basis": "worst monthly mean through 2025-12: 2020-07"},
    }})


def test_past_record_only_at_the_floor(monkeypatch):
    from scoring.anchors import past_record
    _past_record_anchors(monkeypatch)
    assert past_record("boj_memory", 0.0) == {"record": "+57% YoY", "when": "Dec 2025"}
    assert past_record("boj_memory", 12.0) is None
    assert past_record("boj_memory", None) is None
    assert past_record("hazards", 0.0) is None  # no anchor, never marked


def test_past_record_converts_log_anchors_back(monkeypatch):
    from scoring.anchors import past_record
    _past_record_anchors(monkeypatch)
    assert past_record("aero_inv_ship", 0.0) == {"record": "15.9 months", "when": "Jul 2020"}


def test_inputs_metadata_carries_past_record(monkeypatch):
    from datetime import date
    from data.providers.readings import InputReading, inputs_metadata
    _past_record_anchors(monkeypatch)
    meta = inputs_metadata([InputReading("boj_memory", 0.0, date(2026, 9, 30), "BOJ", "+316.2% YoY (Sep 2026)")])
    assert meta[0]["past_record"] == {"record": "+57% YoY", "when": "Dec 2025"}
