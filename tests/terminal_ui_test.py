"""Terminal panes: header, readout, quotes, headlines, briefing, category table, map.

Snapshots are built by hand; nothing touches a database.
"""
from __future__ import annotations

from datetime import date, timedelta

import dash_bootstrap_components as dbc
from dash import dcc, html

import config
from components import terminal as term
from components.charts import build_world_map
from components.terminal_data import TIER_COLORS, category_rows, index_summary
from components.workspace import plain_text


# --- helpers -----------------------------------------------------------------

def walk(node):
    """Yield every Dash component in a tree (children only, depth first)."""
    if isinstance(node, (list, tuple)):
        for child in node:
            yield from walk(child)
        return
    if not hasattr(node, "_prop_names"):
        return
    yield node
    yield from walk(getattr(node, "children", None))


def text_of(node) -> str:
    if node is None:
        return ""
    if isinstance(node, (str, int, float)):
        return str(node)
    if isinstance(node, (list, tuple)):
        return " ".join(text_of(n) for n in node)
    return text_of(getattr(node, "children", None))


def ids(node) -> set:
    return {getattr(c, "id", None) for c in walk(node)} - {None}


def rows_of(table):
    return [c for c in walk(table) if isinstance(c, html.Tr)]


def cells(row):
    return [c for c in row.children if isinstance(c, (html.Td, html.Th))]


def snapshot(with_history=True):
    cats = {c for p in config.INDUSTRY_PROFILES.values() for c in p["weights"]}
    snap = {
        "last_updated_utc": "2026-10-22T20:04:45Z",
        "current_scores": {c: 70.0 + i for i, c in enumerate(sorted(cats))},
        "category_metadata": {
            c: {
                "source": f"{c} source", "raw_value": "GSCPI +1.28", "raw_label": "Pressure",
                "updated": "2026-10-22", "description": f"{c} desc", "calculation": f"{c} calc",
            }
            for c in cats
        },
        "fallback_categories": [],
        "alerts": [], "map_markers": [], "market_data": {}, "briefing": "",
    }
    if with_history:
        dates = [(date(2026, 10, 22) - timedelta(days=n)).isoformat() for n in range(91, -1, -1)]
        scores = {}
        for i, c in enumerate(sorted(cats)):
            series = [None] * len(dates)
            series[-2] = 60.0 + i
            series[-3] = 55.0 + i
            scores[c] = series
        snap["daily_history"] = {"dates": dates, "scores": scores}
    return snap


# --- header ------------------------------------------------------------------

def test_header_has_one_button_and_no_removed_controls():
    header = term.build_header("Updated 5 min ago")
    assert isinstance(header, html.Header)
    found = ids(header)
    for wanted in ["profile-switch", "updated-label", "api-btn", "export-btn", "newsletter-btn",
                   "newsletter-popover", "newsletter-email", "newsletter-submit", "newsletter-feedback"]:
        assert wanted in found, wanted
    assert "refresh-btn" not in found and "profile-selector" not in found
    text = text_of(header)
    assert "higher is healthier" not in text
    assert "Updated 5 min ago" in text

    author = [c for c in walk(header) if isinstance(c, html.A) and c.href == config.APP_AUTHOR_URL]
    assert len(author) == 1 and "William Blair" in text_of(author[0])
    assert author[0].target == "_blank" and author[0].rel == "noopener noreferrer"
    brand = next(c for c in walk(header) if "brand" in (getattr(c, "className", "") or ""))
    assert isinstance(brand, html.A) and brand.href == "/"

    switch = next(c for c in walk(header) if getattr(c, "id", None) == "profile-switch")
    assert isinstance(switch, dcc.RadioItems)
    assert [(o["label"], o["value"]) for o in switch.options] == [
        ("Global", "baseline"), ("Semis", "semiconductor"), ("Aero", "aerospace")]

    popover = next(c for c in walk(header) if getattr(c, "id", None) == "newsletter-popover")
    assert isinstance(popover, dbc.Popover)
    assert popover.target == "newsletter-btn" and popover.trigger == "legacy"
    email = next(c for c in walk(header) if getattr(c, "id", None) == "newsletter-email")
    assert isinstance(email, dcc.Input) and email.type == "email"
    assert any(isinstance(c, html.A) and c.href == "/docs" for c in walk(header))
    for button_id in ["api-btn", "export-btn", "newsletter-btn"]:
        assert isinstance(next(c for c in walk(header) if getattr(c, "id", None) == button_id), html.Button)


