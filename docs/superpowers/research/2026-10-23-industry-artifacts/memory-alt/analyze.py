import json, sys, os
import pandas as pd, numpy as np
sys.path.insert(0, "/Users/williamcblair/Desktop/gscindex")
from scripts.compute_anchors import compute_input_anchor, WORST_THROUGH
from scoring.anchors import anchored_score
D = "/private/tmp/claude-501/-Users-williamcblair-Desktop-gscindex/021fe002-6d2d-440d-8bfd-6ddde78f0cf9/scratchpad/p3/memory-alt/"
print("WORST_THROUGH", WORST_THROUGH)
series = {}
boj = json.load(open(D + "boj_data.json"))
names = {"PRCG20_2500850005": "BOJ imp memory (contract ccy)", "PRCG20_2600850005": "BOJ imp memory (yen)",
         "PRCG20_2300550006": "BOJ exp memory (contract ccy)", "PRCG20_2500850004": "BOJ imp MOS logic (contract ccy)",
         "PRCG20_2600850004": "BOJ imp MOS logic (yen)", "PRCG20_2300550005": "BOJ exp MOS ex-memory (contract ccy)"}
for r in boj["RESULTSET"]:
    v = r["VALUES"]
    idx = pd.to_datetime([str(x) + "01" for x in v["SURVEY_DATES"]])
    series[names[r["SERIES_CODE"]]] = pd.Series(v["VALUES"], index=idx, dtype=float).dropna()
for s, n in [("IR21320", "BLS IR21320 import semis"), ("IQ21320", "BLS IQ21320 export semis"), ("ID8542", "BLS ID8542 export HS8542")]:
    f = pd.read_csv(D + f"fred_{s}.csv", index_col=0, parse_dates=True).iloc[:, 0]
    series[n] = pd.to_numeric(f, errors="coerce").dropna()
dates = ["2021-06", "2021-12", "2022-06", "2023-03", "2024-06"]
out = {}
for n, s in series.items():
    yoy = (s / s.shift(12, freq="MS").reindex(s.index) - 1) * 100
    yoy = yoy.dropna()
    a = compute_input_anchor(yoy, "identity", "lower_better", ("1900-01-01", "2019-12-31"))
    row = {}
    for d in dates + [yoy.index[-1].strftime("%Y-%m")]:
        x = float(yoy[pd.Timestamp(d + "-01")])
        row[d] = (round(x, 1), round(anchored_score(x, a), 0))
    out[n] = row
    print(f"\n{n}: YoY from {yoy.index[0]:%Y-%m}, baseline {a['baseline']}; best {a['best']:.1f} normal {a['normal']:.1f} worst {a['worst']:.1f} ({a['worst_basis']})")
    print("  " + "  ".join(f"{d}: {v[0]:+.1f} -> {v[1]:.0f}" for d, v in row.items()))
    # correlation with month-to-month noise
    print(f"  YoY std pre-2020 {yoy[:'2019'].std():.1f}; mean abs monthly change of YoY {yoy.diff().abs().mean():.1f}")
pd.DataFrame({n: (s / s.shift(12, freq='MS').reindex(s.index) - 1) * 100 for n, s in series.items()}).to_csv(D + "yoy_all.csv")
