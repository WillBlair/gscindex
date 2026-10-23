"""Standalone re-fetch of every scored source; replicates repo formulas without importing repo code."""
import io, json, sys
from datetime import datetime, timedelta
import pandas as pd, requests
OUT = sys.argv[1]
res = {}
def fred(sid, years=30):
    start = (datetime.now()-timedelta(days=365*years)).strftime("%Y-%m-%d")
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid, "cosd": start}, timeout=30)
    r.raise_for_status()
    f = pd.read_csv(io.StringIO(r.text)); dc = "observation_date" if "observation_date" in f else "DATE"
    s = pd.Series(pd.to_numeric(f[sid], errors="coerce").to_numpy(), index=pd.to_datetime(f[dc])).dropna().sort_index()
    return s
def inv_pct(value, s, days=730):
    w = s[s.index >= s.index.max()-pd.Timedelta(days=days)]
    return round((1-(w <= value).mean())*100, 1)
# GSCPI
r = requests.get("https://www.newyorkfed.org/medialibrary/research/interactives/data/gscpi/gscpi_interactive_data.csv", timeout=30)
df = pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig", na_values=["#N/A"])
df.columns = ["Date"]+list(df.columns[1:])
vals = df[df.columns[1:]].apply(pd.to_numeric, errors="coerce")
latest = vals.ffill(axis=1).iloc[:, -1]
dates = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce")
g = pd.Series(latest.values, index=dates).dropna().sort_index()
res["gscpi"] = {"last_vintage_col": str(df.columns[-1]), "last5": {str(k.date()): round(v,2) for k,v in g.tail(5).items()},
  "n": len(g), "first": str(g.index[0].date()),
  "share_months_score_below_40(z>0.8)": round(float((g>0.8).mean()),3),
  "share_months_score_40_59": round(float(((g>-0.8)&(g<=0.8)).mean()),3),
  "median_z_1998_2019": round(float(g[:'2019'].median()),2), "max": round(float(g.max()),2), "max_date": str(g.idxmax().date()),
  "pct_rank_latest_full_history": round(float((g<=g.iloc[-1]).mean()),3)}
g.to_csv(OUT+"/gscpi.csv")
# FRED
for sid in ["TSIFRGHT","EPUTRADE","GASDESW","DCOILWTICO","WEI","DCOILBRENTEU"]:
    try:
        s = fred(sid); s.to_csv(OUT+f"/{sid}.csv")
        d = {"last_date": str(s.index[-1].date()), "last": float(s.iloc[-1]), "tail": {str(k.date()): float(v) for k,v in s.tail(4).items()}}
        if sid in ("EPUTRADE","GASDESW","DCOILWTICO"):
            d["inv_pct_2y_latest"] = inv_pct(s.iloc[-1], s)
            w = s[s.index >= s.index.max()-pd.Timedelta(days=730)]
            d["window_min"], d["window_max"], d["window_median"] = float(w.min()), float(w.max()), float(w.median())
            d["window_max_date"] = str(w.idxmax().date())
            d["inv_pct_full_history"] = round((1-(s <= s.iloc[-1]).mean())*100,1)
            d["history_start"] = str(s.index[0].date())
        if sid == "TSIFRGHT":
            yoy = (s.iloc[-1]/s.iloc[-13]-1)*100
            d["yoy_pct"] = round(yoy,2); d["score"] = round(max(0,min(100,72+6.5*yoy)),1)
            y = (s.pct_change(12)*100).dropna()
            d["yoy_dist"] = {"mean": round(float(y.mean()),2), "sd": round(float(y.std()),2), "p10": round(float(y.quantile(.1)),2), "p90": round(float(y.quantile(.9)),2), "since": str(y.index[0].date())}
            d["share_yoy_months_scoring_ge_80"] = round(float(((72+6.5*y)>=80).mean()),3)
        res[sid] = d
    except Exception as e:
        res[sid] = {"error": str(e)}
# EPUTRADE monthly 2024-
e = pd.read_csv(OUT+"/EPUTRADE.csv", index_col=0, parse_dates=True).iloc[:,0]
res["EPUTRADE"]["since_2024"] = {str(k.date()): round(float(v),1) for k,v in e["2024":].items()}
# yfinance
import yfinance as yf
for t in ["BDRY","IYT","CL=F","BZ=F"]:
    h = yf.Ticker(t).history(period="2y")["Close"].astype(float)
    h.index = pd.DatetimeIndex(h.index.date)
    pct = float((h <= h.iloc[-1]).mean())
    res[t] = {"last_date": str(h.index[-1].date()), "last": round(float(h.iloc[-1]),2), "pct_rank_2y": round(pct*100,1), "min2y": round(float(h.min()),2), "max2y": round(float(h.max()),2)}
    h.to_csv(OUT+f"/{t.replace('=','_')}.csv")
# energy reproduce
cl = res["CL=F"]["last"]; wti = pd.read_csv(OUT+"/DCOILWTICO.csv", index_col=0, parse_dates=True).iloc[:,0]
ds = pd.read_csv(OUT+"/GASDESW.csv", index_col=0, parse_dates=True).iloc[:,0]
res["energy_repro"] = {"crude_leg": inv_pct(cl, wti), "diesel_leg": inv_pct(ds.iloc[-1], ds)}
res["energy_repro"]["score"] = round((res["energy_repro"]["crude_leg"]+res["energy_repro"]["diesel_leg"])/2,1)
json.dump(res, open(OUT+"/sources.json","w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
