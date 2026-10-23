import numpy as np, pandas as pd
from load import fred, yf, real, RAW
pd.set_option("display.width", 220)
M = pd.read_csv("out/inputs_monthly.csv", index_col=0, parse_dates=True)
def qmap_series(x, ref, higher_is_worse=True):
    lo, mid, hi = ref.quantile([.05, .5, .995])
    s = np.where(x >= mid, 70 - 70*(x-mid)/(hi-mid), 70 + 30*(mid-x)/(mid-lo))
    return pd.Series(np.clip(s,0,100), index=x.index), (lo, mid, hi)
cu, al = real(fred("PCOPPUSDM")), real(fred("PALUMUSDM"))
print("copper real pctile exact:", round((cu["1992":] <= cu.iloc[-1]).mean()*100,2), "months above latest:", int((cu["1992":] > cu.iloc[-1]).sum()))
cuq, ca = qmap_series(np.log(cu), np.log(cu["1992":]))
alq, aa = qmap_series(np.log(al), np.log(al["1992":]))
print("copper anchors real $/mt:", [round(float(np.exp(v))) for v in ca], " aluminum:", [round(float(np.exp(v))) for v in aa])
pp = M.PP_comp
ppq, pa = qmap_series(pp, pp["2001-07":])
print("PP composite anchors (z):", [round(float(v),2) for v in pa])
dtq, da = qmap_series(M.DT_comp, M.DT_comp["2001-07":])
S = pd.DataFrame({"PP": ppq, "copper": cuq, "aluminum": alq, "DT(context)": dtq})
S["inputs_A"] = 0.5*S.PP + 0.25*S.copper + 0.25*S.aluminum   # recommended
S["inputs_PPonly"] = S.PP
S["GSCPI"] = M.GSCPI
S["supply_chain_anchor_score"] = (50 - 12.5*M.GSCPI).clip(0,100)
eps = ["2008-07","2009-04","2011-04","2014-06","2016-02","2018-06","2020-04","2021-06","2021-11","2022-06","2023-06","2025-12","2026-03","2026-06","2026-09","2026-10"]
print(S.loc[[pd.Timestamp(e) for e in eps if pd.Timestamp(e) in S.index]].round(1).to_string())
print("corr inputs_A vs supply_chain anchor score 2004+:", round(S.inputs_A["2004":].corr(S.supply_chain_anchor_score["2004":]),2),
      "| PP vs SC anchor:", round(S.PP["2004":].corr(S.supply_chain_anchor_score["2004":]),2),
      "| DT vs SC anchor:", round(S["DT(context)"]["2004":].corr(S.supply_chain_anchor_score["2004":]),2))
en = pd.read_csv("out/energy_daily_v2.csv", index_col=0, parse_dates=True).QS.resample("MS").mean()
print("corr inputs_A vs energy QS (monthly 2004+):", round(S.inputs_A["2004":].corr(en["2004":]),2), "| PP vs energy:", round(S.PP["2004":].corr(en["2004":]),2))
s = S.inputs_A["2004":].dropna(); print("inputs_A: share months <=5:", round((s<=5).mean()*100,1), "median", round(s.median(),1))
S.to_csv("out/inputs_scores.csv", float_format="%.2f")
# daily metals nowcast
hg, ali = yf("HG=F"), yf("ALI=F")
cu_now = hg.iloc[-1]*2204.62; print("HG=F", hg.index[-1].date(), "->", round(cu_now), "$/mt vs IMF Sep", round(fred('PCOPPUSDM').iloc[-1]))
print("ALI=F", ali.index[-1].date(), ali.iloc[-1], "vs IMF Sep", round(fred('PALUMUSDM').iloc[-1]))
