"""
Market Costs Component
======================
"""

from __future__ import annotations

from dash import html

from config import COLORS


def _trend_arrow(current: float, previous: float) -> tuple[str, str, str]:
    """Returns arrow symbol, color, and trend class suffix."""
    if current > previous:
        return "▲", COLORS["green"], "up"
    elif current < previous:
        return "▼", COLORS["red"], "down"
    return "−", COLORS["text_muted"], "neutral"

def build_market_costs_panel(market_data: dict) -> html.Div:
    """Build a horizontal scrolling ticker for market data."""
    if not market_data:
        return html.Div(style={"display": "none"})

    # 1. Build the list of distinct items (Header + Data)
    base_items = []

    # Header Item (Part of the flow now)
    header_item = html.Div(
        className="market-ticker-header",
        children=[
            html.Span("MARKET DATA LIVE", className="ticker-label"),
            html.Span("● LIVE", className="ticker-live-dot")
        ]
    )
    base_items.append(header_item)
    
    # Data Items
    for name, data in market_data.items():
        price = data["price"]
        prev = data["prev"]
        change_abs = price - prev if prev else 0.0
        change_pct = (change_abs / prev) * 100 if prev else 0.0
        
        arrow, color, trend = _trend_arrow(price, prev)
        
        # Ticker Item Structure
        item = html.Div(
            className=f"market-ticker-item market-trend-{trend}",
            children=[
                html.Span(name, className="market-symbol"),
                html.Span(f"{price:,.2f}", className="market-value-price"),
                html.Span(
                    children=[
                        html.Span(arrow, className="market-arrow"),
                        html.Span(f"{abs(change_abs):.2f}", className="market-value-abs"),
                        html.Span(f" ({abs(change_pct):.2f}%)", className="market-value-pct"),
                    ],
                    className="market-change-group",
                    style={"color": color}
                )
            ]
        )
        base_items.append(item)

    # 2. Duplicate content for seamless loop (A + A)
    # The animation will slide -50% (width of one set), then loop.
    ticker_content = base_items + base_items

    return html.Section(
        className="market-section-ticker",
        children=[
            html.Div(
                className="market-ticker-track",
                children=ticker_content
            )
        ]
    )
