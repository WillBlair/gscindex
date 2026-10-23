"""Offline tests for the anchors builder (scripts/compute_anchors.py)."""
import math

import numpy as np
import pandas as pd
import pytest

from scripts.compute_anchors import combined_yoy, common_months, compute_input_anchor


def _monthly(start, values):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def _series_with_tail(tail):
    """2000-01..2019-12 values 1..100 (evenly spaced), then the given 2020+ monthly values."""
    base = np.linspace(1.0, 100.0, 240)
    return _monthly("2000-01-01", np.concatenate([base, tail])), base


def test_compute_input_anchor_lower_better():
    tail = np.full(72, 50.0)            # 2020-01..2025-12
    tail[3] = 150.0                     # 2020-04, the worst month through 2025
    series, base = _series_with_tail(np.concatenate([tail, [900.0]]))   # 2026-01 is past worst_through
    a = compute_input_anchor(series, "identity", "lower_better", ("2000-01-01", "2019-12-31"))
    assert a["best"] == pytest.approx(np.percentile(base, 5))
    assert a["normal"] == pytest.approx(np.median(base))
    assert a["worst"] == pytest.approx(150.0)
    assert a["transform"] == "identity" and a["direction"] == "lower_better"
    assert "2020-04" in a["worst_basis"]
    assert {"baseline", "generated"} <= set(a)


def test_compute_input_anchor_higher_better_flips_tails():
    tail = np.full(72, 50.0)
    tail[3] = -30.0
    series, base = _series_with_tail(np.concatenate([tail, [-900.0]]))
    a = compute_input_anchor(series, "identity", "higher_better", ("2000-01-01", "2019-12-31"))
    assert a["best"] == pytest.approx(np.percentile(base, 95))
    assert a["normal"] == pytest.approx(np.median(base))
    assert a["worst"] == pytest.approx(-30.0)


def test_worst_override_used():
    series, _ = _series_with_tail(np.full(72, 50.0))
    a = compute_input_anchor(series, "identity", "lower_better", ("2000-01-01", "2019-12-31"),
                             worst_override=500.0, worst_basis="USITC, 1933")
    assert a["worst"] == pytest.approx(500.0)
    assert a["worst_basis"] == "USITC, 1933"


def test_daily_values_resampled_to_monthly_means():
    days = pd.date_range("2000-01-01", "2025-12-31", freq="D")
    values = pd.Series(10.0, index=days)
    values[(days >= "2020-04-01") & (days <= "2020-04-30")] = 100.0
    values[pd.Timestamp("2021-06-15")] = 10_000.0      # one bad day; its month mean is far lower
    a = compute_input_anchor(values + np.arange(len(days)) * 1e-9, "identity", "lower_better",
                             ("2000-01-01", "2019-12-31"))
    june_mean = (10_000.0 + 29 * 10.0) / 30
    assert a["worst"] == pytest.approx(max(100.0, june_mean), rel=1e-6)


def test_log_real_deflates_to_the_2025_12_cpi():
    months = pd.date_range("1990-01-01", "2025-12-01", freq="MS")
    cpi = pd.Series(np.linspace(100.0, 300.0, len(months)), index=months)   # 2025-12 CPI = 300
    real = pd.Series(np.linspace(10.0, 50.0, len(months)), index=months)    # in 2025-12 dollars
    prices = real * cpi / 300.0
    a = compute_input_anchor(prices, "log_real", "lower_better", ("1990-01-01", "2019-12-31"),
                             cpi=cpi)
    base = np.log(real["1990":"2019"])
    assert a["normal"] == pytest.approx(np.median(base))
    assert a["best"] == pytest.approx(np.percentile(base, 5))
    assert a["worst"] == pytest.approx(math.log(50.0))


def test_non_monotone_anchor_raises():
    series = _monthly("2000-01-01", np.full(312, 5.0))
    with pytest.raises(ValueError):
        compute_input_anchor(series, "identity", "lower_better", ("2000-01-01", "2019-12-31"))


