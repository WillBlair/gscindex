"""Industry profile config and aerospace scoring tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from config import CATEGORY_COLORS, CATEGORY_LABELS, INDUSTRY_PROFILES
from data.providers.aerospace import (
    AeroMetalsProvider,
    _period_pct_change,
    _smooth_monthly,
    get_aerospace_provider,
)
from data.providers.fred_client import (
    direct_percentile_value,
    inverse_percentile_value,
    normalize_series_direct,
    normalize_series_inverse,
)
from scoring.engine import compute_composite_index


def _monthly_series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    idx = pd.date_range(start=start, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


class IndustryProfileConfigTests(unittest.TestCase):
    def test_every_profile_weights_sum_to_one(self):
        for key, profile in INDUSTRY_PROFILES.items():
            total = sum(profile["weights"].values())
            self.assertTrue(
                np.isclose(total, 1.0, atol=0.01),
                f"{key} weights sum to {total:.4f}, not 1.0",
            )

    def test_labels_and_colors_cover_all_profile_keys(self):
        keys: set[str] = set()
        for profile in INDUSTRY_PROFILES.values():
            keys.update(profile["weights"])
            keys.update(profile.get("card_categories", []))
        missing_labels = keys - set(CATEGORY_LABELS)
        missing_colors = keys - set(CATEGORY_COLORS)
        self.assertEqual(missing_labels, set())
        self.assertEqual(missing_colors, set())

    def test_aerospace_cards_are_a_subset_of_weights(self):
        profile = INDUSTRY_PROFILES["aerospace"]
        extra = set(profile["card_categories"]) - set(profile["weights"])
        self.assertEqual(extra, set())

    def test_aerospace_composite_accepts_profile_scores(self):
        profile = INDUSTRY_PROFILES["aerospace"]
        scores = {cat: 70.0 for cat in profile["weights"]}
        composite = compute_composite_index(scores, weights=profile["weights"])
        self.assertAlmostEqual(composite, 70.0)


class FredPercentileTests(unittest.TestCase):
    def test_direct_percentile_high_value_scores_high(self):
        series = _monthly_series(list(range(1, 25)))
        self.assertGreater(direct_percentile_value(24.0, series), 90.0)
        self.assertLess(direct_percentile_value(1.0, series), 10.0)

    def test_inverse_percentile_high_value_scores_low(self):
        series = _monthly_series(list(range(1, 25)))
        self.assertLess(inverse_percentile_value(24.0, series), 10.0)
        self.assertGreater(inverse_percentile_value(1.0, series), 90.0)

    def test_normalize_helpers_are_mirrors(self):
        series = _monthly_series(list(range(1, 25)))
        direct = normalize_series_direct(series).dropna()
        inverse = normalize_series_inverse(series).dropna()
        self.assertGreater(direct.iloc[-1], inverse.iloc[-1])


class AerospaceHelperTests(unittest.TestCase):
    def test_smooth_monthly_uses_trailing_mean(self):
        series = _monthly_series([10.0, 20.0, 30.0, 40.0])
        smoothed = _smooth_monthly(series, 3)
        self.assertEqual(len(smoothed), 2)
        self.assertAlmostEqual(float(smoothed.iloc[0]), 20.0)
        self.assertAlmostEqual(float(smoothed.iloc[-1]), 30.0)

    def test_smooth_monthly_passthrough_when_short(self):
        series = _monthly_series([10.0, 20.0])
        self.assertTrue(_smooth_monthly(series, 3).equals(series))

    def test_period_pct_change_is_year_over_year_on_monthly(self):
        values = [100.0 + i for i in range(15)]
        series = _monthly_series(values)
        yoy = _period_pct_change(series, 12)
        self.assertEqual(len(yoy), 3)
        expected = (values[-1] / values[-13] - 1.0) * 100.0
        self.assertAlmostEqual(float(yoy.iloc[-1]), expected)


class AerospaceAdapterTests(unittest.TestCase):
    def setUp(self):
        import data.providers.aerospace as aero_mod

        aero_mod._aero_instance = None

    def tearDown(self):
        import data.providers.aerospace as aero_mod

        aero_mod._aero_instance = None

    def _fred_series(self, series_id: str, **_kwargs) -> pd.Series:
        catalogs = {
            "PALUMUSDM": list(range(2000, 2024)),
            "PNICKUSDM": list(range(15000, 15024)),
            "ANAPNO": list(range(8000, 8024)),
            "IPG3364S": [90.0 + i * 0.2 for i in range(24)],
            "PCU336411336411": [100.0 + i * 0.4 for i in range(36)],
        }
        values = catalogs[series_id]
        return _monthly_series(values)

    @patch("data.providers.aerospace._fetch_aluminum_futures", side_effect=RuntimeError("offline"))
    @patch("data.providers.aerospace.fetch_fred_series")
    def test_adapter_packs_additional_scores_and_history(self, mock_fred, _mock_futures):
        mock_fred.side_effect = self._fred_series
        provider = AeroMetalsProvider()
        score, meta = provider.fetch_current()

        self.assertTrue(0.0 <= score <= 100.0)
        self.assertIn("additional_scores", meta)
        self.assertEqual(
            set(meta["additional_scores"]),
            {"aero_orders", "aero_production", "aero_ppi"},
        )
        for extra_score, extra_meta in meta["additional_scores"].values():
            self.assertTrue(0.0 <= extra_score <= 100.0)
            self.assertFalse(extra_meta.get("is_fallback", False))
            self.assertIn("source", extra_meta)
            self.assertIn("calculation", extra_meta)

        history = meta["additional_history"]
        self.assertEqual(set(history), {"aero_orders", "aero_production", "aero_ppi"})
        for series in history.values():
            self.assertGreater(len(series.dropna()), 0)

        metals_hist = provider.fetch_history(90)
        self.assertGreater(len(metals_hist.dropna()), 0)

    @patch("data.providers.aerospace._fetch_aluminum_futures", side_effect=RuntimeError("offline"))
    @patch("data.providers.aerospace.fetch_fred_series")
    def test_steadily_rising_ppi_does_not_pin_at_zero(self, mock_fred, _mock_futures):
        """A grinding-higher PPI level used to score 0. YoY of a steady pace should not."""
        mock_fred.side_effect = self._fred_series
        provider = AeroMetalsProvider()
        _, meta = provider.fetch_current()
        ppi_score, ppi_meta = meta["additional_scores"]["aero_ppi"]
        self.assertGreater(
            ppi_score,
            15.0,
            f"steadily rising PPI pinned at {ppi_score}; expected YoY scoring",
        )
        self.assertIn("% YoY", ppi_meta["raw_value"])
        self.assertIn("inflation", ppi_meta["calculation"].lower())

    @patch("data.providers.aerospace._fetch_aluminum_futures", side_effect=RuntimeError("offline"))
    @patch("data.providers.aerospace.fetch_fred_series", side_effect=RuntimeError("fred down"))
    def test_adapter_falls_back_when_fred_fails(self, _mock_fred, _mock_futures):
        get_aerospace_provider()  # ensure singleton exists
        score, meta = AeroMetalsProvider().fetch_current()
        self.assertEqual(score, 50.0)
        self.assertTrue(meta.get("is_fallback"))
        for extra_score, extra_meta in meta["additional_scores"].values():
            self.assertEqual(extra_score, 50.0)
            self.assertTrue(extra_meta.get("is_fallback"))


if __name__ == "__main__":
    unittest.main()
