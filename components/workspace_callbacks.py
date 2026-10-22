"""Terminal callbacks. They read the cached snapshot only and refresh panes in place,
so the reader's filters, profile and scroll position survive a refresh."""
import dash
from dash import Input, Output, State, dcc

from components.charts import build_world_map
from components.layout import DEFAULT_TREND_DAYS, TREND_DAYS
from components.terminal import (
    build_briefing, build_category_table, build_headlines,
    build_quotes, build_readout, updated_label,
)
from components.workspace import select_news, snapshot_csv
from config import DEFAULT_PROFILE, INDUSTRY_PROFILES


def _profile(key):
    return key if key in INDUSTRY_PROFILES else DEFAULT_PROFILE


def register_workspace_callbacks(app, get_snapshot):
    def snapshot():
        data, fresh = get_snapshot()
        if not data:
            raise dash.exceptions.PreventUpdate
        return data, fresh

    @app.callback(Output("profile-store", "data"), Input("profile-switch", "value"))
    def profile_changed(key):
        return _profile(key)

    @app.callback(
        Output("readout", "children"), Output("category-table", "children"),
        Input("profile-store", "data"), Input("refresh-interval", "n_intervals"), Input("trend-range", "value"),
    )
    def update_profile_panes(key, _, days):
        data, _ = snapshot()
        key = _profile(key)
        days = days if days in TREND_DAYS else DEFAULT_TREND_DAYS
        return build_readout(data, key, days), build_category_table(data, key)

    # serve_layout already renders these panes; skip the duplicate initial run.
    @app.callback(
        Output("world-map", "figure"), Output("quotes", "children"), Output("briefing", "children"),
        Output("updated-label", "children"), Output("refresh-interval", "interval"),
        Input("refresh-interval", "n_intervals"), prevent_initial_call=True,
    )
    def update_context(_):
        data, fresh = snapshot()
        return (
            build_world_map(data.get("map_markers", [])),
            build_quotes(data.get("market_data", {})),
            build_briefing(data.get("briefing", "")),
            updated_label(data),
            300_000 if fresh else 20_000,
        )

    @app.callback(
        Output("news-results", "children"), Output("news-results-count", "children"),
        Input("news-search", "value"), Input("news-severity", "value"), Input("news-category", "value"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_news(query, severity, category, _):
        data, _ = snapshot()
        alerts = data.get("alerts", [])
        selected = select_news(alerts, query, severity or "all", category or "all")
        count = f"{len(alerts)} tracked" if len(selected) == len(alerts) else f"{len(selected)} of {len(alerts)}"
        return build_headlines(selected, limit=None), count

    @app.callback(Output("snapshot-download", "data"), Input("export-btn", "n_clicks"),
                  State("profile-store", "data"), prevent_initial_call=True)
    def export_snapshot(clicks, key):
        data, _ = snapshot()
        if not clicks:
            raise dash.exceptions.PreventUpdate
        key = _profile(key)
        return dcc.send_string(snapshot_csv(data, key), f"gscindex-{key}.csv", type="text/csv")
