"""In-place refresh keeps a reader's filters, scroll and watchlist intact."""
import dash
from dash import ALL, Input, Output, State, ctx, dcc, html
from config import MAP_HEALTH_COLORS

from components.cards import build_category_cards
from components.charts import build_history_chart, build_world_map
from components.feed import build_briefing_panel, build_news_panel
from components.market_costs import build_market_costs_panel
from components.workspace import (
    build_overview, build_drivers, build_freshness, build_port_rows,
    profile_for, select_ports, select_news, snapshot_csv, tier_pill,
)


def register_workspace_callbacks(app, get_snapshot):
    app.clientside_callback(
        "function(n, clicks) { return Date.now(); }",
        Output("refresh-request", "data"),
        Input("refresh-interval", "n_intervals"), Input("refresh-btn", "n_clicks"),
    )

    @app.callback(Output("profile-store", "data"), Input("profile-selector", "value"))
    def profile_changed(key):
        return key or "baseline"

    @app.callback(
        Output("overview-summary", "children"), Output("pressure-drivers", "children"),
        Output("cards-container", "children"), Output("snapshot-status", "children"),
        Output("category-metadata-store", "data"), Output("refresh-interval", "interval"),
        Input("profile-store", "data"), Input("refresh-request", "data"),
    )
    def update_overview(key, _):
        data, fresh = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        profile = profile_for(key)
        return (
            build_overview(data, key, not fresh), build_drivers(data, key),
            build_category_cards(data.get("current_scores", {}), data.get("category_history", {}),
                                 data.get("category_metadata", {}), active_weights=profile["weights"],
                                 card_categories=profile.get("card_categories")),
            build_freshness(data, key, not fresh), data.get("category_metadata", {}),
            300_000 if fresh else 20_000,
        )

    @app.callback(Output("trend-chart", "figure"), Input("profile-store", "data"),
                  Input("refresh-request", "data"), Input("trend-range", "value"))
    def update_trends(key, _, days):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        profile, history = profile_for(key), data.get("category_history", {})
        days = days if days in (7, 30, 90) else 90
        return build_history_chart({c: history[c].tail(days) for c in profile["weights"] if c in history})

    @app.callback(Output("world-map", "figure"), Output("map-count", "children"),
                  Output("map-legend", "children"),
                  Input("refresh-request", "data"), Input("map-mode", "value"))
    def update_map(_, mode):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        markers = data.get("map_markers", [])
        legend = ([html.Span("Higher risk"), html.I(className="risk-gradient"), html.Span("Lower risk")]
                  if mode == "relative" else
                  [html.Span([html.I(className="legend-dot", style={"color": color}), name])
                   for name, color in MAP_HEALTH_COLORS.items()])
        return build_world_map(markers, mode), f"{len(markers)} ports", legend

    @app.callback(Output("port-search", "value"), Output("port-tier", "value"),
                  Output("watch-only", "value"), Input("world-map", "clickData"),
                  prevent_initial_call=True)
    def inspect_map_port(click):
        data, _ = get_snapshot()
        points = (click or {}).get("points") or []
        name = points[0].get("customdata") if points else None
        if not data or name not in {m["name"] for m in data.get("map_markers", [])}:
            raise dash.exceptions.PreventUpdate
        return name, "all", []

    @app.callback(Output("map-selection", "children"), Input("world-map", "clickData"),
                  Input("refresh-request", "data"))
    def map_selection(click, _):
        data, _ = get_snapshot()
        points = (click or {}).get("points") or []
        name = points[0].get("customdata") if points else None
        marker = next((m for m in (data or {}).get("map_markers", []) if m["name"] == name), None)
        if not marker:
            return "Click a port"
        return [html.A(f"{name} · {marker['score']:.1f} ↗", href="#ports"), tier_pill(marker["score"])]

    @app.callback(Output("briefing-panel", "children"), Output("market-panel", "children"),
                  Input("refresh-request", "data"))
    def update_context(_):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        return build_briefing_panel(data.get("briefing", "")), build_market_costs_panel(data.get("market_data", {}))

    @app.callback(Output("port-watchlist", "data"), Input({"type": "watch-port", "index": ALL}, "n_clicks"),
                  State("port-watchlist", "data"), prevent_initial_call=True)
    def toggle_port(clicks, saved):
        if not ctx.triggered_id or not any(clicks):
            raise dash.exceptions.PreventUpdate
        # Ignore replacement/mount events from filtered table rows.
        if not ctx.triggered or not ctx.triggered[0].get("value"):
            raise dash.exceptions.PreventUpdate
        name = ctx.triggered_id["index"]
        saved = list(saved or [])
        return [p for p in saved if p != name] if name in saved else saved + [name]

    @app.callback(Output("port-results", "children"), Output("port-results-count", "children"),
                  Input("port-search", "value"), Input("port-tier", "value"), Input("port-order", "value"),
                  Input("watch-only", "value"), Input("port-watchlist", "data"), Input("refresh-request", "data"))
    def update_ports(query, tier, order, only, saved, _):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        markers = data.get("map_markers", [])
        selected = select_ports(markers, query, tier, saved, "saved" in (only or []), order)
        return build_port_rows(selected, saved), f"{len(selected)}/{len(markers)} ports · ★ {len(saved or [])}"

    @app.callback(Output("news-results", "children"), Output("news-results-count", "children"),
                  Input("news-search", "value"), Input("news-severity", "value"), Input("news-category", "value"),
                  Input("refresh-request", "data"))
    def update_news(query, severity, category, _):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        alerts = data.get("alerts", [])
        selected = select_news(alerts, query, severity, category)
        return build_news_panel(selected), f"{len(selected)}/{len(alerts)} articles · Latest first"

    @app.callback(Output("snapshot-download", "data"), Input("export-btn", "n_clicks"),
                  State("profile-store", "data"), prevent_initial_call=True)
    def export_snapshot(clicks, key):
        data, _ = get_snapshot()
        if not data or not clicks:
            raise dash.exceptions.PreventUpdate
        return dcc.send_string(snapshot_csv(data, key), f"gscindex-{key if key in ('baseline', 'semiconductor', 'aerospace') else 'baseline'}.csv", type="text/csv")
