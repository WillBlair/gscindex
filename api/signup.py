"""/briefing: the landing page for the daily email (ad links point here).

Today's Global index, a big email box, and today's briefing as a sample. A plain HTML form
(no Dash), so it loads fast on a phone. The form posts to the same URL, so the utm tags on
an ad link are still in the query string and are stored as the subscriber's source.
"""
from __future__ import annotations

import re
from typing import Callable

from flask import Flask, render_template_string, request

from api.share import card_numbers, signup_source
from data.providers.chokepoints import CREDIT as PORTWATCH_CREDIT

SnapshotGetter = Callable[[], tuple[dict | None, bool]]

# Letters, digits and . _ % + - in the local part; no quotes, commas or spaces, which
# could otherwise end up inside the email To header. Shared with the dashboard form.
EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}")
SIGNUP_RATE_LIMIT = "10 per hour"   # POST only, per visitor IP
SAMPLE_BULLETS = 3

_SENT_AT = "15:00 UTC"   # the GSC Newsletter Dispatch cron on Render (0 15 * * *)


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(EMAIL_RE.fullmatch(email))


def briefing_bullets(briefing: str | None, limit: int = SAMPLE_BULLETS) -> list[str]:
    """Briefing lines without their bullet characters, as the newsletter formats them."""
    lines = [line.strip().lstrip(" -*•").strip() for line in str(briefing or "").split("\n")]
    return [line for line in lines if line][:limit]


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily supply chain briefing | Global Supply Chain Index</title>
<meta name="description" content="One free email a day: the Global Supply Chain Index and a short briefing on the news behind it.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* Terminal look (assets/terminal.css): black, 1px rules, mono chrome, Inter prose, amber titles. */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: #000000; color: #F2F4F7;
         line-height: 1.6; -webkit-font-smoothing: antialiased; }
  a { color: inherit; }
  :focus-visible { outline: 1px solid #FFB020; outline-offset: 2px; }
  .mono { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; }
  .topbar { border-bottom: 1px solid #1D232B; padding: 0 16px; height: 44px; display: flex; align-items: center;
            font-size: 13px; }
  .topbar-brand { font-weight: 700; letter-spacing: 0.02em; text-decoration: none; }
  .topbar-brand b { color: #FFB020; }
  .topbar-back { margin-left: auto; color: #8A94A3; text-decoration: none; }
  .topbar-back:hover { color: #F2F4F7; }
  .wrap { max-width: 760px; margin: 40px auto 64px; padding: 0 16px; }
  .eyebrow { color: #FFB020; font-size: 13px; letter-spacing: 0.04em; }
  h1 { font-size: 40px; line-height: 1.15; font-weight: 600; margin: 12px 0 14px; letter-spacing: -0.01em; }
  .lede { font-size: 18px; color: #D6DBE3; max-width: 620px; }
  .pane { background: #07090C; border: 1px solid #1D232B; padding: 22px 24px; margin-top: 28px; }
  .pane-title { color: #FFB020; font-size: 13px; margin-bottom: 14px; display: flex; justify-content: space-between;
                gap: 12px; flex-wrap: wrap; }
  .pane-title span:last-child { color: #8A94A3; }
  form { display: flex; gap: 10px; flex-wrap: wrap; }
  input[type=email] { flex: 1 1 280px; min-width: 0; font: 500 18px 'JetBrains Mono', ui-monospace, monospace;
                      background: #000000; color: #F2F4F7; border: 1px solid #3A4350; padding: 16px 14px; border-radius: 0; }
  input[type=email]:focus { border-color: #FFB020; outline: none; }
  button { flex: 0 0 auto; font: 700 16px 'JetBrains Mono', ui-monospace, monospace; background: #FFB020; color: #000000;
           border: 0; padding: 16px 22px; cursor: pointer; border-radius: 0; }
  button:hover { background: #FFC24D; }
  .hp { position: absolute; left: -10000px; width: 1px; height: 1px; overflow: hidden; }
  .fine { color: #8A94A3; font-size: 13px; margin-top: 12px; }
  .msg { margin-top: 14px; font-size: 15px; }
  .msg.ok { color: #35D07F; }
  .msg.err { color: #FF4D5E; }
  .score { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
  .score-num { font: 700 72px/1 'JetBrains Mono', ui-monospace, monospace; }
  .score-tier { font: 700 20px 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.04em; }
  .score-change { color: #8A94A3; font-size: 15px; }
  .bar { display: flex; height: 8px; margin-top: 18px; position: relative; }
  .bar i { display: block; height: 100%; margin-right: 3px; }
  .bar u { position: absolute; top: -7px; width: 4px; height: 22px; background: #F2F4F7; margin-left: -2px; }
  ul.brief { list-style: none; }
  ul.brief li { padding: 12px 0; border-top: 1px solid #1D232B; color: #D6DBE3; font-size: 15px; }
  ul.brief li:first-child { border-top: 0; padding-top: 0; }
  .footer { margin-top: 32px; padding-top: 14px; border-top: 1px solid #1D232B; font-size: 12px; color: #8A94A3;
            display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .footer a { color: #FFB020; text-decoration: none; }
  @media (max-width: 760px) {
    .wrap { margin-top: 24px; }
    h1 { font-size: 30px; }
    .lede { font-size: 16px; }
    .pane { padding: 18px 16px; }
    button { width: 100%; }
    .score-num { font-size: 56px; }
  }
</style>
</head>
<body>
<div class="topbar mono">
  <a class="topbar-brand" href="/"><b>GSC</b> Index</a>
  <a class="topbar-back" href="/">Open the dashboard</a>
</div>
<main class="wrap">
  <div class="eyebrow mono">FREE DAILY BRIEFING</div>
  <h1>Global supply chain stress, scored every day.</h1>
  <p class="lede">One email a day with the Global Supply Chain Index, a 0 to 100 score built from NY Fed, IMF and
    Federal Reserve data, and a short briefing on the news behind it.</p>

  <section class="pane" aria-label="Sign up">
    {% if subscribed %}
      <p class="msg ok mono">You're subscribed. The next briefing goes out at {{ sent_at }}.</p>
    {% else %}
      <form method="post" novalidate>
        <label class="hp" for="website">Leave this empty</label>
        <input class="hp" id="website" name="website" type="text" tabindex="-1" autocomplete="off">
        <input type="email" name="email" value="{{ email }}" placeholder="you@company.com" autocomplete="email"
               aria-label="Email address" required>
        <button type="submit">Get the briefing</button>
      </form>
      {% if error %}<p class="msg err">{{ error }}</p>{% endif %}
      <p class="fine">Sent once a day at {{ sent_at }}. Unsubscribe with one click from any email.</p>
    {% endif %}
  </section>

  {% if today is not none %}
  <section class="pane" aria-label="Today's index">
    <div class="pane-title mono"><span>TODAY'S INDEX</span><span>{{ updated }}</span></div>
    <div class="score">
      <span class="score-num" style="color: {{ tier_color }}">{{ "%.1f"|format(today) }}</span>
      <span class="score-tier" style="color: {{ tier_color }}">{{ tier_label|upper }}</span>
      {% if change_text %}<span class="score-change">{{ change_text }}</span>{% endif %}
    </div>
    <div class="bar" aria-hidden="true">
      {% for width, color in bands %}<i style="flex: {{ width }}; background: {{ color }}"></i>{% endfor %}
      <u style="left: {{ "%.1f"|format(tick) }}%"></u>
    </div>
  </section>
  {% endif %}

  {% if bullets %}
  <section class="pane" aria-label="Sample briefing">
    <div class="pane-title mono"><span>TODAY'S BRIEFING</span><span>sample</span></div>
    <ul class="brief">{% for line in bullets %}<li>{{ line }}</li>{% endfor %}</ul>
  </section>
  {% endif %}

  <div class="footer mono">
    <span>{{ credit }}</span>
    <span><a href="/docs">Methodology</a> &nbsp; <a href="/">Dashboard</a></span>
  </div>
</main>
</body>
</html>
"""

_BANDS = ((40, "Critical"), (20, "Stressed"), (20, "Stable"), (20, "Healthy"))


def render_page(data: dict | None, *, subscribed: bool = False, error: str = "", email: str = "") -> str:
    from components.terminal_data import TIER_COLORS

    summary = card_numbers(data)["global"] or {}
    today, tier = summary.get("today"), summary.get("tier")
    change = summary.get("change")
    change_text = ""
    if today is not None and change is not None:
        change_text = ("Unchanged from yesterday" if round(change, 1) == 0
                       else f"{'Up' if change > 0 else 'Down'} {abs(change):.1f} from yesterday")
    updated = str((data or {}).get("last_updated_utc") or "")[:16].replace("T", " ")
    return render_template_string(
        _TEMPLATE,
        subscribed=subscribed, error=error, email=email, sent_at=_SENT_AT,
        today=today if tier else None,
        tier_label=(tier or {}).get("label", ""), tier_color=(tier or {}).get("color", "#F2F4F7"),
        change_text=change_text, updated=f"{updated} UTC" if updated else "",
        tick=max(0.0, min(100.0, today or 0.0)),
        bands=[(w, TIER_COLORS[label]) for w, label in _BANDS],
        bullets=briefing_bullets((data or {}).get("briefing")),
        credit=PORTWATCH_CREDIT,
    )


def register_signup_routes(server: Flask, get_snapshot: SnapshotGetter, limiter=None) -> None:
    def briefing_page():
        data, _ = get_snapshot()
        if request.method == "GET":
            return render_page(data)
        if request.form.get("website"):            # honeypot: bots fill every field
            return render_page(data, subscribed=True)
        email = str(request.form.get("email") or "").strip().lower()
        if not valid_email(email):
            return render_page(data, error="Please enter a valid email address.", email=email[:254]), 400
        from data.database import add_subscriber
        result = add_subscriber(email, signup_source(request.query_string.decode("utf-8", "replace")))
        if result.get("success"):
            return render_page(data, subscribed=True)
        return render_page(data, error=result.get("message", "An error occurred."), email=email), 400

    view = briefing_page
    if limiter is not None:
        view = limiter.limit(SIGNUP_RATE_LIMIT, methods=["POST"])(view)
    server.add_url_rule("/briefing", "briefing_page", view, methods=["GET", "POST"])
