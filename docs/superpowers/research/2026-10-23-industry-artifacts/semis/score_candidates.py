"""Apply the v2 anchor rule (repo's compute_input_anchor + anchored_score) to semiconductor candidates.
Run: DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -I scripts/score_candidates.py
Writes data/candidate_anchors.json and data/candidate_scores.csv. Reads only local CSVs fetched by the other scripts."""
import json, sys, pathlib
import pandas as pd, numpy as np
sys.path.insert(0, "/Users/williamcblair/Desktop/gscindex"); sys.path.insert(0, "/Users/williamcblair/Desktop/gscindex/scripts")
from compute_anchors import compute_input_anchor
from scoring.anchors import anchored_score
D = pathlib.Path(__file__).resolve().parent.parent / "data"
def load(n):
    s = pd.read_csv(D / f"{n}.csv", parse_dates=["date"]).set_index("date")["value"].astype(float)
    return s.resample("MS").mean().dropna()
def yoy(s):
    s = s.asfreq("MS")
    return ((s / s.shift(12) - 1) * 100).dropna()
cand = {
  # key: (series, direction, baseline, description)
  "kr_dram_xpi_yoy":  (yoy(load("ecos_dram_xpi_usd")), "lower_better", ("1991-01-01","2019-12-31"), "BOK export price index, DRAM, USD basis, YoY %"),
  "kr_nand_xpi_yoy":  (yoy(load("ecos_flash_xpi_usd")), "lower_better", ("2001-01-01","2019-12-31"), "BOK export price index, flash memory, USD basis, YoY %"),
  "us_semi_import_px_yoy": (yoy(load("fred_IR21320")), "lower_better", ("1985-12-01","2019-12-31"), "BLS import price index (end use) semiconductors IR21320, YoY %"),
  "us_semi_ppi_yoy":  (yoy(load("fred_PCU334413334413")), "lower_better", ("1968-01-01","2019-12-31"), "BLS PPI semiconductor & related devices PCU334413334413, YoY %"),
  "kr_syssemi_xpi_yoy": (yoy(load("ecos_syssemi_xpi_usd")), "lower_better", ("1991-01-01","2019-12-31"), "BOK export price index, system (non-memory) semiconductors, USD, YoY %"),
  "us_semi_util":     (load("fred_CAPUTLG3344S"), "lower_better", ("1972-01-01","2019-12-31"), "Fed G.17 capacity utilization NAICS 3344 (%), level"),
  "kr_semi_util_0519": (load("ecos_kr_semi_util_sa"), "lower_better", ("2005-01-01","2019-12-31"), "Statistics Korea semiconductor capacity-utilization index (SA, 2020=100), level; baseline 2005-19 because of 1980-2004 drift"),
  "kr_ic_export_vol_yoy": (yoy(load("ecos_ic_export_volume")), "higher_better", ("2001-01-01","2019-12-31"), "BOK export volume index, integrated circuits, YoY % (shown to illustrate sign ambiguity)"),
  "us_semi_capacity_yoy": (yoy(load("fred_CAPG3344S")), "higher_better", ("1973-01-01","2019-12-31"), "Fed G.17 capacity NAICS 3344, YoY % (shown to illustrate)"),
}
dates = ["2021-06","2021-12","2022-06","2023-03","2024-06"]
anchors, rows = {}, []
for k, (s, direction, base, desc) in cand.items():
    a = compute_input_anchor(s, "identity", direction, base); a["source"] = desc
    anchors[k] = a
    row = {"input": k, "best": a["best"], "normal": a["normal"], "worst": a["worst"], "worst_basis": a["worst_basis"].split(": ")[-1], "baseline": a["baseline"]}
    for d in dates:
        t = pd.Timestamp(d)
        row[d] = f"{s[t]:.1f} -> {anchored_score(s[t], a):.0f}" if t in s.index else "n/a"
    row["latest"] = f"{s.index[-1]:%Y-%m}: {s.iloc[-1]:.1f} -> {anchored_score(s.iloc[-1], a):.0f}"
    rows.append(row)
    # full score history
    pd.DataFrame({"value": s, "score": [anchored_score(v, a) for v in s]}).to_csv(D / f"scored_{k}.csv")
json.dump(anchors, open(D / "candidate_anchors.json", "w"), indent=1)
T = pd.DataFrame(rows).set_index("input"); T.to_csv(D / "candidate_scores.csv")
pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 40)
print(T[["best","normal","worst","worst_basis"]].to_string()); print(T[dates+["latest"]].to_string())