def test_log_real_needs_cpi():
    series, _ = _series_with_tail(np.full(72, 50.0))
    with pytest.raises(ValueError):
        compute_input_anchor(series, "log_real", "lower_better", ("2000-01-01", "2019-12-31"))


def test_empty_baseline_raises():
    series = _monthly("2021-01-01", np.arange(1.0, 40.0))
    with pytest.raises(ValueError):
        compute_input_anchor(series, "identity", "lower_better", ("2000-01-01", "2019-12-31"))


def test_combined_yoy_sums_both_series_and_compares_by_date():
    carloads = _monthly("2000-01-01", [100.0] * 12 + [110.0] * 12)
    intermodal = _monthly("2000-01-01", [100.0] * 12 + [130.0] * 12)
    intermodal = intermodal.drop(pd.Timestamp("2001-03-01"))      # a missing month leaves a gap
    yoy = combined_yoy(carloads, intermodal)
    assert yoy.index[0] == pd.Timestamp("2001-01-01")
    assert yoy[pd.Timestamp("2001-01-01")] == pytest.approx(20.0)  # (110 + 130) / 200 - 1
    assert pd.Timestamp("2001-03-01") not in yoy.index
    assert len(yoy) == 11


def test_common_months_needs_every_survey():
    surveys = {"philly": _monthly("1968-05-01", np.ones(700)),
               "empire": _monthly("2001-07-01", np.ones(300)),
               "dallas": _monthly("2004-06-01", np.ones(260))}
    months = common_months(surveys)
    assert months[0] == pd.Timestamp("2004-06-01")
    assert months[-1] == min(s.index[-1] for s in surveys.values())


def test_sectors_only_merge_keeps_global_keys_identical(tmp_path):
    import difflib
    import json

    from scripts.compute_anchors import SECTOR_INPUT_KEYS, merge_sector_anchors

    original = {
        "method_version": 2,
        "generated": "2026-10-20",
        "inputs": {
            "gscpi": {"transform": "identity", "direction": "lower_better", "best": -1.234567,
                      "normal": -0.1, "worst": 4.321, "baseline": "1998-01 to 2019-12 (264 months)"},
            "brent": {"transform": "log_real", "direction": "lower_better", "best": 3.9,
                      "normal": 4.2, "worst": 5.0123456789, "source": "FRED DCOILBRENTEU"},
        },
        "chokepoint_weights": {"Suez": 0.12345678},
        "waterways": {"mississippi_record_low": -10.7},
    }
    path = tmp_path / "score_anchors.json"
    before = json.dumps(original, indent=2) + "\n"
    path.write_text(before, encoding="utf-8")
    sector = {key: {"transform": "identity", "direction": "lower_better", "best": 1.0, "normal": 2.0,
                    "worst": 3.0, "source": f"dummy {key}"} for key in SECTOR_INPUT_KEYS}

    merge_sector_anchors(path, sector)

    after = path.read_text(encoding="utf-8")
    removed = [line for line in difflib.ndiff(before.splitlines(), after.splitlines()) if line.startswith("- ")]
    assert removed == []                                   # additions only, like `git diff`
    merged = json.loads(after)
    assert set(merged["inputs"]) == set(original["inputs"]) | set(SECTOR_INPUT_KEYS)
    for key, value in original["inputs"].items():
        assert json.dumps(merged["inputs"][key], indent=2) == json.dumps(value, indent=2)
    assert {k: v for k, v in merged.items() if k != "inputs"} == {k: v for k, v in original.items() if k != "inputs"}
    assert merged["inputs"]["boj_memory"]["source"] == "dummy boj_memory"
    assert set(SECTOR_INPUT_KEYS) == {
        "boj_memory", "boj_logic", "fab_util_3344", "aero_caputl", "aero_inv_ship", "ppi_ti_mill",
        "ppi_ni_mill", "ppi_ti_forge", "ppi_nonferrous_forge", "ppi_steel_invest_cast"}

    merge_sector_anchors(path, {**sector, "boj_memory": {**sector["boj_memory"], "worst": 9.0}})
    rerun = json.loads(path.read_text(encoding="utf-8"))   # a re-run replaces sector keys only
    assert rerun["inputs"]["boj_memory"]["worst"] == 9.0
    assert rerun["inputs"]["gscpi"] == original["inputs"]["gscpi"]

    with pytest.raises(ValueError):                        # a global key is never written
        merge_sector_anchors(path, {"gscpi": sector["boj_memory"]})


