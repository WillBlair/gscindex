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
            max-width: 800px;
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
            background: #1a1d26;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .p-card h3 {
            font-size: 1.2rem;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 2px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            align-items: center;
            gap: 8px;
            text-transform: none !important;
        }
        .p-card p {
            font-size: 14px;
            color: #b0b5bf;
            margin-bottom: 0;
            line-height: 1.6;
        }
        .step-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-top: 8px;
        }
        .step-item {
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }
        .step-num {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: #3730a3;
            color: #e0e7ff;
            font-size: 11px;
            font-weight: 700;
            flex-shrink: 0;
            margin-top: -1px;
        }
        .step-text {
            font-size: 14px;
            color: #b0b5bf;
            line-height: 1.5;
        }
        .step-text strong {
            color: #f3f4f6;
            font-weight: 600;
        }
        .highlight-green { color: #4ade80; }
        .highlight-red { color: #f87171; }
        .highlight-blue { color: #38bdf8; }

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
<p>A background thread manages data ingestion to prevent slow page loads. It fetches raw data, passes it through the Gemini API for analysis, saves the daily state to a Postgres database, and caches the final layout for the frontend.</p>

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
    
    D[Background Thread<br>Data Aggregator] --> E[Gemini API<br>Context Engine]
    E --> F[Neon Postgres DB<br>Daily Scores]
    E --> G[Dash UI<br>Live Dashboard]
</div>

## Data Ingestion
<p>The background thread polls three primary data categories every 5 minutes to calculate the global supply chain health.</p>

<div class="grid-3">
    <div class="p-card">
        <h3>Institutional Macro</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Fetch:</strong> Pulls Federal Reserve Economic Data (FRED).</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Target:</strong> GSCPI, Trucking PPI, and Retail Diesel.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Normalize:</strong> Extrapolates against a <span class="highlight-blue">5-year rolling baseline</span>.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Real-Time Markets</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Fetch:</strong> Scrapes live futures markets via yfinance.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Target:</strong> WTI Crude Oil, Natural Gas, CBOE VIX.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Score:</strong> Tracks <span class="highlight-red">minute-by-minute</span> operational cost pressure.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Satellite Weather</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Fetch:</strong> Queries Open-Meteo API.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Target:</strong> 37 specific lat/long global shipping hubs.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Score:</strong> Monitors wind & waves to <span class="highlight-red">throttle port efficiency</span>.</div></div>
        </div>
    </div>
</div>

## Gemini API
<p>Google's Gemini model converts unstructured text from news feeds and our proprietary data into readable summaries and numerical values.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Geopolitical Analysis</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Intercept:</strong> Reads headlines from shipping news feeds.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Filter:</strong> AI removes corporate PR and flags kinetic events.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Impact:</strong> Applies <span class="highlight-red">-10 to +10 penalties</span> to the global score.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Daily Briefings</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Input:</strong> Collects the global event array.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Analyze:</strong> Generates a 3-bullet executive summary.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Display:</strong> Shows <span class="highlight-green">live hover summaries</span> over ports on the map.</div></div>
        </div>
    </div>
</div>

## Scoring Logic
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

## Infrastructure
<p>The application is designed to handle traffic spikes and maintain permanent historical data.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Background Caching</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Update:</strong> Python thread fetches data every 5 minutes.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Cache:</strong> Results are saved to a local JSON payload.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Serve:</strong> Server <span class="highlight-green">instantly loads</span> the JSON cache for users.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>PostgreSQL Database</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Save:</strong> Logs the final <span class="highlight-blue">Daily Score</span> at midnight.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Track:</strong> Calculates precise day-over-day tracking arrows.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Email:</strong> Manages subscriber lists for the daily newsletter.</div></div>
        </div>
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
