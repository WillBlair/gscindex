
from dotenv import load_dotenv
import logging
from data.providers.geopolitical import fetch_supply_chain_news

# Set up logging to see debug output from the provider
logging.basicConfig(level=logging.DEBUG)
load_dotenv()

def verify_news_logic():
    print("🚀 calling fetch_supply_chain_news()...")
    
    try:
        score, alerts = fetch_supply_chain_news()
        
        print(f"\n✅ Fetch complete.")
        print(f"Global Geopolitical Score: {score}")
        print(f"Total Alerts Returned: {len(alerts)}")
        
        print("\n--- Alerts Feed (Top 10) ---")
        for i, alert in enumerate(alerts):
            sev = alert['severity'].upper()
            title = alert['title']
            cat = alert['category']
            sentiment = alert['sentiment']
            source = alert.get('source', 'Unknown')
            url = alert.get('url', '#')
            print(f"[{sev}] {cat.upper()} ({sentiment}) | {source}: {title[:60]}... \n    🔗 {url}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    verify_news_logic()
