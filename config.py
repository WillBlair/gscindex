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
# Claude (Anthropic API) — refresh budget (file-backed cache, per server)
# ---------------------------------------------------------------------------
# Background work still runs every few minutes, but each AI-powered
# component consults its own cache and only calls the API when this TTL
# expires (~once per day by default). Set AI_CACHE_TTL_SECONDS=43200
# for roughly twice daily.
AI_CACHE_TTL_SECONDS: int = int(os.environ.get("AI_CACHE_TTL_SECONDS", "86400"))

# After a failed Claude call, wait this long before trying again instead of
# re-sending the full prompt every 5-minute refresh cycle.
AI_FAILURE_RETRY_SECONDS: int = int(os.environ.get("AI_FAILURE_RETRY_SECONDS", "3600"))

# Bounds on model output that feeds scores. The prompts document these
# ranges; the code enforces them so one bad value cannot swing a category.
AI_SEVERITY_MAX: float = 10.0      # per-article severity is clamped to +/- this
PORT_PENALTY_MAX: float = 50.0     # per-port disruption_penalty is clamped to 0..this

# Claude web search (AI_WEB_SEARCH=0 turns it off). Searches are billed per
# use, so each call has a cap. News search runs once per AI refresh (~daily).
NEWS_WEB_SEARCH_MAX_USES: int = int(os.environ.get("NEWS_WEB_SEARCH_MAX_USES", "8"))
NEWS_WEB_SEARCH_MAX_ARTICLES: int = 15
NEWS_AI_MAX_ARTICLES: int = 35     # articles Claude scores per run (web + RSS)
PORT_WEB_SEARCH_MAX_USES: int = int(os.environ.get("PORT_WEB_SEARCH_MAX_USES", "25"))

# How long a news payload stays usable as a fallback while the next Claude
# run is pending. Freshness of the AI analysis is tracked inside the payload.
NEWS_CACHE_MAX_AGE_SECONDS: int = 7 * 86400

# Re-score geopolitical alerts from live RSS between full AI runs (no API cost).
NEWS_RSS_REFRESH_SECONDS: int = int(os.environ.get("NEWS_RSS_REFRESH_SECONDS", "3600"))

# Shared disk cache key for RSS/AI news payload (alerts, briefing, report).
NEWS_BRIEFING_CACHE_KEY: str = "newsapi_briefing_v18"

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
# GSCPI (supply_chain) is a monthly NY Fed series that can sit flat for weeks.
# Blend in a genuinely daily proxy so the composite moves day to day instead
# of only on print days.
#   supply_chain = (1 - SUPPLY_CHAIN_PROXY_WEIGHT) * GSCPI + SUPPLY_CHAIN_PROXY_WEIGHT * BDRY_proxy
# Kept as a minority blend (25-30%) so the well-vetted monthly print still
# anchors the score; the proxy just adds daily texture between prints.
# If the proxy fetch fails, providers fall back to 100% monthly (no crash).
SUPPLY_CHAIN_PROXY_WEIGHT: float = float(os.environ.get("SUPPLY_CHAIN_PROXY_WEIGHT", "0.30"))

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

# The committed data/fallback_snapshot_safe.json is only served on a cold
# start (no disk cache, no database snapshot) while it is younger than this.
FALLBACK_SNAPSHOT_MAX_AGE_DAYS: int = 14

# Categories scoring below this appear in the disruptions table.
DISRUPTION_SCORE_THRESHOLD: float = 70.0

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
    "weather":             "#60a5fa",
    "supply_chain":        "#c084fc",
    "freight":             "#34d399",
    "energy":              "#fbbf24",
    "tariffs":             "#fb7185",
    "geopolitical":        "#22d3ee",
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
# Pre-Terminal palette (2026-07-25)
# ---------------------------------------------------------------------------

# Used by the newsletter email (scripts/send_newsletter.py). The dashboard
# palette is in
# assets/terminal.css and components.terminal_data.TIER_COLORS.
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

# High-contrast map colors. Health thresholds remain defined by HEALTH_TIERS.
MAP_HEALTH_COLORS = {
    "Critical": "#ff4969", "Stressed": "#ff963f",
    "Stable": "#f8d84a", "Healthy": "#20df9c",
}
MAP_RISK_SCALE = [
    [0.0, "#ff4969"], [0.25, "#ff963f"], [0.5, "#f8d84a"],
    [0.75, "#73e589"], [1.0, "#20df9c"],
]


# ---------------------------------------------------------------------------
# Score rebuild (methodology v2)
# ---------------------------------------------------------------------------
METHODOLOGY_VERSION: int = 2


_SCORE_ANCHORS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "score_anchors.json")


def _load_score_anchors(path: str = _SCORE_ANCHORS_PATH) -> dict:
    """Read data/score_anchors.json; a missing or invalid file gives {} (never raises)."""
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# Anchored 0-100 mapping per input: 100 = healthiest 5% of pre-2020 history,
# 80 = pre-2020 median, 0 = worst monthly average on record through 2025.
SCORE_ANCHORS: dict = _load_score_anchors()

