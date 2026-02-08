"""
Global Supply Chain Index — Global Supply Chain Health Index
==============================================
Central configuration for the entire dashboard.

All tunable parameters, category weights, thresholds, and display settings
live here so you never have to hunt through component code to change behavior.
"""

# ---------------------------------------------------------------------------
# Category Definitions
# ---------------------------------------------------------------------------
# Each category contributes to the overall Supply Chain Health Index.
# Scores are 0–100 where 100 = healthiest / least disrupted.
# Weights MUST sum to 1.0 — the scoring engine will yell at you if they don't.
# ---------------------------------------------------------------------------

CATEGORY_WEIGHTS: dict[str, float] = {
    "weather":      0.15,
    "ports":        0.20,
    "energy":       0.15,
    "tariffs":      0.15,
    "shipping":     0.15,
    "geopolitical": 0.10,
    "demand":       0.10,
}

CATEGORY_LABELS: dict[str, str] = {
    "weather":      "Weather Disruptions",
    "ports":        "Port Congestion",
    "energy":       "Energy & Fuel",
    "tariffs":      "Trade & Tariffs",
    "shipping":     "Shipping Rates",
    "geopolitical": "Geopolitical Risk",
    "demand":       "Demand & Inventory",
}

# ---------------------------------------------------------------------------
# Health-Status Thresholds
# ---------------------------------------------------------------------------
# Maps the composite 0–100 score to a human-readable label and color.
# Evaluated top-down; first matching range wins.
# ---------------------------------------------------------------------------

HEALTH_TIERS: list[dict] = [
    {"min": 80, "max": 100, "label": "Healthy",       "color": "#00d97e"},
    {"min": 60, "max": 79,  "label": "Moderate Risk",  "color": "#f6c343"},
    {"min": 40, "max": 59,  "label": "Elevated Risk",  "color": "#fd7e14"},
    {"min": 0,  "max": 39,  "label": "Critical",       "color": "#e63757"},
]

# ---------------------------------------------------------------------------
# Dashboard Chrome
# ---------------------------------------------------------------------------

APP_TITLE = "Global Supply Chain Index"
APP_SUBTITLE = "Global Supply Chain Health Index"
HISTORY_DAYS = 90            # how many days of history to show in charts
REFRESH_INTERVAL_MS = 0      # 0 = manual only; 300_000 = 5-min auto-refresh

# ---------------------------------------------------------------------------
# Regions Tracked on the Risk Heatmap
# ---------------------------------------------------------------------------

REGIONS: list[str] = [
    "North America",
    "South America",
    "Europe",
    "East Asia",
    "Southeast Asia",
    "South Asia",
    "Middle East",
    "Sub-Saharan Africa",
    "Oceania",
]

# ---------------------------------------------------------------------------
# Color Palette (consistent across all charts)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-Category Colors (used in the multi-line trend chart)
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[str, str] = {
    "weather":      "#3b82f6",   # blue
    "ports":        "#8b5cf6",   # purple
    "energy":       "#f59e0b",   # amber
    "tariffs":      "#ef4444",   # red
    "shipping":     "#06b6d4",   # cyan
    "geopolitical": "#f97316",   # orange
    "demand":       "#10b981",   # emerald
}

# ---------------------------------------------------------------------------
# Color Palette (consistent across all charts)
# ---------------------------------------------------------------------------

COLORS = {
    "bg":           "#0f1117",
    "card":         "#1a1d26",
    "card_border":  "#2a2d3a",
    "text":         "#e1e4ea",
    "text_muted":   "#8a8f9e",
    "accent":       "#6366f1",   # indigo-500
    "green":        "#00d97e",
    "yellow":       "#f6c343",
    "orange":       "#fd7e14",
    "red":          "#e63757",
    "blue":         "#3b82f6",
    "grid":         "#1e2130",
}


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a hex color string to an rgba() CSS string.

    Parameters
    ----------
    hex_color : str
        Hex color like ``"#6366f1"``.
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
