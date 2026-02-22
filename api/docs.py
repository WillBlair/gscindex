"""
Documentation Page
==================
Serves the comprehensive documentation for the Global Supply Chain Index
as a clean, standalone HTML page at /docs.
"""
from flask import Blueprint, render_template_string
import markdown
from markupsafe import Markup
docs_bp = Blueprint("docs", __name__)

_DOCS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Documentation — GSC Index</title>
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
            max-width: 760px;
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
        .prose h1 {
            font-size: 28px;
            font-weight: 800;
            color: #f0f2f5;
            margin-top: 56px;
            margin-bottom: 24px;
            line-height: 1.3;
        }

        .prose h2 {
            font-size: 22px;
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
        
        .prose pre {
            background: #111;
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
            margin-bottom: 24px;
            border: 1px solid rgba(255,255,255,0.06);
        }
        .prose pre code {
            background: transparent;
            padding: 0;
            border-radius: 0;
            color: #c8ccd4;
            font-size: 13px;
        }

        .prose hr {
            border: none;
            border-top: 1px solid rgba(255,255,255,0.06);
            margin: 40px 0;
        }
        
        /* ── Tables ────────────────────────────────────────────── */
        .prose table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 24px;
            font-size: 15px;
        }
        .prose th {
            text-align: left;
            padding: 12px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
            color: #e5e7eb;
            font-weight: 600;
        }
        .prose td {
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            color: #b0b5bf;
        }
        .prose tr:hover td {
            background-color: rgba(255,255,255,0.02);
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
            <span class="article-label">Platform Architecture</span>
            <h1 class="article-title">How the Global Supply Chain Index Works</h1>
            <p class="article-date">Updated February 2026</p>
        </header>

        <div class="prose">
            {{ content }}
        </div>

        <footer class="report-footer">
            <a href="/" class="report-footer-link">&larr; Dashboard</a>
            <span class="report-footer-text">Built by William Blair &middot; Global Supply Chain Index</span>
        </footer>
    </article>

</body>
</html>
"""

_DOCS_MARKDOWN = """
## Overview
The **Global Supply Chain Index (GSCI)** is a real-time health monitor and predictive analytics engine for the global logistics network. Unlike traditional macro-economic reports that rely on weeks-old manual data, this dashboard aggregates live signals from satellite weather APIs, financial futures markets, and real-time AI news analysis to provide an instantaneous view of supply chain stability worldwide.

## 1. Data Aggregation Engine
The platform pulls data from diverse real-time sources to reconstruct a holistic view of the supply chain.

### Institutional Data Integration (FRED)
We poll the Federal Reserve Economic Data (FRED) API for lagging macro indicators. Using inverse normalization, we baseline current pressures against 5-year historical ranges.
* **Global Supply Chain Pressure Index (GSCPI)**
* **Trucking PPI & US Diesel Retail Prices**
* **Trade Policy & Tariff Uncertainty Index**

### Real-Time Financial Proxies
Because physical shipping rates often update slowly or require expensive enterprise subscriptions, we utilize live futures markets via `yfinance` to evaluate immediate operational costs.
* **Energy Costs:** Tracking WTI Crude Oil (`CL=F`) and Natural Gas (`NG=F`) futures.
* **Geopolitical Fear:** Factoring in the CBOE Volatility Index (`^VIX`).

### Satellite Weather Data
We make parallelized API calls to **Open-Meteo** to pull live meteorological conditions (wind gusts, wave heights, precipitation) localized specifically for 37 major global shipping hubs.

## 2. Advanced AI Intelligence Layer
The core differentiator of the GSC Index is the integration of **Google Gemini Pro** to act as an autonomous supply chain analyst.

### Real-Time Geopolitical Scoring
1. We intercept hundreds of live RSS feed articles from industry leaders (*Supply Chain Dive, FreightWaves, The Loadstar*).
2. Gemini evaluates the articles to filter out generic corporate PR and identify severe kinetic events (e.g., canal blockages, port strikes, rebel attacks).
3. The AI scores the semantic impact of these disruptions natively, penalizing the overall Composite Score directly.

### Dynamic Port Summaries
Every 5 minutes during a background refresh, Gemini matches regional news directly to our list of ports. When you hover over a map dot (e.g., Singapore), you aren't just seeing the weather—you are reading a dynamic, AI-generated summary of exactly what is slowing down that specific port today.

### The Daily Briefing AI
Instead of forcing users to scroll through noise, an AI Agent synthesizes the top 3 critical facts from the day's global logistics news and produces an executive "Daily Briefing" for the main dashboard. It also drafts the complete, structured Daily AI Report that powers the `/report` endpoint.

## 3. Scoring Math & Logic
The Index Score is a perfectly weighted 0-100 gauge. **100 represents a friction-free, perfectly optimized global system.**

| Category | Weight | Primary Driver |
|:---|:---|:---|
| **Supply Chain** | 20% | NY Fed GSCPI |
| **Energy Costs** | 20% | Crude Oil Futures (CL=F) |
| **Geopolitical** | 20% | AI Sentiment & Disruptions |
| **Trade & Tariffs**| 15% | Tariff Policy Uncertainty |
| **Inland Freight** | 15% | US Diesel Spot Pricing |
| **Port Weather** | 10% | Lat/Lon Wind & Wave Heights |

**Calculation Engine:**
```text
Composite = Σ (CategoryScore * Weight) - Active_News_Penalty
```

## 4. Multi-Threaded Cache & Database
The platform is designed to handle high loads securely while minimizing expensive API calls.

* **Background Worker:** Dashboards traditionally hang while fetching live data. We run a continuous background thread utilizing Python's `concurrent.futures`. Data refreshes silently every 5 minutes and pushes to a localized JSON state. 
* **Instant Startup:** The server boots instantly for users by reading the safest known state from disk immediately, serving skeleton UI with provisional data while the background thread fetches the latest updates.
* **Neon PostgreSQL Database:** The platform runs a live Postgres database. This securely houses the subscriber network table for our Cron-automated daily email dispatch. Furthermore, it permanently logs the exact mathematical **Daily Score**, allowing us to query and calculate the explicit day-over-day tracking delta on the dashboard gauge with absolute precision.
"""

@docs_bp.route("/docs")
def serve_docs():
    """Serve the documentation as a clean standalone page."""
    docs_html = markdown.markdown(
        _DOCS_MARKDOWN,
        extensions=["extra", "tables"]
    )
    
    return render_template_string(
        _DOCS_TEMPLATE,
        content=Markup(docs_html)
    )
