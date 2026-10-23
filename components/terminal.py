"""Terminal panes: header, index readout, quotes, headlines, briefing, category table.

Each builder returns one Dash component. Structure and class names follow the
Draft E reference (docs/superpowers/specs/terminal-draft/e-terminal.html) so the
stylesheet can match it: ``pane``, ``ttl``, ``num``, ``dim``, ``neg``, ``pos``,
``sev``, ``bar``. Missing numbers always render as an en dash, never as 0.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from urllib.parse import quote

import dash_bootstrap_components as dbc
from dash import dcc, html

import config
from components.feed import _format_time_ago
from components.terminal_data import (
    TIER_COLORS, category_rows, index_history, index_summary, row_history_days, tab_key, tier_for,
)
from components.workspace import plain_text, safe_url, select_news
from config import CATEGORY_LABELS, DEFAULT_TAB, INPUT_LABELS, SECTORS, TABS
from data.providers.chokepoints import CREDIT as PORTWATCH_CREDIT

DASH = "–"
MINUS = "−"
AMBER = "#FFB020"
DIM = "#8A94A3"

TAB_NAMES = {key: "Global" if key == DEFAULT_TAB else SECTORS[key]["label"] for key in TABS}
SEVERITY = {
    "high": ("HIGH", TIER_COLORS["Critical"]),
    "medium": ("MED", TIER_COLORS["Stressed"]),
    "low": ("LOW", DIM),
}
# Headlines Claude has not scored (no API key) show a dash and sort last.
UNSCORED = (DASH, DIM)
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


# --- formatting ------------------------------------------------------------------

def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def fmt(value, digits: int = 1) -> str:
    value = _num(value)
    return DASH if value is None else f"{value:.{digits}f}"


def signed(value, digits: int = 1) -> str:
    """'+1.2', '−1.2', '0.0' for near-zero, '–' when missing."""
    value = _num(value)
    if value is None:
        return DASH
    if abs(value) < 0.05:
        return f"{0:.{digits}f}"
    return ("+" if value > 0 else MINUS) + f"{abs(value):.{digits}f}"


def change_class(value) -> str:
    value = _num(value)
    if value is None:
        return "dim"
    return "neg" if value < -0.05 else "pos" if value > 0.05 else "dim"


def _tier_color(score) -> str:
    score = _num(score)
    return tier_for(score)["color"] if score is not None else DIM


def _tab_name(key: str) -> str:
    return TAB_NAMES[tab_key(key)]


def _stamp(data: dict) -> str:
    raw = data.get("last_updated_utc")
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def updated_label(data: dict, now: datetime | None = None) -> str:
    """'Updated N min ago' from the snapshot time (not the page load)."""
    raw = data.get("last_updated_utc")
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "Update time unavailable"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    minutes = int(max(0.0, ((now or datetime.now(timezone.utc)) - parsed).total_seconds()) // 60)
    if minutes < 1:
        return "Updated just now"
    if minutes < 60:
        return f"Updated {minutes} min ago"
    if minutes < 48 * 60:
        return f"Updated {minutes // 60} h ago"
    return f"Updated {minutes // (24 * 60)} days ago"


# --- sparkline ---------------------------------------------------------------------

def sparkline_svg(values, width: int = 120, height: int = 28, stroke: str = "currentColor") -> str:
    """Python port of the draft's sparkline. A missing value ends the line and the next
    point starts a new segment, so a gap is drawn as a gap and never joined."""
    points = [(i, v) for i, v in enumerate(values) if _num(v) is not None]
    if len(points) < 2:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'
    span = (len(values) - 1) or 1
    ys = [v for _, v in points]
    lo, hi = min(ys), max(ys)
    if hi - lo < 4:
        mid = (hi + lo) / 2
        lo, hi = mid - 2, mid + 2

    def x(i):
        return i / span * (width - 4) + 2

    def y(v):
        return height - 2 - (v - lo) / (hi - lo) * (height - 4)

    segments, prev = [], None
    for i, v in points:
        if prev is not None and i == prev + 1:
            segments[-1].append(f"L{x(i):.1f},{y(v):.1f}")
        else:
            segments.append([f"M{x(i):.1f},{y(v):.1f}"])
        prev = i
    # A lone point between gaps is a zero-length stroke, drawn as a dot by the round cap.
    path = " ".join(" ".join(seg if len(seg) > 1 else seg + ["h0"]) for seg in segments)
    last_i, last_v = points[-1]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
        f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{x(last_i):.1f}" cy="{y(last_v):.1f}" r="2.2" fill="{stroke}"/></svg>'
    )


def sparkline(values, width: int, height: int, stroke: str, class_name: str = "spark") -> html.Img:
    svg = sparkline_svg(values, width, height, stroke)
    return html.Img(src="data:image/svg+xml;utf8," + quote(svg), width=width, height=height,
                    alt="", className=class_name, **{"aria-hidden": "true"})


# --- header ---------------------------------------------------------------------------

def build_header(updated_label: str) -> html.Header:
    newsletter = dbc.Popover(
        dbc.PopoverBody([
            html.Label("Daily briefing by email", htmlFor="newsletter-email", className="newsletter-label"),
            dcc.Input(id="newsletter-email", type="email", placeholder="you@company.com",
                      autoComplete="email", className="newsletter-input"),
            html.Button("Subscribe", id="newsletter-submit", n_clicks=0, className="newsletter-submit"),
            html.Div(id="newsletter-feedback", role="status", className="newsletter-feedback"),
        ]),
        id="newsletter-popover",
        target="newsletter-btn",
        trigger="legacy",
        placement="bottom-end",
        className="newsletter-popover",
    )
    return html.Header([
        html.A([html.B("GSCI"), " Global Supply Chain Index"], href="/", className="brand"),
        dcc.RadioItems(
            id="profile-switch",
            options=[{"label": name, "value": key} for key, name in TAB_NAMES.items()],
            value=DEFAULT_TAB,
            inline=True,
            className="views",
            inputClassName="view-input",
            labelClassName="view-option",
            persistence=True,
            persistence_type="session",
        ),
        html.Div([
            html.Span(updated_label, id="updated-label", className="updated"),
            html.A("Methodology", href="/docs", className="opt"),
            html.Button("API", id="api-btn", n_clicks=0, className="opt link-button"),
            html.Button("CSV", id="export-btn", n_clicks=0, className="opt link-button"),
            html.A("William Blair", href=config.APP_AUTHOR_URL, target="_blank",
                   rel="noopener noreferrer", className="opt author"),
            html.Button("Subscribe", id="newsletter-btn", n_clicks=0, className="sub"),
            newsletter,
        ], className="hr"),
    ], className="head")


# --- index readout ----------------------------------------------------------------------

def build_readout(data: dict, profile_key: str, days: int = 30) -> html.Section:
    summary = index_summary(data, profile_key)
    tier = summary["tier"]
    color = tier["color"] if tier else DIM
    title = html.Div([html.Span(f"{_tab_name(profile_key)} index"), html.Span(_stamp(data))], className="ttl")
    trend = html.Div([
        html.Div(f"{days} days", className="dim spk-label"),
        sparkline(index_history(data, profile_key, days), 268, 46, AMBER),
    ], className="spk")
    if tab_key(profile_key) != DEFAULT_TAB and summary["today"] is None:
        # Fewer sector categories than the coverage minimum: no number, no tier, no change.
        return html.Section([
            title,
            html.Div("Not enough data", className="v v-empty", style={"color": color}),
            trend,
            build_chokepoints(data.get("chokepoints")),
        ], className="pane read")
    return html.Section([
        title,
        html.Div(fmt(summary["today"]), className="v num", style={"color": color}),
        html.Div(tier["label"] if tier else "No live score", className="tier", style={"color": color}),
        html.Div([
            html.Span(signed(summary["change"]), className=change_class(summary["change"])),
            " vs yesterday ",
            html.Span(fmt(summary["yday"]), className="num"),
        ], className="chg"),
        trend,
        build_chokepoints(data.get("chokepoints")),
    ], className="pane read")


# --- chokepoint traffic -----------------------------------------------------------------

CHOKE_SCALE_MAX = 200  # bar spans 0-200% of normal; the tick marks 100%


def chokepoint_color(pct) -> str:
    """Red when traffic collapses, green near normal, amber when far above
    normal (ships rerouted there from a blocked route)."""
    if pct is None:
        return DIM
    if pct < 50:
        return TIER_COLORS["Critical"]
    if pct < 80:
        return TIER_COLORS["Stressed"]
    if pct < 95:
        return TIER_COLORS["Stable"]
    if pct <= 120:
        return TIER_COLORS["Healthy"]
    return AMBER


def build_chokepoints(traffic: dict | None) -> html.Div:
    """Ship transits through major chokepoints, last 7 days vs normal."""
    items = (traffic or {}).get("chokepoints") or []
    if not items:
        return html.Div([
            html.Div("Chokepoint traffic", className="ttl choke-ttl"),
            html.P("Chokepoint traffic is unavailable right now.", className="dim"),
        ], className="choke")
    try:
        as_of = date.fromisoformat(traffic["as_of"]).strftime("%b %-d")
    except (KeyError, TypeError, ValueError):
        as_of = DASH
    rows = []
    for item in items:
        pct = _num(item.get("pct_of_normal"))
        color = chokepoint_color(pct)
        width = 0 if pct is None else min(pct, CHOKE_SCALE_MAX) / CHOKE_SCALE_MAX * 100
        detail = (
            f"{fmt(item.get('recent_per_day'))} ships/day vs "
            f"{fmt(item.get('normal_per_day'))} normal"
        )
        rows.append(html.Div([
            html.Span(plain_text(item.get("name")), className="choke-name"),
            html.Div([
                html.I(style={"width": f"{width:.0f}%", "background": color}),
                html.U(),
            ], className="choke-bar"),
            html.Span(DASH if pct is None else f"{pct:.0f}%", className="num choke-pct", style={"color": color}),
        ], className="choke-row", title=detail))
    return html.Div([
        html.Div([html.Span("Chokepoint traffic"), html.Span(f"vs normal, as of {as_of}")],
                 className="ttl choke-ttl"),
        html.Div(rows, className="choke-rows"),
        html.Div(
            f"Ship transits, last {traffic.get('recent_days', 7)} days vs "
            f"{traffic.get('baseline', 'normal')}. {PORTWATCH_CREDIT}.",
            className="dim choke-note",
        ),
    ], className="choke")


# --- market quotes ------------------------------------------------------------------------

def build_quotes(market_data: dict) -> html.Div:
    if not market_data:
        return html.Div(html.P("Market quotes are unavailable right now.", className="dim"), className="quotes")
    rows = []
    last_group = None
    for name, quote_data in market_data.items():
        quote_data = quote_data or {}
        group = quote_data.get("group")
        if group and group != last_group:
            rows.append(html.Div(group, className="quote-group"))
            last_group = group
        price = _num(quote_data.get("price"))
        pct = _num(quote_data.get("change_pct"))
        prev = _num(quote_data.get("prev"))
        if pct is None and price is not None and prev:
            pct = (price - prev) / prev * 100
        # Price only, colored by today's direction (green up, red down).
        rows.append(html.Div([
            html.Span(name),
            html.B(f"{price:,.2f}" if price is not None else DASH, className=f"num {change_class(pct)}"),
        ], className="quote"))
    return html.Div(rows, className="quotes")


# --- headlines -------------------------------------------------------------------------------

def _clean_source(source) -> str:
    text = plain_text(source)
    return text[: -len("(web search)")].rstrip() if text.endswith("(web search)") else text


def _category_label(cat) -> str:
    cat = str(cat or "")
    return CATEGORY_LABELS.get(cat) or cat.replace("_", " ").title()


def build_headlines(alerts: list[dict], limit: int | None = 10) -> html.Table:
    """Most severe first (HIGH, MED, LOW, then unscored), newest first within a severity.
    ``limit=None`` keeps all."""
    ordered = sorted(select_news(alerts or []), key=lambda a: _SEVERITY_RANK.get(a.get("severity"), 3))[:limit]
    head = html.Thead(html.Tr([
        html.Th("Sev"), html.Th("Category", className="hide-s"), html.Th("Headline"),
        html.Th("Source", className="hide-s"), html.Th("Age", className="r"),
    ]))
    if not ordered:
        body = [html.Tr(html.Td("No headlines right now.", colSpan=5, className="dim"))]
    else:
        body = []
        for alert in ordered:
            label, color = SEVERITY.get(alert.get("severity"), UNSCORED)
            title = plain_text(alert.get("title")) or "Untitled"
            url = safe_url(alert.get("url"))
            headline = (html.A(title, href=url, target="_blank", rel="noopener noreferrer")
                        if url else html.Span(title))
            stamp = alert.get("timestamp")
            body.append(html.Tr([
                html.Td(label, className="sev", style={"color": color},
                        title=None if alert.get("severity") in SEVERITY else "Unscored"),
                html.Td(_category_label(alert.get("category")), className="hide-s dim"),
                html.Td(headline, className="h"),
                html.Td(_clean_source(alert.get("source")), className="hide-s dim"),
                html.Td(_format_time_ago(str(stamp)) if stamp else DASH, className="r dim"),
            ]))
    return html.Table([head, html.Tbody(body)], className="headlines")


# --- briefing --------------------------------------------------------------------------------

def build_briefing(briefing: str) -> html.Div:
    bullets = []
    for line in str(briefing or "").split("\n"):
        text = re.sub(r"^\s*[•*\-–—]\s+", "", line).strip()
        if text:
            bullets.append(html.P(text))
    if not bullets:
        bullets = [html.P("Today's briefing is not ready yet.", className="dim")]
    return html.Div(bullets + [html.A("Read full report", href="/report", className="report-link")],
                    className="brief")


# --- category table ----------------------------------------------------------------------------

def _input_line(item: dict) -> str:
    """'Brent crude 20.1 · as of 2026-10-21 · live' (an en dash for a missing score)."""
    name = str(item.get("name") or "")
    label = INPUT_LABELS.get(name) or name.replace("_", " ").capitalize() or "Input"
    as_of = plain_text(item.get("as_of")) or DASH
    status = plain_text(item.get("status")) or DASH
    line = f"{label} {fmt(item.get('score'))} · as of {as_of} · {status}"
    record = item.get("past_record")
    if isinstance(record, dict) and record.get("record"):
        # The score is at its floor; show how far past the record the reading is.
        when = f" ({plain_text(record['when'])})" if record.get("when") else ""
        now = plain_text(item.get("raw_value"))
        line += (f" · now {now}," if now else " ·") + f" past the record of {plain_text(record['record'])}{when}"
    return line


def _detail_lines(row: dict) -> list:
    lines = []
    if row.get("source"):
        lines.append(f"Source: {plain_text(row['source'])}")
    raw_value, raw_label = row.get("raw_value"), row.get("raw_label")
    if raw_value not in (None, ""):
        lines.append(f"{plain_text(raw_label)}: {plain_text(raw_value)}" if raw_label else f"Raw value: {plain_text(raw_value)}")
    if row.get("stored_on"):
        # A stored fallback: its storage date, never presented as the data date.
        lines.append(f"Last stored reading from {plain_text(row['stored_on'])}; the live source is unavailable.")
    else:
        if row.get("as_of"):
            lines.append(f"As of: {plain_text(row['as_of'])}" + (" (stale)" if row.get("is_stale") else ""))
        if row.get("updated"):
            lines.append(f"Updated: {plain_text(row['updated'])}")
    for item in row.get("inputs") or []:
        lines.append(_input_line(item))
    if row.get("description"):
        lines.append(plain_text(row["description"]))
    if row.get("calculation"):
        lines.append(f"Calculation: {plain_text(row['calculation'])}")
    if row.get("is_fallback") and not row.get("stored_on"):
        lines.append("Live source unavailable; showing the fallback value.")
    if row.get("is_excluded"):
        lines.append("Left out of the index; the other weights are renormalized.")
    return [html.Div(line) for line in lines] or [html.Div("No source details available.")]


def _row_tag(row: dict) -> str | None:
    """One status tag per row: excluded, else fallback, else stale, else past record (score at 0
    because an input is past its worst month on record)."""
    if row.get("is_excluded"):
        return "excluded"
    if row.get("is_fallback"):
        return "fallback"
    if row.get("is_stale"):
        return "stale"
    if row.get("today") == 0 and any(isinstance(i, dict) and i.get("past_record") for i in row.get("inputs") or []):
        return "past record"
    return None


def _bar(today, yday, color) -> html.Div:
    parts = []
    if _num(today) is not None:
        parts.append(html.I(style={"width": f"{max(0.0, min(100.0, today)):.1f}%", "background": color}))
    if _num(yday) is not None:
        parts.append(html.U(style={"left": f"{max(0.0, min(100.0, yday)):.1f}%"}))
    return html.Div(parts, className="bar")


def build_category_table(data: dict, profile_key: str) -> html.Table:
    rows = category_rows(data, profile_key)
    summary = index_summary(data, profile_key)

    head = html.Thead(html.Tr([
        html.Th("Category"), html.Th("Wt", className="r hide-s"), html.Th("Score", className="score-col"),
        html.Th("Today", className="r"), html.Th("Yest.", className="r hide-s"), html.Th("Chg", className="r"),
        html.Th("Effect", className="r"), html.Th(f"{row_history_days(profile_key)} days", className="hide-s"),
    ]))

    body = []
    for row in rows:
        cat, color = row["cat"], _tier_color(row["today"])
        target = f"cat-detail-{cat}"
        tag = _row_tag(row)
        body.append(html.Tr([
            html.Td([
                html.Button(row["label"], id=target, n_clicks=0, className="cat-name", type="button"),
                html.Span(tag, className="row-tag") if tag else None,
                dbc.Tooltip(_detail_lines(row), target=target, trigger="hover focus",
                            placement="top-start", className="cat-tip"),
            ]),
            html.Td(f"{round(row['weight'] * 100)}%", className="r hide-s dim num"),
            html.Td(_bar(row["today"], row["yday"], color)),
            html.Td(fmt(row["today"]), className="r num", style={"color": color}),
            html.Td(fmt(row["yday"]), className="r hide-s dim num"),
            html.Td(signed(row["change"]), className=f"r num {change_class(row['change'])}"),
            html.Td(signed(row["effect"], 2), className=f"r num {change_class(row['effect'])}"),
            html.Td(sparkline(row["history"], 110, 18, color), className="hide-s"),
        ], className=f"is-{tag.replace(' ', '-')}" if tag else None))

    tier = summary["tier"]
    index_color = tier["color"] if tier else DIM
    index_row = html.Tr([
        html.Td(html.B("Index")),
        html.Td("100%", className="r hide-s dim num"),
        html.Td(),
        html.Td(html.B(fmt(summary["today"])), className="r num", style={"color": index_color}),
        html.Td(fmt(summary["yday"]), className="r hide-s dim num"),
        html.Td(signed(summary["change"]), className=f"r num {change_class(summary['change'])}"),
        html.Td(signed(summary["change"], 2), className=f"r num {change_class(summary['change'])}"),
        html.Td(sparkline(index_history(data, profile_key, row_history_days(profile_key)), 110, 18, index_color), className="hide-s"),
    ], className="index-row")

    return html.Table([head, html.Tbody(body), html.Tfoot(index_row)], className="categories")
