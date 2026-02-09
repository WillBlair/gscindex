"""
News & Alerts Feed + Disruption Events Table
=============================================
Bottom section of the dashboard showing:
    - Recent supply-chain alerts (color-coded by severity)
    - Active disruption events with impact scores
"""

from __future__ import annotations

from datetime import datetime

from dash import html

from config import CATEGORY_LABELS, COLORS


_SEVERITY_STYLES: dict[str, dict] = {
    "high":   {"border": COLORS["red"],    "badge_bg": COLORS["red"]},
    "medium": {"border": COLORS["orange"], "badge_bg": COLORS["orange"]},
    "low":    {"border": COLORS["green"],  "badge_bg": COLORS["green"]},
}


def _format_time_ago(iso_timestamp: str) -> str:
    """Convert an ISO timestamp to a human-readable 'X hours ago' string.

    Handles both timezone-aware (NewsAPI sends ``Z`` suffix) and
    timezone-naive timestamps gracefully.
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "recently"

    # Strip timezone info so we can subtract from naive datetime.now()
    dt = dt.replace(tzinfo=None)
    diff = datetime.now() - dt
    total_seconds = diff.total_seconds()

    if total_seconds < 0:
        return "just now"
    if total_seconds < 3600:
        return f"{int(total_seconds / 60)}m ago"
    if total_seconds < 86400:
        return f"{int(total_seconds / 3600)}h ago"
    return f"{int(total_seconds / 86400)}d ago"


def build_alerts_feed(alerts: list[dict], briefing_text: str = "") -> html.Div:
    """Build the alerts/news feed panel.

    Parameters
    ----------
    alerts : list[dict]
        Each dict has keys: timestamp, severity, title, body, category.
    briefing_text : str
        Optional AI-generated daily briefing summary.

    Returns
    -------
    html.Div
    """
    if not alerts and not briefing_text:
        return html.Div(
            className="panel",
            children=[
                html.H3("Recent Alerts", className="panel-title"),
                html.P(
                    "No alerts available. Configure API keys to enable live alerts.",
                    className="alert-body",
                    style={"color": COLORS["text_muted"], "padding": "20px 0"},
                ),
            ],
        )

    items = []

    # --- Daily Briefing Card ---
    # Option 5: Show button to generate briefing on-demand (reduces automatic API usage)
    if briefing_text:
        # Briefing already exists - display it
        items.append(
            html.Div(
                className="daily-briefing-card",
                style={
                    "backgroundColor": "#f8f9fa",
                    "border": f"1px solid {COLORS['card_border']}",
                    "borderRadius": "8px",
                    "padding": "16px",
                    "marginBottom": "20px",
                    "boxShadow": "0 2px 4px rgba(0,0,0,0.05)",
                },
                children=[
                    html.H4(
                        "AI Daily Briefing", 
                        style={
                            "margin": "0 0 12px 0", 
                            "fontSize": "14px", 
                            "fontWeight": "700",
                            "color": COLORS["accent"],
                            "textTransform": "uppercase",
                            "letterSpacing": "0.5px"
                        }
                    ),
                    html.Div(
                        id="briefing-content",
                        style={"fontSize": "13px", "lineHeight": "1.5", "color": "#1f2937"},
                        children=[html.P(line) for line in briefing_text.split("\n") if line.strip()]
                    ),
                    # Hidden button placeholder to prevent callback errors
                    html.Button(id="generate-briefing-btn", style={"display": "none"}),
                ]
            )
        )
    else:
        # No briefing yet - show generate button (reduces automatic API calls)
        items.append(
            html.Div(
                className="daily-briefing-card",
                style={
                    "backgroundColor": "#1a1d26",
                    "border": f"1px solid {COLORS['card_border']}",
                    "borderRadius": "8px",
                    "padding": "16px",
                    "marginBottom": "20px",
                    "textAlign": "center",
                },
                children=[
                    html.H4(
                        "AI Daily Briefing", 
                        style={
                            "margin": "0 0 12px 0", 
                            "fontSize": "14px", 
                            "fontWeight": "700",
                            "color": COLORS["accent"],
                            "textTransform": "uppercase",
                            "letterSpacing": "0.5px"
                        }
                    ),
                    html.Div(
                        id="briefing-content",
                        children=[
                            html.P(
                                "Click to generate an AI-powered summary of today's supply chain news.",
                                style={"color": COLORS["text_muted"], "marginBottom": "12px", "fontSize": "13px"}
                            ),
                            html.Button(
                                "Generate Briefing",
                                id="generate-briefing-btn",
                                style={
                                    "backgroundColor": COLORS["accent"],
                                    "color": "white",
                                    "border": "none",
                                    "borderRadius": "6px",
                                    "padding": "10px 20px",
                                    "fontSize": "13px",
                                    "fontWeight": "600",
                                    "cursor": "pointer",
                                },
                            ),
                        ]
                    ),
                ]
            )
        )

    for alert in alerts:
        sev = _SEVERITY_STYLES.get(alert["severity"], _SEVERITY_STYLES["low"])

        # Show which supply chain category this alert was classified into
        cat_key = alert.get("category", "geopolitical")
        cat_label = CATEGORY_LABELS.get(cat_key, cat_key.title())

        item = html.Div(
            className="alert-item",
            style={"borderLeft": f"3px solid {sev['border']}"},
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
                                    style={"backgroundColor": sev["badge_bg"]},
                                ),
                                html.Span(
                                    cat_label,
                                    className="category-tag",
                                    style={
                                        "fontSize": "10px",
                                        "color": COLORS["text_muted"],
                                        "backgroundColor": COLORS["card"],
                                        "padding": "2px 8px",
                                        "borderRadius": "4px",
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
                    style={"display": "block", "textDecoration": "none", "color": "inherit", "fontWeight": "600", "marginBottom": "4px", "hover": {"textDecoration": "underline"}}
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