def test_full_run_writes_inputs_in_the_committed_key_order(tmp_path, monkeypatch):
    """A full regeneration orders ``inputs`` like the committed file (sector keys first, as
    --sectors-only wrote them), so it never reorders the JSON. Builders are stubbed: offline."""
    import json
    from pathlib import Path

    from data.providers import fred_client
    from scripts import compute_anchors as ca

    committed = json.loads((Path(ca.ROOT) / "data" / "score_anchors.json").read_text(encoding="utf-8"))

    def anchor(key):
        return {"transform": "identity", "direction": "lower_better", "best": 1.0, "normal": 2.0, "worst": 3.0}

    prices = ("brent", "ulsd", "ttf", "copper", "aluminum", "ttf_monthly", "copper_monthly", "aluminum_monthly")
    monkeypatch.setattr(ca, "ROOT", tmp_path)
    monkeypatch.setattr(ca, "OUT", tmp_path / "score_anchors.json")
    monkeypatch.setattr(fred_client, "fetch_fred_full", lambda series_id: pd.Series(dtype=float))
    monkeypatch.setattr(ca, "cpi_reference", lambda cpi: 320.0)
    monkeypatch.setattr(ca, "build_gscpi", lambda: anchor("gscpi"))
    monkeypatch.setattr(ca, "build_prices", lambda cpi: {k: anchor(k) for k in prices})
    monkeypatch.setattr(ca, "build_tariff_burden", lambda: anchor("tariff_burden"))
    monkeypatch.setattr(ca, "build_tpu", lambda: (anchor("tpu"), "ok"))
    monkeypatch.setattr(ca, "build_gpr", lambda: (anchor("gpr"), "ok"))
    monkeypatch.setattr(ca, "build_tsifrght", lambda: anchor("tsifrght"))
    monkeypatch.setattr(ca, "build_rail", lambda: (anchor("rail_volume"), "ok"))
    monkeypatch.setattr(ca, "build_prices_paid", lambda: (anchor("prices_paid"), {}))
    # Sector anchors come back in a scrambled order; the output must not depend on it.
    monkeypatch.setattr(ca, "build_sectors", lambda: {
        k: {**anchor(k), "source": f"dummy {k}"} for k in reversed(ca.SECTOR_INPUT_KEYS)})
    monkeypatch.setattr(ca, "build_chokepoints", lambda: ({"Suez": 1.0}, {"1": 10.0}))
    monkeypatch.setattr(ca, "build_port_shares", lambda: ({f"P{i}": 0.01 * (i + 1) for i in range(12)}, []))
    monkeypatch.setattr(ca, "build_waterways", lambda: {
        "mississippi_record_low": -10.7, "mississippi_record_low_date": "2022-10-17", "mississippi_threshold": 1.0})
    for name in ("print_inputs", "print_categories", "print_sectors"):
        monkeypatch.setattr(ca, name, lambda anchors: None)

    assert ca.main([]) == 0
    written = json.loads((tmp_path / "score_anchors.json").read_text(encoding="utf-8"))
    assert list(written["inputs"]) == list(committed["inputs"])
    assert list(written) == list(committed)
    assert list(written["inputs"])[:len(ca.SECTOR_INPUT_KEYS)] == list(ca.SECTOR_INPUT_KEYS)
    assert written["inputs"]["boj_memory"]["source"] == "dummy boj_memory"
    assert written["inputs"]["gscpi"]["source"] == ca.SOURCES["gscpi"]
