"""Download FRED series (API, key from gscindex .env) into data/fred_<ID>.csv."""
import os, sys, json, urllib.request, pathlib
from dotenv import dotenv_values
key = dotenv_values("/Users/williamcblair/Desktop/gscindex/.env").get("FRED_API_KEY")
out = pathlib.Path(__file__).resolve().parent.parent / "data"
for sid in sys.argv[1:]:
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={key}&file_type=json"
    d = json.load(urllib.request.urlopen(url, timeout=60))
    rows = [(o["date"], o["value"]) for o in d["observations"] if o["value"] != "."]
    (out / f"fred_{sid}.csv").write_text("date,value\n" + "\n".join(f"{a},{b}" for a, b in rows))
    meta = json.load(urllib.request.urlopen(f"https://api.stlouisfed.org/fred/series?series_id={sid}&api_key={key}&file_type=json", timeout=60))["seriess"][0]
    print(sid, len(rows), rows[0][0], rows[-1], "| updated", meta["last_updated"][:10], "|", meta["title"][:70])