# --- category table ------------------------------------------------------------

def test_category_table_index_row_matches_summary():
    snap = snapshot()
    for key in config.INDUSTRY_PROFILES:
        table = term.build_category_table(snap, key)
        assert isinstance(table, html.Table)
        body = [r for r in rows_of(table) if not any(isinstance(c, html.Th) for c in r.children)]
        assert len(body) == len(category_rows(snap, key)) + 1
        last = cells(body[-1])
        assert "Index" in text_of(last[0])
        assert text_of(last[3]) == f"{index_summary(snap, key)['today']:.1f}"


def test_missing_yesterday_shows_dash():
    snap = snapshot(with_history=False)
    table = term.build_category_table(snap, "baseline")
    assert "–" in text_of(table)
    body = [r for r in rows_of(table) if not any(isinstance(c, html.Th) for c in r.children)]
    for row in body:
        change = text_of(cells(row)[5]).strip()
        effect = text_of(cells(row)[6]).strip()
        assert change == "–" and effect == "–"
        assert "0.0" not in change


def test_every_category_row_has_hover_detail():
    snap = snapshot()
    table = term.build_category_table(snap, "semiconductor")
    tooltips = {c.target: c for c in walk(table) if isinstance(c, dbc.Tooltip)}
    for row in category_rows(snap, "semiconductor"):
        cat = row["cat"]
        button = next(c for c in walk(table) if getattr(c, "id", None) == f"cat-detail-{cat}")
        assert isinstance(button, html.Button) and "cat-name" in button.className
        tip = tooltips[f"cat-detail-{cat}"]
        assert tip.trigger == "hover focus"
        tip_text = text_of(tip)
        for piece in [f"{cat} source", "GSCPI +1.28", "Pressure", "2026-10-22", f"{cat} desc", f"{cat} calc"]:
            assert piece in tip_text, piece


def test_fallback_rows_are_marked():
    snap = snapshot()
    snap["fallback_categories"] = ["energy"]
    table = term.build_category_table(snap, "baseline")
    row = next(r for r in rows_of(table)
               if any(getattr(c, "id", None) == "cat-detail-energy" for c in walk(r)))
    assert "is-fallback" in (row.className or "")
    assert "fallback" in text_of(cells(row)[0])


def test_category_table_has_no_source_column():
    table = term.build_category_table(snapshot(), "baseline")
    header = [text_of(c).strip() for c in walk(table) if isinstance(c, html.Th)]
    assert "Source" not in header


def test_missing_live_score_renders_dash_not_zero():
    snap = snapshot()
    del snap["current_scores"]["energy"]
    table = term.build_category_table(snap, "baseline")
    body = [r for r in rows_of(table) if not any(isinstance(c, html.Th) for c in r.children)]
    assert text_of(cells(body[-1])[3]).strip() == "–"
    readout = term.build_readout(snap, "baseline")
    assert "–" in text_of(readout)
    assert "0.0" not in text_of(readout).split("vs yesterday")[0]


# --- readout -------------------------------------------------------------------

def test_readout_shows_index_and_tier_without_repeating_the_category_table():
    snap = snapshot()
    summary = index_summary(snap, "aerospace")
    readout = term.build_readout(snap, "aerospace", days=90)
    assert isinstance(readout, html.Section)
    text = text_of(readout)
    assert f"{summary['today']:.1f}" in text
    assert summary["tier"]["label"] in text
    assert "Aero" in text and "90 days" in text
    for row in category_rows(snap, "aerospace"):
        assert row["label"] not in text
    assert any(isinstance(c, html.Img) and c.src.startswith("data:image/svg+xml") for c in walk(readout))


def test_index_row_has_its_own_30_day_line():
    table = term.build_category_table(snapshot(), "baseline")
    index_row = next(c for c in walk(table) if "index-row" in str(getattr(c, "className", "") or ""))
    assert any(isinstance(c, html.Img) and c.src.startswith("data:image/svg+xml") for c in walk(index_row))


def test_readout_renders_without_daily_history():
    readout = term.build_readout(snapshot(with_history=False), "baseline", days=7)
    assert "–" in text_of(readout)


