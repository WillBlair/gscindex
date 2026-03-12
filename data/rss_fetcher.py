
"""
RSS Fetcher Module
==================
Fetches supply chain news from specific high-quality industry RSS feeds.
"""
import feedparser
import logging
from datetime import datetime
import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# List of high-quality industry feeds provided by user
FEED_URLS = [
    # Supply Chain Dive
    "https://www.supplychaindive.com/feeds/news/",
    
    # FreightWaves
    "https://www.freightwaves.com/feed",
    
    # SupplyChainBrain
    "https://www.supplychainbrain.com/rss/articles",
    "https://www.supplychainbrain.com/rss/topic/296-last-mile-delivery",
    
    # Logistics Management
    "https://www.logisticsmgmt.com/rss/topic/transportation_news",
    "https://www.logisticsmgmt.com/rss/topic/ocean_freight",
    
    # Maritime & Shipping (High Volume)
    "https://gcaptain.com/feed/",
    "https://splash247.com/feed/",
    "https://theloadstar.com/feed/",
    
    # Strategic & Global
    "https://www.scmr.com/rss/resources", # Supply Chain Management Review
    "https://logisticsviewpoints.com/feed/",
    "https://www.maritime-executive.com/rss/news",
]

def parse_pub_date(entry) -> str:
    """Robustly extract and normalize publication date."""
    # 1. Try parsed struct_time first (most reliable)
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6]).isoformat()
        
    # 2. Try raw strings
    raw_date = entry.get("published", "") or entry.get("updated", "") or entry.get("pubDate", "")
    
    if not raw_date:
        return datetime.now().isoformat()
        
    return str(raw_date)

def fetch_single_feed(url: str) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    articles = []
    try:
        # feedparser handles basic HTTP caching/etags automatically if we wanted,
        # but for now just basic fetch.
        feed = feedparser.parse(url)
        
        if feed.bozo:
             logger.warning(f"RSS Parse Warning for {url}: {feed.bozo_exception}")
             # often bozo is just encoding error, usually entries still usable
        
        source_name = feed.feed.get("title", "Industry News")
        
        # Take top 15 to ensure we get enough recent ones even if some are irrelevant
        for entry in feed.entries[:15]: 
            # Normalize fields
            title = entry.get("title", "No Title")
            link = entry.get("link", "#")
            
            # Description can be in summary, description, or content
            description = entry.get("summary", "") or entry.get("description", "")
            
            # Published date
            pub_date = parse_pub_date(entry)
            
            articles.append({
                "title": title,
                "description": description[:800], # Truncate massive contents
                "url": link,
                "source": source_name,
                "published": pub_date,
                "is_rss": True # Flag to prioritize in analysis
            })
            
    except Exception as e:
        logger.error(f"Failed to fetch RSS {url}: {e}")
        
    return articles

def fetch_rss_articles(max_items: int = 60) -> list[dict]:
    """
    Fetch from all RSS feeds in parallel and return distinct articles.
    
    Returns
    -------
    list[dict]
        List of normalized article dicts sorted by date (if possible) or just shuffled.
    """
    import random
    all_articles = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_single_feed, url): url for url in FEED_URLS}
        
        for future in as_completed(future_to_url):
            try:
                data = future.result()
                all_articles.extend(data)
            except Exception as e:
                logger.error(f"RSS worker failed: {e}")
    
    # Deduplicate by URL
    seen_urls = set()
    unique_articles = []
    
    # Process standard web articles
    for art in all_articles:
        if art["url"] not in seen_urls:
            unique_articles.append(art)
            seen_urls.add(art["url"])
            
    # Mix them up so we don't get 10 articles from the same source in a row
    random.shuffle(unique_articles)
    
    # Try to sort by date if possible, but date formats vary wildly. 
    # Reliability of 'published' string vary.
    # For now, shuffling is better than sorted-by-source.
    
    logger.info(f"Fetched {len(unique_articles)} unique articles from RSS feeds.")
    return unique_articles[:max_items]

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    items = fetch_rss_articles()
    for item in items[:5]:
        print(f"- [{item['source']}] {item['title']}")
