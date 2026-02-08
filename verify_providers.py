import logging
import sys
from data.providers.commodities import CommoditiesProvider
from data.providers.shipping_financials import ShippingFinancialsProvider

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def test_providers():
    print("Testing CommoditiesProvider...")
    cp = CommoditiesProvider()
    try:
        current = cp.fetch_current()
        print(f"  Current Score: {current}")
        hist = cp.fetch_history(30)
        print(f"  History Points: {len(hist)}")
        if hist.empty:
            print("  WARNING: History is empty!")
    except Exception as e:
        print(f"  ERROR: {e}")

    print("\nTesting ShippingFinancialsProvider...")
    sfp = ShippingFinancialsProvider()
    try:
        current = sfp.fetch_current()
        print(f"  Current Score: {current}")
        hist = sfp.fetch_history(30)
        print(f"  History Points: {len(hist)}")
        if hist.empty:
            print("  WARNING: History is empty!")
    except Exception as e:
        print(f"  ERROR: {e}")

if __name__ == "__main__":
    test_providers()
