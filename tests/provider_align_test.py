"""Tests for aggregator history alignment and Gemini port-summary coercion."""

from __future__ import annotations

import unittest

import pandas as pd

from data.aggregator import _align_history_to_dates
from data.port_analyst import _normalize_summaries


class HistoryAlignTests(unittest.TestCase):
    def test_tz_aware_utc_reindexes_onto_naive_dates(self):
        dates = pd.date_range("2026-08-01", periods=5, freq="D")
        hist = pd.Series(
            [70.0],
            index=[pd.Timestamp("2026-08-04", tz="UTC")],
            name="chip_fab_util",
        )
        aligned = _align_history_to_dates(hist, dates, score=81.0)
        self.assertIsNone(aligned.index.tz)
        self.assertEqual(float(aligned.iloc[-1]), 81.0)
        self.assertTrue(pd.isna(aligned.iloc[0]))
        self.assertEqual(float(aligned.iloc[-2]), 70.0)


class PortSummaryNormalizeTests(unittest.TestCase):
    def test_dict_payload_still_works(self):
        raw = {
            "Rotterdam": {"summary": "Clear", "disruption_penalty": 4},
            "Shanghai": "Yard tight",
        }
        out = _normalize_summaries(raw, ["Rotterdam", "Shanghai"])
        self.assertEqual(out["Rotterdam"]["disruption_penalty"], 4.0)
        self.assertEqual(out["Shanghai"]["summary"], "Yard tight")

    def test_list_of_port_rows(self):
        raw = [
            {"port": "Rotterdam", "summary": "Clear", "disruption_penalty": 5},
            {"name": "Shanghai", "summary": "Busy", "disruption_penalty": "12"},
        ]
        out = _normalize_summaries(raw, ["Rotterdam", "Shanghai"])
        self.assertEqual(out["Rotterdam"]["summary"], "Clear")
        self.assertEqual(out["Shanghai"]["disruption_penalty"], 12.0)

    def test_list_of_single_key_objects(self):
        raw = [{"Rotterdam": {"summary": "Clear", "disruption_penalty": 1.0}}]
        out = _normalize_summaries(raw, ["Rotterdam"])
        self.assertEqual(out["Rotterdam"]["disruption_penalty"], 1.0)

    def test_wrapped_object(self):
        raw = {
            "ports": {
                "Rotterdam": {"summary": "Clear", "disruption_penalty": 2.0},
            }
        }
        out = _normalize_summaries(raw, ["Rotterdam"])
        self.assertEqual(out["Rotterdam"]["disruption_penalty"], 2.0)


if __name__ == "__main__":
    unittest.main()