# --- headlines, quotes, briefing -------------------------------------------------

def test_headlines_link_out_and_strip_web_search_label():
    alerts = [
        {"title": "Port strike <b>widens</b>", "url": "https://example.org/a", "source": "Reuters (web search)",
         "severity": "high", "category": "ports", "timestamp": "2026-10-22T10:00:00Z"},
        {"title": "Bad link story", "url": "javascript:alert(1)", "source": "Wire",
         "severity": "low", "category": "energy", "timestamp": "2026-10-21T10:00:00Z"},
    ]
    table = term.build_headlines(alerts)
    assert isinstance(table, html.Table)
    text = text_of(table)
    assert "Reuters" in text and "(web search)" not in text
    assert "HIGH" in text and "LOW" in text
    links = [c for c in walk(table) if isinstance(c, html.A)]
    assert [a.href for a in links] == ["https://example.org/a"]
    assert all(a.target == "_blank" and "noopener" in a.rel for a in links)
    assert "Bad link story" in text
    assert "<b>" not in text and "Port strike widens" in text
    sev = [c for c in walk(table) if isinstance(c, html.Td) and "sev" in (c.className or "")]
    assert sev[0].style["color"] == TIER_COLORS["Critical"]


def test_headlines_empty_state():
    assert "No headlines" in text_of(term.build_headlines([]))


def test_quotes_show_price_and_change():
    quotes = term.build_quotes({
        "Crude Oil": {"price": 99.22, "prev": 97.15, "change_pct": 2.13},
        "Gold": {"price": 4039.1, "prev": 4150.0},
    })
    text = text_of(quotes)
    assert "Crude Oil" in text and "99.22" in text and "4,039.10" in text
    assert "%" not in text
    prices = {text_of(c): str(c.className) for c in walk(quotes) if isinstance(c, html.B)}
    assert "pos" in prices["99.22"] and "neg" in prices["4,039.10"]
    assert "unavailable" in text_of(term.build_quotes({})).lower()


def test_quotes_are_grouped_in_order():
    quotes = term.build_quotes({
        "WTI crude": {"price": 99.0, "change_pct": 1.0, "group": "Energy"},
        "Brent crude": {"price": 112.0, "change_pct": 1.0, "group": "Energy"},
        "Dry bulk (BDRY)": {"price": 12.4, "change_pct": -1.0, "group": "Shipping"},
    })
    groups = [text_of(c) for c in walk(quotes) if "quote-group" in str(getattr(c, "className", "") or "")]
    assert groups == ["Energy", "Shipping"]


def test_briefing_bullets_and_report_link():
    brief = term.build_briefing("• First point.\n- Second point.\n\n* Third point.")
    paragraphs = [text_of(p) for p in walk(brief) if isinstance(p, html.P)]
    assert paragraphs == ["First point.", "Second point.", "Third point."]
    link = next(c for c in walk(brief) if isinstance(c, html.A))
    assert link.href == "/report" and "Read full report" in text_of(link)
    assert any(isinstance(c, html.A) and c.href == "/report" for c in walk(term.build_briefing("")))


def test_briefing_strips_one_bullet_marker_only():
    brief = term.build_briefing("-5% drop in volume\n- Fuel up\n-- nested\n  • Indented\n–3 ports closed\n— Dash")
    paragraphs = [text_of(p) for p in walk(brief) if isinstance(p, html.P)]
    assert paragraphs == ["-5% drop in volume", "Fuel up", "-- nested", "Indented", "–3 ports closed", "Dash"]


# --- map -------------------------------------------------------------------------

def test_map_keeps_port_hover_text():
    marker = {"name": "Test port", "lat": 1, "lon": 2, "score": 43.0,
              "description": '<b>Region:</b> East Asia<br><b>AI Status:</b> Delays after storm.<br><b>[HIGH]</b> Terminal closure reported'}
    hover = build_world_map([marker]).data[0].text[0]
    assert "Region: East Asia" in plain_text(hover)
    assert "Delays after storm." in hover
    assert "Terminal closure reported" in hover
    assert "43.0 / 100" in hover
    assert "<b>Port update:</b>" in hover


