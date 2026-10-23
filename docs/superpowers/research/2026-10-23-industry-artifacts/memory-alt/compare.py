import pandas as pd
D="/private/tmp/claude-501/-Users-williamcblair-Desktop-gscindex/021fe002-6d2d-440d-8bfd-6ddde78f0cf9/scratchpad/p3/"
b=pd.read_csv(D+"memory-alt/yoy_all.csv",index_col=0,parse_dates=True)
k=pd.read_csv(D+"semis-sources/data/explore_transformed.csv",index_col=0,parse_dates=True)[["dram_xpi_usd_yoy","flash_xpi_usd_yoy","syssemi_xpi_usd_yoy"]]
k["dram_flash_mean"]=k[["dram_xpi_usd_yoy","flash_xpi_usd_yoy"]].mean(axis=1)
j=b.join(k,how="inner")
for per,(s,e) in {"2001-2019":("2001","2019"),"2020-latest":("2020","2026"),"all":("2001","2026")}.items():
    jj=j.loc[s:e]
    print(per)
    for c in ["BOJ imp memory (contract ccy)","BOJ exp memory (contract ccy)","BOJ imp memory (yen)"]:
        print(f"  {c}: r vs DRAM {jj[c].corr(jj.dram_xpi_usd_yoy):.2f}, vs flash {jj[c].corr(jj.flash_xpi_usd_yoy):.2f}, vs mean {jj[c].corr(jj.dram_flash_mean):.2f}")
        # best lag
        lags={L: jj[c].corr(jj.dram_flash_mean.shift(L)) for L in range(0,7)}
        print("   lag corr (BOK leads by L months):",{L:round(v,2) for L,v in lags.items()})
    for c in ["BOJ imp MOS logic (contract ccy)","BOJ exp MOS ex-memory (contract ccy)","BLS IR21320 import semis"]:
        print(f"  {c}: r vs KR syssemi {jj[c].corr(jj.syssemi_xpi_usd_yoy):.2f}")
print(k.dropna().index[-1], k.dropna().iloc[-1].round(1).to_dict())
for d in ["2021-06","2021-12","2022-06","2023-03","2024-06","2025-12","2026-09"]:
    t=pd.Timestamp(d+"-01"); print(d, k.loc[t].round(1).to_dict() if t in k.index else None)
