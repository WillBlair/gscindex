"""Offline tests for score-integrity fixes: bounded AI output, the news
cache clock, no invented history, and failures never shown as measurements."""

from __future__ import annotations

import io
import time
import unittest
from unittest import mock

import pandas as pd

from config import AI_CACHE_TTL_SECONDS, PORT_PENALTY_MAX


class SeverityClampTests(unittest.TestCase):
    def test_out_of_range_severity_is_clamped(self):
        from data.providers.geopolitical import _clamp_severity

        self.assertEqual(_clamp_severity(-60), -10.0)
        self.assertEqual(_clamp_severity(25), 10.0)
        self.assertEqual(_clamp_severity("-3.5"), -3.5)
        self.assertEqual(_clamp_severity(None), 0.0)

    def test_single_extreme_article_cannot_take_whole_deduction(self):
        from data.providers.geopolitical import _clamp_severity, _risk_score_from_alerts

        alerts = [{"title": "Bad", "sentiment": _clamp_severity(-60.0)}]
        self.assertGreaterEqual(_risk_score_from_alerts(alerts), 90.0)


class FallbackBriefingTests(unittest.TestCase):
    def test_fallback_briefing_states_headlines_plainly_without_repeating_a_category(self):
        from data.providers.geopolitical import _build_fallback_briefing

        alerts = [
            {"title": "Ships struck near Hormuz", "category": "energy", "severity": "high", "sentiment": -9, "source": "gCaptain"},
            {"title": "RICO case against freight brokers", "category": "geopolitical", "severity": "high", "sentiment": -8, "source": "The Loadstar"},
            {"title": "Autonomous logistics network launches", "category": "geopolitical", "severity": "high", "sentiment": -7, "source": "Logistics Viewpoints"},
            {"title": "Tariff ruling on steel imports", "category": "tariffs", "severity": "medium", "sentiment": -5, "source": "Reuters"},
        ]
        text = _build_fallback_briefing(alerts)
        bullets = [line for line in text.splitlines() if line.strip()]
        self.assertEqual(len(bullets), 3)
        self.assertNotIn("high priority after reports that", text)
        self.assertIn("Ships struck near Hormuz", text)
        self.assertIn("Tariff ruling on steel imports", text)
        self.assertNotIn("Autonomous logistics network launches", text)


class NewsCacheClockTests(unittest.TestCase):
    def test_refresh_due_uses_payload_timestamp(self):
        from data.providers.geopolitical import _ai_refresh_due

        now = time.time()
        self.assertTrue(_ai_refresh_due({}, now))
        self.assertFalse(_ai_refresh_due({"ai_generated_at": now - 60}, now))
        self.assertTrue(
            _ai_refresh_due({"ai_generated_at": now - AI_CACHE_TTL_SECONDS - 1}, now)
        )

    def test_rss_refresh_relabels_scoring_as_vader(self):
        from data.providers import geopolitical as geo

        articles = [
            {
                "title": "Port strike shuts terminal",
                "description": "Dock workers walk out, container terminal closed",
                "url": "https://example.com/a",
                "source": "Test",
                "published": "2026-10-22",
            }
        ]
        cached = {"score": 90.0, "alerts": [], "briefing": "x", "scoring": geo.SCORING_CLAUDE}
        with mock.patch("data.rss_fetcher.fetch_rss_articles", return_value=articles):
            refreshed = geo._refresh_cached_news_from_rss(cached)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["scoring"], geo.SCORING_VADER)
        self.assertIn("alerts_refreshed_at", refreshed)


