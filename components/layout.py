"""Terminal dashboard layout: one continuous grid of panes (Draft E).

Desktop grid (300px | 1fr | 300px):
    header
    readout | map | quotes
    headlines (two columns) | briefing
    category table (full width)
"""
from __future__ import annotations

from datetime import datetime

import dash_bootstrap_components as dbc
from dash import dcc, html

from components.charts import _finite_score, build_world_map
from components.terminal import (
    build_briefing, build_category_table, build_header, build_headlines,
    build_quotes, build_readout, updated_label,
)
from config import CATEGORY_LABELS, DEFAULT_PROFILE, INDUSTRY_PROFILES

TREND_DAYS = (7, 30, 90)
# Filters, range and profile survive a reload within the browser session.
PERSIST = {"persistence": True, "persistence_type": "session"}
DEFAULT_TREND_DAYS = 30

# Drag to pan and scroll to zoom stay on; the mode bar is hidden as in the draft.
MAP_CONFIG = {"displayModeBar": False, "scrollZoom": True, "responsive": True, "displaylogo": False}


def map_caption(markers) -> str:
    """Pane caption; counts the markers the map actually draws."""
    count = sum(1 for m in markers or [] if _finite_score(m.get("score", 100)))
    return f"{count} ports, colored by relative risk"


def _title(left, right=""):
    return html.Div([html.Span(left), html.Span(right)], className="ttl")


def news_filter_options():
    """Headlines are global, so the topics are the baseline categories."""
    return [{"label": "All topics", "value": "all"}] + [
        {"label": CATEGORY_LABELS.get(c, c), "value": c} for c in INDUSTRY_PROFILES[DEFAULT_PROFILE]["weights"]
    ]


def _hidden_label(text, target):
    return html.Label(text, htmlFor=target, className="visually-hidden")


def _news_filters():
    return html.Div([
        _hidden_label("Search headlines", "news-search"),
        dcc.Input(id="news-search", type="search", placeholder="Search", debounce=True, className="flt flt-search", **PERSIST),
        _hidden_label("Severity", "news-severity"),
        dbc.Select(id="news-severity", value="all", className="flt",
                   options=[{"label": "All severities", "value": "all"}]
                   + [{"label": s.title(), "value": s} for s in ("high", "medium", "low")], **PERSIST),
        _hidden_label("Topic", "news-category"),
        dbc.Select(id="news-category", value="all", className="flt", options=news_filter_options(), **PERSIST),
    ], className="filters")


def _api_modal():
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Public API")),
        dbc.ModalBody([
            html.P("Read the Global Supply Chain Index from your own dashboards or research.", className="sans"),
            html.Div("Endpoint", className="ttl"),
            html.Code("GET https://gscindex.com/api/v1/latest", className="api-code"),
            html.Div("Example", className="ttl"),
            html.Code("curl https://gscindex.com/api/v1/latest", className="api-code"),
            html.Div("Rate limits", className="ttl"),
            html.Ul([html.Li("500 requests per hour per IP"), html.Li("2000 requests per day")]),
            html.P("Data is cached and updated every 5 minutes. Please do not poll faster than that.", className="dim"),
        ]),
        dbc.ModalFooter(html.Button("Close", id="api-modal-close", n_clicks=0, className="link-button")),
    ], id="api-modal", is_open=False, size="lg", centered=True, className="term-modal")


def build_layout(data: dict, *, is_provisional=False, last_updated: datetime | None = None):
    markers = data.get("map_markers", [])
    alerts = data.get("alerts", [])
    return html.Div(className="shell", children=[
        dcc.Interval(id="refresh-interval", interval=20_000 if is_provisional else 300_000, n_intervals=0),
        dcc.Store(id="profile-store", data=DEFAULT_PROFILE),
        dcc.Download(id="snapshot-download"),

        build_header(updated_label(data)),

        html.Div([
            html.Div(build_readout(data, DEFAULT_PROFILE, DEFAULT_TREND_DAYS), id="readout"),
            dcc.RadioItems(
                id="trend-range", value=DEFAULT_TREND_DAYS, inline=True, className="range",
                options=[{"label": f"{n}D", "value": n} for n in TREND_DAYS],
                inputClassName="view-input", labelClassName="view-option", **PERSIST,
            ),
        ], className="pane read-cell"),
        html.Section([
            html.Div([html.Span("Port map"), html.Span(map_caption(markers), id="map-caption")],
                     className="ttl map-ttl"),
            dcc.Graph(id="world-map", figure=build_world_map(markers), config=MAP_CONFIG,
                      responsive=True, className="map-graph"),
        ], className="pane map-pane", **{"aria-label": "Port map"}),
        html.Section([
            _title("Markets", "last"),
            html.Div(build_quotes(data.get("market_data", {})), id="quotes"),
        ], className="pane"),

        html.Section([
            _title("Categories"),
            html.Div(build_category_table(data, DEFAULT_PROFILE), id="category-table"),
        ], className="pane wide"),
        html.Section([
            _title("Briefing"),
            html.Div(build_briefing(data.get("briefing", "")), id="briefing"),
        ], className="pane"),

        html.Section([
            html.Div([
                html.Span("Headlines"),
                _news_filters(),
                html.Span(id="news-results-count", role="status", className="count"),
            ], className="ttl news-head"),
            html.Div(build_headlines(alerts, limit=None), id="news-results", className="news-scroll"),
        ], className="pane full"),

        _api_modal(),
    ])
