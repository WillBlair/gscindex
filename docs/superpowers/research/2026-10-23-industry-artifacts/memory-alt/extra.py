import pandas as pd
y=pd.read_csv("../yoy_all.csv",index_col=0,parse_dates=True)
for c in ["BOJ imp memory (contract ccy)","BOJ exp memory (contract ccy)","BOJ imp MOS logic (contract ccy)"]:
    s=y[c].dropna(); pre=s[:"2024-12"]; print(c,"max through 2024:",pre.idxmax().date(),round(pre.max(),1),"| max pre-2020:",s[:"2019"].idxmax().date(),round(s[:"2019"].max(),1))
    print("  2025:",s["2025"].round(1).tolist()); print("  2026:",s["2026"].round(1).tolist())
