"""
Global Supply Chain Index — Global Supply Chain Health Index
==============================================
Central configuration for the entire dashboard.

All tunable parameters, category weights, thresholds, and display settings
live here so you never have to hunt through component code to change behavior.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Gemini API — refresh budget (file-backed cache, per server)
# ---------------------------------------------------------------------------
# Background work still runs every few minutes, but each Gemini-powered
# component consults its own cache and only calls the API when this TTL
# expires (~once per day by default). Set GEMINI_CACHE_TTL_SECONDS=43200
# for roughly twice daily.
GEMINI_CACHE_TTL_SECONDS: int = int(os.environ.get("GEMINI_CACHE_TTL_SECONDS", "86400"))

# Re-score geopolitical alerts from live RSS between full Gemini runs (no API cost).
NEWS_RSS_REFRESH_SECONDS: int = int(os.environ.get("NEWS_RSS_REFRESH_SECONDS", "3600"))

# Shared disk cache key for RSS/Gemini news payload (alerts, briefing, report).
NEWS_BRIEFING_CACHE_KEY: str = "newsapi_briefing_v16"

# FRED inverse/direct scoring uses a trailing window (not full 5yr history).
# Avoids COVID-era spikes from pinning "normal" prices in the middle of the scale.
FRED_SCORE_LOOKBACK_DAYS: int = int(os.environ.get("FRED_SCORE_LOOKBACK_DAYS", "730"))

# ---------------------------------------------------------------------------
# GSCPI score calibration
# ---------------------------------------------------------------------------
# GSCPI is a z-score (0 = average pressure). We map it to 0-100 health via
#   score = 50 - GSCPI * GSCPI_SCORE_SCALE   (clipped 0-100)
# Scale 12.5 means the index zeroes out at +4 sigma — GSCPI's real historical
# extreme (Dec-2021 COVID peak was ~+4.3). The previous scale of 25 zeroed out
# at only +2 sigma, which collapsed moderate-but-not-crisis readings (e.g.
# +1.8 sigma) to a near-zero "Critical" score and overstated severity.
GSCPI_SCORE_SCALE: float = float(os.environ.get("GSCPI_SCORE_SCALE", "12.5"))

# ---------------------------------------------------------------------------
# Daily proxy blend weights (Fix 2: supplement frozen monthly series)
# ---------------------------------------------------------------------------
# GSCPI (supply_chain) and EPUTRADE (tariffs) are monthly FRED/NY-Fed series —
# they can sit flat for weeks. Blend in a genuinely daily proxy for each so
# the composite actually moves day to day instead of only on print days.
#   supply_chain = (1 - SUPPLY_CHAIN_PROXY_WEIGHT) * GSCPI + SUPPLY_CHAIN_PROXY_WEIGHT * BDRY_proxy
#   tariffs      = (1 - TARIFFS_PROXY_WEIGHT) * EPUTRADE + TARIFFS_PROXY_WEIGHT * tariff_news_nowcast
# Kept as a minority blend (25-30%) so the well-vetted monthly print still
# anchors the score; the proxy just adds daily texture between prints.
# If the proxy fetch fails, providers fall back to 100% monthly (no crash).
SUPPLY_CHAIN_PROXY_WEIGHT: float = float(os.environ.get("SUPPLY_CHAIN_PROXY_WEIGHT", "0.30"))
TARIFFS_PROXY_WEIGHT: float = float(os.environ.get("TARIFFS_PROXY_WEIGHT", "0.30"))

# TSIFRGHT (BTS Freight Transportation Services Index) is monthly with a
# 1-2 month publication lag -- the longest lag of any category. Blend in a
# daily transportation-sector equity proxy (IYT) the same way GSCPI and
# EPUTRADE are blended above. Same 30% minority weight, same fail-safe
# fallback to 100% TSIFRGHT if the proxy fetch fails.
FREIGHT_PROXY_WEIGHT: float = float(os.environ.get("FREIGHT_PROXY_WEIGHT", "0.30"))

# ---------------------------------------------------------------------------
# Port disruption blend weight (aggregate port_analyst signal -> geopolitical)
# ---------------------------------------------------------------------------
# generate_port_summaries() (data/port_analyst.py) already produces a
# per-port AI disruption_penalty (0-50) grounded in live news, but until now
# it only affected individual map markers -- the aggregate signal never fed
# back into the geopolitical category score. Blending a minority weight in
# gives geopolitical a second, port-grounded read on top of the raw
# news-severity score.
PORT_DISRUPTION_WEIGHT: float = float(os.environ.get("PORT_DISRUPTION_WEIGHT", "0.15"))

# ---------------------------------------------------------------------------
# Industry-specific provider cache
# ---------------------------------------------------------------------------
# Semiconductor and other industry-specific data is slow-moving (quarterly
# or monthly updates). A 24-hour cache prevents unnecessary API calls.
INDUSTRY_PROVIDER_CACHE_TTL: int = int(os.environ.get("INDUSTRY_PROVIDER_CACHE_TTL", "86400"))

# ---------------------------------------------------------------------------
# Freight Flow score calibration (BTS Freight Transportation Services Index)
# ---------------------------------------------------------------------------
# Physical freight throughput is scored from its year-over-year growth:
#   score = FREIGHT_YOY_BASELINE + yoy_pct * FREIGHT_YOY_SLOPE   (clipped 0-100)
# A freight *contraction* (negative YoY) signals real disruption / demand
# destruction and pulls the score down; steady or growing volume reads healthy.
# Baseline 72 puts flat YoY (0%) at "Stable"; slope 6.5 puts a -6% freight
# recession near "Critical" (33) and +4% growth near "Healthy" (98).
FREIGHT_YOY_BASELINE: float = float(os.environ.get("FREIGHT_YOY_BASELINE", "72.0"))
FREIGHT_YOY_SLOPE: float = float(os.environ.get("FREIGHT_YOY_SLOPE", "6.5"))

# ---------------------------------------------------------------------------
# Category Definitions
# ---------------------------------------------------------------------------
# Each category contributes to the overall Supply Chain Health Index.
# Scores are 0–100 where 100 = healthiest / least disrupted.
# Weights MUST sum to 1.0 — the scoring engine will yell at you if they don't.
# ---------------------------------------------------------------------------

# Weights favor genuine disruption/flow signals over pure cost gauges.
# Disruption-oriented (weather, supply_chain, freight, geopolitical) = 0.65;
# cost-oriented (energy+fuel, tariffs) = 0.35. Crude oil and diesel are the
# same petroleum complex (diesel is refined crude, correlation > 0.9), so they
# are blended into a single "energy" category rather than weighted twice.
CATEGORY_WEIGHTS: dict[str, float] = {
    "weather":             0.10,
    "supply_chain":        0.25,  # NY Fed GSCPI — core disruption index
    "freight":             0.10,  # BTS Freight Transportation Services Index (throughput)
    "energy":              0.20,  # blended WTI crude + retail diesel cost pressure
    "tariffs":             0.15,  # trade policy uncertainty
    "geopolitical":        0.20,
}

# Fallback scores when a provider fails — visible and tunable in one place.
DEFAULT_FALLBACK_SCORES: dict[str, float] = {
    "weather":      75.0,   # Conservative — assumes minor disruptions
    "geopolitical": 85.0,   # Optimistic baseline (100 means "no risk at all")
    "default":      50.0,   # Neutral for everything else
}

CATEGORY_LABELS: dict[str, str] = {
    "weather":             "Weather",  # Shortened to fit on one line
    "supply_chain":        "Supply Chain", # Shortened to fit on one line
    "freight":             "Freight Flow",
    "energy":              "Energy & Fuel",
    "tariffs":             "Trade & Tariffs",
    "geopolitical":        "Geopolitical Risk",
    # Semiconductor-specific categories (industry profile mode)
    "chip_fab_util":       "Fab Utilization",
    "chip_memory_prices":  "Memory Prices",
    "chip_lead_times":     "Lead Times",
    "chip_wafer_prices":   "Wafer Prices",
    # Aerospace-specific categories (industry profile mode)
    "aero_metals":         "Aero Metals",
    "aero_orders":         "Aircraft Orders",
    "aero_production":     "Aero Production",
    "aero_ppi":            "Aircraft PPI",
}

# ---------------------------------------------------------------------------
# Industry Profiles
# ---------------------------------------------------------------------------
# Each profile defines custom category weights, which cards to show in the
# dashboard row (`card_categories`), and optional industry-specific providers.
# Weights MUST sum to 1.0 per profile. Switching profiles replaces the card
# row (it does not append) while the gauge still uses the full weight set.
# ---------------------------------------------------------------------------

DEFAULT_PROFILE: str = "baseline"

INDUSTRY_PROFILES: dict[str, dict] = {
    "baseline": {
        "label": "Baseline (Global)",
        "description": "General supply chain health across all sectors",
        "weights": {
            "weather":        0.10,
            "supply_chain":   0.25,
            "freight":        0.10,
            "energy":         0.20,
            "tariffs":        0.15,
            "geopolitical":   0.20,
        },
        # Cards shown in the dashboard row (replaces on profile switch).
        "card_categories": [
            "weather",
            "supply_chain",
            "freight",
            "energy",
            "tariffs",
            "geopolitical",
        ],
        "providers": [],
    },
    "semiconductor": {
        "label": "Semiconductor",
        "description": (
            "Chip supply chain — fab utilization, memory prices, lead times, "
            "and wafer pricing from Silicon Analysts API"
        ),
        "weights": {
            "weather":            0.05,
            "supply_chain":       0.15,
            "freight":            0.05,
            "energy":             0.10,
            "tariffs":            0.10,
            "geopolitical":       0.15,
            "chip_fab_util":      0.20,
            "chip_memory_prices": 0.10,
            "chip_lead_times":    0.05,
            "chip_wafer_prices":  0.05,
        },
        # Replace the baseline row with chip signals + the two highest-weight
        # shared categories. Remaining weights still feed the composite gauge.
        "card_categories": [
            "chip_fab_util",
            "chip_memory_prices",
            "chip_lead_times",
            "chip_wafer_prices",
            "supply_chain",
            "geopolitical",
        ],
        "providers": ["silicon_analysts"],
    },
    "aerospace": {
        "label": "Aerospace & Manufacturing",
        "description": (
            "Aerospace industrial base — aluminum/nickel cost pressure, "
            "Census aircraft orders, Fed aerospace production, and aircraft PPI"
        ),
        "weights": {
            "weather":          0.05,
            "supply_chain":     0.10,
            "freight":          0.10,
            "energy":           0.10,
            "tariffs":          0.10,
            "geopolitical":     0.15,
            "aero_metals":      0.15,
            "aero_orders":      0.10,
            "aero_production":  0.10,
            "aero_ppi":         0.05,
        },
        # Replace the baseline row with aero signals + the two highest-weight
        # shared categories. Remaining weights still feed the composite gauge.
        "card_categories": [
            "aero_metals",
            "aero_orders",
            "aero_production",
            "aero_ppi",
            "geopolitical",
            "supply_chain",
        ],
        "providers": ["aerospace"],
    },
}

# ---------------------------------------------------------------------------
# Health-Status Thresholds
# ---------------------------------------------------------------------------
# Maps the composite 0–100 score to a human-readable label and color.
# Evaluated top-down; first matching range wins.
# ---------------------------------------------------------------------------

HEALTH_TIERS: list[dict] = [
    {"min": 80, "max": 100, "label": "Healthy",  "color": "#3d9b6e"},
    {"min": 60, "max": 79,  "label": "Stable",   "color": "#c4a35a"},
    {"min": 40, "max": 59,  "label": "Stressed", "color": "#c47a3a"},
    {"min": 0,  "max": 39,  "label": "Critical", "color": "#c44d5f"},
]

# ---------------------------------------------------------------------------
# Dashboard Chrome
# ---------------------------------------------------------------------------

APP_TITLE = "Global Supply Chain Index"
APP_SUBTITLE = "by William Blair"
APP_AUTHOR_URL = "https://williamcblair.com"
HISTORY_DAYS = 90            # how many days of history to show in charts
REFRESH_INTERVAL_MS = 0      # 0 = manual only; 300_000 = 5-min auto-refresh

# ---------------------------------------------------------------------------
# Per-Category Colors (used in the multi-line trend chart)
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[str, str] = {
    "weather":             "#6b8cae",
    "supply_chain":        "#8a7e9c",
    "freight":             "#5f8f7a",
    "energy":              "#b8956a",
    "tariffs":             "#a66d6d",
    "geopolitical":        "#a67c5b",
    "chip_fab_util":       "#5f8f9c",
    "chip_memory_prices":  "#7d7394",
    "chip_lead_times":     "#5a8f86",
    "chip_wafer_prices":   "#9c6b7a",
    "aero_metals":         "#6a8494",
    "aero_orders":         "#7a6e8a",
    "aero_production":     "#5f8a72",
    "aero_ppi":            "#a07a62",
}

# ---------------------------------------------------------------------------
# Color Palette (consistent across all charts)
# ---------------------------------------------------------------------------

# Keep in sync with :root tokens in assets/style.css (UI makeover 2026-07-25).
COLORS = {
    "bg":           "#0a0a0b",
    "card":         "#111113",
    "card_raised":  "#18181b",
    "card_border":  "rgba(255,255,255,0.10)",
    "card_border_hex": "#2a2a2e",  # Plotly geo attrs need solid hex
    "text":         "#ececef",
    "text_muted":   "#8b8b93",
    "text_faint":   "#5c5c66",
    "accent":       "#a1a1aa",  # quiet focus / link hover — not indigo
    "green":        "#4ade80",
    "yellow":       "#c4a35a",
    "orange":       "#c47a3a",
    "red":          "#c44d5f",
    "blue":         "#6b8cae",
    "grid":         "#1e1e22",
}


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a hex color string to an rgba() CSS string.

    Parameters
    ----------
    hex_color : str
        Hex color like ``"#3d9b6e"``.
    alpha : float
        Opacity between 0.0 and 1.0.

    Returns
    -------
    str
        CSS ``rgba(r, g, b, a)`` string.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"
