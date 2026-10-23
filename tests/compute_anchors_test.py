"""Offline tests for the anchors builder (scripts/compute_anchors.py)."""
import math

import numpy as np
import pandas as pd
import pytest

from scripts.compute_anchors import compute_input_anchor


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
