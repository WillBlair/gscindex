"""
History Page
============
Public, server-rendered /history: the Global index for every stored day, six past episodes,
how the history was made, a sign-up form and /history.csv. Everything is read from memory
(``data.long_history`` and the dashboard snapshot); no request touches the database or disk.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from flask import Flask, Response, render_template_string
from markupsafe import Markup, escape

import config
from components import history_chart, history_data, terminal_data
from data import long_history
from data.providers.chokepoints import CREDIT

DASH = "–"  # placeholder for a missing value
_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]


def safe_text(text: str) -> Markup:
    """Escaped like autoescape, except an ampersand followed by a space stays "&" (valid HTML,
    and it keeps labels such as "Energy & Fuel" readable in the page source and the CSV)."""
    return Markup(str(escape(text)).replace("&amp; ", "& "))


def fmt_date(day: date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def fmt_value(value: float | None) -> str:
    return DASH if value is None else f"{value:.1f}"


def fmt_change(value: float | None) -> str:
    return DASH if value is None else f"{value:+.1f}"


def count_word(n: int) -> str:
    """'One' to 'Ten' as words, larger counts as digits."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def episodes_title(n: int) -> str:
    return f"{count_word(n)} {'episode' if n == 1 else 'episodes'}"


def _has_history(hist: dict | None) -> bool:
    return bool(hist and hist.get("dates"))


def build_context(hist: dict | None, snapshot: dict | None) -> dict:
    """Everything the template shows, computed from the stored days and the snapshot."""
    start = date.fromisoformat(config.HISTORY_START_DATE)
    ctx = {
        "title": config.HISTORY_PAGE_TITLE,
        "description": config.HISTORY_PAGE_DESCRIPTION,
        "heading": f"Global Supply Chain Index, daily since {fmt_date(start)}",
        "loading": not _has_history(hist),
        "credit": CREDIT,
        "chart_css": Markup(history_chart.CHART_CSS),
    }
    if ctx["loading"]:
        return ctx

    points = history_data.series(hist, snapshot)
    summary = terminal_data.index_summary(snapshot, "global") if snapshot else {"today": None, "tier": None}
    ext = history_data.extremes(points)
    low, high = ext["low"], ext["high"]
    excluded = [config.CATEGORY_LABELS.get(c, c) for c in (snapshot or {}).get("excluded_categories") or []]
    tier = summary.get("tier")
    ctx["numbers"] = [
        {"label": "Today", "value": fmt_value(summary.get("today")), "color": tier["color"] if tier else None,
         "sub": tier["label"] if tier else "", "note": safe_text(f"Excluded today: {', '.join(excluded)}") if excluded else ""},
    ]
    for label, point in (("Lowest", low), ("Highest", high)):
        value = point[1] if point else None
        t = terminal_data.tier_for(value) if value is not None else None
        ctx["numbers"].append({"label": label, "value": fmt_value(value), "color": t["color"] if t else None,
                               "sub": fmt_date(point[0]) if point else "", "note": ""})

    live_from = date.fromisoformat(config.HISTORY_LIVE_FROM_DATE)
    rows = history_data.episode_rows(hist, config.HISTORY_EPISODES, config.HISTORY_CHANGE_DAYS)
    for row in rows:
        row["label"] = safe_text(row["label"])
        row["text"] = safe_text(row["text"])
        row["date_text"] = fmt_date(row["date"])
        row["index_text"] = fmt_value(row["index"])
        row["change_text"] = f"{fmt_change(row['change'])} over {config.HISTORY_CHANGE_DAYS} days" \
            if row["change"] is not None else DASH
        for cat in row["categories"]:
            cat["label"] = safe_text(cat["label"])
            cat["score_text"] = fmt_value(cat["score"])
            cat["change_text"] = fmt_change(cat["change"])
    measured = [r for r in rows if r["index"] is not None]
    day_2020 = date(2020, 4, 15)
    value_2020 = dict(zip(hist["dates"], history_data.daily_index(hist))).get(day_2020.isoformat())
    ctx.update({
        "chart": Markup(history_chart.chart_html(points, rows, live_from)),
        "episodes": rows,
        "episodes_title": episodes_title(len(rows)),
        "stable_count": sum(1 for r in measured if r["tier"]["label"] == "Stable"),
        "measured_count": len(measured),
        "live_from": fmt_date(live_from),
        "start": fmt_date(start),
        "backfill_end": fmt_date(date.fromisoformat(config.HISTORY_BACKFILL_END_DATE)),
        "backfill_month": config.HISTORY_BACKFILL_MONTH,
        "value_2020": None if value_2020 is None else f"{value_2020:.1f}",
    })
    return ctx


_PAGE_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: #000000; color: #F2F4F7;
       line-height: 1.65; -webkit-font-smoothing: antialiased; }