def test_map_uses_terminal_palette_and_relative_red_to_green_scale():
    markers = [{"name": str(i), "lat": i, "lon": i, "score": s, "description": ""}
               for i, s in enumerate([90, 70, 50, 20])]
    fig = build_world_map(markers)
    geo = fig.layout.geo
    assert geo.landcolor == "#151B22" and geo.oceancolor == "#07090C" and geo.countrycolor == "#1E252E"
    marker = fig.data[0].marker
    # Drawn healthiest first; the healthiest port is fully green, the worst fully red.
    assert list(marker.color) == [1.0, 2 / 3, 1 / 3, 0.0]
    scale = [c[1] for c in marker.colorscale]
    assert scale[0] == TIER_COLORS["Critical"] and scale[-1] == TIER_COLORS["Healthy"]
    assert min(marker.size) >= 11


def test_map_spreads_ports_that_share_one_tier_from_red_to_green():
    markers = [{"name": str(i), "lat": i, "lon": i, "score": s, "description": ""}
               for i, s in enumerate([66, 63, 60])]
    colors = list(build_world_map(markers).data[0].marker.color)
    assert colors == [1.0, 0.5, 0.0]


# --- loading state, report and docs ------------------------------------------------

def _class_names(node) -> set:
    names = set()
    for c in walk(node):
        names.update(str(getattr(c, "className", None) or "").split())
    return names


def test_skeleton_uses_terminal_grid():
    from components.skeleton import build_skeleton_layout

    skeleton = build_skeleton_layout()
    names = _class_names(skeleton)
    assert "shell" in names and "pane" in names and "head" in names
    for old in ["overview-card", "dashboard", "dash-header", "tech-card", "chart-panel",
                "hero-row", "cards-row", "skeleton-pulse"]:
        assert old not in names, old
    # Same panes, same order as the live grid
    panes = [c for c in walk(skeleton) if "pane" in str(getattr(c, "className", "") or "").split()]
    assert len(panes) == 6
    assert "wide" in panes[3].className and "full" in panes[5].className
    # app.py's boot callbacks need these
    assert {"loading-message", "boot-reload-trigger", "boot-interval"} <= ids(skeleton)
    assert "Satoshi" not in repr(skeleton)


def test_report_and_docs_use_terminal_palette(monkeypatch):
    import flask
    from api import docs, report

    monkeypatch.setattr(report, "get_cached", lambda *a, **k: None)
    monkeypatch.setattr("data.cache.get_cached_dashboard", lambda: None)
    app = flask.Flask(__name__)
    app.register_blueprint(report.report_bp)
    app.register_blueprint(docs.docs_bp)
    client = app.test_client()
    for path in ("/report", "/docs"):
        body = client.get(path).get_data(as_text=True)
        assert "#000000" in body and "JetBrains Mono" in body and "#FFB020" in body, path
        assert "family=JetBrains+Mono" in body and "Inter" in body, path
        for old in ("#0c1216", "#6366f1", "backdrop-filter"):
            assert old not in body, (path, old)


def test_report_still_escapes_html_and_blocks_script_links(monkeypatch):
    import flask
    from api import report

    md = "## Title\n<script>alert(1)</script>\n\n[x](javascript:alert(1))"
    monkeypatch.setattr(report, "get_cached", lambda *a, **k: {"full_report": md, "generated_at": 0})
    app = flask.Flask(__name__)
    app.register_blueprint(report.report_bp)
    body = app.test_client().get("/report").get_data(as_text=True)
    assert "<script>alert" not in body and "&lt;script&gt;" in body
    assert 'href="javascript:' not in body


def test_phone_rules_in_stylesheet():
    from pathlib import Path

    css = Path(__file__).resolve().parents[1].joinpath("assets", "terminal.css").read_text()
    assert "@media (max-width: 760px)" in css
    phone = css.split("@media (max-width: 760px)", 1)[1]
    assert ".hide-s" in phone and "grid-template-columns: minmax(0, 1fr)" in phone


def test_category_detail_opens_above_or_below_so_it_fits_a_phone():
    # "right" has no room beside the name on a 375px screen and popper cannot
    # flip it, so the tooltip pushed the page sideways.
    table = term.build_category_table(snapshot(), "baseline")
    for tip in (c for c in walk(table) if isinstance(c, dbc.Tooltip)):
        assert tip.placement == "top-start" and getattr(tip, "flip", True) is not False


