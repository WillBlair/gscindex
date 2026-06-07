"""Public news source configuration for supply-chain intelligence."""
from __future__ import annotations

from typing import TypedDict


class NewsSource(TypedDict):
    name: str
    url: str
    group: str
    max_items: int


SOURCE_GROUPS: set[str] = {
    "logistics_trade",
    "ports_shipping",
    "trade_policy",
    "weather_disasters",
}


NEWS_SOURCES: list[NewsSource] = [
    {
        "name": "Supply Chain Dive",
        "url": "https://www.supplychaindive.com/feeds/news/",
        "group": "logistics_trade",
        "max_items": 8,
    },
    {
        "name": "FreightWaves",
        "url": "https://www.freightwaves.com/feed",
        "group": "logistics_trade",
        "max_items": 8,
    },
    {
        "name": "SupplyChainBrain",
        "url": "https://www.supplychainbrain.com/rss/articles",
        "group": "logistics_trade",
        "max_items": 6,
    },
    {
        "name": "SupplyChainBrain Last Mile",
        "url": "https://www.supplychainbrain.com/rss/topic/296-last-mile-delivery",
        "group": "logistics_trade",
        "max_items": 4,
    },
    {
        "name": "Logistics Management Transportation",
        "url": "https://www.logisticsmgmt.com/rss/topic/transportation_news",
        "group": "logistics_trade",
        "max_items": 6,
    },
    {
        "name": "Logistics Management Ocean Freight",
        "url": "https://www.logisticsmgmt.com/rss/topic/ocean_freight",
        "group": "ports_shipping",
        "max_items": 6,
    },
    {
        "name": "gCaptain",
        "url": "https://gcaptain.com/feed/",
        "group": "ports_shipping",
        "max_items": 6,
    },
    {
        "name": "Splash 247",
        "url": "https://splash247.com/feed/",
        "group": "ports_shipping",
        "max_items": 6,
    },
    {
        "name": "The Loadstar",
        "url": "https://theloadstar.com/feed/",
        "group": "ports_shipping",
        "max_items": 6,
    },
    {
        "name": "Maritime Executive",
        "url": "https://www.maritime-executive.com/rss/news",
        "group": "ports_shipping",
        "max_items": 6,
    },
    {
        "name": "Supply Chain Management Review",
        "url": "https://www.scmr.com/rss/resources",
        "group": "logistics_trade",
        "max_items": 4,
    },
    {
        "name": "Logistics Viewpoints",
        "url": "https://logisticsviewpoints.com/feed/",
        "group": "logistics_trade",
        "max_items": 4,
    },
    {
        "name": "WTO News",
        "url": "http://www.wto.org/library/rss/latest_news_e.xml",
        "group": "trade_policy",
        "max_items": 5,
    },
    {
        "name": "GDACS Disaster Alerts",
        "url": "https://www.gdacs.org/xml/rss.xml",
        "group": "weather_disasters",
        "max_items": 8,
    },
    {
        "name": "NHC Atlantic Tropical Cyclones",
        "url": "https://www.nhc.noaa.gov/index-at.xml",
        "group": "weather_disasters",
        "max_items": 5,
    },
    {
        "name": "NHC Eastern Pacific Tropical Cyclones",
        "url": "https://www.nhc.noaa.gov/index-ep.xml",
        "group": "weather_disasters",
        "max_items": 5,
    },
    {
        "name": "NHC Atlantic Tropical Weather Outlook",
        "url": "https://www.nhc.noaa.gov/xml/TWOAT.xml",
        "group": "weather_disasters",
        "max_items": 3,
    },
    {
        "name": "NHC Atlantic High Seas Forecast",
        "url": "https://www.nhc.noaa.gov/xml/HSFAT2.xml",
        "group": "weather_disasters",
        "max_items": 3,
    },
]


def get_sources_by_group(group: str) -> list[NewsSource]:
    """Return configured sources for a source group."""
    return [source for source in NEWS_SOURCES if source["group"] == group]
