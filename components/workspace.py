"""Monitoring tools built exclusively from the existing dashboard snapshot."""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pandas as pd
from dash import html

from config import CATEGORY_LABELS, DEFAULT_PROFILE, INDUSTRY_PROFILES
from scoring import compute_composite_index, get_health_tier


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    """Strip RSS markup without ever rendering publisher HTML."""
    parser = _PlainText()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def safe_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def profile_for(key):
    return INDUSTRY_PROFILES.get(key, INDUSTRY_PROFILES[DEFAULT_PROFILE])


def finite_score(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def composite_for(data, key):
    weights = profile_for(key)["weights"]
    scores = data.get("current_scores", {})
    if any(not finite_score(scores.get(cat)) for cat in weights):
        return None
    return compute_composite_index(scores, weights)


def daily_delta(data, key):
    """Compare the same profile on adjacent calendar dates, never across gaps."""
    weights = profile_for(key)["weights"]
    metadata = data.get("category_metadata", {})
    history = data.get("category_history", {})
    if any(metadata.get(cat, {}).get("is_fallback") or cat not in history for cat in weights):
        return None
    frame = pd.DataFrame({cat: history[cat] for cat in weights}).sort_index()
    if len(frame) < 2 or frame.iloc[-2:].isna().any().any():
        return None
    if frame.index[-1] - frame.index[-2] != pd.Timedelta(days=1):
        return None
    current = composite_for(data, key)
    if current is None:
        return None
    return round(current - sum(weights[c] * float(frame[c].iloc[-2]) for c in weights), 1)


def tier_pill(score):
    tier = get_health_tier(score)
    return html.Span(tier["label"], className="status-pill tier-" + tier["label"].lower())


def build_overview(data, key=DEFAULT_PROFILE, provisional=False):
    profile = profile_for(key)
    scores = data.get("current_scores", {})
    score = composite_for(data, key)
    delta = None if provisional else daily_delta(data, key)
    return html.Div([
        html.Div([html.Span("HEALTH INDEX", className="eyebrow"),
                  tier_pill(score) if score is not None else html.Span("No data", className="status-pill")], className="panel-heading"),
        html.Div([html.Span(f"{score:.1f}" if score is not None else "—", className="hero-score"),
                  html.Span("/ 100", className="score-denominator")], className="score-line"),
        html.Div("Δ —" if delta is None else
                 f"{'↑' if delta > 0 else '↓' if delta < 0 else '→'} {abs(delta):.1f} pts / day",
                 className="score-change " + ("positive" if delta and delta > 0 else "negative" if delta and delta < 0 else "")),
        html.Span("0–100 · higher is healthier", className="scale-caption"),
    ])


def build_drivers(data, key=DEFAULT_PROFILE):
    weights = profile_for(key)["weights"]
    scores = data.get("current_scores", {})
    meta = data.get("category_metadata", {})
    ranked = sorted([(c, (100 - scores[c]) * w) for c, w in weights.items()
                     if finite_score(scores.get(c))], key=lambda x: x[1], reverse=True)[:3]
    return html.Div([
        html.H2("Top drags", className="driver-heading", title="Largest weighted contributions to the gap from 100"),
        *[html.Div([
            html.Div([html.Span(f"0{i + 1}", className="driver-rank"),
                      html.Div([html.Strong(CATEGORY_LABELS.get(cat, cat)),
                                html.Small("Fallback estimate" if meta.get(cat, {}).get("is_fallback") else f"{weights[cat]:.0%} weight")]),
                      html.Span(f"−{pressure:.1f}", className="driver-value")], className="driver-row"),
            html.Div(html.Div(style={"width": f"{min(100, pressure / max(ranked[0][1], 1) * 100)}%"}), className="driver-track"),
        ], className="driver-item") for i, (cat, pressure) in enumerate(ranked)],
    ])


def build_freshness(data, key, provisional=False, now=None):
    now = now or datetime.now(timezone.utc)
    raw = data.get("last_updated_utc")
    try:
        updated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = max(0, (now - updated).total_seconds())
        stamp = updated.astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    except (ValueError, TypeError):
        age, stamp = float("inf"), "Update time unavailable"
    metadata = data.get("category_metadata", {})
    scores = data.get("current_scores", {})
    missing = [CATEGORY_LABELS.get(c, c) for c in profile_for(key)["weights"]
               if metadata.get(c, {}).get("is_fallback") or not finite_score(scores.get(c))]
    stale = provisional or age > 1800
    label = "Cached snapshot" if stale else "Partial coverage" if missing else "Latest snapshot"
    return html.Div([
        html.Span([html.Span(className="status-dot"), label], className="snapshot-label"),
        html.Span(stamp),
        html.Span(f"{len(missing)} fallback", title=", ".join(missing), className="fallback-summary") if missing else None,
    ], className="freshness-strip" + (" freshness-warning" if stale or missing else ""), role="status")


def select_ports(markers, query="", tier="all", saved=None, only_saved=False, order="risk"):
    saved = saved or []
    query = (query or "").strip().casefold()
    selected = [m for m in markers if finite_score(m.get("score"))
                and query in m.get("name", "").casefold()
                and (tier == "all" or get_health_tier(m["score"])["label"].lower() == tier)
                and (not only_saved or m.get("name") in saved)]
    return sorted(selected, key=(lambda m: m["name"]) if order == "name" else (lambda m: (m["score"], m["name"])))


def build_port_rows(markers, saved=None):
    saved = saved or []
    if not markers:
        return html.Div([html.Strong("No matching ports"), html.P("Clear search or change filters.")], className="empty-state")
    return html.Table([
        html.Thead(html.Tr([html.Th("Watch", scope="col"), html.Th("Port", scope="col"),
                           html.Th("Health", scope="col"), html.Th("Condition", scope="col"), html.Th("Context", scope="col")])),
        html.Tbody([html.Tr([
            html.Td(html.Button("★" if m["name"] in saved else "☆", id={"type": "watch-port", "index": m["name"]}, n_clicks=0,
                                className="watch-button" + (" is-saved" if m["name"] in saved else ""),
                                **{"aria-label": ("Unsave " if m["name"] in saved else "Save ") + m["name"], "aria-pressed": str(m["name"] in saved).lower()})),
            html.Th(m["name"], scope="row"), html.Td(f'{m["score"]:.1f}', className="port-score"),
            html.Td(tier_pill(m["score"])),
            html.Td(html.Details([html.Summary("View conditions"), html.P(plain_text(m.get("description", "No additional context available.")))], className="port-context")),
        ]) for m in markers]),
    ], className="port-table")


def select_news(alerts, query="", severity="all", category="all"):
    query = (query or "").strip().casefold()
    selected = [a for a in alerts if (severity == "all" or a.get("severity") == severity)
                and (category == "all" or a.get("category") == category)
                and query in plain_text(" ".join(str(a.get(k) or "") for k in ("title", "body", "source"))).casefold()]
    return sorted(selected, key=lambda a: str(a.get("timestamp") or ""), reverse=True)


def snapshot_csv(data, key):
    """A profile-scoped export with provenance and fallback status."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["snapshot_utc", "profile", "category", "score", "weight", "weighted_points", "status", "source", "source_updated"])
    def cell(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    for cat, weight in profile_for(key)["weights"].items():
        score = data.get("current_scores", {}).get(cat)
        meta = data.get("category_metadata", {}).get(cat, {})
        available = finite_score(score)
        writer.writerow([cell(data.get("last_updated_utc")), cell(profile_for(key)["label"]), CATEGORY_LABELS.get(cat, cat),
                         score if available else "", weight, round(score * weight, 3) if available else "",
                         "missing" if not available else "fallback" if meta.get("is_fallback") else "measured",
                         cell(meta.get("source")), cell(meta.get("updated"))])
    return output.getvalue()
