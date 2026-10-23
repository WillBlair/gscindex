import numpy as np, pandas as pd
from load import fred, yf, real, RAW
pd.set_option("display.width", 220)
def ms(s): return s.resample("MS").mean()
# GSCPI latest vintage
g = pd.read_csv(RAW/"gscpi.csv"); g = g[g.iloc[:,0].notna()]
g.index = pd.to_datetime(g.iloc[:,0], format="%d-%b-%Y").dt.to_period("M").dt.to_timestamp()
gscpi = g.iloc[:,1:].apply(pd.to_numeric, errors="coerce").ffill(axis=1).iloc[:,-1].rename("GSCPI")
print("GSCPI latest:", gscpi.dropna().index[-1].date(), gscpi.dropna().iloc[-1], "| prior 3:", gscpi.dropna().iloc[-4:-1].round(2).tolist())
# Regional Fed
kc = pd.read_excel(RAW/"kc.xlsx", header=None)
kdates = pd.to_datetime(kc.iloc[2,1:]).dt.to_period("M").dt.to_timestamp()
kc_dt = pd.Series(pd.to_numeric(kc.iloc[16,1:]).to_numpy(), index=kdates, name="KC_DT")
kc_pp = pd.Series(pd.to_numeric(kc.iloc[13,1:]).to_numpy(), index=kdates, name="KC_PP")
rf = pd.read_excel(RAW/"richmond.xlsx"); rf.index = pd.to_datetime(rf["date"]).dt.to_period("M").dt.to_timestamp()
ri_dt = rf["sa_mfg_vend_lead_c"].astype(float).rename("RICH_DT")
DT = pd.concat([fred("DTCDFSA066MSFRBPHI").rename("PHIL_DT"), fred("DTCDISA066MSFRBNY").rename("NY_DT"), fred("DTMSAMFRBDAL").rename("DAL_DT"), kc_dt, ri_dt], axis=1)
PP = pd.concat([fred("PPCDFSA066MSFRBPHI").rename("PHIL_PP"), fred("PPCDISA066MSFRBNY").rename("NY_PP"), fred("PRMSAMFRBDAL").rename("DAL_PP"), kc_pp], axis=1)
print("\nLatest regional readings:"); 
for c in list(DT)+list(PP):
    s = (DT[c] if c in DT else PP[c]).dropna(); ref = s["2004":]
    print(f"  {c}: {s.index[-1].date()} = {s.iloc[-1]:.1f}  (pctile since 2004: {(ref<=s.iloc[-1]).mean()*100:.0f}; 2021 max {s['2021':'2022'].max():.1f}; median {ref.median():.1f})")
z = lambda d: (d - d["2004":"2025"].mean())/d["2004":"2025"].std()
dtc = z(DT).mean(axis=1).rename("DT_comp"); ppc = z(PP).mean(axis=1).rename("PP_comp")
# PPI & metals & activity
ppi_core = fred("WPSID69115"); ppi_proc = fred("WPSID61"); ppi_mfg = fred("WPSID611")
yoy = lambda s: (np.log(s) - np.log(s.shift(12)))*100
cu, al = fred("PCOPPUSDM"), fred("PALUMUSDM"); hrc = ms(yf("HRC=F")); cuf = ms(yf("HG=F")); alf = ms(yf("ALI=F"))
metals = fred("PMETAINDEXM"); ip = fred("INDPRO"); ipm = fred("IPMAN"); tcu = fred("MCUMFN")
en = pd.read_csv("out/energy_daily_v2.csv", index_col=0, parse_dates=True)
enm = en[["Q","QS","current","brent_real","distillate_real","gas_real"]].resample("MS").mean()
M = pd.concat([gscpi, dtc, ppc, yoy(ppi_core).rename("PPIcore_yoy"), yoy(ppi_proc).rename("PPIproc_yoy"), yoy(ppi_mfg).rename("PPImfg_yoy"),
               np.log(real(cu)).rename("cu_lreal"), np.log(real(al)).rename("al_lreal"), yoy(cu).rename("cu_yoy"), yoy(al).rename("al_yoy"), yoy(metals).rename("metals_yoy"),
               np.log(real(hrc)).rename("hrc_lreal"), yoy(ip).rename("IP_yoy"), tcu.rename("MCU"),
               enm.Q.rename("energyQ"), np.log(enm.brent_real).rename("brent_lreal")], axis=1)
