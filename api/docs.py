"""
Documentation Page
==================
Serves the highly visual, structured documentation for the Global Supply Chain Index
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
    <title>Platform Documentation — GSC Index</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet" />
    
    <!-- Mermaid.js for Architecture Diagrams -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({ 
            startOnLoad: true, 
            theme: 'dark',
            fontFamily: 'Inter, sans-serif'
        });
    </script>

    <style>
        /* ── Reset & Base ──────────────────────────────────────── */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: #0a0b0f;
            color: #c8ccd4;
            line-height: 1.6;
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
            padding: 16px 32px;
            display: flex;
            align-items: center;
            justify-content: flex-start;
        }
        .topbar-back {
            font-size: 14px;
            color: #9ca3af;
            text-decoration: none;
            font-weight: 600;
            transition: color 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .topbar-back:hover { color: #f3f4f6; }

        /* ── Main Container (Wider for UI Grids) ───────────────── */
        .docs-container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 60px 24px 120px;
        }

        /* ── Page Header ───────────────────────────────────────── */
        .docs-header {
            margin-bottom: 60px;
            text-align: center;
        }
        .docs-kicker {
            display: inline-block;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: #6366f1;
            margin-bottom: 16px;
        }
        .docs-title {
            font-size: 2rem;
            font-weight: 700;
            color: #e1e4ea;
            line-height: 1.1;
            margin-bottom: 24px;
            letter-spacing: -0.02em;
        }
        .docs-subtitle {
            font-size: 0.95rem;
            color: #8a8f9e;
            font-weight: 400;
            max-width: 700px;
            margin: 0 auto;
        }

        /* ── Markdown Content Styling ──────────────────────────── */
        .prose h2 {
            font-size: 1.5rem;
            font-weight: 700;
            color: #e1e4ea;
            margin-top: 60px;
            margin-bottom: 20px;
            letter-spacing: -0.02em;
            border-bottom: 1px solid #2a2d3a;
            padding-bottom: 12px;
        }

        .prose h3 {
            font-size: 1rem;
            font-weight: 600;
            color: #e1e4ea;
            margin-top: 32px;
            margin-bottom: 12px;
        }

        .prose p {
            margin-bottom: 24px;
            font-size: 16px;
            color: #b0b5bf;
            line-height: 1.7;
        }

        .prose strong {
            color: #f3f4f6;
            font-weight: 600;
        }

        /* ── UI Grids & Cards (Custom HTML inside Markdown) ────── */
        .grid-3 {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        
        .grid-2 {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 24px;
            margin-bottom: 40px;
        }

        .p-card {
            background: #11131a;
            border: 1px solid #1f222e;
            border-radius: 12px;
            padding: 24px;
            transition: transform 0.2s, border-color 0.2s;
        }
        .p-card:hover {
            transform: translateY(-2px);
            border-color: #374151;
        }
        .p-card h4 {
            font-size: 16px;
            font-weight: 700;
            color: #f3f4f6;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .p-card.fred h4 { color: #38bdf8; }         /* Light Blue */
        .p-card.market h4 { color: #facc15; }       /* Yellow */
        .p-card.weather h4 { color: #4ade80; }      /* Green */
        .p-card.ai h4 { color: #a78bfa; }           /* Purple */
        .p-card.db h4 { color: #f87171; }           /* Red */

        .p-card p {
            font-size: 14px;
            color: #9ca3af;
            margin-bottom: 0;
            line-height: 1.5;
        }

        /* ── Visual Math Block ─────────────────────────────────── */
        .math-block {
            background: #0f172a; /* Deep slate blue */
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 32px;
            text-align: center;
            margin: 40px 0;
            box-shadow: inset 0 2px 20px rgba(0,0,0,0.5);
        }
        .math-block code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 20px;
            color: #818cf8;
            font-weight: 700;
        }
        .math-block span.operator { color: #c8ccd4; margin: 0 10px; }
        .math-block span.variable { color: #38bdf8; }
        .math-block span.penalty { color: #f87171; }
        .math-caption {
            display: block;
            margin-top: 16px;
            font-size: 13px;
            color: #64748b;
        }

        /* ── Mermaid Container ─────────────────────────────────── */
        .mermaid {
            background: #11131a;
            border: 1px solid #1f222e;
            border-radius: 12px;
            padding: 32px;
            margin-bottom: 40px;
            display: flex;
            justify-content: center;
        }

        /* ── Tables ────────────────────────────────────────────── */
        .prose table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 40px;
            font-size: 15px;
            background: #11131a;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid #1f222e;
        }
        .prose th {
            text-align: left;
            padding: 16px 20px;
            background: #151821;
            color: #f3f4f6;
            font-weight: 600;
            border-bottom: 1px solid #1f222e;
        }
        .prose td {
            text-align: left;
            padding: 16px 20px;
            border-bottom: 1px solid #1f222e;
            color: #b0b5bf;
        }
        .prose tr:last-child td { border-bottom: none; }

        /* ── Footer ────────────────────────────────────────────── */
        .docs-footer {
            margin-top: 80px;
            padding-top: 32px;
            border-top: 1px solid #1f222e;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .docs-footer-text {
            font-size: 13px;
            color: #6b7280;
        }
        
        /* ── Responsive ────────────────────────────────────────── */
        @media (max-width: 768px) {
            .docs-title { font-size: 1.5rem; }
            .grid-3, .grid-2 { grid-template-columns: 1fr; }
            .docs-container { padding: 40px 16px 80px; }
            .math-block code { font-size: 14px; }
        }
    </style>
</head>
<body>

    <!-- Top Bar -->
    <nav class="topbar">
        <a href="/" class="topbar-back">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
            Back to Dashboard
        </a>
    </nav>

    <!-- Content -->
    <main class="docs-container">
        <header class="docs-header">
            <h1 class="docs-title">Documentation</h1>
        </header>

        <div class="prose">
            {{ content }}
        </div>

        <footer class="docs-footer">
            <span class="docs-footer-text">&copy; 2026 William Blair &middot; Global Supply Chain Index</span>
        </footer>
    </main>

</body>
</html>
"""

