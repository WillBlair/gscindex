import sys; sys.path.insert(0, sys.argv[1])
from load import s, yoy
import pandas as pd, numpy as np
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
ids = {"acft":"PCU336411336411","eng":"PCU336412336412","parts":"PCU336413336413","aero":"PCU3364133641",
       "Ti_mill":"WPU102505","Ni_mill":"WPU102504","Ti_forg":"PCU33211233211242","NF_forg":"PCU332112332112",
       "inv_cast":"PCU3315123315120","forge_shop":"WPU1015","ppiaco":"PPIACO","NiLME":"PNICKUSDM","AlLME":"PALUMUSDM"}
Y = pd.DataFrame({k: yoy(s(v)) for k, v in ids.items()})
cpi = s("CPIAUCSL"); ref = cpi["2025-12-01"]
R = pd.DataFrame({k: np.log(s(v) * (ref / cpi.reindex(s(v).index))) for k, v in ids.items()})
dates = pd.to_datetime(["2008-06-01","2011-06-01","2016-06-01","2019-06-01","2020-06-01","2022-06-01","2023-09-01","2024-10-01","2025-06-01","2026-06-01","2026-08-01","2026-09-01"])
print("YoY %"); print(Y.reindex(dates).round(1).to_string())
print("pre-2020 YoY quantiles (5,50,95) and max-thru-2025 (date)")
for k in Y:
    y = Y[k].dropna(); b = y[:"2019"]
    print(f"{k:10} start {y.index[0]:%Y-%m} q05 {b.quantile(.05):6.1f} med {b.median():6.1f} q95 {b.quantile(.95):6.1f} max {y[:'2025'].max():6.1f} ({y[:'2025'].idxmax():%Y-%m})  sd_mom {(s(ids[k]).pct_change()*100).std():.2f}")
print("real log level: score-ish relative position")
for k in R:
    r = R[k].dropna(); b = r[:"2019"]
    print(f"{k:10} start {r.index[0]:%Y-%m} q05 {np.exp(b.quantile(.05)):8.1f} med {np.exp(b.median()):8.1f} max {np.exp(r[:'2025'].max()):8.1f} ({r[:'2025'].idxmax():%Y-%m}) latest {np.exp(r.iloc[-1]):8.1f} ({r.index[-1]:%Y-%m})")
