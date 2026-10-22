"""
Full Report Page
================
Serves the daily supply chain intelligence report as a clean,
standalone HTML page at /report.
"""
from flask import Blueprint, render_template_string
import html
import re
import markdown

from config import NEWS_BRIEFING_CACHE_KEY, NEWS_CACHE_MAX_AGE_SECONDS
from data.cache import get_cached

report_bp = Blueprint("report", __name__)

_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Daily Intelligence Report — GSC Index</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
    <style>
        /* Terminal look (assets/terminal.css): black, 1px rules, mono chrome, Inter prose, amber titles. */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background-color: #000000;
            color: #F2F4F7;
            line-height: 1.65;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        a { color: inherit; }
        :focus-visible { outline: 1px solid #FFB020; outline-offset: 2px; }

        /* ── Top bar ───────────────────────────────────────────── */
        .topbar {
            position: sticky;
            top: 0;
            z-index: 100;
            background: #000000;
            border-bottom: 1px solid #1D232B;
            padding: 0 16px;
            height: 44px;
            display: flex;
            align-items: center;
            gap: 22px;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 13px;
        }
        .topbar-brand { font-weight: 700; letter-spacing: 0.02em; white-space: nowrap; color: #F2F4F7; text-decoration: none; }
        .topbar-brand b { color: #FFB020; }
        .topbar-back { margin-left: auto; color: #8A94A3; text-decoration: none; white-space: nowrap; }
        .topbar-back:hover { color: #F2F4F7; }

        /* ── Article pane ──────────────────────────────────────── */
        .article-container {
            max-width: 760px;
            margin: 32px auto 80px;
            background: #07090C;
            border: 1px solid #1D232B;
            padding: 24px 28px 28px;
        }

        .article-meta {
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid #1D232B;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
        }
        .article-title { font-size: 13px; font-weight: 400; color: #FFB020; }
        .article-date { font-size: 13px; color: #8A94A3; }

        /* ── Prose ─────────────────────────────────────────────── */
        .prose { font-size: 15px; color: #D6DBE3; }
        .prose h2 {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 13px;
            font-weight: 400;
            color: #FFB020;
            margin: 32px 0 12px;
            padding-top: 16px;
            border-top: 1px solid #1D232B;
        }
        .prose > h2:first-child { margin-top: 0; padding-top: 0; border-top: 0; }
        .prose h3 { font-size: 15px; font-weight: 600; color: #F2F4F7; margin: 24px 0 8px; }
        .prose p { margin-bottom: 16px; }
        .prose strong { color: #F2F4F7; font-weight: 600; }
        .prose em { color: #8A94A3; }
        .prose ul, .prose ol { margin-bottom: 16px; padding-left: 22px; }
        .prose li { margin-bottom: 6px; }
        .prose li::marker { color: #8A94A3; }
        .prose a { color: #FFB020; text-decoration: none; }
        .prose a:hover { text-decoration: underline; }
        .prose blockquote {
            margin: 20px 0;
            padding: 0 0 0 20px;
            color: #8A94A3;
        }
        .prose code {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 13px;
            background: #000000;
            border: 1px solid #1D232B;
            padding: 1px 5px;
        }
        .prose hr { border: none; border-top: 1px solid #1D232B; margin: 28px 0; }
        .prose table { width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 13px; }
        .prose th { color: #8A94A3; font-weight: 400; text-align: left; padding: 0 10px 6px 0; border-bottom: 1px solid #1D232B; }
        .prose td { padding: 7px 10px 7px 0; border-bottom: 1px solid #1D232B; }

        /* ── Footer ────────────────────────────────────────────── */
        .report-footer {
            margin-top: 32px;
            padding-top: 14px;
            border-top: 1px solid #1D232B;
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 12px;
        }
        .report-footer-text { color: #8A94A3; }
        .report-footer-link { color: #FFB020; text-decoration: none; }
        .report-footer-link:hover { text-decoration: underline; }

        @media (max-width: 760px) {
            .article-container { margin: 0; border: 0; border-bottom: 1px solid #1D232B; padding: 20px 16px 28px; }
            .topbar-brand span { display: none; }
            .prose { overflow-wrap: anywhere; }
        }
    </style>
</head>
<body>

    <!-- Top Bar -->
    <nav class="topbar">
        <a href="/" class="topbar-brand"><b>GSCI</b><span> Global Supply Chain Index</span></a>
        <a href="/" class="topbar-back">&larr; Dashboard</a>
    </nav>

    <!-- Article -->
    <article class="article-container">
        <header class="article-meta">
            <h1 class="article-title">Daily Supply Chain Intelligence Report</h1>
            <p class="article-date">{{ date }}</p>
        </header>

        <div class="prose">
            {{ content }}
        </div>

        <footer class="report-footer">
            <a href="/" class="report-footer-link">&larr; Dashboard</a>
            <span class="report-footer-text">Generated by GSC Index AI &middot; Sources: Supply Chain Dive, FreightWaves, Logistics Management</span>
        </footer>
    </article>

</body>
</html>
"""


@report_bp.route("/report")
def serve_report():
    """Serve the full report as a clean standalone page."""
    from datetime import datetime
    from markupsafe import Markup
    from zoneinfo import ZoneInfo

    cached = get_cached(NEWS_BRIEFING_CACHE_KEY, ttl=NEWS_CACHE_MAX_AGE_SECONDS)
    report_md = ""
    report_generated = None

    if cached and isinstance(cached, dict):
        report_md = cached.get("full_report", "")
        generated_at = cached.get("generated_at")
        if report_md and isinstance(generated_at, (int, float)):
            report_generated = datetime.fromtimestamp(generated_at, tz=ZoneInfo("UTC"))

    if not report_md:
        # Fallback: try the persisted dashboard snapshot (survives deploys)
        from data.cache import get_cached_dashboard
        dashboard = get_cached_dashboard()
        if dashboard and isinstance(dashboard, dict):
            report_md = dashboard.get("full_report", "")
            raw_last_updated = dashboard.get("last_updated_utc")
            if isinstance(raw_last_updated, str) and raw_last_updated:
                try:
                    report_generated = datetime.fromisoformat(raw_last_updated.replace("Z", "+00:00"))
                except ValueError:
                    report_generated = None

    if not report_md:
        report_md = "## Report Not Yet Available\nThe system is generating the daily report. Please check back in a few minutes."

    # Escape raw HTML first so untrusted inline tags/scripts cannot execute.
    escaped_md = html.escape(report_md)

    # Convert markdown to HTML.
    raw_report_html = markdown.markdown(
        escaped_md,
        extensions=["extra", "smarty"]
    )

    # Block dangerous link protocols that markdown may still render.
    report_html = re.sub(
        r'href\s*=\s*"(?:\s*javascript:|\s*data:)[^"]*"',
        'href="#" rel="nofollow noopener noreferrer"',
        raw_report_html,
        flags=re.IGNORECASE,
    )
    report_html = re.sub(
        r"href\s*=\s*'(?:\s*javascript:|\s*data:)[^']*'",
        "href='#' rel='nofollow noopener noreferrer'",
        report_html,
        flags=re.IGNORECASE,
    )

    display_dt = report_generated or datetime.now(ZoneInfo("America/Denver"))
    if display_dt.tzinfo is None:
        display_dt = display_dt.replace(tzinfo=ZoneInfo("UTC"))
    display_dt = display_dt.astimezone(ZoneInfo("America/Denver"))
    report_date = display_dt.strftime("%B %d, %Y")


    return render_template_string(
        _REPORT_TEMPLATE,
        content=Markup(report_html),
        date=report_date,
    )
