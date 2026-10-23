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

# Bounds on model output. The prompts document these ranges; the code enforces
# them so one bad value cannot swing a headline severity or a port.
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

# Claude scores headlines it has not seen yet this often (incremental; earlier
# severities are kept). Web search, the briefing and the full report stay on the
# daily AI_CACHE_TTL_SECONDS run. News is display-only; it feeds no score.
NEWS_AI_REFRESH_SECONDS: int = int(os.environ.get("NEWS_AI_REFRESH_SECONDS", "21600"))
# Between Claude runs the RSS feeds are re-read this often; new headlines join the cached
# alerts unscored until the next NEWS_AI_REFRESH_SECONDS run scores them (no Claude call).
NEWS_RSS_REFRESH_SECONDS: int = int(os.environ.get("NEWS_RSS_REFRESH_SECONDS", "3600"))
NEWS_MAX_ALERTS: int = 60          # headlines kept, newest by published time
NEWS_BRIEFING_MAX_ALERTS: int = 15 # top alerts (severity, then recency) the daily briefing reads

# Shared disk cache key for RSS/AI news payload (alerts, briefing, report).
NEWS_BRIEFING_CACHE_KEY: str = "newsapi_briefing_v19"

# FRED inverse/direct scoring uses a trailing window (not full 5yr history).
# Avoids COVID-era spikes from pinning "normal" prices in the middle of the scale.
FRED_SCORE_LOOKBACK_DAYS: int = int(os.environ.get("FRED_SCORE_LOOKBACK_DAYS", "730"))

# ---------------------------------------------------------------------------
# Category Definitions
# ---------------------------------------------------------------------------
# Each category contributes to the overall Supply Chain Health Index.
# Scores are 0–100 where 100 = healthiest / least disrupted.
# Weights MUST sum to 1.0 — the scoring engine will yell at you if they don't.
# ---------------------------------------------------------------------------

# Methodology v2 (docs/superpowers/specs/2026-10-22-score-rebuild-design.md, section 2).
# A category whose provider fails to fetch uses its last stored score while it is younger
# than CATEGORY_DROP_AFTER_DAYS; beyond that it is excluded and the aggregator renormalizes the
# remaining weights explicitly (scoring.engine.renormalized_weights). A category whose inputs
# are all past their FRESHNESS drop windows is excluded at once. Weather is map-only.
CATEGORY_WEIGHTS: dict[str, float] = {
    "supply_chain":  0.20,  # NY Fed GSCPI, anchored
    "chokepoints":   0.15,  # IMF PortWatch transits through eight maritime corridors
    "energy":        0.15,  # Brent, NY Harbor ULSD and TTF, real prices plus spike penalty
    "tariffs":       0.15,  # tariff burden (customs duties / goods imports) + trade policy uncertainty
    "geopolitical":  0.10,  # Caldara-Iacoviello daily GPR (Claude register in shadow)
    "freight":       0.10,  # BTS Freight TSI YoY + weekly STB rail carloads and intermodal YoY
    "inputs":        0.10,  # regional Fed prices paid + real copper and aluminum
    "physical":      0.05,  # GDACS hazards near ports + Mississippi at St. Louis
}

# Seconds the aggregator waits for each provider, counted from the start of the refresh
# cycle. A provider that times out takes the same path as one that failed (last stored
# score, else excluded). Physical (GDACS up to ~83 s plus three gauges in series) and
# freight (a cold Socrata rail query up to 120 s) get longer.
PROVIDER_TIMEOUT_SECONDS: float = 45
PROVIDER_TIMEOUT_OVERRIDES: dict[str, float] = {"physical": 150, "freight": 150}

# The committed data/fallback_snapshot_safe.json is only served on a cold
# start (no disk cache, no database snapshot) while it is younger than this.
FALLBACK_SNAPSHOT_MAX_AGE_DAYS: int = 14

# Categories scoring below this appear in the disruptions table.
DISRUPTION_SCORE_THRESHOLD: float = 70.0

CATEGORY_LABELS: dict[str, str] = {
    "weather":             "Weather",  # Shortened to fit on one line
    "supply_chain":        "Supply Chain", # Shortened to fit on one line
    "chokepoints":         "Chokepoints",
    "freight":             "Freight Volume",
    "energy":              "Energy & Fuel",
    "tariffs":             "Trade & Tariffs",
    "geopolitical":        "Geopolitical Risk",
    "inputs":              "Input Costs",
    "physical":            "Physical Disruption",
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
    # Sector index categories (SECTORS below; never part of the global composite)
    "semis_memory_prices":   "Memory Prices",
    "semis_logic_prices":    "Logic Chip Prices",
    "semis_fab_utilization": "Fab Utilization",
    "aero_throughput":       "Aero Throughput",
    "aero_flow":             "Delivery Flow",
    "aero_mill_prices":      "Mill Prices",
    "aero_forge_cast":       "Forgings & Castings",
}

