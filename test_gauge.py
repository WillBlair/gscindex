from dash import Dash, dcc, html
import plotly.graph_objects as go
from scoring.engine import get_health_tier
from config import COLORS, hex_to_rgba, HEALTH_TIERS

app = Dash(__name__)

composite = 77.5
delta = 2.0
tier = get_health_tier(composite)

gauge_fig = go.Figure(
    go.Indicator(
        mode="gauge+number",
        value=composite,
        number={
            "font": {"size": 48, "color": tier["color"], "family": "JetBrains Mono, monospace"},
            "suffix": "",
        },
        title={
            "text": f"Supply Chain Health Index<br><span style='font-size:14px;color:{tier['color']}'>{tier['label']}</span>",
            "font": {"size": 16, "color": COLORS["text"], "family": "Inter"},
        },
        gauge={
            "axis": {
                "range": [0, 100],
                "tickwidth": 1,
                "tickcolor": COLORS["text_muted"],
                "tickfont": {"size": 11, "color": COLORS["text_muted"]},
            },
            "bar": {"color": tier["color"], "thickness": 0.3},
            "bgcolor": COLORS["card"],
            "borderwidth": 0,
            "steps": [
                {"range": [t["min"], t["max"] + 1], "color": hex_to_rgba(t["color"], 0.1)}
                for t in HEALTH_TIERS
            ],
            "threshold": {
                "line": {"color": "#ffffff", "width": 3},
                "thickness": 0.8,
                "value": composite,
            },
        },
    )
)

gauge_fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font={"family": "Inter"},
    margin={"t": 60, "b": 20, "l": 30, "r": 30},
    height=300,
)

app.layout = html.Div(
    style={
        "backgroundColor": "#0f1117",
        "padding": "50px",
        "fontFamily": "Inter"
    },
    children=[
        html.Div(
            className="chart-panel gauge-panel-container",
            style={
                "position": "relative",
                "display": "flex",
                "flexDirection": "column",
                "alignItems": "center",
                "background": "#1a1d26",
                "padding": "16px",
                "borderRadius": "6px",
                "width": "400px"
            },
            children=[
                dcc.Graph(
                    id="gauge",
                    figure=gauge_fig,
                    config={"displayModeBar": False, "responsive": True},
                ),
                html.Div(
                    className="gauge-custom-delta",
                    style={
                        "position": "absolute",
                        "bottom": "10px",
                        "left": "50%",
                        "transform": "translateX(-50%)",
                        "textAlign": "center",
                        "zIndex": "10"
                    },
                    children=[
                        html.Span(
                            f"▲ {delta:.1f}",
                            className="gauge-delta-val",
                            style={
                                "color": "#00d97e",
                                "fontFamily": "'JetBrains Mono', monospace",
                                "fontSize": "1.15rem",
                                "fontWeight": "500",
                                "letterSpacing": "0.05em"
                            }
                        )
                    ]
                )
            ]
        )
    ]
)

if __name__ == "__main__":
    app.run_server(debug=True, port=8055)
