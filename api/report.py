"""
Full Report Page
================
Serves the daily supply chain intelligence report as a clean,
standalone HTML page at /report.
"""
from flask import Blueprint, render_template_string
from data.cache import get_cached
import markdown

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
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    <style>
        /* ── Reset & Base ──────────────────────────────────────── */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: #0a0b0f;
            color: #c8ccd4;
            line-height: 1.7;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        /* ── Top Bar ───────────────────────────────────────────── */
        .topbar {
            position: sticky;
            top: 0;
            z-index: 100;
            background: rgba(10, 11, 15, 0.85);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            padding: 14px 32px;
            display: flex;
            align-items: center;
            justify-content: flex-start;
        }
        .topbar-back {
            font-size: 13px;
            color: #6b7280;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.2s;
        }
        .topbar-back:hover { color: #e5e7eb; }

        /* ── Article Container ─────────────────────────────────── */
        .article-container {
            max-width: 720px;
            margin: 0 auto;
            padding: 60px 24px 120px;
        }

        /* ── Meta Header ───────────────────────────────────────── */
        .article-meta {
            margin-bottom: 40px;
            padding-bottom: 32px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .article-label {
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: #6366f1;
            margin-bottom: 16px;
        }
        .article-title {
            font-size: 36px;
            font-weight: 800;
            color: #f0f2f5;
            line-height: 1.2;
            margin-bottom: 12px;
            letter-spacing: -0.5px;
        }
        .article-date {
            font-size: 14px;
            color: #6b7280;
            font-weight: 500;
        }

        /* ── Prose Content ─────────────────────────────────────── */

        .prose h2 {
            font-size: 20px;
            font-weight: 700;
            color: #e5e7eb;
            margin-top: 48px;
            margin-bottom: 16px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            letter-spacing: -0.3px;
        }

        .prose h3 {
            font-size: 17px;
            font-weight: 600;
            color: #d1d5db;
            margin-top: 28px;
            margin-bottom: 10px;
        }

        .prose p {
            margin-bottom: 20px;
            font-size: 16px;
            color: #b0b5bf;
        }

        .prose strong {
            color: #e5e7eb;
            font-weight: 600;
        }

        .prose em {
            color: #9ca3af;
        }

        .prose ul, .prose ol {
            margin-bottom: 20px;
            padding-left: 24px;
        }
        .prose li {
            margin-bottom: 8px;
            font-size: 16px;
            color: #b0b5bf;
        }
        .prose li::marker {
            color: #4f46e5;
        }

        .prose blockquote {
            border-left: 3px solid #4f46e5;
            padding: 12px 20px;
            margin: 24px 0;
            background: rgba(79, 70, 229, 0.06);
            border-radius: 0 6px 6px 0;
            color: #9ca3af;
            font-style: italic;
        }

        .prose code {
            background: rgba(255,255,255,0.05);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 14px;
            color: #a5b4fc;
        }

        .prose hr {
            border: none;
            border-top: 1px solid rgba(255,255,255,0.06);
            margin: 40px 0;
        }

        /* ── Footer ────────────────────────────────────────────── */
        .report-footer {
            margin-top: 64px;
            padding-top: 24px;
            border-top: 1px solid rgba(255,255,255,0.06);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .report-footer-text {
            font-size: 12px;
            color: #4b5563;
        }
        .report-footer-link {
            font-size: 13px;
            color: #6366f1;
            text-decoration: none;
            font-weight: 600;
            transition: color 0.2s;
        }
        .report-footer-link:hover { color: #818cf8; }

        /* ── Responsive ────────────────────────────────────────── */
        @media (max-width: 640px) {
            .article-title { font-size: 28px; }
            .article-container { padding: 40px 16px 80px; }
            .topbar { padding: 12px 16px; }
        }
    </style>
</head>
<body>

    <!-- Top Bar -->
    <nav class="topbar">
        <a href="/" class="topbar-back">&larr; Back to Dashboard</a>
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

    cached = get_cached("newsapi_briefing_v14")
    report_md = ""
    
    if cached and isinstance(cached, dict):
        report_md = cached.get("full_report", "")

    if not report_md:
        # Fallback: try the persisted dashboard snapshot (survives deploys)
        from data.cache import get_cached_dashboard
        dashboard = get_cached_dashboard()
        if dashboard and isinstance(dashboard, dict):
            report_md = dashboard.get("full_report", "")

    if not report_md:
        report_md = "## Report Not Yet Available\nThe system is generating the daily report. Please check back in a few minutes."

    # Convert markdown to HTML
    report_html = markdown.markdown(
        report_md,
        extensions=["extra", "smarty"]
    )

    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo('America/Denver')).strftime("%B %d, %Y")


    return render_template_string(
        _REPORT_TEMPLATE,
        content=Markup(report_html),
        date=today,
    )
