"""
News & Alerts Feed + Disruption Events Table
=============================================
Bottom section of the dashboard showing:
    - Recent supply-chain alerts (color-coded by severity)
    - Active disruption events with impact scores
"""

from __future__ import annotations

from datetime import datetime, timezone

from dash import html, dcc

from config import CATEGORY_LABELS, COLORS, hex_to_rgba


# Soft pills: tinted background + tier-colored text/border, no harsh
# white-on-neon fill and no colored left edge on the alert card itself.
_SEVERITY_STYLES: dict[str, dict] = {
    "high":   {"color": COLORS["red"],    "bg": hex_to_rgba(COLORS["red"], 0.15)},
    "medium": {"color": COLORS["orange"], "bg": hex_to_rgba(COLORS["orange"], 0.15)},
    "low":    {"color": COLORS["green"],  "bg": hex_to_rgba(COLORS["green"], 0.15)},
}


def _format_time_ago(iso_timestamp: str, *, now: datetime | None = None) -> str:
    """Convert an ISO timestamp to a human-readable 'X hours ago' string.

    Handles both timezone-aware (NewsAPI sends ``Z`` suffix) and
    timezone-naive timestamps gracefully.
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "recently"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    current_time = now if now is not None else datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    diff = current_time.astimezone(timezone.utc) - dt.astimezone(timezone.utc)
    total_seconds = diff.total_seconds()

    if total_seconds < 0:
        return "just now"
    if total_seconds < 3600:
        return f"{int(total_seconds / 60)}m ago"
    if total_seconds < 86400:
        return f"{int(total_seconds / 3600)}h ago"
    return f"{int(total_seconds / 86400)}d ago"


def format_briefing_content(briefing_text: str) -> list:
    """Turn briefing text into styled bullet rows matching the alerts panel language.

    Lines are split on newlines; leading bullet glyphs (``•``, ``-``, ``*``)
    are stripped so CSS can render a consistent mono marker.
    """
    items = []
    for line in briefing_text.split("\n"):
        text = line.strip()
        if not text:
            continue
        if text[:1] in {"•", "-", "*", "–", "—"}:
            text = text[1:].strip()
        items.append(
            html.Div(
                className="briefing-item",
                children=[
                    html.Span("▸", className="briefing-marker", **{"aria-hidden": "true"}),
                    html.P(text, className="briefing-text"),
                ],
            )
        )
    return items


def build_briefing_panel(briefing_text: str = "") -> html.Div:
    """Build the AI Daily Briefing panel.

    Parameters
    ----------
    briefing_text : str
        Optional AI-generated daily briefing summary.

    Returns
    -------
    html.Div
    """
    if briefing_text:
        content = html.Div(
            className="daily-briefing-card",
            children=[
                html.Div(
                    id="briefing-content",
                    className="briefing-list",
                    children=format_briefing_content(briefing_text),
                ),
                # Hidden button placeholder (keeps the on-demand callback wired)
                html.Button(id="generate-briefing-btn", style={"display": "none"}),
                html.A(
                    "Read Full Report →",
                    href="/report",
                    target="_blank",
                    className="briefing-report-link",
                ),
            ],
        )
    else:
        content = html.Div(
            className="daily-briefing-card daily-briefing-card--empty",
            children=[
                dcc.Loading(
                    id="briefing-loading",
                    type="dot",
                    color=COLORS["text_muted"],
                    custom_spinner=html.Div(
                        className="briefing-spinner",
                        children=[
                            html.Span("Composing briefing…", className="briefing-spinner-label"),
                        ],
                    ),
                    children=html.Div(
                        id="briefing-content",
                        className="briefing-empty",
                        children=[
                            html.P(
                                "Click to generate an AI-powered summary of today's supply chain news.",
                                className="briefing-empty-copy",
                            ),
                            html.Button(
                                "Generate Briefing",
                                id="generate-briefing-btn",
                                className="briefing-generate-btn",
                            ),
                        ],
                    ),
                ),
            ],
        )

    return html.Div(
        className="panel",
        children=[
            html.H3("AI Daily Briefing", className="panel-title"),
            content,
        ],
    )


def build_news_panel(alerts: list[dict]) -> html.Div:
    """Build the Recent Alerts / News list panel.

    Parameters
    ----------
    alerts : list[dict]
        Each dict has keys: timestamp, severity, title, body, category.

    Returns
    -------
    html.Div
    """
    if not alerts:
        return html.Div(
            className="panel",
            children=[
                html.H3("Recent Alerts", className="panel-title"),
                html.P(
                    "No alerts available.",
                    className="alert-body",
                    style={"color": COLORS["text_muted"], "padding": "20px 0"},
                ),
            ],
        )

    items = []
    for alert in alerts:
        sev = _SEVERITY_STYLES.get(alert["severity"], _SEVERITY_STYLES["low"])
        cat_key = alert.get("category", "geopolitical")
        cat_label = CATEGORY_LABELS.get(cat_key, cat_key.title())

        item = html.Div(
            className="alert-item",
            children=[
                html.Div(
                    className="alert-header",
                    children=[
                        html.Div(
                            style={"display": "flex", "gap": "8px", "alignItems": "center"},
                            children=[
                                html.Span(
                                    alert["severity"].upper(),
                                    className="severity-badge",
                                    style={
                                        "backgroundColor": sev["bg"],
                                        "color": sev["color"],
                                        "border": f"1px solid {sev['color']}",
                                    },
                                ),
                                html.Span(
                                    cat_label,
                                    className="category-tag",
                                    style={
                                        "fontSize": "10px",
                                        "color": COLORS["text_muted"],
                                        "backgroundColor": COLORS["card"],
                                        "padding": "2px 8px",
                                        "borderRadius": "var(--radius)",
                                        "border": f"1px solid {COLORS['card_border']}",
                                    },
                                ),
                            ],
                        ),
                        html.Div(
                            className="alert-meta",
                            style={"display": "flex", "gap": "6px", "alignItems": "center", "fontSize": "11px", "color": COLORS["text_muted"]},
                            children=[
                                html.Span(alert.get("source", "News"), className="alert-source", style={"fontWeight": "600", "color": COLORS["text"]}),
                                html.Span("•"),
                                html.Span(
                                    _format_time_ago(alert["timestamp"]),
                                    className="alert-time",
                                ),
                            ]
                        ),
                    ],
                ),
                html.A(
                    alert["title"],
                    href=alert.get("url", "#"),
                    target="_blank",
                    className="alert-title",
                    style={"display": "block", "textDecoration": "none", "color": "inherit", "fontWeight": "600", "marginBottom": "4px"},
                ),
                html.P(alert["body"], className="alert-body"),
            ],
        )
        items.append(item)

    return html.Div(
        className="panel",
        children=[
            html.H3("Recent Alerts", className="panel-title"),
            html.Div(items, className="alerts-list"),
        ],
    )


def build_disruptions_table(disruptions: list[dict]) -> html.Div:
    """Build the active disruption events table.

    Parameters
    ----------
    disruptions : list[dict]
        Each dict has keys: event, region, impact_score, categories, started, status.

    Returns
    -------
    html.Div
    """
    if not disruptions:
        return html.Div(
            className="panel",
            children=[
                html.H3("Active Disruptions", className="panel-title"),
                html.P(
                    "No active disruptions tracked.",
                    className="alert-body",
                    style={"color": COLORS["text_muted"], "padding": "20px 0"},
                ),
            ],
        )

    header = html.Tr([
        html.Th("Event"),
        html.Th("Region"),
        html.Th("Impact"),
        html.Th("Affected"),
        html.Th("Since"),
        html.Th("Status"),
    ])

    rows = []
    for d in sorted(disruptions, key=lambda x: x["impact_score"], reverse=True):
        # Color the impact score by severity
        impact = d["impact_score"]
        if impact >= 7:
            impact_color = COLORS["red"]
        elif impact >= 5:
            impact_color = COLORS["orange"]
        else:
            impact_color = COLORS["yellow"]

        # Use text labels instead of emojis for the affected categories
        affected_labels = ", ".join(
            CATEGORY_LABELS.get(c, c) for c in d["categories"]
        )

        row = html.Tr([
            html.Td(d["event"], className="td-event"),
            html.Td(d["region"]),
            html.Td(
                f"{impact:.1f}",
                style={"color": impact_color, "fontWeight": "600"},
            ),
            html.Td(affected_labels, className="td-affected"),
            html.Td(d["started"]),
            html.Td(d["status"], className="td-status"),
        ])
        rows.append(row)

    table = html.Table(
        className="disruptions-table",
        children=[
            html.Thead(header),
            html.Tbody(rows),
        ],
    )

    return html.Div(
        className="panel",
        children=[
            html.H3("Active Disruptions", className="panel-title"),
            table,
        ],
    )