# Per input: (stale_after_days, drop_after_days), counted from the observation's
# period end. Past stale_after the input is flagged stale; past drop_after it is dropped.
FRESHNESS: dict[str, tuple[int, int]] = {
    "gscpi":            (75, 150),
    "chokepoint_flow":  (14, 42),
    "brent":            (10, 30),
    "ulsd":             (10, 30),
    "ttf":              (10, 30),
    "copper":           (10, 30),
    "aluminum":         (10, 30),
    "ttf_monthly":      (75, 150),
    "copper_monthly":   (75, 150),
    "aluminum_monthly": (75, 150),
    "tariff_burden":    (60, 150),
    "tpu":              (14, 42),
    "gpr":              (14, 42),
    "geo_register":     (3, 9),
    "tsifrght":         (120, 200),
    "rail_volume":      (14, 45),
    "prices_paid":      (60, 150),
    "hazards":          (3, 9),
    "gatun":            (3, 9),
    "mississippi":      (3, 9),
}

# Live Yahoo scaling (data/sources/markets.py): the move since the official date must stay
# inside these bounds, otherwise it is a unit change or bad tick and the official value is used.
LIVE_SCALE_RATIO_BOUNDS: tuple[float, float] = (0.5, 2.0)

# Days between a period ending and the source publishing it; history is dated by this lag.
PUBLICATION_LAG_DAYS: dict[str, int] = {
    "gscpi":           5,
    "tsifrght":        80,
    "prices_paid":     0,
    "imf_monthly":     35,
    "dts":             1,
    "bopgimp":         35,
    "gpr":             7,
    "tpu":             7,
    "rail_volume":     5,
    "chokepoint_flow": 4,
}

# A category whose oldest used input is older than this is dropped from the composite.
CATEGORY_DROP_AFTER_DAYS: dict[str, int] = {
    "supply_chain": 150,
    "chokepoints":  42,
    "energy":       30,
    "tariffs":      150,
    "geopolitical": 42,
    "freight":      200,
    "inputs":       150,
    "physical":     9,
}

# Chokepoints: a corridor at or above this share of its normal traffic is not a problem
# (deadband); each corridor's shortfall below it is weighted and multiplied by the
# severity factor, so a closed Hormuz alone takes the category to about 63.
CHOKEPOINT_DEADBAND = 0.90
CHOKEPOINT_SEVERITY = 3.0

# Energy: leg weights (renormalized over the legs that are available) and the spike
# penalty. The penalty takes `max_points` off a leg whose real price rose `full` or more
# over `ENERGY_SPIKE_LOOKBACK_DAYS`, nothing below `start`, linear in between. Each leg's
# penalty is weighted like the leg and subtracted from the blended score.
ENERGY_LEG_WEIGHTS: dict[str, float] = {"brent": 0.35, "ulsd": 0.40, "ttf": 0.25}
ENERGY_SPIKE: dict[str, float] = {"start": 0.20, "full": 0.82, "max_points": 15.0}
ENERGY_SPIKE_LOOKBACK_DAYS = 91

# Live TTF: EUR/MWh x EURUSD / this = USD/MMBtu. The quote must be at most this many days old.
MWH_PER_MMBTU = 3.412
TTF_LIVE_MAX_AGE_DAYS = 5

# Runtime FRED window for the energy legs and CPI: enough for the current value, the 91-day
# reference, the CPI deflator and the history tail, never the full history.
ENERGY_FRED_LOOKBACK_DAYS = 3 * 365

# Trade & Tariffs: customs duties as a share of goods imports (Treasury DTS / BOPGIMP) and
# the daily Trade Policy Uncertainty index (Caldara et al.). Keys are the canonical input keys.
TARIFF_WEIGHTS: dict[str, float] = {"tariff_burden": 0.6, "tpu": 0.4}
TARIFF_BURDEN_MONTHS = 3         # trailing months summed on both sides of the burden ratio
TPU_MEAN_DAYS = 30               # trailing days averaged in the daily TPU index
TPU_MIN_PERIODS = 20             # fewest observations a 30-day mean may rest on
# Runtime FRED window for BOPGIMP and EPUTRADE: the burden's 3-month sums, the history tail
# and the publication lag, never the full history.
TARIFFS_FRED_LOOKBACK_DAYS = 3 * 365

# Geopolitical category: the 30-day mean of the daily GPR index, plus a hook for the
# stored Claude disruption register (written by the register job; weight 0 until it is trusted).
GPR_MEAN_DAYS = 30               # trailing days averaged in the daily GPR index
GPR_MIN_PERIODS = 20             # fewest observations a 30-day mean may rest on
GEO_REGISTER_WEIGHT = 0.0        # share of the geopolitical score taken from the stored register

# Claude disruption register (data/register.py): ongoing disruptions stay counted until
# Claude finds evidence they are resolved. Score = 100 - min(100, factor x sum(severity x share)).
REGISTER_WEB_SEARCH_MAX_USES: int = int(os.environ.get("REGISTER_WEB_SEARCH_MAX_USES", "8"))
REGISTER_MAX_ARTICLES = 50       # RSS articles shown to Claude per register run
REGISTER_MAX_OPEN_EVENTS = 25    # open events kept per run, highest severity first
REGISTER_MAX_EVIDENCE = 5        # evidence URLs kept per event
REGISTER_SEVERITY_MAX = 10.0     # severity is clamped to 0..this
REGISTER_SCORE_FACTOR = 0.3      # points per unit of severity x trade share %