def test_map_stops_capturing_swipes_on_phones_and_touch():
    # Desktop keeps pan and scroll zoom (server-side figure and config);
    # assets/terminal.js turns map dragging off on narrow or touch screens
    # so a one-finger swipe scrolls the page.
    from pathlib import Path
    from components.layout import MAP_CONFIG

    assert MAP_CONFIG["scrollZoom"] is True
    assert build_world_map([]).layout.dragmode == "pan"
    js = Path(__file__).resolve().parents[1].joinpath("assets", "terminal.js").read_text()
    assert 'matchMedia("(max-width: 760px), (pointer: coarse)")' in js
    assert "world-map" in js and "plotly_afterplot" in js
    assert "dragmode: false" in js and 'dragmode: "pan"' in js


def test_docs_and_report_have_no_colored_edges_or_emoji():
    import re
    from api import docs, report

    for source in (docs._DOCS_TEMPLATE, report._REPORT_TEMPLATE):
        assert not re.search(r"border-left:\s*\d+px solid #FFB020", source)
    assert "💡" not in docs._DOCS_MARKDOWN and "callout-icon" not in docs._DOCS_MARKDOWN
    callout = docs._DOCS_TEMPLATE.split(".callout {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid #1D232B" in callout


def test_skeleton_marks_whole_grid_busy():
    from components.skeleton import build_skeleton_layout

    skeleton = build_skeleton_layout()
    assert getattr(skeleton, "aria-busy", None) == "true"
    header = next(c for c in walk(skeleton) if isinstance(c, html.Header))
    assert getattr(header, "aria-busy", None) is None


def test_map_skips_markers_without_a_finite_score():
    good = {"name": "Good", "lat": 1, "lon": 2, "score": 60.0, "description": ""}
    bad = [{"name": n, "lat": 3, "lon": 4, "score": s, "description": ""}
           for n, s in [("None", None), ("NaN", float("nan")), ("Inf", float("inf")), ("Text", "n/a")]]
    fig = build_world_map(bad + [good])
    assert list(fig.data[0].lat) == [1]
    assert len(build_world_map(bad).data[0].lat) == 0


def test_map_caption_counts_drawn_ports():
    from components.layout import map_caption
    markers = [{"score": 80.0}, {"score": None}, {"score": 40.0}, {}]
    assert map_caption(markers) == "3 ports, colored by relative risk"
    assert map_caption([]) == "0 ports, colored by relative risk"


def test_chokepoint_panel_shows_bars_colors_and_source():
    traffic = {
        "as_of": "2026-10-18", "recent_days": 7, "baseline": "same month in 2022-2023",
        "source": "IMF PortWatch",
        "chokepoints": [
            {"name": "Hormuz", "recent_per_day": 3.7, "normal_per_day": 98.1, "pct_of_normal": 4},
            {"name": "Malacca", "recent_per_day": 215.1, "normal_per_day": 218.9, "pct_of_normal": 98},
            {"name": "Cape of Good Hope", "recent_per_day": 85.7, "normal_per_day": 46.6, "pct_of_normal": 184},
        ],
    }
    panel = term.build_chokepoints(traffic)
    text = text_of(panel)
    assert "Hormuz" in text and "4%" in text and "184%" in text
    assert "as of Oct 18" in text and "IMF PortWatch" in text
    assert term.chokepoint_color(4) == TIER_COLORS["Critical"]
    assert term.chokepoint_color(98) == TIER_COLORS["Healthy"]
    assert term.chokepoint_color(184) == term.AMBER
    rows = [c for c in walk(panel) if getattr(c, "className", None) == "choke-row"]
    assert rows[0].title == "3.7 ships/day vs 98.1 normal"


def test_chokepoint_panel_handles_missing_data():
    assert "unavailable" in text_of(term.build_chokepoints(None)).lower()
    assert "unavailable" in text_of(term.build_chokepoints({"chokepoints": []})).lower()


def test_readout_includes_chokepoint_panel():
    snap = snapshot()
    snap["chokepoints"] = {"as_of": "2026-10-18", "chokepoints": [
        {"name": "Suez", "recent_per_day": 44.3, "normal_per_day": 73.5, "pct_of_normal": 60}]}
    assert "Suez" in text_of(term.build_readout(snap, "baseline"))
