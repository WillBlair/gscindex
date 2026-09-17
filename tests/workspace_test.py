"""Behavioral coverage for profile-aware monitoring and snapshot exports."""
import csv
import io
from datetime import datetime, timezone

import pandas as pd
import pytest

from components.workspace import (plain_text, safe_url, select_news,
                                  daily_delta, composite_for, snapshot_csv, build_freshness)
from components.charts import build_world_map
from config import INDUSTRY_PROFILES


@pytest.fixture
def snapshot():
    categories = {c for p in INDUSTRY_PROFILES.values() for c in p["weights"]}
    dates = pd.date_range("2026-09-15", periods=2)
    return {
        "last_updated_utc": "2026-09-16T12:00:00Z",
        "current_scores": {c: 80.0 for c in categories},
        "category_history": {c: pd.Series([60.0, 80.0], index=dates) for c in categories},
        "category_metadata": {c: {"source": "A source", "updated": "2026-09-16"} for c in categories},
        "alerts": [], "disruptions": [], "map_markers": [], "market_data": {}, "briefing": "",
    }


def test_rss_is_readable_and_script_contents_are_removed():
    assert plain_text('<p>Trade &amp; ports</p><script>steal()</script><p>Next<br>line</p>') == "Trade & ports Next line"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,test", "//evil.test", "https://", "https://["])
def test_unsafe_article_links_are_not_linked(url):
    assert safe_url(url) is None


def test_external_article_url_is_preserved():
    assert safe_url("https://example.org/news?q=ports") == "https://example.org/news?q=ports"


def test_news_filters_search_clean_content_and_order_newest():
    alerts = [{"title": "Ports", "body": "<p>Oil &amp; gas</p>", "severity": "high", "category": "energy", "timestamp": t} for t in ["2026-09-14", "2026-09-16"]]
    assert select_news(alerts, "oil & gas", "high", "energy") == alerts[::-1]
    assert select_news(alerts, "oil", "low") == []


def test_each_profile_compares_its_own_weighted_history(snapshot):
    snapshot["current_scores"]["chip_fab_util"] = 100.0
    assert daily_delta(snapshot, "baseline") == 20.0
    assert daily_delta(snapshot, "semiconductor") == 24.0


def test_missing_scores_never_become_zero(snapshot):
    del snapshot["current_scores"]["chip_fab_util"]
    assert composite_for(snapshot, "semiconductor") is None
    assert composite_for(snapshot, "baseline") == 80.0


def test_fallbacks_and_gaps_do_not_make_daily_comparisons(snapshot):
    snapshot["category_metadata"]["weather"]["is_fallback"] = True
    assert daily_delta(snapshot, "baseline") is None
    snapshot["category_metadata"]["weather"] = {}
    snapshot["category_history"]["weather"].iloc[-2] = float("nan")
    assert daily_delta(snapshot, "baseline") is None


def test_export_is_profile_scoped_and_protects_spreadsheet_cells(snapshot):
    snapshot["category_metadata"]["weather"] = {"source": "=SUM(1,1)", "is_fallback": True}
    rows = list(csv.DictReader(io.StringIO(snapshot_csv(snapshot, "semiconductor"))))
    assert len(rows) == len(INDUSTRY_PROFILES["semiconductor"]["weights"])
    weather = next(r for r in rows if r["category"] == "Weather")
    assert weather["source"] == "'=SUM(1,1)"
    assert weather["status"] == "fallback"
    assert weather["snapshot_utc"] == snapshot["last_updated_utc"]


def test_stale_snapshot_is_never_labelled_latest(snapshot):
    status = build_freshness(snapshot, "baseline", now=datetime(2026, 9, 17, tzinfo=timezone.utc))
    assert status.children[0].children[1] == "Cached snapshot"


def test_relative_map_spreads_close_scores_without_changing_the_readings():
    markers = [{"name": str(i), "lat": i, "lon": i, "score": score, "description": ""}
               for i, score in enumerate([61, 62, 63])]
    fig = build_world_map(markers)
    assert list(fig.data[0].marker.color) == [1.0, 0.5, 0.0]
    assert "63.0 / 100" in fig.data[0].text[0]
    assert min(fig.data[0].marker.size) >= 11


def test_relative_map_ties_do_not_invent_differences():
    markers = [{"name": str(i), "lat": i, "lon": i, "score": 65, "description": ""} for i in range(3)]
    assert set(build_world_map(markers).data[0].marker.color) == {0.5}