print("\nCorrelation of monthly levels, 2004-01..2026-09 (n varies):")
cols = ["GSCPI","DT_comp","PP_comp","PPIcore_yoy","PPImfg_yoy","cu_yoy","al_yoy","metals_yoy","IP_yoy","MCU","energyQ","cu_lreal","hrc_lreal"]
print(M.loc["2004":"2026-09", cols].corr().round(2).to_string())
# Does DT composite add info beyond GSCPI? regress DT on GSCPI
d = M[["DT_comp","GSCPI"]]["2004":].dropna()
b = np.polyfit(d.GSCPI, d.DT_comp, 1); resid = d.DT_comp - np.polyval(b, d.GSCPI)
print(f"\nDT_comp ~ GSCPI: R2 {np.corrcoef(d.GSCPI, d.DT_comp)[0,1]**2:.2f}; residual sd {resid.std():.2f} vs DT sd {d.DT_comp.std():.2f}; latest DT_comp {d.DT_comp.iloc[-1]:.2f} vs fitted {np.polyval(b, d.GSCPI.iloc[-1]):.2f}")
# lead/lag: does DT lead GSCPI?
print("corr(DT_comp_t, GSCPI_t+k):", {k: round(M.DT_comp.corr(M.GSCPI.shift(-k)),2) for k in range(-2,4)})
print("corr(PP_comp_t, PPIcore_yoy_t+k):", {k: round(M.PP_comp.corr(M.PPIcore_yoy.shift(-k)),2) for k in range(0,7)})
print("\nLatest: DT_comp", dtc.dropna().index[-1].date(), round(dtc.dropna().iloc[-1],2), "| PP_comp", ppc.dropna().index[-1].date(), round(ppc.dropna().iloc[-1],2))
for c in ["PPIcore_yoy","PPIproc_yoy","PPImfg_yoy","cu_yoy","al_yoy","metals_yoy","IP_yoy","MCU"]:
    s = M[c].dropna(); print(f"  {c}: {s.index[-1].date()} {s.iloc[-1]:.2f}  pctile since 1990: {(s['1990':]<=s.iloc[-1]).mean()*100:.0f}")
# episode table
eps = ["2008-07","2009-04","2011-04","2016-02","2020-04","2021-06","2021-12","2022-06","2023-06","2025-12","2026-03","2026-06","2026-09"]
print("\nEpisode readings:"); print(M.loc[[pd.Timestamp(e) for e in eps], ["GSCPI","DT_comp","PP_comp","PPIcore_yoy","metals_yoy","IP_yoy","MCU","energyQ"]].round(2).to_string())
# Real metal prices: quantiles
for n, s in {"copper (IMF $/mt)": cu, "aluminum (IMF $/mt)": al, "HRC=F ($/st, monthly avg)": hrc}.items():
    r = real(s); ref = r["1992":]
    print(f"{n}: latest {s.index[-1].date()} nominal {s.iloc[-1]:.0f}, real pctile since {ref.index[0].year}: {(ref<=r.iloc[-1]).mean()*100:.0f}, real max {ref.max():.0f} on {ref.idxmax().date()}")
print("Daily: HG=F", yf("HG=F").index[-1].date(), yf("HG=F").iloc[-1].round(3), "$/lb; ALI=F", yf("ALI=F").iloc[-1], "$/mt; HRC=F", yf("HRC=F").iloc[-1], "$/st")
# HRC data quality
h = yf("HRC=F"); print("HRC=F share of unchanged daily closes:", round((h.diff()==0).mean(),3), "| ALI=F:", round((yf('ALI=F').diff()==0).mean(),3), "| HG=F:", round((yf('HG=F').diff()==0).mean(),3))
M.to_csv("out/inputs_monthly.csv", float_format="%.3f")