class PortPenaltyTests(unittest.TestCase):
    def test_penalty_is_clamped_on_normalize(self):
        from data.port_analyst import _normalize_summaries

        out = _normalize_summaries(
            {"ports": [{"port": "Rotterdam", "summary": "x", "disruption_penalty": 400}]},
            ["Rotterdam"],
        )
        self.assertEqual(out["Rotterdam"]["disruption_penalty"], PORT_PENALTY_MAX)

    def test_aggregate_score_is_pure_and_bounded(self):
        from data.port_analyst import aggregate_disruption_score

        score, count, _ = aggregate_disruption_score(
            {"A": {"disruption_penalty": 0.0}, "B": {"disruption_penalty": 999.0}}
        )
        self.assertEqual(count, 2)
        self.assertEqual(score, 50.0)
        with self.assertRaises(ValueError):
            aggregate_disruption_score({})

    def test_provider_blend_never_calls_the_model(self):
        from data.providers import geopolitical as geo

        with mock.patch("data.port_analyst.get_cached_port_summaries", return_value={}), \
             mock.patch("data.port_analyst.generate_port_summaries") as gen:
            score, suffix, note = geo.blend_port_disruption(80.0)
        gen.assert_not_called()
        self.assertEqual((score, suffix, note), (80.0, "", ""))

    def test_blend_applies_weight(self):
        from config import PORT_DISRUPTION_WEIGHT
        from data.providers import geopolitical as geo

        score, suffix, _ = geo.blend_port_disruption(
            80.0, {"A": {"disruption_penalty": 25.0}}
        )
        expected = round((1 - PORT_DISRUPTION_WEIGHT) * 80.0 + PORT_DISRUPTION_WEIGHT * 50.0, 1)
        self.assertEqual(score, expected)
        self.assertIn("port-disruption", suffix)

    def test_port_prompt_forbids_invented_numbers(self):
        from data.port_analyst import SYSTEM_PROMPT

        self.assertIn("ONLY the news items", SYSTEM_PROMPT)
        self.assertIn("never state a number", SYSTEM_PROMPT)
        self.assertNotIn("expert knowledge", SYSTEM_PROMPT)


class AiFailureTests(unittest.TestCase):
    def test_failed_briefing_returns_empty_not_all_clear(self):
        from data import ai_analyst, llm

        with mock.patch.object(llm, "is_configured", return_value=True), \
             mock.patch.object(llm, "complete_text", side_effect=llm.LLMError("boom")):
            self.assertEqual(ai_analyst.generate_briefing([{"title": "x"}]), "")
            self.assertEqual(
                ai_analyst.generate_full_report(
                    [{"title": "x", "source": None, "description": None}]
                ),
                "",
            )

    def test_on_demand_briefing_failure_is_not_cached(self):
        from api import briefing

        with mock.patch.object(briefing, "generate_briefing", return_value=""), \
             mock.patch.object(briefing, "set_cached") as set_cached:
            briefing._generation_running = True
            briefing._generate_in_background([{"title": "x"}])
        set_cached.assert_not_called()
        self.assertFalse(briefing._generation_running)

    def test_on_demand_briefing_never_blocks_the_request(self):
        from api import briefing

        with mock.patch.object(briefing, "get_cached", side_effect=[{"alerts": [{"title": "x"}]}, None]), \
             mock.patch.object(briefing.threading, "Thread") as thread:
            briefing._generation_running = False
            result = briefing.get_on_demand_briefing()
        self.assertFalse(result["success"])
        thread.return_value.start.assert_called_once()