_DOCS_MARKDOWN = """
## System Architecture
<p>The GSC Index completely diverges from traditional, static macroeconomic reports. It operates as an autonomous, multi-threaded intelligence engine. Background threads poll raw data arrays, feed them through Google's Gemini Pro LLM for contextual analysis, save state to a persistent Neon PostgreSQL database, and serve clients instantly via an optimized Dash/Flask cache.</p>

<div class="mermaid">
flowchart LR
    style A fill:#111,stroke:#333
    style B fill:#111,stroke:#333
    style C fill:#111,stroke:#333
    style D fill:#151821,stroke:#4f46e5,stroke-width:2px,color:#fff
    style E fill:#1a0b22,stroke:#a78bfa,stroke-width:2px,color:#fff
    style F fill:#220f11,stroke:#f87171,stroke-width:2px,color:#fff
    style G fill:#0b1a11,stroke:#4ade80,stroke-width:2px,color:#fff

    A[Open-Meteo] --> D
    B[NewsAPI] --> D
    C[FRED / Markets] --> D
    
    D[Background Thread<br>Data Aggregator] --> E[Gemini AI<br>Context Engine]
    E --> F[Neon Postgres DB<br>Daily Scores]
    E --> G[Dash UI<br>Live Dashboard]
</div>

## Data Aggregation Engine
<p>The platform reconstructs global logistics health by aggregating hundreds of disparate signals into a unified environment every 5 minutes.</p>

<div class="grid-3">
    <div class="p-card fred">
        <h4>🏦 Institutional Macro</h4>
        <p>Polling the Federal Reserve Economic Data (FRED) API for foundational indicators like the Global Supply Chain Pressure Index (GSCPI), absolute Trucking PPI, and Retail Diesel Prices. We normalize this against a 5-year rolling baseline.</p>
    </div>
    <div class="p-card market">
        <h4>📈 Real-Time Markets</h4>
        <p>Because physical shipping rates update weekly, we scrape live futures markets via <code>yfinance</code> (WTI Crude Oil, Natural Gas) and volatility indices (CBOE VIX) to measure the immediate, minute-by-minute operational cost pressure.</p>
    </div>
    <div class="p-card weather">
        <h4>🌪️ Satellite Weather</h4>
        <p>Executing parallelized API queries to Open-Meteo for 37 distinctly latitude/longitude-mapped global shipping hubs, pulling wind gusts, wave heights, and storm data to dynamically throttle port efficiency logic.</p>
    </div>
</div>

## Autonomous AI Intelligence (Gemini)
<p>The core differentiator of the platform is passing raw string arrays through Google Gemini Pro to convert unstructured noise into rigid numerical intelligence.</p>

<div class="grid-2">
    <div class="p-card ai">
        <h4>Geopolitical Severity Engine</h4>
        <p>Gemini intercepts hundreds of RSS headlines (from <em>Supply Chain Dive, FreightWaves</em>) and filters out corporate PR. It identifies severe kinetic events (canal blockages, piracy, port strikes) and assigns absolute numerical penalties (-10 to +10) that dynamically override the global index score.</p>
    </div>
    <div class="p-card ai">
        <h4>Synthesized Human Briefings</h4>
        <p>Instead of forcing users to read a ticker of raw events, a specialized prompt instructs Gemini to write a 3-bullet executive "Daily Briefing" summarizing the global state, as well as distinct, hoverable contextual summaries for individual ports on the live map.</p>
    </div>
</div>

## Calculus & Algorithmic Weights
<p>The underlying Index Score is a mathematically rigid 0-100 gauge. <strong>A score of 100 represents a completely frictionless global logistics network.</strong></p>

| Category | Weight | Primary Data Driver | Function |
|:---|:---|:---|:---|
| **Supply Chain** | 20% | NY Fed GSCPI | Inverse normalization of global backlogs. |
| **Energy Costs** | 20% | WTI Crude / NatGas | Direct measurement of transportation fuel overhead. |
| **Geopolitical** | 20% | AI Sentiment | Subtracts severe event impacts (strikes, conflicts). |
| **Trade & Tariffs**| 15% | TPU Index | Algorithmic tracking of tariff legislation anxiety. |
| **Inland Freight** | 15% | US Diesel Spot | Ground-level trucking logistics costs. |
| **Port Weather** | 10% | Wind & Wave Array | Average operational degradation across 30+ hubs. |

<div class="math-block">
    <code>
        <span class="variable">Composite</span>
        <span class="operator">=</span>
        Σ ( <span class="variable">Category_Score</span> × <span class="variable">Weight</span> )
        <span class="operator">-</span>
        <span class="penalty">AI_Disruption_Penalty</span>
    </code>
    <span class="math-caption">The baseline is established by economic fundamentals, and aggressively throttled downward by real-time disruptions.</span>
</div>

## Infrastructure & Database State
<p>To survive traffic spikes and maintain permanent historical records, the underlying application architecture avoids standard single-thread bottlenecks.</p>

<div class="grid-2">
    <div class="p-card db">
        <h4>Threaded Instant Startup</h4>
        <p>Live API aggregations take roughly 50 seconds to complete. The Flask server instantly returns a skeleton React DOM to the client, displaying safe, provisional JSON state from the hard disk while the background python thread silently updates global variables.</p>
    </div>
    <div class="p-card db">
        <h4>Neon PostgreSQL Engine</h4>
        <p>A live Postgres database maintains the newsletter subscriber array and permanently logs the mathematically absolute <strong>Daily Score</strong> right before midnight. The UI dashboard queries this remote table to compute perfectly accurate day-over-day tracking arrows.</p>
    </div>
</div>
"""

@docs_bp.route("/docs")
def serve_docs():
    """Serve the documentation as a highly visual standalone page."""
    docs_html = markdown.markdown(
        _DOCS_MARKDOWN,
        extensions=["extra", "tables"]
    )
    
    return render_template_string(
        _DOCS_TEMPLATE,
        content=Markup(docs_html)
    )
