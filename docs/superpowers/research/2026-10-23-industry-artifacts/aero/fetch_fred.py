"""Download full FRED histories (API, key from repo .env) into data/fred/<ID>.csv with vintage info."""
import sys, json, requests, pandas as pd
from pathlib import Path
from dotenv import dotenv_values
key = dotenv_values("/Users/williamcblair/Desktop/gscindex/.env").get("FRED_API_KEY")
out = Path(__file__).resolve().parent.parent / "data" / "fred"; out.mkdir(parents=True, exist_ok=True)
meta = {}
mp = out / "_meta.json"
if mp.exists(): meta = json.loads(mp.read_text())
for sid in sys.argv[1:]:
    r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": sid, "api_key": key, "file_type": "json"}, timeout=60)
    if r.status_code != 200:
        print(sid, "HTTP", r.status_code, r.text[:200]); continue
    obs = r.json()["observations"]
    s = pd.Series({o["date"]: o["value"] for o in obs})
    s = pd.to_numeric(s, errors="coerce").dropna()
    s.to_csv(out / f"{sid}.csv", header=["value"], index_label="date")
    i = requests.get("https://api.stlouisfed.org/fred/series", params={"series_id": sid, "api_key": key, "file_type": "json"}, timeout=60).json()["seriess"][0]
    meta[sid] = {"title": i["title"], "units": i["units"], "freq": i["frequency_short"], "sa": i["seasonal_adjustment_short"], "last_updated": i["last_updated"], "first": s.index[0], "last": s.index[-1], "n": len(s)}
    print(f"{sid:<20} {s.index[0]}..{s.index[-1]} n={len(s)} last={s.iloc[-1]} upd={i['last_updated'][:10]}")
mp.write_text(json.dumps(meta, indent=1))
