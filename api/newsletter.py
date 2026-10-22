"""
Newsletter unsubscribe endpoints.

GET shows a confirmation button (mail scanners prefetch links, so a GET
must not unsubscribe). POST unsubscribes; it also serves RFC 8058 one-click
requests from mail clients via the List-Unsubscribe-Post header.
"""
from __future__ import annotations

import logging

from flask import Blueprint, render_template_string, request

from data.database import unsubscribe_user
from data.unsubscribe import verify_token

logger = logging.getLogger(__name__)

newsletter_bp = Blueprint("newsletter", __name__)

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unsubscribe | Global Supply Chain Index</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0f1117;color:#e1e4ea;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:16px}
  main{max-width:440px;text-align:center}
  h1{font-size:22px;margin:0 0 12px}
  p{color:#a0a6b4;line-height:1.5}
  button{margin-top:16px;padding:12px 20px;border:0;border-radius:8px;background:#e1e4ea;color:#0f1117;
         font-size:15px;font-weight:600;cursor:pointer}
  a{color:#e1e4ea}
</style></head><body><main>
  <h1>{{ title }}</h1>
  <p>{{ message }}</p>
  {% if show_button %}
  <form method="post" action="/unsubscribe?t={{ token }}">
    <button type="submit">Unsubscribe {{ email }}</button>
  </form>
  {% endif %}
  <p><a href="/">Back to the dashboard</a></p>
</main></body></html>"""


def _render(title: str, message: str, *, token: str = "", email: str = "", show_button=False, status=200):
    return (
        render_template_string(
            _PAGE, title=title, message=message, token=token, email=email, show_button=show_button
        ),
        status,
    )


@newsletter_bp.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    token = request.args.get("t", "")
    email = verify_token(token)
    if not email:
        return _render(
            "Link not valid",
            "This unsubscribe link is invalid or incomplete. Use the link from your most recent briefing.",
            status=400,
        )

    if request.method == "GET":
        return _render(
            "Unsubscribe from the daily briefing?",
            "You will stop receiving the Global Supply Chain Index morning email.",
            token=token,
            email=email,
            show_button=True,
        )

    if not unsubscribe_user(email):
        logger.error("Unsubscribe failed for a valid token")
        return _render(
            "Something went wrong",
            "We couldn't process the request. Please try the link again in a few minutes.",
            status=500,
        )
    return _render("You're unsubscribed", f"{email} will no longer receive the daily briefing.")
