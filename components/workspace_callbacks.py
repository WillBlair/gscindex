"""In-place refresh keeps the reader's filters and scroll position intact."""
import dash
from dash import Input, Output, State, dcc

from components.cards import build_category_cards
from components.charts import build_history_chart, build_world_map
from components.feed import build_briefing_panel, build_news_panel
from components.market_costs import build_market_costs_panel
from components.workspace import (
    build_overview, build_drivers, build_freshness,
    profile_for, select_news, snapshot_csv,
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
                  Input("refresh-request", "data"))
    def update_map(_):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        markers = data.get("map_markers", [])
        return build_world_map(markers), f"{len(markers)} ports"

    @app.callback(Output("briefing-panel", "children"), Output("market-panel", "children"),
                  Input("refresh-request", "data"))
    def update_context(_):
        data, _ = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        return build_briefing_panel(data.get("briefing", "")), build_market_costs_panel(data.get("market_data", {}))

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
