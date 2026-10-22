"""Cold-start loading state: the terminal grid with dim placeholder panes.

Shown while the first fetch runs (app.serve_layout returns it when there is
no snapshot yet). Same panes and order as components/layout.py, so the page
does not jump when the real dashboard replaces it. The boot callbacks in
app.py drive ``loading-message`` and ``boot-reload-trigger`` from
``boot-interval``.
"""
from dash import dcc, html


def _ph(width="100%", height=10, class_name="ph"):
    """A dim placeholder bar."""
    return html.Div(className=class_name, style={"width": width, "height": f"{height}px"})


def _title(left, right=""):
    return html.Div([html.Span(left), html.Span(right)], className="ttl")


def _rows(count, widths=("100%",), height=10):
    return [_ph(widths[i % len(widths)], height) for i in range(count)]


def build_skeleton_layout():
    """Returns the loading-state layout (same grid as the live dashboard)."""
    header = html.Header([
        html.Div([html.B("GSCI"), " Global Supply Chain Index"], className="brand"),
        html.Div(_ph("180px", 22), className="sk-views"),
        html.Div(_ph("92px", 22), className="hr"),
    ], className="head", **{"aria-busy": "true"})

    readout = html.Section([
        _title("Index"),
        html.Div("Loading", className="sk-v"),
        html.Div("Initializing system...", id="loading-message", role="status", className="sk-msg dim"),
        _ph("100%", 46, "ph sk-spark"),
        html.Div(_rows(6, ("100%", "88%", "94%")), className="sk-kv"),
    ], className="pane read-cell sk")

    map_pane = html.Section(html.Div(className="ph sk-map"), className="pane map-pane sk",
                            **{"aria-label": "Port map"})

    quotes = html.Section([_title("Markets", "last")] + _rows(5, height=14), className="pane sk sk-list")

    headlines = html.Section([_title("Headlines")] + _rows(8, ("100%", "82%", "91%", "74%"), 12),
                             className="pane wide sk sk-list")

    briefing = html.Section([_title("Briefing")] + _rows(7, ("100%", "96%", "70%"), 12),
                            className="pane sk sk-list")

    categories = html.Section([_title("Categories", "bar = today, tick = yesterday")] + _rows(7, height=12),
                              className="pane full sk sk-list")

    return html.Div([
        header, readout, map_pane, quotes, headlines, briefing, categories,
        html.Div(id="boot-reload-trigger", style={"display": "none"}),
        dcc.Interval(id="boot-interval", interval=1000, n_intervals=0),
    ], className="shell")
