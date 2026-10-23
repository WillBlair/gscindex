"""
Methodology Page
================
Serves the Global Supply Chain Index methodology (v2) as a standalone page at /docs.

Weights, freshness limits and anchor values are read from ``config`` (and through it
``data/score_anchors.json``) when the page is requested, so the page cannot drift from
the numbers the providers use. The prose around them is fixed text.
"""
from __future__ import annotations

import math
from datetime import date

from flask import Blueprint, render_template_string
import markdown
from markupsafe import Markup

import config

docs_bp = Blueprint("docs", __name__)

_DOCS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Methodology | GSC Index</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
    
    <!-- Mermaid.js for Architecture Diagrams -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({
            startOnLoad: true,
            theme: 'dark',
            fontFamily: 'JetBrains Mono, ui-monospace, monospace',
            themeVariables: { background: '#07090C', lineColor: '#8A94A3', fontSize: '13px' }
        });
    </script>

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
            justify-content: space-between;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 13px;
        }
        .topbar-back {
            color: #8A94A3;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .topbar-back:hover { color: #F2F4F7; }
        .topbar-tag { color: #FFB020; font-size: 12px; }

        /* ── Main pane ─────────────────────────────────────────── */
        .docs-container {
            max-width: 860px;
            margin: 32px auto 80px;
            background: #07090C;
            border: 1px solid #1D232B;
            padding: 24px 28px 28px;
        }

        .docs-header {
            margin-bottom: 8px;
            padding-bottom: 14px;
            border-bottom: 1px solid #1D232B;
        }
        .docs-title {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 13px;
            font-weight: 400;
            color: #FFB020;
        }

        /* ── Section headings ─────────────────────────────────── */
        .section-heading {
            display: flex;
            align-items: baseline;
            gap: 10px;
            margin-top: 40px;
            margin-bottom: 0;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
        }
        .section-num { color: #8A94A3; font-size: 13px; flex-shrink: 0; }
        .section-heading h2 { font-size: 13px; font-weight: 400; color: #FFB020; margin: 0; }
        .section-rule { border: none; height: 1px; background: #1D232B; margin: 10px 0 18px; }

        /* ── Prose ─────────────────────────────────────────────── */
        .prose p { margin-bottom: 18px; font-size: 15px; color: #D6DBE3; line-height: 1.65; }
        .prose strong { color: #F2F4F7; font-weight: 600; }

        /* ── Card grids: panes separated by 1px rules ─────────── */
        .grid-3, .grid-2, .grid-1 {
            display: grid;
            gap: 1px;
            background: #1D232B;
            border: 1px solid #1D232B;
            margin-bottom: 32px;
        }
        .grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .grid-1 { grid-template-columns: minmax(0, 1fr); }

        .p-card {
            background: #07090C;
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            min-width: 0;
        }
        .p-card h3 {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 12px;
            font-weight: 400;
            color: #FFB020;
            margin-bottom: 0;
            display: flex;
            align-items: baseline;
            gap: 8px;
            text-transform: none !important;
        }
        .card-badge {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 12px;
            color: #8A94A3;
            margin-left: auto;
            white-space: nowrap;
        }
        .p-card p { font-size: 14px; color: #D6DBE3; margin-bottom: 0; line-height: 1.55; }

        /* ── Step lists ───────────────────────────────────────── */
        .step-list { display: flex; flex-direction: column; gap: 10px; }
        .step-item { display: flex; align-items: flex-start; gap: 10px; }
        .step-num {
            color: #8A94A3;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 12px;
            line-height: 1.55;
            flex-shrink: 0;
            min-width: 12px;
        }
        .step-text { font-size: 14px; color: #D6DBE3; line-height: 1.55; min-width: 0; }
        .step-text strong { color: #F2F4F7; font-weight: 600; }

        /* ── Highlights (tier colors from the dashboard) ──────── */
        .highlight-green  { color: #35D07F; }
        .highlight-red    { color: #FF4D5E; }
        .highlight-blue   { color: #F2F4F7; }
        .highlight-amber  { color: #F5C542; }
        .highlight-purple { color: #FFB020; }

        /* ── Inline code ──────────────────────────────────────── */
        .code-inline {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 12px;
            color: #F2F4F7;
            background: #000000;
            border: 1px solid #1D232B;
            padding: 0 5px;
        }

        /* ── Formula block ────────────────────────────────────── */
        .math-block {
            background: #000000;
            border: 1px solid #1D232B;
            padding: 24px 16px;
            text-align: center;
            margin: 24px 0 32px;
        }
        .math-block code {
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 16px;
            color: #FFB020;
            font-weight: 500;
        }
        .math-block span.operator { color: #8A94A3; margin: 0 8px; }
        .math-block span.variable { color: #F2F4F7; }
        .math-caption { display: block; margin-top: 14px; font-size: 13px; color: #8A94A3; line-height: 1.5; }

        /* ── Mermaid diagram ──────────────────────────────────── */
        .mermaid {
            background: #000000;
            border: 1px solid #1D232B;
            padding: 24px 16px;
            margin-bottom: 32px;
            display: flex;
            justify-content: center;
            overflow-x: auto;
        }

        /* ── Tables ───────────────────────────────────────────── */
        .prose table { width: 100%; border-collapse: collapse; margin-bottom: 28px; font-size: 13px; }
        .prose th {
            text-align: left;
            padding: 0 12px 6px 0;
            color: #8A94A3;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-weight: 400;
            font-size: 12px;
            border-bottom: 1px solid #1D232B;
        }
        .prose td {
            text-align: left;
            padding: 8px 12px 8px 0;
            border-bottom: 1px solid #1D232B;
            color: #D6DBE3;
            vertical-align: top;
        }
        .prose tr:hover td { background: #0D1117; }

        /* ── Callout ──────────────────────────────────────────── */
        .callout {
            border: 1px solid #1D232B;
            background: #000000;
            padding: 12px 16px;
            margin: 24px 0 32px;
        }
        .callout::before {
            content: "Note";
            display: block;
            margin-bottom: 6px;
            font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
            font-size: 12px;
            color: #FFB020;
        }
        .callout p { font-size: 14px; color: #D6DBE3; line-height: 1.6; margin-bottom: 0 !important; }

        /* ── Footer ───────────────────────────────────────────── */
        .docs-footer {
            margin-top: 40px;
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
        .docs-footer-text { color: #8A94A3; }
        .docs-footer-link { color: #FFB020; text-decoration: none; }
        .docs-footer-link:hover { text-decoration: underline; }

        /* ── Phones ───────────────────────────────────────────── */
        @media (max-width: 760px) {
            .docs-container { margin: 0; border: 0; border-bottom: 1px solid #1D232B; padding: 20px 16px 28px; }
            .grid-3, .grid-2, .grid-1 { grid-template-columns: minmax(0, 1fr); }
            .math-block code { font-size: 13px; }
            .prose table { display: block; overflow-x: auto; }
            .prose { overflow-wrap: anywhere; }
            .prose th, .prose td { overflow-wrap: normal; min-width: 64px; }
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
        <span class="topbar-tag">Methodology v{{ version }}</span>
    </nav>

    <!-- Content -->
    <main class="docs-container">
        <header class="docs-header">
            <h1 class="docs-title">Methodology</h1>
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

# ---------------------------------------------------------------------------
# Numbers read from config at request time
# ---------------------------------------------------------------------------

# Month of each input's in-sample zero point, as recorded in data/score_anchors.json
# ("worst_basis"). tests/docs_page_test.py checks they agree with the file. The tariff
# burden's zero point is a cited 1933 reference, described in the text.
WORST_MONTHS: dict[str, date] = {
    "gscpi": date(2021, 12, 1),
    "brent": date(2008, 6, 1),
    "ulsd": date(2008, 6, 1),
    "ttf": date(2022, 8, 1),
    "copper": date(2011, 2, 1),
    "aluminum": date(2006, 5, 1),
    "tpu": date(2025, 4, 1),
    "gpr": date(2001, 10, 1),
    "tsifrght": date(2009, 4, 1),
    "rail_volume": date(2009, 5, 1),
    "prices_paid": date(2021, 11, 1),
}

# How each input's anchor values are shown, in the units readers know (anchors are stored
# on the transformed scale: log real prices, log index levels, YoY %, z-scores).
_ANCHOR_FORMATS = {
    "gscpi": lambda v: f"{v:+.2f}",
    "brent": lambda v: f"${math.exp(v):.0f}/bbl",
    "ulsd": lambda v: f"${math.exp(v):.2f}/gal",
    "ttf": lambda v: f"${math.exp(v):.2f}/MMBtu",
    "copper": lambda v: f"${math.exp(v):,.0f}/t",
    "aluminum": lambda v: f"${math.exp(v):,.0f}/t",
    "tariff_burden": lambda v: f"{v:.1f}%",
    "tpu": lambda v: f"{math.exp(v):,.0f}",
    "gpr": lambda v: f"{math.exp(v):,.0f}",
    "tsifrght": lambda v: f"{v:+.1f}%",
    "rail_volume": lambda v: f"{v:+.1f}%",
    "prices_paid": lambda v: f"z {v:+.2f}",
}

# Category table: what each category measures and its main sources.
_CATEGORY_SUMMARY = {
    "supply_chain": ("Global supply chain pressure", "NY Fed GSCPI"),
    "chokepoints": ("Ship traffic through eight maritime chokepoints", "IMF PortWatch"),
    "energy": ("Real prices of Brent crude, diesel and European gas", "EIA and IMF via FRED, live futures"),
    "tariffs": ("Customs duties as a share of imports, and trade policy uncertainty",
                "U.S. Treasury, Census via FRED, Caldara et al."),
    "geopolitical": ("Newspaper coverage of geopolitical threats and acts", "Caldara-Iacoviello GPR"),
    "freight": ("Year-over-year growth in US freight and rail volume", "BTS, STB"),
    "inputs": ("Manufacturers' prices paid, real copper and aluminum prices",
               "Philadelphia, New York and Dallas Feds, IMF, live futures"),
    "physical": ("Natural hazards near major ports, Panama Canal and Mississippi River water levels",
                 "GDACS, Panama Canal Authority, USGS"),
}
# Categories built from events rather than anchored levels: a normal day reads about 100.
_EVENT_CATEGORIES = ("chokepoints", "physical")
_CORRIDOR_NAMES = {"Taiwan": "Taiwan Strait", "RedSea": "Red Sea"}

_UNAVAILABLE = "the anchor file is not loaded on this server"


def _anchor(key: str) -> dict | None:
    try:
        anchor = config.SCORE_ANCHORS["inputs"][key]
        return anchor if all(k in anchor for k in ("best", "normal", "worst", "direction")) else None
    except (KeyError, TypeError):
        return None


def _anchors(key: str, label: str = "", when_note: str = "") -> str:
    """'100 at X or lower, 80 at Y, 0 at Z (Mon YYYY)' for one input."""
    anchor = _anchor(key)
    prefix = f"{label} " if label else ""
    if anchor is None:
        return f"{prefix}anchors unavailable ({_UNAVAILABLE})"
    fmt = _ANCHOR_FORMATS[key]
    better = "or lower" if anchor["direction"] == "lower_better" else "or higher"
    month = WORST_MONTHS.get(key)
    when = f" ({when_note}{month:%b %Y})" if month else ""
    return (f"{prefix}100 at {fmt(anchor['best'])} {better}, 80 at {fmt(anchor['normal'])}, "
            f"0 at {fmt(anchor['worst'])}{when}")


def _pct(weight: float) -> str:
    return f"{round(weight * 100)}%"


def _fresh(key: str) -> str:
    stale, drop = config.FRESHNESS[key]
    return f"stale after {stale} days, dropped after {drop}"


def _category_rows() -> str:
    rows = ["| Category | Weight | What it measures | Main sources |", "|:---|:---|:---|:---|"]
    for cat, weight in config.CATEGORY_WEIGHTS.items():
        measures, sources = _CATEGORY_SUMMARY.get(cat, ("", ""))
        rows.append(f"| **{config.CATEGORY_LABELS.get(cat, cat)}** | {_pct(weight)} | {measures} | {sources} |")
    return "\n".join(rows)


def _cpi_dollars() -> str:
    try:
        ref = date.fromisoformat(str(config.SCORE_ANCHORS["cpi_reference"]["date"])[:10])
        return f"{ref:%B %Y} dollars"
    except (KeyError, TypeError, ValueError):
        return "dollars of the CPI reference month"


def _chokepoint_text() -> tuple[str, str]:
    """Tonnage weights and the single-closure examples, from the anchors file."""
    weights = config.SCORE_ANCHORS.get("chokepoint_weights") if isinstance(config.SCORE_ANCHORS, dict) else None
    if not isinstance(weights, dict) or not weights:
        return f"Tonnage weights are unavailable ({_UNAVAILABLE}).", ""
    ordered = sorted(weights.items(), key=lambda kv: -kv[1])
    listing = ", ".join(f"{_CORRIDOR_NAMES.get(name, name)} {_pct(w)}" for name, w in ordered)
    severity = config.CHOKEPOINT_SEVERITY * 100
    examples = [f"{name} alone takes the score to about {max(0.0, 100 - severity * weights[name]):.0f}"
                for name in ("Hormuz", "Malacca") if name in weights]
    closure = ("Closing " + ", and closing ".join(examples) + ".") if examples else ""
    return f"Tonnage weights: {listing}.", closure


def _waterway_text() -> tuple[str, str]:
    waterways = config.SCORE_ANCHORS.get("waterways") if isinstance(config.SCORE_ANCHORS, dict) else None
    full = f"{config.GATUN_FULL_DRAFT_FT:.0f} ft"
    try:
        gatun_low = float(waterways["gatun_record_low"])
        gatun_day = date.fromisoformat(str(waterways["gatun_record_low_date"]))
        river_low = float(waterways["mississippi_record_low"])
        river_day = date.fromisoformat(str(waterways["mississippi_record_low_date"]))
        threshold = float(waterways["mississippi_threshold"])
    except (KeyError, TypeError, ValueError):
        return (f"Gatun Lake: 100 at {full} or above, 0 at the record low.",
                "Mississippi: 100 at or above the gauge's 10th-percentile stage, 0 at the record low.")
    gatun = (f"Gatun Lake: 100 at {full} or above (the level the Panama Canal needs for the full "
             f"50 ft draft), falling in a straight line to 0 at the record low, {gatun_low:.2f} ft "
             f"({gatun_day:%b %Y}).")
    river = (f"Mississippi at St. Louis: 100 at {threshold:.2f} ft or above, falling in a straight line "
             f"to 0 at the record low, {river_low:.2f} ft ({river_day:%b %Y}). {threshold:.2f} ft is the "
             "gauge's 10th-percentile daily stage since 1982, because no official low-water stage for "
             "St. Louis was found.")
    return gatun, river


def _burden_reference() -> str:
    anchor = _anchor("tariff_burden")
    if anchor is None:
        return ""
    text = (f"0 at {anchor['worst']:.1f}%: duties as a share of imports in 1933, the peak under the "
            "Smoot-Hawley Tariff Act (USITC). It is a historical reference because the record in this "
            "data is the current period")
    in_sample, month = anchor.get("in_sample_worst"), anchor.get("in_sample_worst_month")
    if isinstance(in_sample, (int, float)) and month:
        try:
            text += f" (the highest reading is {in_sample:.1f}% in {date.fromisoformat(month + '-01'):%b %Y})"
        except ValueError:
            pass
    return text + "."


def _burden_anchors() -> str:
    anchor = _anchor("tariff_burden")
    if anchor is None:
        return f"Burden anchors unavailable ({_UNAVAILABLE})."
    try:
        first, last = (date.fromisoformat(m + "-01") for m in str(anchor["baseline"]).split(" (")[0].split(" to "))
        period = f"{first:%b %Y} to {last:%b %Y}"
    except (KeyError, ValueError):
        period = "the years before 2018"
    return (f"Burden 100 at {anchor['best']:.1f}% or lower, 80 at {anchor['normal']:.1f}% "
            f"(the median for {period}), " + _burden_reference())


def _docs_values() -> dict[str, str]:
    weights = config.CATEGORY_WEIGHTS
    normal = sum(w * (100 if cat in _EVENT_CATEGORIES else 80) for cat, w in weights.items())
    weights_text, closure_text = _chokepoint_text()
    gatun_text, river_text = _waterway_text()
    radius = config.HAZARD_RADIUS_KM
    drop = config.CATEGORY_DROP_AFTER_DAYS
    return {
        "category_rows": _category_rows(),
        "normal_composite": f"{normal:.0f}",
        "cpi_dollars": _cpi_dollars(),
        **{f"w_{cat}": _pct(w) for cat, w in weights.items()},
        **{f"drop_{cat}": str(days) for cat, days in drop.items()},
        **{f"fresh_{key}": _fresh(key) for key in config.FRESHNESS},
        "lag_gscpi": str(config.PUBLICATION_LAG_DAYS["gscpi"]),
        "lag_chokepoint": str(config.PUBLICATION_LAG_DAYS["chokepoint_flow"]),
        "lag_tsifrght": str(config.PUBLICATION_LAG_DAYS["tsifrght"]),
        "lag_rail": str(config.PUBLICATION_LAG_DAYS["rail_volume"]),
        "lag_imf": str(config.PUBLICATION_LAG_DAYS["imf_monthly"]),
        "lag_bopgimp": str(config.PUBLICATION_LAG_DAYS["bopgimp"]),
        "a_gscpi": _anchors("gscpi"),
        "a_brent": _anchors("brent", "Brent"),
        "a_ulsd": _anchors("ulsd", "Diesel"),
        "a_ttf": _anchors("ttf", "Gas"),
        "a_burden": _burden_anchors(),
        "a_tpu": _anchors("tpu", "Uncertainty", "30-day mean, "),
        "a_gpr": _anchors("gpr"),
        "a_tsifrght": _anchors("tsifrght", "Freight TSI"),
        "a_rail": _anchors("rail_volume", "Rail"),
        "a_prices_paid": _anchors("prices_paid", "Prices paid"),
        "a_copper": _anchors("copper", "Copper"),
        "a_aluminum": _anchors("aluminum", "Aluminum"),
        "deadband": _pct(config.CHOKEPOINT_DEADBAND),
        "deadband_ratio": f"{config.CHOKEPOINT_DEADBAND:.2f}",
        "severity": f"{config.CHOKEPOINT_SEVERITY * 100:.0f}",
        "corridor_weights": weights_text,
        "closure_examples": closure_text,
        "ew_brent": _pct(config.ENERGY_LEG_WEIGHTS["brent"]),
        "ew_ulsd": _pct(config.ENERGY_LEG_WEIGHTS["ulsd"]),
        "ew_ttf": _pct(config.ENERGY_LEG_WEIGHTS["ttf"]),
        "spike_start": _pct(config.ENERGY_SPIKE["start"]),
        "spike_full": _pct(config.ENERGY_SPIKE["full"]),
        "spike_points": f"{config.ENERGY_SPIKE['max_points']:.0f}",
        "ratio_low": f"{config.LIVE_SCALE_RATIO_BOUNDS[0]:g}",
        "ratio_high": f"{config.LIVE_SCALE_RATIO_BOUNDS[1]:g}",
        "mwh_per_mmbtu": f"{config.MWH_PER_MMBTU:g}",
        "ttf_max_age": str(config.TTF_LIVE_MAX_AGE_DAYS),
        "tw_burden": _pct(config.TARIFF_WEIGHTS["tariff_burden"]),
        "tw_tpu": _pct(config.TARIFF_WEIGHTS["tpu"]),
        "burden_months": str(config.TARIFF_BURDEN_MONTHS),
        "tpu_days": str(config.TPU_MEAN_DAYS),
        "gpr_days": str(config.GPR_MEAN_DAYS),
        "register_weight": _pct(config.GEO_REGISTER_WEIGHT),
        "register_factor": f"{config.REGISTER_SCORE_FACTOR:g}",
        "fw_tsi": _pct(config.FREIGHT_WEIGHTS["tsifrght"]),
        "fw_rail": _pct(config.FREIGHT_WEIGHTS["rail_volume"]),
        "rail_weeks": str(config.RAIL_MEAN_WEEKS),
        "iw_pp": _pct(config.INPUT_WEIGHTS["prices_paid"]),
        "iw_copper": _pct(config.INPUT_WEIGHTS["copper"]),
        "iw_aluminum": _pct(config.INPUT_WEIGHTS["aluminum"]),
        "pw_hazards": _pct(config.PHYSICAL_WEIGHTS["hazards"]),
        "pw_gatun": _pct(config.PHYSICAL_WEIGHTS["gatun"]),
        "pw_river": _pct(config.PHYSICAL_WEIGHTS["mississippi"]),
        "hazard_scale": f"{config.HAZARD_SCALE:,.0f}",
        "r_tc": f"{radius['TC']:.0f}", "r_fl": f"{radius['FL']:.0f}",
        "r_eq": f"{radius['EQ']:.0f}", "r_vo": f"{radius['VO']:.0f}",
        "orange_points": f"{config.HAZARD_LEVEL_POINTS['Orange']:g}",
        "red_points": f"{config.HAZARD_LEVEL_POINTS['Red']:g}",
        "gatun_text": gatun_text,
        "river_text": river_text,
        "news_hours": f"{config.NEWS_AI_REFRESH_SECONDS / 3600:g}",
        "rss_minutes": f"{config.NEWS_RSS_REFRESH_SECONDS / 60:g}",
        "briefing_alerts": str(config.NEWS_BRIEFING_MAX_ALERTS),
        "news_max_days": f"{config.NEWS_CACHE_MAX_AGE_SECONDS / 86400:g}",
        "retry_minutes": f"{config.AI_FAILURE_RETRY_SECONDS / 60:g}",
        "port_penalty_max": f"{config.PORT_PENALTY_MAX:g}",
        "timeout": f"{config.PROVIDER_TIMEOUT_SECONDS:g}",
        "timeout_long": f"{max(config.PROVIDER_TIMEOUT_OVERRIDES.values()):g}",
    }


def _step(num: int, label: str, text: str) -> str:
    return (f'<div class="step-item"><div class="step-num">{num}</div><div class="step-text">'
            f'<strong>{label}:</strong> {text}</div></div>')


def _card(title: str, badge: str, steps: list[tuple[str, str]]) -> str:
    body = "\n".join(_step(i, label, text) for i, (label, text) in enumerate(steps, 1))
    return (f'<div class="p-card">\n<h3>{title} <span class="card-badge">{badge}</span></h3>\n'
            f'<div class="step-list">\n{body}\n</div>\n</div>')


def _category_cards(v: dict[str, str]) -> str:
    """One card per weighted category: sources, measure, score, anchors, updates."""
    label = lambda cat: config.CATEGORY_LABELS[cat].replace("&", "&amp;")
    cards = {
        "supply_chain": [
            ("Source", "Federal Reserve Bank of New York, Global Supply Chain Pressure Index "
                       '(<span class="code-inline">GSCPI</span>), monthly.'),
            ("Measures", "Transport costs and supplier delivery times across major economies, combined "
                         "into one z-score where 0 is the historical average. Higher means more pressure."),
            ("Score", "The latest GSCPI on the anchored scale, lower is better. Baseline 1998 to 2019."),
            ("Anchors", v["a_gscpi"] + "."),
            ("Updates", f"Published about {v['lag_gscpi']} days after the month ends. "
                        f"GSCPI is {v['fresh_gscpi']}."),
        ],
        "chokepoints": [
            ("Source", "IMF PortWatch daily ship transits, counted from satellite AIS signals. "
                       "Sources: UN Global Platform; IMF PortWatch."),
            ("Measures", "Traffic through Malacca, the Taiwan Strait, Gibraltar, Hormuz, Dover, the Red Sea "
                         "(the worse of Bab el-Mandeb and Suez), the Bosporus and Panama. Cape of Good Hope "
                         "is shown for context only, because its traffic rises when ships reroute."),
            ("Score", "For each corridor, the 7-day average of daily transits divided by the average for "
                      "the same calendar month in January 2022 to October 2023. Traffic at "
                      f"{v['deadband']} of normal or above costs nothing. Below that: "
                      f'<span class="highlight-blue">Score = 100 &minus; {v["severity"]} &times; '
                      f"&Sigma;(weight &times; (1 &minus; min(ratio / {v['deadband_ratio']}, 1)))</span>, "
                      f"clipped to 0 to 100. {v['corridor_weights']}"),
            ("Anchors", f"There is no 80 point: a normal week scores 100. {v['closure_examples']}"),
            ("Updates", f"PortWatch publishes about {v['lag_chokepoint']} days after the date it covers. "
                        f"Transits are {v['fresh_chokepoint_flow']}."),
        ],
        "energy": [
            ("Sources", "EIA spot prices on FRED: Brent crude (<span class=\"code-inline\">DCOILBRENTEU</span>) "
                        "and New York Harbor ultra-low-sulfur diesel (<span class=\"code-inline\">DDFUELNYH</span>). "
                        "European TTF gas from IMF Primary Commodity Prices "
                        "(<span class=\"code-inline\">PNGASEUUSDM</span>). Live futures through Yahoo Finance: "
                        "Brent (BZ=F), heating oil (HO=F), TTF (TTF=F) and the euro-dollar rate (EURUSD=X)."),
            ("Measures", "Fuel cost pressure. Low prices score high even when they come from weak demand."),
            ("Score", f"Each price is adjusted to {v['cpi_dollars']}, put on a log scale and anchored. "
                      f"Weights: Brent {v['ew_brent']}, diesel {v['ew_ulsd']}, gas {v['ew_ttf']}. A leg whose "
                      f"real price rose more than {v['spike_start']} in 3 months loses up to "
                      f"{v['spike_points']} points (the full {v['spike_points']} at a rise of {v['spike_full']} or more), "
                      "weighted like the leg. For Brent and diesel, the latest official price is moved by "
                      "the futures change since that date. If the futures quote is older than the official "
                      f"price, or the change is outside {v['ratio_low']}x to {v['ratio_high']}x, the official "
                      "price is used and the hover text says so. Gas is converted directly: TTF=F (EUR/MWh) "
                      f"&times; EURUSD=X / {v['mwh_per_mmbtu']} gives $/MMBtu. It is used only when both quotes "
                      f"are at most {v['ttf_max_age']} days old and the result is within {v['ratio_low']}x to "
                      f"{v['ratio_high']}x of the latest IMF monthly price; otherwise the monthly price is used."),
            ("Anchors", f"{v['a_brent']}. {v['a_ulsd']}. {v['a_ttf']}. Baseline 1990 to 2019 (gas 1992 to 2019)."),
            ("Updates", "EIA spot prices on FRED update weekly; futures move the score during trading hours. "
                        f"Brent, diesel and live gas are {v['fresh_brent']}. The monthly gas price, used when "
                        f"the live quote fails, is {v['fresh_ttf_monthly']}."),
        ],
        "tariffs": [
            ("Sources", "Customs duty deposits from the U.S. Treasury Daily Treasury Statement. US goods "
                        "imports from the Census Bureau through FRED (<span class=\"code-inline\">BOPGIMP</span>). "
                        "The daily Trade Policy Uncertainty index by Caldara, Iacoviello, Molligo, Prestipino "
                        "and Raffo."),
            ("Measures", "What tariffs cost importers, and how uncertain trade policy is."),
            ("Score", f"{v['tw_burden']} tariff burden plus {v['tw_tpu']} trade policy uncertainty. Burden = "
                      f"customs deposits / goods imports, each summed over {v['burden_months']} months. Duties "
                      "are mostly paid the month after the goods arrive, so deposits for month m+1 are "
                      "paired with imports for month m. Deposits are counted before any IEEPA tariff "
                      f"refunds. Uncertainty is the {v['tpu_days']}-day mean of the daily index on a log "
                      "scale, anchored on the monthly index for 1985 to 2019."),
            ("Anchors", f"{v['a_burden']} {v['a_tpu']}."),
            ("Updates", "Treasury publishes deposits the next business day. Imports come about "
                        f"{v['lag_bopgimp']} days after the month ends, so a month's burden is ready about five "
                        f"weeks after it ends. The burden is {v['fresh_tariff_burden']}; uncertainty is "
                        f"{v['fresh_tpu']}."),
        ],
        "geopolitical": [
            ("Source", "Caldara-Iacoviello daily Geopolitical Risk (GPR) index."),
            ("Measures", "The share of newspaper articles about geopolitical threats and acts: wars, "
                         "terrorism, military buildups. 100 is the 1985 to 2019 average."),
            ("Score", f"The {v['gpr_days']}-day mean of the daily index on a log scale, anchored on the "
                      "monthly index for 1985 to 2019. Headlines do not affect this score."),
            ("Anchors", v["a_gpr"] + ", the record month."),
            ("Updates", f"The file is updated about weekly. GPR is {v['fresh_gpr']}. A disruption register "
                        f"kept by Claude is stored daily at {v['register_weight']} weight (see below)."),
        ],
        "freight": [
            ("Sources", "Bureau of Transportation Statistics Freight Transportation Services Index "
                        "(<span class=\"code-inline\">TSIFRGHT</span>), monthly. Surface Transportation Board "
                        "weekly rail carloads (EP 724) through USDA AgTransport."),
            ("Measures", "How much freight is moving in the US, as year-over-year growth. A contraction "
                         "scores low. Congestion and cost are measured elsewhere."),
            ("Score", f"{v['fw_tsi']} TSIFRGHT growth plus {v['fw_rail']} rail growth. Rail is originated "
                      f"carloads plus intermodal containers and trailers, the {v['rail_weeks']}-week average "
                      "against the same weeks a year earlier. The weekly STB series starts in 2017, so the "
                      "rail anchors come from BTS monthly rail carloads plus intermodal units on FRED "
                      "(RAILFRTCARLOADSD11 and RAILFRTINTERMODALD11), 2001 to 2019."),
            ("Anchors", f"{v['a_tsifrght']}. {v['a_rail']}. Baseline 2001 to 2019."),
            ("Updates", f"TSIFRGHT comes about {v['lag_tsifrght']} days after the month ends; rail about "
                        f"{v['lag_rail']} days after the week ends. TSIFRGHT is {v['fresh_tsifrght']}; rail is "
                        f"{v['fresh_rail_volume']}."),
        ],
        "inputs": [
            ("Sources", "Manufacturing prices-paid indexes from the Federal Reserve Banks of Philadelphia, "
                        "New York (Empire State) and Dallas, through FRED. IMF Primary Commodity Prices for "
                        "copper and aluminum (<span class=\"code-inline\">PCOPPUSDM</span>, "
                        "<span class=\"code-inline\">PALUMUSDM</span>). Live copper (HG=F) and aluminum (ALI=F) "
                        "futures through Yahoo Finance."),
            ("Measures", "What manufacturers pay for their inputs. Low prices score high even when they come "
                         "from weak demand."),
            ("Score", f"{v['iw_pp']} prices paid, {v['iw_copper']} copper, {v['iw_aluminum']} aluminum. Each "
                      "survey becomes a z-score against its own 2004 to 2019 mean and standard deviation, and "
                      "the surveys that reported that month are averaged. Metals are adjusted to "
                      f"{v['cpi_dollars']}, logged and anchored; live futures move the latest monthly price "
                      "the same way as in energy. Supplier delivery times are shown for context only."),
            ("Anchors", f"{v['a_prices_paid']}. {v['a_copper']}. {v['a_aluminum']}. Metals baseline 1992 to 2019."),
            ("Updates", "The surveys come out during the month they cover; IMF prices about "
                        f"{v['lag_imf']} days after the month ends. Surveys are {v['fresh_prices_paid']}. Live "
                        f"metals are {v['fresh_copper']}; the monthly fallback is {v['fresh_copper_monthly']}."),
        ],
        "physical": [
            ("Sources", "GDACS (Global Disaster Alert and Coordination System) alerts. Panama Canal Authority "
                        "Gatun Lake level. USGS gauge 07010000, Mississippi River at St. Louis."),
            ("Measures", "Natural events that stop ships near major ports, and low water on two waterways "
                         "that carry bulk cargo."),
            ("Score", f"{v['pw_hazards']} hazards, {v['pw_gatun']} Gatun Lake, {v['pw_river']} Mississippi. "
                      "Each Orange or Red GDACS alert for a tropical cyclone, flood, earthquake or volcano "
                      f"whose center is within {v['r_tc']}, {v['r_fl']}, {v['r_eq']} or {v['r_vo']} km of one "
                      f"of the 37 ports costs {v['hazard_scale']} &times; the port's share of world port calls "
                      f"&times; {v['orange_points']} (Orange) or {v['red_points']} (Red) points; the hazard score is 100 "
                      "minus the total, floored at 0. The cyclone radius is "
                      "our judgment, because GDACS gives only the storm's center."),
            ("Anchors", "There is no 80 point: a quiet day scores 100. One Red alert over a median top-10 "
                        f"port costs about 50 hazard points. {v['gatun_text']} {v['river_text']}"),
            ("Updates", f"Daily. Each input is {v['fresh_hazards']}. The Rhine gauge at Kaub is recorded, not "
                        "scored."),
        ],
    }
    return "\n".join(_card(label(cat), v[f"w_{cat}"], cards[cat]) for cat in config.CATEGORY_WEIGHTS)


_DOCS_MARKDOWN = """
<div class="section-heading"><span class="section-num">1.</span><h2>How the index is calculated</h2></div>
<hr class="section-rule">
<p>The Global Supply Chain Index is a weighted average of eight category scores. Each category runs from 0 to 100, where <strong>100 is healthiest</strong>. The site recalculates every 5 minutes. Most sources publish daily, weekly or monthly, so a category moves only when its source does.</p>

{category_rows}

<div class="math-block">
    <code>
        <span class="variable">Composite</span>
        <span class="operator">=</span>
        &Sigma; ( <span class="variable">Score<sub>i</sub></span> &times; <span class="variable">Weight<sub>i</sub></span> )
    </code>
    <span class="math-caption">The weights sum to 1.0. A category with no usable reading is left out, and the other weights are scaled up so they still sum to 1.0.</span>
</div>

<div class="callout">
    <p>When a category is excluded, the composite uses those renormalized weights. The weights shown in the category table, the CSV export and the API are the nominal ones, so on those days the scores times the listed weights do not add up to the composite. The snapshot is flagged degraded, and that day's composite is not saved to the history.</p>
</div>

<p>The composite maps to a health tier:</p>

| Score | Tier | Color |
|:---|:---|:---|
| 80 to 100 | **Healthy** | <span class="highlight-green">&#9679; Green</span> |
| 60 to 79 | **Stable** | <span class="highlight-amber">&#9679; Amber</span> |
| 40 to 59 | **Stressed** | <span style="color: #fb923c;">&#9679; Orange</span> |
| 0 to 39 | **Critical** | <span class="highlight-red">&#9679; Red</span> |

<div class="section-heading"><span class="section-num">2.</span><h2>The 0 to 100 scale</h2></div>
<hr class="section-rule">
<p>Six of the eight categories put each input on a fixed scale with three anchors taken from that input's own history:</p>

<div class="step-list" style="margin-bottom: 18px;">
    <div class="step-item"><div class="step-num">100</div><div class="step-text">The healthiest 5% of months before 2020 (the 5th or 95th percentile, depending on direction).</div></div>
    <div class="step-item"><div class="step-num">80</div><div class="step-text">The median before 2020. This is "normal".</div></div>
    <div class="step-item"><div class="step-num">0</div><div class="step-text">The worst monthly average on record through 2025. For the tariff burden, where the record is the current period, a cited historical reference is used instead.</div></div>
</div>
<p>Between anchors the score follows a straight line, and it is held at 0 or 100 beyond them. Prices are adjusted for inflation with CPI (<span class="code-inline">CPIAUCSL</span>) to {cpi_dollars} and put on a log scale. The two newspaper indexes (trade policy uncertainty and geopolitical risk) are also on a log scale. Volumes use year-over-year growth. The anchors are stored in <span class="code-inline">data/score_anchors.json</span> and change only with a new methodology version.</p>
<p>Normal is 80, the bottom of the Healthy tier. Chokepoints and Physical Disruption are built from events, so a normal day reads about 100 there. With every input at normal the composite is about {normal_composite}.</p>

<div class="section-heading"><span class="section-num">3.</span><h2>Freshness, fallbacks and history</h2></div>
<hr class="section-rule">
<div class="step-list">
    <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Age</strong> is counted from the end of the period a value covers: the last day of the month for monthly data, the week-ending date for weekly data, the day itself for daily data.</div></div>
    <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Two limits per input.</strong> Past the first, the input is flagged stale. Past the second, it is dropped. Each category's limits are listed below.</div></div>
    <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Missing inputs.</strong> If one input in a category is missing, the category uses the others with their weights scaled up. The category is stale if any input it uses is stale.</div></div>
    <div class="step-item"><div class="step-num">4</div><div class="step-text"><strong>Failed categories.</strong> If every input fails to load, the category shows its last stored daily score, flagged stale and fallback, until that stored score is too old (Supply Chain {drop_supply_chain} days, Chokepoints {drop_chokepoints}, Energy {drop_energy}, Tariffs {drop_tariffs}, Geopolitical {drop_geopolitical}, Freight {drop_freight}, Input Costs {drop_inputs}, Physical {drop_physical}). After that it is excluded from the composite. If the inputs load but are all past their drop limits, the category is excluded right away, because a stored score would be older still. A neutral placeholder score is never used.</div></div>
    <div class="step-item"><div class="step-num">5</div><div class="step-text"><strong>History</strong> is recomputed from the real source series with the same formulas. Each value is dated by when its source published it. Days before a source's first observation stay blank, and gaps are never filled.</div></div>
</div>

<div class="section-heading"><span class="section-num">4.</span><h2>Categories</h2></div>
<hr class="section-rule">
<p>Every number on the dashboard carries its source, the date of the data behind it and its stale or fallback status. Hover over a category name, or tap it on a phone, to see each input.</p>

<div class="grid-1">
{category_cards}
</div>

<div class="section-heading"><span class="section-num">5.</span><h2>What Claude does</h2></div>
<hr class="section-rule">
<p>Anthropic's Claude writes the headline severities, the briefing, the full report, the port summaries and the disruption register. None of these set a category score.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Headlines, briefing and report</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Headlines:</strong> articles from 17 RSS feeds, plus a daily Claude web search, are filtered for relevance. The feeds are re-read every {rss_minutes} minutes, and new headlines appear with no severity until Claude's next run. Every {news_hours} hours Claude scores the headlines it has not seen yet; earlier scores are kept. Without an API key, headlines show with no severity.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Topics:</strong> tags use whole-word matching, so "port" does not match "report".</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Briefing and report:</strong> once a day Claude writes a 3-bullet briefing from the top {briefing_alerts} headlines and the full report at <span class="code-inline">/report</span>.</div></div>
            <div class="step-item"><div class="step-num">4</div><div class="step-text"><strong>Failures:</strong> a failed call is retried after {retry_minutes} minutes. The last result stays up, marked stale, for up to {news_max_days} days.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Port summaries and disruption register</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Port summaries:</strong> once a day Claude writes a summary and a 0 to {port_penalty_max} disruption penalty for each of the 37 ports, shown on the map.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Disruption register:</strong> once a day Claude, with web search, keeps a list of ongoing disruptions. Each has a severity from 0 to 10 and the share of world trade affected, with a cited basis. An event stays open until there is evidence it has ended.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Shadow mode:</strong> register score = 100 &minus; {register_factor} &times; &Sigma;(severity &times; trade share %), floored at 0. It is stored every day at {register_weight} weight in Geopolitical Risk while it is compared with PortWatch and GPR.</div></div>
        </div>
    </div>
</div>

<div class="section-heading"><span class="section-num">6.</span><h2>Port map</h2></div>
<hr class="section-rule">
<p>Each of the 37 ports scores 60% of the composite plus 40% of its local weather (Open-Meteo: weather code, wind gusts, the day's precipitation and temperature). It then loses Claude's port penalty (0 to {port_penalty_max}), set from the day's port summary. Headlines are not matched to ports and do not change a port's score. Weather is shown on the map only and is not part of the composite.</p>

<div class="section-heading"><span class="section-num">7.</span><h2>Public API</h2></div>
<hr class="section-rule">
<p><span class="code-inline">GET /api/v1/latest</span> is free and returns the latest snapshot as JSON, limited to 500 requests per hour and 2,000 per day per IP. Data is licensed CC-BY-4.0. If you use the chokepoint data, credit "Sources: UN Global Platform; IMF PortWatch".</p>

| Field | Contents |
|:---|:---|
| <span class="code-inline">methodology_version</span> | 2 |
| <span class="code-inline">timestamp</span> | When the snapshot was made (UTC) |
| <span class="code-inline">composite_index</span> | The composite stored with the snapshot. Under an exclusion it uses renormalized weights |
| <span class="code-inline">categories</span> | One object per category: <span class="code-inline">score</span> (null when excluded), <span class="code-inline">weight</span> (nominal), <span class="code-inline">as_of</span> (date of the oldest input used), <span class="code-inline">source</span>, <span class="code-inline">is_stale</span>, <span class="code-inline">is_fallback</span>, <span class="code-inline">stored_on</span> (date of the stored score a fallback shows) and <span class="code-inline">inputs</span> (each input's name, score, as_of, status, source and raw value) |
| <span class="code-inline">degraded</span> | True when any category is on a fallback or excluded |
| <span class="code-inline">fallback_categories</span> | Categories showing their last stored score |
| <span class="code-inline">excluded_categories</span> | Categories left out of the composite |
| <span class="code-inline">stale_categories</span> | Categories using an input past its stale limit |
| <span class="code-inline">disruptions</span> | Low-scoring categories (impact = 100 &minus; score) and high-severity headlines (impact = severity &times; 10) |
| <span class="code-inline">map_markers</span> | The 37 ports with score and hover text |

<p><span class="code-inline">GET /health</span> returns <span class="code-inline">state</span> (warming_up, healthy or degraded, with HTTP 503 for degraded), <span class="code-inline">data_age_seconds</span>, <span class="code-inline">last_fetch_status</span>, <span class="code-inline">last_fetch_error</span> (the error type only), <span class="code-inline">fallback_categories</span>, <span class="code-inline">stale_categories</span> and <span class="code-inline">excluded_categories</span>.</p>

<div class="section-heading"><span class="section-num">8.</span><h2>Infrastructure</h2></div>
<hr class="section-rule">
<p>The site is built with <strong>Plotly Dash</strong>, served by Gunicorn and hosted on Render. A background thread does all the fetching, so page loads read from memory.</p>

<div class="mermaid">
flowchart LR
    style A fill:#07090C,stroke:#1D232B,color:#8A94A3
    style B fill:#07090C,stroke:#1D232B,color:#8A94A3
    style C fill:#07090C,stroke:#1D232B,color:#8A94A3
    style D fill:#07090C,stroke:#1D232B,color:#8A94A3
    style E fill:#07090C,stroke:#FFB020,stroke-width:2px,color:#F2F4F7
    style F fill:#07090C,stroke:#8A94A3,color:#F2F4F7
    style G fill:#07090C,stroke:#8A94A3,color:#F2F4F7
    style H fill:#07090C,stroke:#8A94A3,color:#F2F4F7

    A["NY Fed, FRED, Treasury<br>BTS, STB, Caldara-Iacoviello"] --> E
    B["IMF PortWatch, GDACS<br>Panama Canal, USGS"] --> E
    C["Yahoo Finance<br>(live futures)"] --> E
    D["RSS feeds and web search<br>(display only)"] --> F
    E["Background thread<br>8 category providers"] --> G["Neon Postgres<br>daily scores"]
    F["Claude<br>headlines, ports, register"] --> H
    E --> H["Dash UI<br>dashboard and API"]
</div>

<div class="grid-2">
    <div class="p-card">
        <h3>Background data pipeline</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Cycle:</strong> every 5 minutes the providers run 3 at a time. Each has {timeout} seconds ({timeout_long} for Freight and Physical); one that runs over is treated as failed.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Cache:</strong> results are saved to disk. A fresh deploy loads the last snapshot saved in the database, then a committed fallback snapshot if it is under 14 days old.</div></div>
            <div class="step-item"><div class="step-num">3</div><div class="step-text"><strong>Serve:</strong> page loads read the in-memory snapshot and never call a data source.</div></div>
        </div>
    </div>
    <div class="p-card">
        <h3>Storage and email</h3>
        <div class="step-list">
            <div class="step-item"><div class="step-num">1</div><div class="step-text"><strong>Database:</strong> Neon PostgreSQL stores daily category scores, the daily composite (only on days with no excluded category), the latest snapshot, the disruption register and river gauge readings.</div></div>
            <div class="step-item"><div class="step-num">2</div><div class="step-text"><strong>Newsletter:</strong> the daily briefing is emailed each morning with the stored composite. No email goes out when there is no composite. Every email has an unsubscribe link.</div></div>
        </div>
    </div>
</div>

<div class="section-heading"><span class="section-num">9.</span><h2>News sources</h2></div>
<hr class="section-rule">
<p>Headlines come from 17 RSS feeds from industry, trade policy and weather alert sources, plus a daily Claude web search. They are shown for context and do not feed any score.</p>

<div class="grid-2">
    <div class="p-card">
        <h3>Ports and shipping</h3>
        <p>gCaptain, Splash 247, The Loadstar, Maritime Executive, Logistics Management (Ocean Freight)</p>
    </div>
    <div class="p-card">
        <h3>Supply chain and logistics</h3>
        <p>Supply Chain Dive, SupplyChainBrain, FreightWaves, Logistics Management (Transportation), Supply Chain Management Review, Logistics Viewpoints</p>
    </div>
    <div class="p-card">
        <h3>Trade policy</h3>
        <p>WTO News</p>
    </div>
    <div class="p-card">
        <h3>Weather and disasters</h3>
        <p>GDACS Disaster Alerts, plus four NOAA National Hurricane Center feeds (Atlantic and Eastern Pacific cyclones, Atlantic outlook, Atlantic high seas forecast)</p>
    </div>
</div>

<div class="section-heading"><span class="section-num">10.</span><h2>Data sources and credits</h2></div>
<hr class="section-rule">

| Source | Data used |
|:---|:---|
| [Federal Reserve Bank of New York](https://www.newyorkfed.org/research/policy/gscpi) | Global Supply Chain Pressure Index; Empire State Manufacturing Survey prices paid (FRED PPCDISA066MSFRBNY) |
| [IMF PortWatch](https://portwatch.imf.org) | Daily chokepoint transits and port calls. Sources: UN Global Platform; IMF PortWatch |
| [FRED, Federal Reserve Bank of St. Louis](https://fred.stlouisfed.org) | Distribution of most monthly and daily series below, and CPI (CPIAUCSL) |
| [U.S. Energy Information Administration (EIA)](https://www.eia.gov) | Brent crude and New York Harbor ULSD spot prices (FRED DCOILBRENTEU, DDFUELNYH) |
| [Yahoo Finance](https://finance.yahoo.com) | Live futures quotes from ICE (Brent, TTF) and CME Group (heating oil, copper, aluminum) |
| [U.S. Treasury, Daily Treasury Statement](https://fiscaldata.treasury.gov) | Customs duty deposits |
| [U.S. Census Bureau via FRED](https://fred.stlouisfed.org/series/BOPGIMP) | Goods imports (BOPGIMP) |
| [Caldara and Iacoviello](https://www.matteoiacoviello.com/gpr.htm) | Geopolitical Risk (GPR) index |
| [Caldara, Iacoviello, Molligo, Prestipino and Raffo](https://www.matteoiacoviello.com/tpu.htm) | Trade Policy Uncertainty index |
| [Bureau of Transportation Statistics](https://www.bts.gov) | Freight Transportation Services Index (TSIFRGHT); monthly rail carloads and intermodal units (FRED RAILFRTCARLOADSD11, RAILFRTINTERMODALD11) |
| [Surface Transportation Board, via USDA AgTransport](https://agtransport.usda.gov/Rail/STB-Weekly-Rail-Carloads/tb7q-kn5i) | Weekly rail carloads (EP 724) |
| [Federal Reserve Bank of Philadelphia](https://fred.stlouisfed.org/series/PPCDFSA066MSFRBPHI) | Manufacturing Business Outlook Survey prices paid |
| [Federal Reserve Bank of Dallas](https://fred.stlouisfed.org/series/PRMSAMFRBDAL) | Texas Manufacturing Outlook Survey prices paid for raw materials |
| [IMF Primary Commodity Prices](https://www.imf.org/en/Research/commodity-prices) | European natural gas, copper and aluminum (FRED PNGASEUUSDM, PCOPPUSDM, PALUMUSDM) |
| [GDACS](https://www.gdacs.org) | Natural hazard alerts |
| [Panama Canal Authority](https://evtms-rpts.pancanal.com/eng/h2o/index.html) | Gatun Lake level |
| [USGS](https://waterdata.usgs.gov/monitoring-location/07010000/) | Mississippi River gauge height at St. Louis (site 07010000) |
| [USITC](https://www.usitc.gov/documents/dataweb/ave_table_1891_2018.pdf) | Duties as a share of imports, 1891 to 2018 (tariff burden zero point) |
| [Open-Meteo](https://open-meteo.com) | Port weather for the map |
| [Anthropic](https://www.anthropic.com) | Claude: headline severities, briefing, report, port summaries, disruption register |
"""


def _docs_markdown() -> str:
    values = _docs_values()
    values["category_cards"] = _category_cards(values)
    return _DOCS_MARKDOWN.format(**values)


@docs_bp.route("/docs")
def serve_docs():
    """Serve the methodology page, with the current config's numbers filled in."""
    docs_html = markdown.markdown(_docs_markdown(), extensions=["extra", "tables"])
    return render_template_string(
        _DOCS_TEMPLATE,
        content=Markup(docs_html),
        version=config.METHODOLOGY_VERSION,
    )
