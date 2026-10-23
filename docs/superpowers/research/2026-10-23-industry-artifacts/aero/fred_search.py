import sys, os, json, requests
from dotenv import dotenv_values
key = dotenv_values("/Users/williamcblair/Desktop/gscindex/.env").get("FRED_API_KEY")
for q in sys.argv[1:]:
    r = requests.get("https://api.stlouisfed.org/fred/series/search", params={"search_text": q, "api_key": key, "file_type": "json", "limit": 40}, timeout=30)
    print("=== ", q, r.status_code)
    for s in r.json().get("seriess", []):
        print(f"{s['id']:<22} {s['frequency_short']} {s['observation_start']}..{s['observation_end']} {s['seasonal_adjustment_short']} | {s['title'][:110]} | pop{s['popularity']}")
