"""Behavioral coverage for profile-aware monitoring and snapshot exports."""
import csv
import io
from datetime import datetime, timezone

import pandas as pd
import pytest

from dash import dcc, html

from components.workspace import plain_text, safe_url, select_news, snapshot_csv
from components.charts import build_world_map
from components.terminal import fmt
from components.terminal_data import TIER_COLORS, index_summary
from config import INDUSTRY_PROFILES


@pytest.fixture
def snapshot():
    categories = {c for p in INDUSTRY_PROFILES.values() for c in p["weights"]}
    dates = pd.date_range("2026-09-15", periods=2)
    return {
        "last_updated_utc": "2026-09-16T12:00:00Z",
        # Distinct per category, so each profile's weights give a different index.
        "current_scores": {c: 50.0 + 3 * i for i, c in enumerate(sorted(categories))},
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


def test_export_is_profile_scoped_and_protects_spreadsheet_cells(snapshot):
    snapshot["category_metadata"]["weather"] = {"source": "=SUM(1,1)", "is_fallback": True}
    rows = list(csv.DictReader(io.StringIO(snapshot_csv(snapshot, "semiconductor"))))
    assert len(rows) == len(INDUSTRY_PROFILES["semiconductor"]["weights"])
    weather = next(r for r in rows if r["category"] == "Weather")
    assert weather["source"] == "'=SUM(1,1)"
    assert weather["status"] == "fallback"
    assert weather["snapshot_utc"] == snapshot["last_updated_utc"]


def test_map_colors_relative_risk_without_changing_the_readings():
    markers = [{"name": str(i), "lat": i, "lon": i, "score": score, "description": ""}
               for i, score in enumerate([61, 62, 63])]
    fig = build_world_map(markers)
    assert list(fig.data[0].marker.color) == [1.0, 0.5, 0.0]
    assert "63.0 / 100" in fig.data[0].text[0]
    assert min(fig.data[0].marker.size) >= 11


def test_map_ties_do_not_invent_differences():
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


# --- terminal layout and callbacks ----------------------------------------------

def _walk(node):
    if isinstance(node, (list, tuple)):
        for child in node:
            yield from _walk(child)
        return
    if not hasattr(node, "_prop_names"):
        return
    yield node
    yield from _walk(getattr(node, "children", None))


def _text(node):
    if node is None:
        return ""
    if isinstance(node, (str, int, float)):
        return str(node)
    if isinstance(node, (list, tuple)):
        return " ".join(_text(n) for n in node)
    return _text(getattr(node, "children", None))


def _callback(app, output):
    return next(v["callback"].__wrapped__ for k, v in app.callback_map.items() if output in [part.strip(".") for part in k.split("...")])


@pytest.fixture
def terminal_app(snapshot, monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    snapshot["daily_history"] = {
        "dates": ["2026-09-15", "2026-09-16"],
        "scores": {c: [score - 2 - i % 3, None]
                   for i, (c, score) in enumerate(sorted(snapshot["current_scores"].items()))},
    }
    snapshot["alerts"] = [
        {"title": f"Story {i}", "severity": sev, "category": "energy", "source": "Wire",
         "url": "https://example.org", "timestamp": f"2026-09-{10 + i:02d}T00:00:00Z"}
        for i, sev in enumerate(["high", "low", "medium", "low", "high", "low", "low", "medium", "low", "low", "low", "high"])
    ]
    monkeypatch.setattr(application, "_DATA_CACHE", snapshot)
    monkeypatch.setattr(application, "_DATA_IS_FRESH", True)
    monkeypatch.setattr("data.cache.get_cached_dashboard", lambda: None)
    return application


def test_layout_serves_the_terminal_panes_only(terminal_app):
    response = terminal_app.server.test_client().get("/_dash-layout")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    for pane_id in ("profile-switch", "readout", "trend-range", "world-map", "quotes", "news-search",
                    "news-severity", "news-category", "news-results", "news-results-count", "briefing",
                    "category-table", "refresh-interval", "profile-store", "snapshot-download", "api-modal",
                    "newsletter-popover", "updated-label"):
        assert f'"id":"{pane_id}"' in text, pane_id
    for removed in ("refresh-btn", "profile-selector", "overview-summary", "pressure-drivers", "cards-container",
                    "trend-chart", "details-modal", "newsletter-modal", "generate-briefing-btn", "port-search", "map-mode"):
        assert f'"id":"{removed}"' not in text, removed
    assert "higher is healthier" not in text


def test_removed_callbacks_are_gone(terminal_app):
    outputs = " ".join(terminal_app.app.callback_map)
    for gone in ("briefing-content", "details-modal", "newsletter-modal", "modal-body"):
        assert gone not in outputs


def test_workspace_callbacks_render_all_profiles_and_export(terminal_app):
    app = terminal_app.app
    snapshot = terminal_app._DATA_CACHE
    yesterday = {c: v[0] for c, v in snapshot["daily_history"]["scores"].items()}
    assert _callback(app, "profile-store.data")("semiconductor") == "semiconductor"
    overview = _callback(app, "category-table.children")
    seen = set()
    for key, profile in INDUSTRY_PROFILES.items():
        weights = profile["weights"]
        expected_today = sum(w * snapshot["current_scores"][c] for c, w in weights.items())
        expected_yday = sum(w * yesterday[c] for c, w in weights.items())
        readout, table = overview(key, 0, 30)
        index_row = next(c for c in _walk(table) if getattr(c, "className", None) == "index-row")
        cells = [_text(c) for c in index_row.children]
        assert cells[3] == fmt(expected_today) == fmt(index_summary(snapshot, key)["today"])
        assert cells[4] == fmt(expected_yday)
        assert fmt(expected_today) in _text(readout)
        body_rows = [c for c in _walk(table) if isinstance(c, html.Tr)]
        assert len(body_rows) == len(weights) + 2  # header + rows + index
        seen.add(cells[3])
    assert len(seen) == len(INDUSTRY_PROFILES)  # the weights actually matter
    download = _callback(app, "snapshot-download.data")(1, "baseline")
    assert download["filename"] == "gscindex-baseline.csv"
    assert "weighted_points" in download["content"]


def test_trend_range_drives_the_readout_line(terminal_app):
    overview = _callback(terminal_app.app, "category-table.children")
    assert "7 days" in _text(overview("baseline", 0, 7)[0])
    assert "90 days" in _text(overview("baseline", 0, 90)[0])
    assert "30 days" in _text(overview("baseline", 0, "bogus")[0])


def test_refresh_updates_context_panes_and_interval(terminal_app, monkeypatch):
    refresh = _callback(terminal_app.app, "refresh-interval.interval")
    figure, quotes, briefing, updated, caption, interval = refresh(3)
    assert figure.data[0].type == "scattergeo"
    assert "Read full report" in _text(briefing)
    assert updated.startswith("Updated")
    assert caption.endswith("ports, colored by relative risk")
    assert interval == 300_000
    monkeypatch.setattr(terminal_app, "_DATA_IS_FRESH", False)
    assert refresh(4)[-1] == 20_000


def _headline_titles(table):
    return [_text(c) for c in _walk(table) if getattr(c, "className", None) == "h"]


def test_headlines_list_every_alert_by_severity_then_newest_and_filter(terminal_app):
    news = _callback(terminal_app.app, "news-results.children")
    table, count = news("", "all", "all", 0)
    # HIGH, then MED, then LOW; newest first within each (Draft E order).
    high, medium, low = [11, 4, 0], [7, 2], [10, 9, 8, 6, 5, 3, 1]
    assert _headline_titles(table) == [f"Story {i}" for i in high + medium + low]
    assert count == "12 tracked"
    table, count = news("story", "high", "all", 0)
    assert _headline_titles(table) == ["Story 11", "Story 4", "Story 0"]
    assert count == "3 of 12"


def test_initial_headlines_use_the_same_order(terminal_app):
    from components.layout import build_layout
    layout = build_layout(terminal_app._DATA_CACHE)
    results = next(c for c in _walk(layout) if getattr(c, "id", None) == "news-results")
    assert _headline_titles(results)[:3] == ["Story 11", "Story 4", "Story 0"]
    assert len(_headline_titles(results)) == 12


def test_controls_persist_for_the_session(snapshot):
    from components.layout import build_layout
    controls = {getattr(c, "id", None): c for c in _walk(build_layout(snapshot))}
    for control_id in ("news-search", "news-severity", "news-category", "trend-range", "profile-switch"):
        assert controls[control_id].persistence is True, control_id
        assert controls[control_id].persistence_type == "session", control_id


def test_map_graph_hides_modebar_and_keeps_pan_and_zoom(snapshot):
    from components.layout import build_layout
    graph = next(c for c in _walk(build_layout(snapshot)) if getattr(c, "id", None) == "world-map")
    assert isinstance(graph, dcc.Graph)
    assert graph.config["displayModeBar"] is False
    assert graph.config["scrollZoom"] is True
    assert graph.figure.layout.dragmode == "pan"


def test_map_hover_uses_the_terminal_mono_face():
    assert "JetBrains Mono" in build_world_map([]).layout.hoverlabel.font.family


def test_updated_label_reads_minutes_since_the_snapshot():
    from components.terminal import updated_label
    now = datetime(2026, 9, 16, 12, 7, 30, tzinfo=timezone.utc)
    assert updated_label({"last_updated_utc": "2026-09-16T12:00:00Z"}, now=now) == "Updated 7 min ago"
    assert updated_label({"last_updated_utc": "2026-09-16T11:59:40Z"}, now=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)) == "Updated just now"
    assert updated_label({"last_updated_utc": "2026-09-16T09:00:00Z"}, now=now) == "Updated 3 h ago"
    assert updated_label({}, now=now) == "Update time unavailable"


def test_startup_snapshot_without_daily_history_stays_provisional(monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    recent = datetime(2026, 10, 22, 11, 30, tzinfo=timezone.utc)
    old = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
    with_history = {"daily_history": {"dates": [], "scores": {}}}
    assert application._startup_is_fresh(with_history, recent, now) is True
    assert application._startup_is_fresh({}, recent, now) is False
    assert application._startup_is_fresh({"current_scores": {}}, recent, now) is False
    assert application._startup_is_fresh(with_history, old, now) is False
    assert application._startup_is_fresh(None, None, now) is False
