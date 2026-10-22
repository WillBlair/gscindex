"""Offline tests for the Claude web-search helpers (no API calls)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock


def _block(**kw):
    return SimpleNamespace(**kw)


def _response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=None)


class ResearchJsonTests(unittest.TestCase):
    def _client(self, responses):
        client = mock.Mock()
        client.with_options.return_value = client
        client.beta.messages.create.side_effect = responses
        return client

    def test_resumes_pause_turn_then_returns_submit_input(self):
        from data import llm

        search = _block(type="server_tool_use", name="web_search", input={})
        submit = _block(type="tool_use", name="submit_results", input={"articles": []})
        client = self._client([_response([search], "pause_turn"), _response([submit], "tool_use")])
        with mock.patch.object(llm, "is_configured", return_value=True), \
             mock.patch.object(llm, "_get_client", return_value=client):
            out = llm.research_json("q", schema={"type": "object"})
        self.assertEqual(out, {"articles": []})
        second_call = client.beta.messages.create.call_args_list[1].kwargs
        self.assertEqual(second_call["messages"][-1]["role"], "assistant")
        self.assertEqual(second_call["messages"][-1]["content"], [search])
        tools = second_call["tools"]
        self.assertEqual(tools[0]["type"], "web_search_20260209")
        self.assertTrue(tools[1]["strict"])

    def test_finishing_without_submit_is_an_error(self):
        from data import llm

        text = _block(type="text", text="done")
        client = self._client([_response([text], "end_turn")])
        with mock.patch.object(llm, "is_configured", return_value=True), \
             mock.patch.object(llm, "_get_client", return_value=client):
            with self.assertRaises(llm.LLMError):
                llm.research_json("q", schema={"type": "object"})


class WebNewsTests(unittest.TestCase):
    def test_bad_rows_dropped_and_source_labelled(self):
        from data import llm, web_news

        result = {
            "articles": [
                {"title": "Port strike", "url": "https://x.com/a", "source": "Reuters",
                 "published": "2026-10-22", "summary": "Workers walk out."},
                {"title": "", "url": "https://x.com/b", "source": "R", "published": "", "summary": ""},
                {"title": "No link", "url": "javascript:alert(1)", "source": "R", "published": "", "summary": ""},
            ]
        }
        with mock.patch.object(llm, "WEB_SEARCH_ENABLED", True), \
             mock.patch.object(llm, "is_configured", return_value=True), \
             mock.patch.object(llm, "research_json", return_value=result):
            articles = web_news.search_supply_chain_news()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "Reuters (web search)")

    def test_search_failure_returns_empty(self):
        from data import llm, web_news

        with mock.patch.object(llm, "WEB_SEARCH_ENABLED", True), \
             mock.patch.object(llm, "is_configured", return_value=True), \
             mock.patch.object(llm, "research_json", side_effect=llm.LLMError("x")):
            self.assertEqual(web_news.search_supply_chain_news(), [])

    def test_merge_dedupes_by_url_and_title(self):
        from data.web_news import merge_articles

        primary = [{"title": "A", "url": "https://x.com/a/"}]
        extra = [
            {"title": "a", "url": "https://other.com"},
            {"title": "B", "url": "https://x.com/a"},
            {"title": "C", "url": "https://x.com/c"},
        ]
        merged = merge_articles(primary, extra)
        self.assertEqual([m["title"] for m in merged], ["A", "C"])


class PortSearchTests(unittest.TestCase):
    def test_port_summaries_use_search_when_enabled(self):
        from data import llm, port_analyst

        payload = {"ports": [{"port": "Rotterdam", "summary": "No disruption reported in current news.",
                              "disruption_penalty": 0}]}
        with mock.patch.object(port_analyst, "get_cached", return_value=None), \
             mock.patch.object(port_analyst, "set_cached"), \
             mock.patch.object(port_analyst, "MAJOR_PORTS", [("Rotterdam", 0, 0, [])]), \
             mock.patch("data.rss_fetcher.fetch_rss_articles", return_value=[]), \
             mock.patch.object(llm, "WEB_SEARCH_ENABLED", True), \
             mock.patch.object(llm, "is_configured", return_value=True), \
             mock.patch.object(llm, "research_json", return_value=payload) as research, \
             mock.patch.object(llm, "complete_json") as plain:
            out = port_analyst.generate_port_summaries.__wrapped__()
        research.assert_called_once()
        plain.assert_not_called()
        self.assertIn("web_search", research.call_args.kwargs["system"])
        self.assertEqual(out["Rotterdam"]["disruption_penalty"], 0.0)


if __name__ == "__main__":
    unittest.main()
