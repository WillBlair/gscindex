"""
Docs Component
==============
Contains the content for the "How it Works" documentation modal.
"""
from dash import html, dcc
import dash_bootstrap_components as dbc

def build_docs_modal():
    """Build the detailed documentation modal."""
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("How the Global Supply Chain Index Works"), className="modal-header"),
            dbc.ModalBody(
                children=[
                    # ── Overview ─────────────────────────────────────────────
                    html.H4("Overview", className="text-white mb-3"),
                    html.P(
                        "The Global Supply Chain Index is a real-time health monitor for the global logistics network. "
                        "Unlike traditional reports that rely on weeks-old data, this dashboard aggregates live signals "
                        "from satellite weather data, financial markets, and real-time news analysis to provide an "
                        "instantaneous view of supply chain stability.",
                        className="text-muted mb-4"
                    ),

                    # ── Data Architecture ────────────────────────────────────
                    html.H4("Data Sources & Integration", className="text-white mb-3"),
                    html.Div([
                        html.H6("1. AI-Powered News Analysis (Gemini)", className="text-info"),
                        html.P(
                            "We use Google's Gemini AI to read thousands of industry news headlines every hour. "
                            "Specialized agents filter out irrelevant noise (e.g., consumer product launches) and "
                            "score relevant events based on severity (-10 to +10).",
                            className="text-muted small"
                        ),
                        html.Ul([
                            html.Li("RSS Feeds: Supply Chain Dive, FreightWaves, The Loadstar, Logistics Management."),
                            html.Li("Regional Analysis: News is geo-tagged to specific ports and regions."),
                            html.Li("Sentiment Scoring: VADER analysis + AI context awareness."),
                        ], className="text-muted small mb-3"),

                        html.H6("2. Real-Time Market Data", className="text-warning"),
                        html.P(
                            "We track key financial indicators that serve as proxies for logistics costs:",
                            className="text-muted small"
                        ),
                        html.Ul([
                            html.Li("Energy: Crude Oil (CL=F) and Natural Gas (NG=F) futures via Yahoo Finance."),
                            html.Li("Stability: CBOE Volatility Index (VIX) as a measure of market fear."),
                            html.Li("Shipping: Tracking major logistics ETFs and shipping stock baskets."),
                        ], className="text-muted small mb-3"),
                        
                        html.H6("3. Satellite & Weather Data", className="text-primary"),
                        html.P(
                            "We poll Open-Meteo for real-time weather conditions at 30+ major global ports. "
                            "Extreme wind, wave heights, and precipitation directly impact port efficiency scores.",
                            className="text-muted small"
                        ),
                    ], className="bg-#1a1d26 p-3 rounded mb-4", style={"backgroundColor": "#111", "borderRadius": "8px", "padding": "15px"}),

                    # ── Scoring Logic ────────────────────────────────────────
                    html.H4("Scoring & Weights", className="text-white mb-3"),
                    html.P(
                        "The Index Score (0-100) is a weighted composite of six key categories. "
                        "A score of 100 represents a perfectly optimized, friction-free supply chain.",
                        className="text-muted mb-3"
                    ),
                    
                    html.Table([
                        html.Thead(html.Tr([
                            html.Th("Category", style={"color": "#a5b4fc"}),
                            html.Th("Weight", style={"color": "#a5b4fc"}),
                            html.Th("Data Driver", style={"color": "#a5b4fc"})
                        ])),
                        html.Tbody([
                            html.Tr([html.Td("Supply Chain"), html.Td("20%"), html.Td("NY Fed GSCPI (Global Supply Chain Pressure Index)")]),
                            html.Tr([html.Td("Energy Costs"), html.Td("20%"), html.Td("Crude Oil & Natural Gas Prices")]),
                            html.Tr([html.Td("Geopolitical"), html.Td("20%"), html.Td("AI News Sentiment & Conflict Analysis")]),
                            html.Tr([html.Td("Trade & Tariffs"), html.Td("15%"), html.Td("Trade Policy & Tariff Announcements")]),
                            html.Tr([html.Td("Inland Freight"), html.Td("15%"), html.Td("Trucking PPI & Diesel Prices")]),
                            html.Tr([html.Td("Weather"), html.Td("10%"), html.Td("Real-time Wind/Precipitation at Ports")]),
                        ], style={"color": "#d1d5db", "fontSize": "0.9rem"})
                    ], className="table table-dark table-sm mb-4"),

                    html.Div([
                        html.Strong("Calculation Logic: "),
                        html.Code("Composite = Σ (CategoryScore * Weight) - NewsPenalty"),
                        html.Br(),
                        html.Small("Where NewsPenalty is dynamically applied based on the severity of active disruptions (e.g., Canal blockage = -15 pts).")
                    ], className="alert alert-dark", style={"borderColor": "#4338ca", "backgroundColor": "#1e1b4b", "color": "#e0e7ff"}),

                    # ── AI Integration Detail ────────────────────────────────
                    html.H4("AI Agent Architecture", className="text-white mb-3"),
                    html.P(
                        "The dashboard runs an autonomous AI agent loop:",
                        className="text-muted"
                    ),
                    html.Ol([
                        html.Li("Aggregator collects raw data from all providers."),
                        html.Li("AI Analyst reads news, filters noise, and assigns severity scores."),
                        html.Li("Port Analyst generates specific summaries for major hubs (e.g., 'Singapore: Severe congestion due to monsoon')."),
                        html.Li("Briefing Agent synthesizes a 3-bullet executive summary for the dashboard header."),
                    ], className="text-muted small"),
                    
                ]
            ),
            dbc.ModalFooter(
                dbc.Button("Close", id="docs-modal-close", className="ms-auto", n_clicks=0)
            ),
        ],
        id="docs-modal",
        is_open=False,
        size="lg",
        centered=True,
        scrollable=True,
    )
