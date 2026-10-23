"""Score proposed aero categories with the v2 anchor rule (repo's compute_input_anchor + anchored_score)
and replicate the current rolling-percentile categories for the audit. Reads data/fred/*.csv only."""
import sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parent; OUT = HERE.parent
sys.path.insert(0, "/Users/williamcblair/Desktop/gscindex"); sys.path.insert(0, str(HERE))
import numpy as np, pandas as pd
from scripts.compute_anchors import compute_input_anchor, transform_series
from scoring.anchors import anchored_score
from data.providers.fred_client import normalize_series_direct, normalize_series_inverse
from load import s, yoy
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50)
cpi = s("CPIAUCSL")

def mscore(series, anchor, transform, cpi_=None):
    x = transform_series(series, transform, cpi_).resample("MS").mean().dropna()
    return x.apply(lambda v: anchored_score(float(v), anchor))

INPUTS = {}   # key -> (category, raw series, transform, direction, baseline, label)
def add(key, cat, series, transform, direction, baseline, label):
    INPUTS[key] = (cat, series.dropna(), transform, direction, baseline, label)

# 1 Throughput
add("cu_aero", "aero_throughput", s("CAPUTLG3364T9S")["1972":], "identity", "higher_better", ("1972-01-01", "2019-12-31"),
    "Fed G.17 capacity utilization, aerospace & misc transport eq. (NAICS 3364-9), %")
# 2 Flow blockage: inventories / 3-mo avg shipments, nondefense aircraft & parts
add("inv_ship", "aero_flow", (s("ANAPTI") / s("ANAPVS").rolling(3).mean()), "log", "lower_better", ("1992-01-01", "2019-12-31"),
    "Census M3 nondefense aircraft & parts inventories / 3-mo avg shipments (months)")
# 3 Materials: real titanium and nickel-alloy mill shapes PPI
add("ti_mill", "aero_materials", s("WPU102505"), "log_real", "lower_better", ("1971-01-01", "2019-12-31"),
    "BLS PPI titanium & Ti-alloy mill shapes (WPU102505), CPI-real")
add("ni_mill", "aero_materials", s("WPU102504"), "log_real", "lower_better", ("1971-01-01", "2019-12-31"),
    "BLS PPI nickel & Ni-alloy mill shapes (WPU102504), CPI-real")
# 3b Mill-product price pressure (YoY)
add("ti_mill_yoy", "aero_mill_prices", yoy(s("WPU102505")), "identity", "lower_better", ("1972-01-01", "2019-12-31"),
    "BLS PPI titanium & Ti-alloy mill shapes (WPU102505) YoY %")
add("ni_mill_yoy", "aero_mill_prices", yoy(s("WPU102504")), "identity", "lower_better", ("1972-01-01", "2019-12-31"),
    "BLS PPI nickel & Ni-alloy mill shapes (WPU102504) YoY %")
# 4 Forgings & castings price pressure (YoY)
add("ti_forg_yoy", "aero_forge_cast", yoy(s("PCU33211233211242")), "identity", "lower_better", ("1985-01-01", "2019-12-31"),
    "BLS PPI titanium forgings (PCU33211233211242) YoY %")
add("nf_forg_yoy", "aero_forge_cast", yoy(s("PCU332112332112")), "identity", "lower_better", ("1985-01-01", "2019-12-31"),
    "BLS PPI nonferrous forging (PCU332112332112) YoY %")
add("inv_cast_yoy", "aero_forge_cast", yoy(s("PCU3315123315120")), "identity", "lower_better", ("1985-01-01", "2019-12-31"),
    "BLS PPI steel investment castings (PCU3315123315120) YoY %")
add("eng_parts_yoy", "aero_forge_cast", yoy(s("PCU3364123364127")), "identity", "lower_better", ("1987-01-01", "2019-12-31"),
    "BLS PPI aircraft engine parts & accessories (PCU3364123364127) YoY %")
# Alternatives (not in the proposal, for comparison)
add("ip_yoy", "alt", yoy(s("IPG3364S")), "identity", "higher_better", ("1973-01-01", "2019-12-31"), "IPG3364S YoY %")
add("inv_ship_total", "alt", (s("ANAPTI") + s("ADAPTI")) / (s("ANAPVS") + s("ADAPVS")).rolling(3).mean(), "log", "lower_better",
    ("1992-01-01", "2019-12-31"), "nondefense+defense aircraft I/S")
add("backlog_months", "alt", s("ANAPUO") / s("ANAPVS").rolling(3).mean(), "log", "lower_better", ("1992-01-01", "2019-12-31"),
    "nondefense backlog / 3-mo shipments (months)")
add("acft_ppi_yoy", "alt", yoy(s("PCU336411336411")), "identity", "lower_better", ("1987-01-01", "2019-12-31"), "aircraft PPI YoY")
add("ni_imf", "alt", s("PNICKUSDM"), "log_real", "lower_better", ("1992-01-01", "2019-12-31"), "IMF nickel, CPI-real")