# Display names for the canonical input keys in a category's ``inputs`` metadata
# (the category hover lists each input with its as-of date and status).
INPUT_LABELS: dict[str, str] = {
    "gscpi":            "NY Fed GSCPI",
    "chokepoint_flow":  "Chokepoint transits",
    "brent":            "Brent crude",
    "ulsd":             "Diesel (ULSD)",
    "ttf":              "TTF gas",
    "ttf_monthly":      "TTF gas (monthly)",
    "tariff_burden":    "Tariff burden",
    "tpu":              "Trade policy uncertainty",
    "gpr":              "Geopolitical risk index",
    "geo_register":     "Disruption register",
    "tsifrght":         "Freight TSI",
    "rail_volume":      "Rail volume",
    "prices_paid":      "Prices paid surveys",
    "copper":           "Copper",
    "aluminum":         "Aluminum",
    "copper_monthly":   "Copper (monthly)",
    "aluminum_monthly": "Aluminum (monthly)",
    "hazards":          "Natural hazards",
    "mississippi":      "Mississippi River stage",
    "boj_memory":       "Memory chip import prices (BOJ)",
    "boj_logic":        "Logic chip import prices (BOJ)",
    "fab_util_3344":    "Semiconductor capacity utilization",
    "aero_caputl":           "Aerospace capacity utilization",
    "aero_inv_ship":         "Aircraft inventory to shipments",
    "ppi_ti_mill":           "Titanium mill shapes PPI",
    "ppi_ni_mill":           "Nickel alloy mill shapes PPI",
    "ppi_ti_forge":          "Titanium forgings PPI",
    "ppi_nonferrous_forge":  "Nonferrous forgings PPI",
    "ppi_steel_invest_cast": "Steel investment castings PPI",
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

# Temporary until industry profiles are rebuilt: the baseline categories take 0.60 of each
# industry profile (the baseline weights x 0.60) and the industry categories keep their 0.40.
INDUSTRY_BASELINE_SHARE: float = 0.60


def _industry_weights(industry: dict[str, float]) -> dict[str, float]:
    weights = {cat: round(w * INDUSTRY_BASELINE_SHARE, 10) for cat, w in CATEGORY_WEIGHTS.items()}
    weights.update(industry)
    return weights


INDUSTRY_PROFILES: dict[str, dict] = {
    "baseline": {
        "label": "Baseline (Global)",
        "description": "General supply chain health across all sectors",
        "weights": dict(CATEGORY_WEIGHTS),
        # Cards shown in the dashboard row (replaces on profile switch).
        "card_categories": list(CATEGORY_WEIGHTS),
        "providers": [],
    },
    "semiconductor": {
        "label": "Semiconductor",
        "description": (
            "Chip supply chain — fab utilization, memory prices, lead times, "
            "and wafer pricing from Silicon Analysts API"
        ),
        "weights": _industry_weights({
            "chip_fab_util":      0.20,
            "chip_memory_prices": 0.10,
            "chip_lead_times":    0.05,
            "chip_wafer_prices":  0.05,
        }),
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
        "weights": _industry_weights({
            "aero_metals":      0.15,
            "aero_orders":      0.10,
            "aero_production":  0.10,
            "aero_ppi":         0.05,
        }),
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

for _key, _profile in INDUSTRY_PROFILES.items():
    if abs(sum(_profile["weights"].values()) - 1.0) > 1e-9:
        raise ValueError(f"INDUSTRY_PROFILES[{_key!r}] weights must sum to 1.0")

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
    "chokepoints":         "#818cf8",
    "freight":             "#34d399",
    "energy":              "#fbbf24",
    "tariffs":             "#fb7185",
    "geopolitical":        "#22d3ee",
    "inputs":              "#fb923c",
    "physical":            "#a3e635",
    "chip_fab_util":       "#5f8f9c",
    "chip_memory_prices":  "#7d7394",
    "chip_lead_times":     "#5a8f86",
    "chip_wafer_prices":   "#9c6b7a",
    "aero_metals":         "#6a8494",
    "aero_orders":         "#7a6e8a",
    "aero_production":     "#5f8a72",
    "aero_ppi":            "#a07a62",
    "semis_memory_prices":   "#8b7fc7",
    "semis_logic_prices":    "#4aa3b8",
    "semis_fab_utilization": "#4fae9a",
    "aero_throughput":       "#e8854a",
    "aero_flow":             "#6f8fd8",
    "aero_mill_prices":      "#b9c04a",
    "aero_forge_cast":       "#c9708f",
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
    "tariff_burden":    (75, 150),
    "tpu":              (14, 42),
    "gpr":              (14, 42),
    "geo_register":     (3, 9),
    "tsifrght":         (120, 200),
    "rail_volume":      (14, 45),
    "prices_paid":      (60, 150),
    "hazards":          (3, 9),
    "mississippi":      (3, 9),
    "boj_memory":       (75, 150),
    "boj_logic":        (75, 150),
    "fab_util_3344":    (75, 150),
    "aero_caputl":           (75, 150),
    "aero_inv_ship":         (75, 150),
    "ppi_ti_mill":           (75, 150),
    "ppi_ni_mill":           (75, 150),
    "ppi_ti_forge":          (75, 150),
    "ppi_nonferrous_forge":  (75, 150),
    "ppi_steel_invest_cast": (75, 150),
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
    "boj_cgpi":        12,   # Bank of Japan Corporate Goods Price Index, about 12 days after month end
    "g17":             16,   # Fed G.17 industrial production, mid-month for the prior month
    "census_m3":       35,   # Census M3 manufacturers' shipments, inventories and orders
    "bls_ppi":         15,   # BLS Producer Price Index, mid-month for the prior month
}

# How long a category whose provider failed to fetch may show its last stored daily score
# (counted from the day the row was stored, flagged fallback and stale); after that it is
# excluded from the composite. Inputs are dropped by their own FRESHNESS limits; when every
# input that returned data is past its drop window the provider raises InputsExpired and the
# category is excluded at once, with no stored score.
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
# severity factor, so a closed Hormuz alone (tonnage weight 0.13) takes the category to about 61.
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

# Freight Volume: year-over-year growth of the BTS Freight TSI (monthly) and of weekly STB rail
# carloads plus intermodal units, equally weighted (renormalized over the inputs available).
# Keys are the canonical input keys. IYT is not an input.
FREIGHT_WEIGHTS: dict[str, float] = {"tsifrght": 0.5, "rail_volume": 0.5}
TSIFRGHT_YOY_MONTHS = 12         # months back the TSIFRGHT year-over-year compares with
RAIL_MEAN_WEEKS = 4              # trailing weeks averaged before the rail year-over-year
RAIL_YOY_LAG_WEEKS = 52          # weeks back the rail year-over-year compares with
# Runtime FRED window for TSIFRGHT: the 12-month base, the history tail and the publication lag.
FREIGHT_FRED_LOOKBACK_DAYS = 3 * 365

# Input Costs: regional Fed manufacturing prices-paid composite (z-scored against each
# survey's own 2004-2019 mean and sd, SCORE_ANCHORS["prices_paid_stats"]) plus real copper and
# aluminum prices. Keys are the canonical input keys; weights are renormalized over what is available.
INPUT_WEIGHTS: dict[str, float] = {"prices_paid": 0.5, "copper": 0.25, "aluminum": 0.25}
COPPER_USD_PER_LB_TO_USD_PER_MT = 2204.62   # HG=F is $/lb, the IMF series PCOPPUSDM is $/mt
ALUMINUM_LIVE_UNIT_FACTOR = 1.0             # ALI=F is already $/mt (checked against PALUMUSDM)
# Runtime FRED window for the surveys, metals and CPI: the current value, the CPI deflator and
# the history tail, never the full history.
INPUTS_FRED_LOOKBACK_DAYS = 3 * 365

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

# Physical Disruption: natural hazards near ports (GDACS Orange and Red alerts, weighted by
# port throughput share) and the Mississippi River stage at St. Louis. Keys are the canonical
# input keys; weights are renormalized over what is available. The Kaub (Rhine) gauge is stored
# for later study and never scored.
# The Panama Canal's Gatun Lake level is deliberately not an input: the Panama Canal Authority's
# data page asks for written consent before redistribution, and Panama disruptions are already
# measured by IMF PortWatch Panama Canal transits in the Chokepoints category.
PHYSICAL_WEIGHTS: dict[str, float] = {"hazards": 2 / 3, "mississippi": 1 / 3}

# GDACS hazard penalty = HAZARD_SCALE x sum over affected ports of (port throughput share x
# level points). Shares are each port's share of all PortWatch port calls in 2022-2023
# (SCORE_ANCHORS["port_throughput_share"]); the top 10 of the 37 ports hold 0.51% (Tokyo) to
# 2.37% (Singapore), median 0.99%. Calibrated so one Red event over the median top-10 port
# costs about 50 points (5000 x 0.0099 x 1.0): Tokyo 26, Hong Kong 43, Shanghai or Singapore
# the whole 100.
HAZARD_SCALE: float = 5000.0
HAZARD_LEVEL_POINTS: dict[str, float] = {"Orange": 0.5, "Red": 1.0}
# A port is affected by an event whose centre lies within this many km. Rough footprints of
# a damaging event of each GDACS type (ours, not GDACS's): tropical cyclone 450 km, flood
# 100 km, earthquake 150 km, volcano 50 km. The cyclone radius is a judgment, not a citation:
# a strong typhoon's gale-force wind radius commonly extends several hundred km, and GDACS
# gives only the storm's centre point. At 300 km, Red typhoon CHAMPI-26 (centre 358 km from
# Kaohsiung on 2026-10-22, its tropical-storm-force wind zone within 80 km of the port) did not
# register.
HAZARD_RADIUS_KM: dict[str, float] = {"TC": 450.0, "FL": 100.0, "EQ": 150.0, "VO": 50.0}
# Days of GDACS events fetched for the current reading; an event still active today may have
# started weeks ago (a tropical cyclone lasts up to about two weeks).
HAZARD_LOOKBACK_DAYS = 90
# Days of St. Louis gauge height requested for the current reading (the latest daily value
# is used; the extra days cover a gap in the series).
PHYSICAL_GAUGE_LOOKBACK_DAYS = 30
# The Rhine at Kaub (stored for study, never scored) is fetched and upserted at most this often.
KAUB_STORE_INTERVAL_SECONDS = 3600

# Mississippi at St. Louis: no single published stage was found that the Coast Guard or the Corps
# ties to draft or tow limits (the Corps has said it can hold a 9 ft channel down to about -5 ft,
# while the Coast Guard decides restrictions from observed conditions, not the gauge reading), so
# the low-water threshold is the gauge's own 10th-percentile stage,
# SCORE_ANCHORS["waterways"]["mississippi_threshold"], and 0 is its record low,
# SCORE_ANCHORS["waterways"]["mississippi_record_low"] (both computed in Task 12).
# Sanity bounds on source values; a unit or datum change falls outside and counts as missing.
MISSISSIPPI_STL_PLAUSIBLE_FT: tuple[float, float] = (-15.0, 50.0)

# ---------------------------------------------------------------------------
# Sector indexes (Semis, Aero)
# ---------------------------------------------------------------------------
# Each sector has its own categories and equal weights. Sector categories never enter the
# global composite, its disruptions, degraded flags or /health status. A sector index is shown
# only while at least ``min_categories`` of its categories have a score.
SECTORS: dict[str, dict] = {
    "semiconductor": {
        "label": "Semis",
        "title": "Semiconductor",
        "weights": {
            "semis_memory_prices":   1 / 3,
            "semis_logic_prices":    1 / 3,
            "semis_fab_utilization": 1 / 3,
        },
        "min_categories": 2,
    },
    "aerospace": {
        "label": "Aero",
        "title": "Aerospace",
        "weights": {
            "aero_throughput":  1 / 4,
            "aero_flow":        1 / 4,
            "aero_mill_prices": 1 / 4,
            "aero_forge_cast":  1 / 4,
        },
        "min_categories": 3,
    },
}

for _key, _sector in SECTORS.items():
    if abs(sum(_sector["weights"].values()) - 1.0) > 1e-9:
        raise ValueError(f"SECTORS[{_key!r}] weights must sum to 1.0")

# A sector category with no fresh inputs is excluded after this many days (monthly sources).
SECTOR_DROP_AFTER_DAYS: int = 150

# Seconds the aggregator waits for each sector provider, counted from the start of its cycle.
SECTOR_PROVIDER_TIMEOUT_SECONDS: float = 60

# Categories of the industry profiles retired in project 3 (Silicon Analysts and the old aerospace
# adapter). Their stored rows stay in the database untouched; the aggregator never reads them and
# app startup strips them from an old snapshot.
RETIRED_CATEGORIES: frozenset[str] = frozenset({
    "chip_fab_util", "chip_memory_prices", "chip_lead_times", "chip_wafer_prices",
    "aero_metals", "aero_orders", "aero_production", "aero_ppi",
})

# Credit line required by the Bank of Japan Time-Series Data Search API terms. It appears in the
# description of every category that uses BOJ data and in the API output.
BOJ_CREDIT: str = (
    "This service uses the API provided by the 'Bank of Japan Time-Series Data Search.' "
    "The Bank of Japan does not guarantee the content of the service.")

# Runtime FRED window for the Fed G.17 capacity utilization series: the latest month, the
# history tail and the publication lag, never the full history.
SEMIS_FRED_LOOKBACK_DAYS = 3 * 365

# Runtime FRED window for the Aero series: 13 months for a year-over-year change, 3 months of
# shipments, the history tail and the publication lag, never the full history.
AERO_FRED_LOOKBACK_DAYS = 3 * 365
