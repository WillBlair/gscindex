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
            background-color: #0c1216;
            color: #d6e1de;
            line-height: 1.7;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        /* ── Top Bar ───────────────────────────────────────────── */
        .topbar {
            position: sticky;
            top: 0;
            z-index: 100;
            background: rgba(12, 18, 22, 0.96);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            padding: 14px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .topbar-back {
            font-size: 13px;
            color: #8a8f9e;
            text-decoration: none;
            font-weight: 600;
            transition: color 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .topbar-back:hover { color: #f3f4f6; }
        .topbar-tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            color: #6366f1;
            background: rgba(99, 102, 241, 0.1);
            padding: 4px 10px;
            border-radius: 6px;
            letter-spacing: 0.04em;
        }

        /* ── Main Container ────────────────────────────────────── */
        .docs-container {
            max-width: 780px;
            margin: 0 auto;
            padding: 56px 28px 120px;
        }

        /* ── Page Header ───────────────────────────────────────── */
        .docs-header {
            margin-bottom: 56px;
            text-align: center;
        }
        .docs-title {
            font-size: 1.8rem;
            font-weight: 600;
            color: #f3f4f6;
            line-height: 1.2;
            letter-spacing: -0.02em;
        }

        /* ── Section Headings ─────────────────────────────────── */
        .section-heading {
            display: flex;
            align-items: baseline;
            gap: 10px;
            margin-top: 64px;
            margin-bottom: 12px;
        }
        .section-num {
            color: #4b5563;
            font-size: 14px;
            font-weight: 600;
            flex-shrink: 0;
        }
        .section-heading h2 {
            font-size: 1.3rem;
            font-weight: 600;
            color: #f3f4f6;
            letter-spacing: -0.01em;
            margin: 0;
        }
        .section-rule {
            border: none;
            height: 1px;
            background: linear-gradient(90deg, #2a2d3a 0%, transparent 100%);
            margin-bottom: 24px;
        }

        /* ── Prose ─────────────────────────────────────────────── */
        .prose p {
            margin-bottom: 24px;
            font-size: 15px;
            color: #9ca3af;
            line-height: 1.75;
        }
        .prose strong {
            color: #e5e7eb;
            font-weight: 600;
        }

        /* ── Card Grids ───────────────────────────────────────── */
        .grid-3 {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 40px;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
            margin-bottom: 40px;
        }

        .p-card {
            background: #1a1d26;
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 6px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }
        .p-card h3 {
            font-size: 1.05rem;
            font-weight: 700;
            color: #f3f4f6;
            margin-bottom: 0;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            display: flex;
            align-items: center;
            gap: 8px;
            text-transform: none !important;
        }

        .card-badge {
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            font-weight: 600;
            color: #6b7280;
            padding: 2px 8px;
            border-radius: 6px;
            margin-left: auto;
            white-space: nowrap;
        }

        .p-card p {
            font-size: 13.5px;
            color: #9ca3af;
            margin-bottom: 0;
            line-height: 1.65;
        }

        /* ── Step Lists ───────────────────────────────────────── */
        .step-list {
            display: flex;
            flex-direction: column;
            gap: 14px;
            margin-top: 4px;
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
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.06);
            color: #6b7280;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            font-weight: 600;
            flex-shrink: 0;
            margin-top: 2px;
        }
        .step-text {
            font-size: 13.5px;
            color: #9ca3af;
            line-height: 1.55;
        }
        .step-text strong {
            color: #e5e7eb;
            font-weight: 600;
        }

        /* ── Highlight Colors ─────────────────────────────────── */
        .highlight-green  { color: #34d399; }
        .highlight-red    { color: #f87171; }
        .highlight-blue   { color: #60a5fa; }
        .highlight-amber  { color: #fbbf24; }
        .highlight-purple { color: #a78bfa; }

        /* ── Code Inline ──────────────────────────────────────── */
        .code-inline {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #a5b4fc;
            background: rgba(99, 102, 241, 0.1);
            padding: 2px 7px;
            border-radius: 6px;
        }

        /* ── Visual Math Block ────────────────────────────────── */
        .math-block {
            background: #111827;
            border: 1px solid #1e293b;
            border-radius: 6px;
            padding: 32px;
            text-align: center;
            margin: 32px 0 40px;
        }
        .math-block code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 18px;
            color: #818cf8;
            font-weight: 700;
        }
        .math-block span.operator { color: #d6e1de; margin: 0 8px; }
        .math-block span.variable { color: #60a5fa; }
        .math-caption {
            display: block;
            margin-top: 16px;
            font-size: 13px;
            color: #6b7280;
            line-height: 1.5;
        }

        /* ── Mermaid Container ────────────────────────────────── */
        .mermaid {
            background: #111827;
            border: 1px solid #1e293b;
            border-radius: 6px;
            padding: 32px;
            margin-bottom: 40px;
            display: flex;
            justify-content: center;
        }

        /* ── Tables ───────────────────────────────────────────── */
        .prose table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 32px;
            font-size: 13.5px;
            background: #111827;
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid #1e293b;
        }
        .prose th {
            text-align: left;
            padding: 14px 20px;
            background: #1a1d26;
            color: #e5e7eb;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            border-bottom: 1px solid #1e293b;
        }
        .prose td {
            text-align: left;
            padding: 14px 20px;
            border-bottom: 1px solid rgba(30, 41, 59, 0.6);
            color: #9ca3af;
        }
        .prose tr:nth-child(even) td {
            background: rgba(17, 24, 39, 0.5);
        }
        .prose tr:last-child td { border-bottom: none; }

        /* ── Info Callout ─────────────────────────────────────── */
        .callout {
            background: rgba(99, 102, 241, 0.06);
            border: 1px solid rgba(99, 102, 241, 0.15);
            border-radius: 6px;
            padding: 20px 24px;
            margin: 24px 0 40px;
            display: flex;
            gap: 14px;
            align-items: flex-start;
        }
        .callout-icon {
            font-size: 18px;
            flex-shrink: 0;
            margin-top: 2px;
        }
        .callout p {
            font-size: 13.5px;
            color: #a5b4fc;
            line-height: 1.6;
            margin-bottom: 0 !important;
        }

        /* ── Footer ───────────────────────────────────────────── */
        .docs-footer {
            margin-top: 80px;
            padding-top: 32px;
            border-top: 1px solid #1e293b;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .docs-footer-text {
            font-size: 12px;
            color: #4b5563;
        }
        .docs-footer-link {
            font-size: 13px;
            font-weight: 600;
            color: #6366f1;
            text-decoration: none;
            transition: color 0.2s;
        }
        .docs-footer-link:hover { color: #818cf8; }
        
        /* ── Responsive ───────────────────────────────────────── */
        @media (max-width: 768px) {
            .docs-title { font-size: 1.4rem; }
            .grid-3, .grid-2 { grid-template-columns: 1fr; }
            .docs-container { padding: 32px 16px 80px; }
            .math-block code { font-size: 13px; }
            .section-heading { margin-top: 48px; }
            .section-heading h2 { font-size: 1.1rem; }
        }

        @media (max-width: 480px) {
            .topbar { padding: 12px 16px; }
            .topbar-tag { display: none; }
            .docs-footer { flex-direction: column; gap: 12px; text-align: center; }
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
        <span class="topbar-tag">v2.0 &middot; Live</span>
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
            <a href="/" class="docs-footer-link">&larr; View Live Dashboard</a>
            <span class="docs-footer-text">&copy; 2026 William Blair &middot; Global Supply Chain Index</span>
        </footer>
    </main>

</body>
</html>
"""

_DOCS_MARKDOWN = """
<div class="section-heading"><span class="section-num">1.</span><h2>System Architecture</h2></div>
<hr class="section-rule">
<p>A daemon thread fetches data from the 6 category providers (plus 2 industry-profile providers) in parallel every 5 minutes. Anthropic's Claude API scores news severity and summarizes port conditions about once a day. Daily scores and the latest snapshot are saved to a Neon PostgreSQL database, and the snapshot is cached as JSON for instant page loads.</p>

<div class="mermaid">
flowchart LR
    style A fill:#111827,stroke:#374151,color:#9ca3af
    style B fill:#111827,stroke:#374151,color:#9ca3af
    style C fill:#111827,stroke:#374151,color:#9ca3af
    style D fill:#111827,stroke:#374151,color:#9ca3af
    style E fill:#1a1d26,stroke:#4f46e5,stroke-width:2px,color:#e5e7eb
    style F fill:#1a1d26,stroke:#a78bfa,stroke-width:2px,color:#e5e7eb
    style G fill:#1a1d26,stroke:#f87171,stroke-width:2px,color:#e5e7eb
    style H fill:#1a1d26,stroke:#34d399,stroke-width:2px,color:#e5e7eb

    A["FRED + NY Fed<br>(GSCPI · EPUTRADE · TSI · Diesel)"] --> E
    B["Open-Meteo<br>(37 Ports)"] --> E
    C["Yahoo Finance<br>(CL=F · BDRY · IYT)"] --> E
    D["RSS Feeds<br>(17 Feeds)"] --> E
    
    E["Background Thread<br>Parallel Aggregator"] --> F["Claude Sonnet<br>News + Port Analyst"]
    F --> G["Neon Postgres<br>Daily Scores"]
    E --> H["Dash UI<br>Live Dashboard"]
</div>

<div class="section-heading"><span class="section-num">2.</span><h2>Data Providers</h2></div>
<hr class="section-rule">
<p>Six providers fetch and normalize data from independent sources. Each produces a 0–100 category score where <strong>100 = healthiest</strong>. Monthly sources are blended with a daily proxy so scores move between releases. If a proxy fails, the monthly source is used alone.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Supply Chain Pressure <span class="card-badge">25%</span></h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Source:</strong> NY Fed Global Supply Chain Pressure Index (<span class="code-inline">GSCPI</span>, monthly), blended with a daily dry-bulk freight-rate proxy (<span class="code-inline">BDRY</span>).</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Signal:</strong> GSCPI is a z-score built from transport costs and PMI delivery-time and backlog components. 0 is average pressure. The NY Fed Weekly Economic Index (WEI) is shown for context only and is not scored.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Scoring:</strong> <span class="highlight-blue">Score = 50 − (GSCPI × 12.5)</span>, clipped to 0–100, then blended 70/30 with BDRY scored by inverse percentile over the trailing 2 years.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Energy &amp; Fuel <span class="card-badge">20%</span></h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Source:</strong> Live WTI Crude futures (<span class="code-inline">CL=F</span>) plus DOE retail diesel (<span class="code-inline">GASDESW</span>) via FRED.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Baseline:</strong> Each leg scored against its trailing 2-year FRED distribution.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Scoring:</strong> Average of the two inverse percentiles — <span class="highlight-amber">cheaper fuel = higher score</span>. Crude and diesel are blended into one gauge to avoid double-weighting the oil complex.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Geopolitical Risk <span class="card-badge">20%</span></h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Source:</strong> 17 RSS feeds (FreightWaves, gCaptain, Supply Chain Dive, WTO, NOAA hurricane alerts, and more).</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Analysis:</strong> Claude Sonnet scores each article's severity (<span class="highlight-red">-10 to +10</span>). VADER sentiment is the fallback, and re-scores alerts hourly between Claude runs.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Scoring:</strong> Starts at 100 and deducts the 10 most severe negative articles (duplicates removed), with a maximum deduction of 60. That result is blended 85/15 with an AI port-disruption score (100 − 2 × the average port penalty). Positive news never raises the score.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Trade & Tariffs <span class="card-badge">15%</span></h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Source:</strong> Baker-Bloom-Davis Trade Policy Uncertainty categorical index (<span class="code-inline">EPUTRADE</span>, monthly) via FRED, plus a daily tariff news nowcast from the RSS feeds.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Signal:</strong> Counts newspaper coverage of trade policy uncertainty (tariffs, trade wars, import and export policy). The nowcast scores tariff-related headlines with VADER sentiment.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Scoring:</strong> Inverse percentile against the <span class="highlight-blue">trailing 2-year range</span>. When tariff news scores lower, it is blended in at 30%. The news can only lower this score.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Port Weather <span class="card-badge">10%</span></h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Source:</strong> Open-Meteo API (free, no key required).</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Coverage:</strong> 37 major ports, including Houston, Shanghai, Rotterdam, Singapore, and Busan.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Scoring:</strong> Continuous deductions for <span class="highlight-red">wind, precipitation, temperature extremes, and WMO condition codes</span>, averaged across all ports.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Freight Flow <span class="card-badge">10%</span></h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Source:</strong> BTS Freight Transportation Services Index (<span class="code-inline">TSIFRGHT</span>, monthly, 1 to 2 month lag), blended with a daily transportation-stock proxy (<span class="code-inline">IYT</span>).</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Signal:</strong> Physical throughput across trucking, rail, air, and waterborne freight — are goods actually moving?</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Scoring:</strong> <span class="highlight-amber">Score = 72 + (YoY % × 6.5)</span>, clipped to 0–100, so contraction lowers the score. Blended 70/30 with IYT scored by percentile over the trailing 2 years.</div></div>
        </div>
    </div>
</div>

<div class="section-heading"><span class="section-num">3.</span><h2>Scoring Engine</h2></div>
<hr class="section-rule">
<p>The composite index is a <strong>weighted average</strong> of all six category scores, producing a single 0–100 value where 100 represents a completely frictionless global logistics network. The Semiconductor and Aerospace &amp; Manufacturing profiles add four industry categories each and use their own weights.</p>

| Category | Weight | Primary Source | Normalization |
|:---|:---|:---|:---|
| **Supply Chain Pressure** | 25% | NY Fed GSCPI + BDRY proxy | 50 − GSCPI × 12.5, blended 70/30 with BDRY percentile |
| **Energy & Fuel** | 20% | WTI Crude (CL=F) + DOE Diesel (GASDESW) | Average inverse percentile vs trailing 2-year range |
| **Geopolitical Risk** | 20% | RSS + Claude AI | Severity deductions from 100, blended 85/15 with port disruption |
| **Trade & Tariffs** | 15% | EPUTRADE (FRED) + news nowcast | Inverse percentile vs trailing 2-year range; news can only lower it |
| **Port Weather** | 10% | Open-Meteo | Continuous weather deductions |
| **Freight Flow** | 10% | BTS Freight TSI + IYT proxy | 72 + YoY % × 6.5, blended 70/30 with IYT percentile |

<div class="math-block">
    <code>
        <span class="variable">Composite</span>
        <span class="operator">=</span>
        Σ ( <span class="variable">Category_Score<sub>i</sub></span> × <span class="variable">Weight<sub>i</sub></span> )
    </code>
    <span class="math-caption">Weights must sum to 1.0. Each category score is on a 0–100 scale, and the composite is clipped to [0, 100].</span>
</div>

<div class="callout">
    <span class="callout-icon">💡</span>
    <p>The geopolitical score already includes news severity and the AI port-disruption signal (15% of that category). There is no separate penalty term in the composite formula.</p>
</div>

<p>The composite score maps to a health tier for display:</p>

| Score Range | Tier | Color |
|:---|:---|:---|
| 80 – 100 | **Healthy** | <span class="highlight-green">● Green</span> |
| 60 – 79 | **Stable** | <span class="highlight-amber">● Amber</span> |
| 40 – 59 | **Stressed** | <span style="color: #fb923c;">● Orange</span> |
| 0 – 39 | **Critical** | <span class="highlight-red">● Red</span> |

<div class="section-heading"><span class="section-num">4.</span><h2>AI Intelligence Layer</h2></div>
<hr class="section-rule">
<p>Anthropic's Claude Sonnet model runs several separate calls: <strong>article scoring plus the briefing (one call)</strong>, the full report, port summaries, and the explanation shown when you hover over the gauge. Each result is reused for about 24 hours. A failed call is retried after an hour. Without Claude, the site falls back to VADER sentiment and fixed text.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Article Analysis</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Ingest:</strong> Articles are pulled from <span class="highlight-purple">17 RSS feeds</span> and deduplicated. The 25 newest go to Claude for scoring.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Filter:</strong> Irrelevant articles (sports, crypto, fashion, market research spam) are pre-filtered via keyword exclusion.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Score:</strong> Claude assigns each article a severity from <span class="highlight-red">-10</span> (catastrophic) to <span class="highlight-green">+10</span> (miracle).</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Generated Outputs</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Briefing:</strong> A 3-bullet executive summary shown on the dashboard.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Full Report:</strong> A Chief Strategy Officer-style Markdown intelligence report.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Port Summaries:</strong> AI-generated context and a 0–50 disruption penalty for each of the 37 ports, shown in the <span class="highlight-green">map tooltip</span>.</div></div>
        </div>
    </div>
</div>

<div class="section-heading"><span class="section-num">5.</span><h2>Infrastructure</h2></div>
<hr class="section-rule">
<p>The application is built with <strong>Plotly Dash</strong>, served by Gunicorn, and deployed on Render. A background thread handles all data fetching so page loads are instant.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Background Data Pipeline</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Cycle:</strong> A Python daemon thread fetches from <span class="highlight-blue">all providers in parallel</span> (3 at a time) every 5 minutes.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Cache:</strong> Results are saved to a JSON payload on disk. A fresh deploy loads the last snapshot saved in the database, then a committed fallback snapshot if that is under 14 days old.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Serve:</strong> Page loads read directly from the in-memory cache — <span class="highlight-green">zero database queries on render</span>.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Persistence & Distribution</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Database:</strong> Neon PostgreSQL stores <span class="highlight-blue">daily composite and category scores</span> for the trend charts and day-over-day deltas, plus the latest snapshot.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Newsletter:</strong> Subscriber emails are managed in Postgres. The daily briefing is emailed each morning, and every email has an unsubscribe link.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>API:</strong> A public REST endpoint at <span class="code-inline">GET /api/v1/latest</span> serves the latest index data, limited to 500 requests per hour and 2,000 per day per IP.</div></div>
        </div>
    </div>
</div>

<div class="section-heading"><span class="section-num">6.</span><h2>News Sources</h2></div>
<hr class="section-rule">
<p>The geopolitical provider reads 17 curated RSS feeds from industry, trade-policy, and weather-alert sources rather than general news aggregators.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Ports & Shipping</h3>
        <p>gCaptain, Splash 247, The Loadstar, Maritime Executive, Logistics Management (Ocean Freight)</p>
    </div>
    <div class="p-card">
        <h3>Supply Chain & Logistics</h3>
        <p>Supply Chain Dive, SupplyChainBrain, FreightWaves, Logistics Management (Transportation), Supply Chain Management Review, Logistics Viewpoints</p>
    </div>
    <div class="p-card">
        <h3>Trade Policy</h3>
        <p>WTO News</p>
    </div>
    <div class="p-card">
        <h3>Weather & Disasters</h3>
        <p>GDACS Disaster Alerts, plus four NOAA National Hurricane Center feeds (Atlantic and Eastern Pacific cyclones, Atlantic outlook, Atlantic high seas forecast)</p>
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