a { color: inherit; }
:focus-visible { outline: 1px solid #FFB020; outline-offset: 2px; }
.mono, .topbar, h1, h2, .num, .ep-meta, table, summary, .btn, .badge { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; }
.topbar { position: sticky; top: 0; z-index: 100; background: #000000; border-bottom: 1px solid #1D232B;
          padding: 0 16px; height: 44px; display: flex; align-items: center; gap: 22px; font-size: 13px; }
.topbar a { text-decoration: none; color: #8A94A3; white-space: nowrap; }
.topbar a:hover { color: #F2F4F7; }
.topbar .brand { font-weight: 700; letter-spacing: 0.02em; color: #F2F4F7; margin-right: auto; }
.topbar .brand b { color: #FFB020; }
.pane { max-width: 1100px; margin: 32px auto 80px; background: #07090C; border: 1px solid #1D232B; }
section, header.head { padding: 24px 28px; border-top: 1px solid #1D232B; }
header.head { border-top: 0; }
h1 { font-size: 20px; font-weight: 500; color: #F2F4F7; line-height: 1.3; }
h2 { font-size: 13px; font-weight: 400; color: #FFB020; margin-bottom: 12px; }
p { font-size: 15px; color: #D6DBE3; margin-bottom: 14px; overflow-wrap: anywhere; }
p:last-child { margin-bottom: 0; }
p a, .ep-text a { color: #FFB020; text-decoration: none; }
p a:hover, .ep-text a:hover { text-decoration: underline; }
.numbers { display: flex; gap: 0; padding: 0; }
.numbers .n { flex: 1 1 0; min-width: 0; padding: 20px 28px; border-left: 1px solid #1D232B; }
.numbers .n:first-child { border-left: 0; }
.n .lab { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 12px; color: #8A94A3; }
.n .num { font-size: 56px; font-weight: 500; letter-spacing: -0.03em; line-height: 1.1; }
.n .sub { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 13px; color: #8A94A3; min-height: 20px; }
.n .note { font-size: 12px; color: #FF8A3D; margin: 6px 0 0; }
.ep { padding: 16px 0; border-top: 1px solid #1D232B; }
.ep:first-of-type { border-top: 0; }
.ep-top { display: grid; grid-template-columns: 28px 120px minmax(0, 1fr) 120px 150px; gap: 12px; align-items: baseline; }
.ep-n { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 13px; color: #FFB020; }
.ep-meta { font-size: 13px; color: #8A94A3; }
.ep-label { font-size: 15px; font-weight: 600; color: #F2F4F7; }
.ep-text { font-size: 15px; color: #D6DBE3; margin: 4px 0 0; }
.ep-idx { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 13px; }
.ep-chg { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 13px; color: #8A94A3; }
details { margin-top: 8px; }
summary { font-size: 12px; color: #8A94A3; cursor: pointer; }
table { width: 100%; max-width: 520px; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
th { color: #8A94A3; font-weight: 400; text-align: left; padding: 0 10px 6px 0; border-bottom: 1px solid #1D232B; }
td { padding: 6px 10px 6px 0; border-bottom: 1px solid #1D232B; }
td.r, th.r { text-align: right; }
.signup-row { display: flex; align-items: center; gap: 16px; }
.badge { background: #FFB020; color: #07090C; font-weight: 800; font-size: 15px; letter-spacing: 0.04em; padding: 4px 9px; line-height: 1.2; }
.signup-row p { margin: 0; }
form { display: flex; margin-top: 14px; max-width: 520px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
input[type=email] { flex: 1 1 auto; min-width: 0; background: #000000; color: #F2F4F7; border: 1px solid #1D232B; border-right: 0;
                    border-radius: 0; padding: 10px; font: inherit; font-size: 16px; }
input[type=email]:focus { outline: none; border-color: #FFB020; }
.btn { background: #FFB020; color: #000000; border: 0; border-radius: 0; padding: 10px 16px; font-weight: 800; font-size: 14px; white-space: nowrap; cursor: pointer; }
.btn:hover { filter: brightness(1.08); }
.dl a.btn { display: inline-block; text-decoration: none; margin-bottom: 14px; }
@media (max-width: 760px) {
  .pane { margin: 0; border: 0; }
  section, header.head { padding: 20px 16px; }
  .numbers { flex-direction: column; }
  .numbers .n { border-left: 0; border-top: 1px solid #1D232B; padding: 16px; }
  .numbers .n:first-child { border-top: 0; }
  .n .num { font-size: 44px; }
  .ep-top { grid-template-columns: 24px minmax(0, 1fr); row-gap: 2px; }
  .ep-top > :nth-child(n+3) { grid-column: 2; }
  .signup-row { flex-wrap: wrap; gap: 10px; }
  .topbar .brand span { display: none; }
  .topbar { gap: 16px; }
}
"""

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{{ title }}</title>
<meta name="description" content="{{ description }}" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
<style>{{ page_css }}{{ chart_css }}</style>
</head>
<body>
<nav class="topbar">
  <a href="/" class="brand"><b>GSCI</b><span> Global Supply Chain Index</span></a>
  <a href="/">Dashboard</a>
  <a href="/docs">Methodology</a>
</nav>
<main class="pane">
<header class="head"><h1>{{ heading }}</h1></header>
{% if loading %}
<section><p>History is loading. Reload in a minute.</p></section>
{% else %}
<div class="numbers">
{% for n in numbers %}
  <div class="n">
    <div class="lab">{{ n.label }}</div>
    <div class="num"{% if n.color %} style="color:{{ n.color }}"{% endif %}>{{ n.value }}</div>
    <div class="sub">{{ n.sub }}</div>
    {% if n.note %}<p class="note">{{ n.note }}</p>{% endif %}
  </div>
{% endfor %}
</div>
<section id="chart">
{{ chart }}
<p style="margin-top:14px">The index moves when several categories are under stress for weeks. A single event shows in its own category and can leave the index Stable.</p>
</section>
<section id="episodes">
<h2>{{ episodes_title }}</h2>
<p>These dates were fixed in the methodology research before this page existed. The index was Stable on {{ stable_count }} of the {{ measured_count }}.</p>
{% for e in episodes %}
<div class="ep" id="ep-{{ e.n }}">
  <div class="ep-top">
    <span class="ep-n">{{ e.n }}</span>
    <span class="ep-meta">{{ e.date_text }}</span>
    <div>
      <div class="ep-label">{{ e.label }}</div>
      {% if e.text %}<p class="ep-text">{{ e.text }}{% if e.source_url %} <a href="{{ e.source_url }}" rel="noopener">Source</a>{% endif %}</p>{% endif %}
    </div>
    <span class="ep-idx">{{ e.index_text }}{% if e.tier %} <span style="color:{{ e.tier.color }}">{{ e.tier.label }}</span>{% endif %}</span>
    <span class="ep-chg">{{ e.change_text }}</span>
  </div>
  <details>
    <summary>All eight categories</summary>
    <table>
      <thead><tr><th>Category</th><th class="r">Score</th><th class="r">90-day change</th></tr></thead>
      <tbody>
      {% for c in e.categories %}
        <tr><td>{{ c.label }}</td><td class="r">{{ c.score_text }}</td><td class="r">{{ c.change_text }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </details>
</div>
{% endfor %}
</section>
<section id="how">
<h2>How this history was made</h2>
<p>Recomputed, then recorded. Days before {{ live_from }} were calculated afterwards from the source data, so they include later revisions and are not what a live site showed that day. Days from {{ start }} to {{ backfill_end }} were calculated in {{ backfill_month }}. Days from 23 July 2026 to 22 October 2026 were calculated on 23 October 2026. Monthly and weekly figures sit on the day they were published. Daily figures (oil and diesel prices, the geopolitical risk and trade policy uncertainty indexes) sit on their own day.</p>
<p>The scale was set on this same history. In each category, 0 is the worst month on record through 2025, so the worst months of 2021 score near 0 in their category by construction. The chart shows how the scale reads the past. It is not a test of prediction.</p>
<p>{% if value_2020 %}A demand collapse reads as healthy costs. On 15 April 2020 the index was {{ value_2020 }}, because oil and metal prices fell.{% else %}In a demand collapse oil and metal prices fall, so the cost categories read as healthy.{% endif %} <a href="/docs">Limitations</a></p>
<p>Chokepoint traffic is compared with 2022 to 2023 volumes for every year, including 2019 to 2021.</p>
</section>
{% endif %}
<section id="signup">
  <div class="signup-row"><span class="badge">FREE</span><p>Get this index in your inbox every day. Today's score and a short briefing on the news behind it.</p></div>
  <form method="post" action="/history/signup">
    <label for="history-email" class="sr">Email address</label>
    <input type="email" id="history-email" name="email" autocomplete="email" placeholder="you@company.com" required />
    <button type="submit" class="btn">Sign up free</button>
  </form>
</section>
<section id="download" class="dl">
  <a class="btn" href="/history.csv">Download CSV</a>
  <p>License: CC-BY-4.0. {{ credit }} <a href="/docs">Methodology</a></p>
</section>
</main>
</body>
</html>
"""


def register_history_routes(server: Flask, get_snapshot: Callable[[], tuple[dict | None, bool]], limiter) -> None:
    """Register GET /history and GET /history.csv (the sign-up POST is added separately)."""

    @server.route("/history")
    def history_page():
        snapshot, _fresh = get_snapshot()
        ctx = build_context(long_history.get(), snapshot)
        return render_template_string(_TEMPLATE, page_css=Markup(_PAGE_CSS), **ctx)

    @server.route("/history.csv")
    def history_csv():
        hist = long_history.get()
        if not _has_history(hist):
            return Response("History is loading.", status=503, mimetype="text/plain")
        snapshot, _fresh = get_snapshot()
        return Response(
            history_data.history_csv(hist, snapshot),
            mimetype="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="gscindex-history.csv"',
                "Cache-Control": "public, max-age=3600",
            },
        )