def test_map_hover_restores_conditions_and_news_without_active_html():
    marker = {"name": "Test port", "lat": 1, "lon": 2, "score": 43.0,
              "description": '<b>Region:</b> East Asia<br><b>AI Status:</b> Delays after storm.<br><b>[HIGH]</b> Terminal closure reported<br><script>bad()</script><img src=x onerror=bad()>'}
    hover = build_world_map([marker]).data[0].text[0]
    assert "Region: East Asia" in plain_text(hover)
    assert "Delays after storm." in hover
    assert "Terminal closure reported" in hover
    assert "43.0 / 100" in hover
    assert "Click to inspect" not in hover
    assert "<script>" not in hover and "<img" not in hover and "bad()" not in hover


def test_port_hover_joins_legacy_wrapping_before_reflowing():
    marker = {"name": "Shanghai", "lat": 1, "lon": 2, "score": 60.9,
              "description": "Score: 61/100<br>────────────<br><b>Region:</b> China<br>"
              "<b>AI Status:</b> <i>Maintaining global lead in capacity<br>despite<br>"
              "manufacturing slowdowns; newbuild<br>orders remain strong.</i>"}
    hover = build_world_map([marker]).data[0].text[0]
    assert "<br>despite<br>" not in hover
    assert "────────" not in hover
    assert "Maintaining global lead in capacity despite manufacturing slowdowns; newbuild orders remain strong." in plain_text(hover)
    assert "<b>Port update:</b>" in hover


def test_map_hover_keeps_all_supplied_context_and_handles_absence():
    marker = {"name": "Test", "lat": 1, "lon": 2, "score": 50.0}
    assert "Port context unavailable" in build_world_map([marker]).data[0].text[0]
    marker["description"] = "<b>Score:</b> 50/100<br>" + "Long context " * 30 + "Final event."
    hover = build_world_map([marker]).data[0].text[0]
    assert "Final event." in hover.replace("<br>", " ")
    assert "Score:" not in hover


def test_workspace_callbacks_render_all_profiles_and_export(snapshot, monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    monkeypatch.setattr(application, "_DATA_CACHE", snapshot)
    monkeypatch.setattr(application, "_DATA_IS_FRESH", True)
    client = application.server.test_client()
    layout_response = client.get("/_dash-layout")
    assert layout_response.status_code == 200
    layout_text = layout_response.get_data(as_text=True)
    assert '"id":"port-search"' not in layout_text
    assert '"id":"map-mode"' not in layout_text
    app = application.app
    overview = next(v["callback"].__wrapped__ for k, v in app.callback_map.items() if "overview-summary.children" in k)
    for key in INDUSTRY_PROFILES:
        result = overview(key, 0)
        assert len(result[2]) == len(INDUSTRY_PROFILES[key]["card_categories"])
        assert result[-1] == 300_000
    download = app.callback_map["snapshot-download.data"]["callback"].__wrapped__(1, "baseline")
    assert download["filename"] == "gscindex-baseline.csv"
    assert "weighted_points" in download["content"]


def test_api_uses_snapshot_timestamp(snapshot, monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    monkeypatch.setattr("data.cache.get_cached_dashboard", lambda: snapshot)
    response = application.server.test_client().get("/api/v1/latest")
    assert response.status_code == 200
    assert response.json["timestamp"] == "2026-09-16T12:00:00Z"


@pytest.mark.parametrize("email", ["bad@", "person @example.com", "@example.com"])
def test_newsletter_rejects_invalid_addresses_without_writes(email, monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    def unexpected_write(_):
        pytest.fail("Invalid addresses must not reach subscriber storage")
    monkeypatch.setattr("data.database.add_subscriber", unexpected_write)
    handler = next(v["callback"].__wrapped__ for k, v in application.app.callback_map.items() if "newsletter-feedback.children" in k)
    assert handler(1, email)[0] == "Please enter a valid email address."


def test_map_navigation_is_enabled():
    assert build_world_map([]).layout.dragmode == "pan"


def test_missing_daily_comparison_is_distinct_from_zero():
    from components.cards import build_category_cards
    def text(node):
        if isinstance(node, (list, tuple)):
            return " ".join(text(x) for x in node)
        if hasattr(node, "children"):
            return text(node.children)
        return str(node or "")
    dates = pd.date_range("2026-09-15", periods=2)
    args = {"current_scores": {"weather": 80.0}, "active_weights": {"weather": 1.0}}
    flat = text(build_category_cards(category_history={"weather": pd.Series([80., 80.], index=dates)}, **args))
    sparse = text(build_category_cards(category_history={"weather": pd.Series([80.], index=dates[-1:])}, **args))
    assert "24h change 0.0" in flat
    assert "No prior day" in sparse
    fallback = text(build_category_cards(category_history={}, metadata={"weather": {"is_fallback": True}}, **args))
    assert "Estimated" in fallback and "History unavailable" in fallback
    assert "30d low N/A" in fallback and "30d high N/A" in fallback