anchors, scores, raws = {}, {}, {}
for key, (cat, ser, tf, dirn, base, label) in INPUTS.items():
    a = compute_input_anchor(ser, tf, dirn, base, cpi=cpi if tf == "log_real" else None)
    a["source"] = label; a["category"] = cat
    anchors[key] = a
    scores[key] = mscore(ser, a, tf, cpi if tf == "log_real" else None)
    raws[key] = ser.resample("MS").mean()
S = pd.DataFrame(scores); R = pd.DataFrame(raws)
CATS = {"aero_throughput": ["cu_aero"], "aero_flow": ["inv_ship"], "aero_mill_prices": ["ti_mill_yoy", "ni_mill_yoy"],
        "aero_forge_cast": ["ti_forg_yoy", "nf_forg_yoy", "inv_cast_yoy"],
        "ALT_materials_real_level": ["ti_mill", "ni_mill"], "ALT_forge_cast_plus_engine": ["ti_forg_yoy", "nf_forg_yoy", "inv_cast_yoy", "eng_parts_yoy"]}
C = pd.DataFrame({c: S[k].mean(axis=1, skipna=True) for c, k in CATS.items()})  # equal weights, renormalised over present inputs

# Current categories (rolling 730-day percentile, as in data/providers/aerospace.py; ALI=F nowcast omitted)
cur = pd.DataFrame({
  "cur_orders": normalize_series_direct(s("ANAPNO").rolling(3, min_periods=3).mean().dropna(), 730),
  "cur_production": normalize_series_direct(s("IPG3364S"), 730),
  "cur_ppi": normalize_series_inverse(yoy(s("PCU336411336411")).dropna(), 730),
  "cur_metals": pd.concat([normalize_series_inverse(s("PALUMUSDM"), 730), normalize_series_inverse(s("PNICKUSDM"), 730)], axis=1).mean(axis=1),
})

dates = pd.to_datetime(["2019-06-01", "2020-06-01", "2022-06-01", "2023-09-01", "2024-10-01"])
def latest(col):
    x = col.dropna(); return x.index[-1], x.iloc[-1]
rows = []
for key, a in anchors.items():
    d, v = latest(S[key])
    rows.append([key, a["category"], a["transform"], a["direction"], a["best"], a["normal"], a["worst"], a["worst_basis"][-7:],
                 f"{d:%Y-%m}", round(R[key].dropna().iloc[-1], 2), round(v, 1)] + [round(S[key].get(t, np.nan), 1) for t in dates]
                + [round(R[key].get(t, np.nan), 2) for t in dates])
cols = ["input", "category", "tf", "dir", "best", "normal", "worst", "worst_mo", "latest_mo", "latest_raw", "latest_score"] + \
       [f"s{t:%Y-%m}" for t in dates] + [f"raw{t:%Y-%m}" for t in dates]
T = pd.DataFrame(rows, columns=cols)
print(T.iloc[:, :17].to_string(index=False)); print(); print(T[["input"] + cols[-5:]].to_string(index=False))
print("\nCATEGORY scores (equal-weight mean of input scores)")
cat_tab = pd.DataFrame({c: [round(C[c].dropna().iloc[-1], 1)] + [round(C[c].get(t, np.nan), 1) for t in dates] for c in C},
                       index=["latest"] + [f"{t:%Y-%m}" for t in dates]).T
cat_tab["latest_month"] = [f"{C[c].dropna().index[-1]:%Y-%m}" for c in C]
print(cat_tab.to_string())
print("\nCURRENT categories replicated (730-day rolling percentile)")
cur_tab = pd.DataFrame({c: [round(cur[c].dropna().iloc[-1], 1)] + [round(cur[c].reindex([t]).iloc[0], 1) for t in dates] for c in cur},
                       index=["latest"] + [f"{t:%Y-%m}" for t in dates]).T
print(cur_tab.to_string())
print("\nNoise: mean |month-to-month change| of score, 2015-2026")
noise = pd.concat([C, cur.resample("MS").last()], axis=1)["2015":].diff().abs().mean().round(1)
print(noise.to_string())
print("\nPre-2020 share of months each category < 60 (Stressed or worse):")
print((C[:"2019"] < 60).mean().round(3).to_string())
P = ["aero_throughput", "aero_flow", "aero_mill_prices", "aero_forge_cast"]
comp = C[P].mean(axis=1)
print("\nAero block (equal 0.10 each) at dates:", {f"{d:%Y-%m}": round(comp.get(d, np.nan), 1) for d in dates}, "latest", f"{comp.dropna().index[-1]:%Y-%m}", round(comp.dropna().iloc[-1], 1))
print("\nCategory annual means 2006-2026"); print(C["2006":].resample("YE").mean().round(0).to_string())
(OUT / "proposed_anchors.json").write_text(json.dumps(anchors, indent=1, default=str))
S.join(C).to_csv(OUT / "proposed_scores_monthly.csv"); cur.to_csv(OUT / "current_categories_replicated.csv")
T.to_csv(OUT / "input_table.csv", index=False)
