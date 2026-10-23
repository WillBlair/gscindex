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
