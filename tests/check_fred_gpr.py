
import os
import sys
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.getcwd())

from data.providers.fred_client import fetch_fred_series
from data.providers.geopolitical import GeopoliticalProvider

load_dotenv()

def test_vix_logic():
    print("Testing VIX Logic for Geopolitical History...")
    
    # 1. Fetch raw VIX
    try:
        vix = fetch_fred_series("VIXCLS", lookback_days=30)
        print(f"[SUCCESS] Fetched {len(vix)} VIX data points.")
        print(f"Latest VIX: {vix.iloc[-1]} on {vix.index[-1].date()}")
        
        # 2. Test Scoring Logic
        # Formula: Score = 120 - 2 * VIX (clipped 0-100)
        latest_vix = vix.iloc[-1]
        score = max(0, min(100, 120 - 2 * latest_vix))
        print(f"Calculated Score from VIX {latest_vix}: {score}")
        
    except Exception as e:
        print(f"[FAILED] Could not fetch VIX: {e}")
        return

    # 3. Test Provider Integration
    print("\nTesting GeopoliticalProvider.fetch_history()...")
    provider = GeopoliticalProvider()
    try:
        # We need to mock fetch_current to avoid hitting NewsAPI limit or needing key
        # But let's just try running it if key exists, otherwise mock it.
        if not os.environ.get("NEWSAPI_KEY"):
            print("No NEWSAPI_KEY, mocking fetch_current return 80.0")
            provider.fetch_current = lambda: 80.0
            
        history = provider.fetch_history(days=30)
        print(f"[SUCCESS] History series length: {len(history)}")
        print(f"Last point (should match current score): {history.iloc[-1]}")
        print("First 5 points:\n", history.head())
        
        # Check if it has variance (should not be flat unless VIX is flat)
        if history.std() > 0:
            print("Series has variance (Good).")
        else:
            print("Series is flat (Might be fallback or flat VIX).")
            
    except Exception as e:
        print(f"[FAILED] Provider fetch_history failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_vix_logic()
