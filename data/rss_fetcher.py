
"""
RSS Fetcher Module
==================
Fetches supply chain news from specific high-quality industry RSS feeds.
"""
import feedparser
import time
import logging
import ssl
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Bypass SSL verification for RSS feeds (common issue with some old feed servers or local certs)
if hasattr(ssl, '_create_unverified_context'):
    ssl._create_default_https_context = ssl._create_unverified_context

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
    "http://feeds.feedburner.com/logisticsmgmt/latest", # Note: http often used in older RSS for feedburner, let's try https if fails but list provided was https
    
    # Strategic & Global
    "https://www.scmr.com/rss/resources", # Supply Chain Management Review
    "https://logisticsviewpoints.com/feed/",
    "https://theloadstar.com/feed/",
]

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
        
        for entry in feed.entries[:10]: # Top 10 per feed to keep it recent
            # Normalize fields
            title = entry.get("title", "No Title")
            link = entry.get("link", "#")
            
            # Description can be in summary, description, or content
            description = entry.get("summary", "") or entry.get("description", "")
            # Clean up HTML tags if simple text needed? 
            # For AI input, some HTML is okay, but cleaner is better.
            # We'll leave it raw-ish for now, the AI handles it well.
            
            # Published date
            pub_date = entry.get("published", "")
            if not pub_date:
                pub_date = entry.get("updated", datetime.now().isoformat())
            
            articles.append({
                "title": title,
                "description": description[:500], # Truncate massive contents
                "url": link,
                "source": source_name,
                "published": pub_date,
                "is_rss": True # Flag to prioritize in analysis
            })
            
    except Exception as e:
        logger.error(f"Failed to fetch RSS {url}: {e}")
        
    return articles

def fetch_rss_articles(max_items: int = 50) -> list[dict]:
    """
    Fetch from all RSS feeds in parallel and return distinct articles.
    
    Returns
    -------
    list[dict]
        List of normalized article dicts sorted by date (if possible) or just shuffled.
    """
    all_articles = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
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
    for art in all_articles:
        if art["url"] not in seen_urls:
            unique_articles.append(art)
            seen_urls.add(art["url"])
    
    # Assign IDs
    # We use a simple hash or counter. In `geopolitical.py` they are assigned index IDs.
    # Here we just return the list.
    
    logger.info(f"Fetched {len(unique_articles)} unique articles from RSS feeds.")
    return unique_articles[:max_items]

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    items = fetch_rss_articles()
    for item in items[:5]:
        print(f"- [{item['source']}] {item['title']}")