class NoInventedHistoryTests(unittest.TestCase):
    def test_tariff_history_is_eputrade_only(self):
        from data.providers import tariffs

        raw = pd.Series(
            [100.0, 120.0, 140.0] * 8,
            index=pd.date_range("2024-08-01", periods=24, freq="MS"),
        )
        with mock.patch.object(tariffs, "fetch_fred_series", return_value=raw), \
             mock.patch.object(tariffs, "fetch_tariff_news_score", return_value=(0.0, 5, "x")) as news:
            hist = tariffs.TariffsProvider().fetch_history(30)
        news.assert_not_called()
        self.assertFalse(hist.empty)

    def test_quiet_tariff_news_does_not_boost_score(self):
        from data.providers import tariffs

        raw = pd.Series(
            [100.0, 120.0, 140.0] * 8,
            index=pd.date_range("2024-08-01", periods=24, freq="MS"),
        )
        with mock.patch.object(tariffs, "fetch_fred_series", return_value=raw), \
             mock.patch.object(tariffs, "fetch_tariff_news_score", return_value=(100.0, 3, "x")):
            score, _ = tariffs.TariffsProvider().fetch_current()
        eputrade_only = float(tariffs.normalize_series_inverse(raw).iloc[-1])
        self.assertEqual(score, eputrade_only)

    def test_weather_total_failure_is_flagged_not_75(self):
        from data.providers import weather

        provider = weather.WeatherProvider()
        with mock.patch.object(weather, "get_cached", return_value=None), \
             mock.patch.object(weather, "set_cached") as set_cached, \
             mock.patch.object(provider, "_fetch_chunk", side_effect=RuntimeError("down")):
            batch = provider.fetch_batch_port_weather([("Rotterdam", 51.9, 4.1)])
            self.assertIsNone(batch["Rotterdam"]["score"])
            set_cached.assert_not_called()
            with mock.patch.object(provider, "fetch_batch_port_weather", return_value=batch):
                with self.assertRaises(RuntimeError):
                    provider.fetch_current()

    def test_zero_celsius_is_a_reading(self):
        from data.providers.weather import _score_hub_current

        freezing = _score_hub_current({"temperature_2m": 0.0})
        mild = _score_hub_current({"temperature_2m": 20.0})
        self.assertLess(freezing, mild)


class GscpiParsingTests(unittest.TestCase):
    CSV = (
        "Date,Aug-26,Sep-26,Oct-26\n"
        "31-Jul-2026,0.79,0.94,0.93\n"
        "31-Aug-2026,#N/A,1.06,1.20\n"
        "30-Sep-2026,#N/A,#N/A,1.28\n"
    )

    def test_values_keyed_by_data_month_from_latest_vintage(self):
        from data import gscpi_client

        response = mock.Mock(content=self.CSV.encode(), raise_for_status=lambda: None)
        with mock.patch.object(gscpi_client, "get_cached", return_value=None), \
             mock.patch.object(gscpi_client, "set_cached"), \
             mock.patch.object(gscpi_client.requests, "get", return_value=response):
            series = gscpi_client.fetch_gscpi_series()
        self.assertEqual(series.loc["2026-09-30"], 1.28)
        self.assertEqual(series.loc["2026-08-31"], 1.20)
        self.assertEqual(series.loc["2026-07-31"], 0.93)


class NewsRelevanceTests(unittest.TestCase):
    def test_hobby_and_collectible_stories_are_irrelevant(self):
        from data.providers.geopolitical import _is_irrelevant_article

        self.assertTrue(_is_irrelevant_article("el nino delays magic: the gathering trading cards"))
        self.assertTrue(_is_irrelevant_article("pokemon cards sell out"))
        self.assertTrue(_is_irrelevant_article("toy recall hits store shelves"))
        self.assertFalse(_is_irrelevant_article("port strike halts container terminal"))
        self.assertFalse(_is_irrelevant_article("toyota halts production after parts shortage"))
        self.assertTrue(_is_irrelevant_article("toys recalled over choking hazard"))
        self.assertTrue(_is_irrelevant_article("toy-maker opens new studio"))

    def test_consumer_goods_story_with_supply_chain_anchor_is_relevant(self):
        from data.providers.geopolitical import _is_irrelevant_article

        self.assertFalse(_is_irrelevant_article("US tariffs on Chinese toys raise import costs"))
        self.assertFalse(_is_irrelevant_article("Video game console shipments held at Long Beach port"))
        self.assertFalse(_is_irrelevant_article("Chip shortage hits video game console production"))

    def test_anchor_matches_whole_words_only(self):
        from data.providers.geopolitical import _is_irrelevant_article

        self.assertTrue(_is_irrelevant_article("pokemon cards are important to support fans"))

    def test_analysis_prompt_rules_out_consumer_product_delays(self):
        from data.ai_analyst import SYSTEM_PROMPT

        self.assertIn("consumer product shortages, launches or delivery delays", SYSTEM_PROMPT.lower())

    def test_briefing_cache_key_is_v18(self):
        from config import NEWS_BRIEFING_CACHE_KEY

        self.assertEqual(NEWS_BRIEFING_CACHE_KEY, "newsapi_briefing_v18")


if __name__ == "__main__":
    unittest.main()
