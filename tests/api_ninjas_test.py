"""API Ninjas commodity client unit tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from data.providers.api_ninjas import get_commodity_quote, usd_per_metric_ton


class UsdPerMetricTonTests(unittest.TestCase):
    def test_metric_ton_passthrough(self):
        self.assertAlmostEqual(
            usd_per_metric_ton(
                {"price": 3438.85, "unit": "metric_ton", "currency_unit": "USD"}
            ),
            3438.85,
        )

    def test_lb_converts(self):
        # $1.56/lb * 2204.62262185 ≈ $3439/mt
        converted = usd_per_metric_ton(
            {"price": 1.56, "unit": "lb", "currency_unit": "USD"}
        )
        self.assertAlmostEqual(converted, 1.56 * 2204.62262185)

    def test_usx_cents_divided_first(self):
        converted = usd_per_metric_ton(
            {"price": 156.0, "unit": "lb", "currency_unit": "USX"}
        )
        self.assertAlmostEqual(converted, 1.56 * 2204.62262185)

    def test_rejects_troy_ounce(self):
        with self.assertRaises(ValueError):
            usd_per_metric_ton(
                {"price": 4431.1, "unit": "troy_ounce", "currency_unit": "USD"}
            )


class SnapshotLookupTests(unittest.TestCase):
    @patch("data.providers.api_ninjas.fetch_commodity_snapshot", return_value={})
    def test_missing_slug_returns_none(self, _mock):
        self.assertIsNone(get_commodity_quote("aluminum"))

    @patch(
        "data.providers.api_ninjas.fetch_commodity_snapshot",
        return_value={"heating_oil": {"price": 4.159, "change_24h": 0.0273}},
    )
    def test_present_slug_returns_quote(self, _mock):
        quote = get_commodity_quote("heating_oil")
        self.assertIsNotNone(quote)
        self.assertEqual(quote["price"], 4.159)


if __name__ == "__main__":
    unittest.main()
