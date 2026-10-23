"""Variant Q: quantile-anchored log mapping; Variant QS: Q + spike penalty. Event tests."""
import numpy as np, pandas as pd
from energy_backtest import build, WEIGHTS, REF_START, OUT
from load import fred, yf, real
pd.set_option("display.width", 220)
out, stats, k = build()
legs = list(WEIGHTS)
anch = {}
def qmap(r, lo, mid, hi):
    y = np.log(r)
    s = np.where(y >= mid, 70 - 70 * (y - mid) / (hi - mid), 70 + 30 * (mid - y) / (mid - lo))
    return pd.Series(np.clip(s, 0, 100), index=r.index)
for n in legs:
    ref = np.log(out[f"{n}_real"][REF_START:].dropna())
    lo, mid, hi = ref.quantile([.05, .50, .995])
    anch[n] = tuple(np.exp([lo, mid, hi]))
    out[f"{n}_q"] = qmap(out[f"{n}_real"], lo, mid, hi)
w = pd.Series(WEIGHTS)
q = out[[f"{n}_q" for n in legs]]
out["Q"] = (q * w.values).sum(axis=1) / (q.notna() * w.values).sum(axis=1)
# spike penalty: 91-calendar-day change in log real price, weighted across legs
chg = pd.DataFrame({n: np.log(out[f"{n}_real"]) - np.log(out[f"{n}_real"].shift(65)) for n in legs})  # 65 bdays ~ 91 cal days
wchg = (chg * w.values).sum(axis=1) / (chg.notna() * w.values).sum(axis=1)
ref = wchg[REF_START:].dropna()
p90, p995 = ref.quantile([.90, .995])
out["spike_pen"] = (15 * (wchg - p90) / (p995 - p90)).clip(0, 15)
out["QS"] = (out.Q - out.spike_pen).clip(0, 100)
print("anchors (real Sep-2026 $): q05 -> 100, median -> 70, q99.5 -> 0")
for n,(a,b,c) in anch.items(): print(f"  {n}: {a:.2f} / {b:.2f} / {c:.2f}")
print(f"spike penalty: weighted 3-month log change p90={p90:.3f} (+{(np.exp(p90)-1)*100:.0f}%) -> 0 pts, p99.5={p995:.3f} (+{(np.exp(p995)-1)*100:.0f}%) -> 15 pts")
cols = ["current", "proposed", "Q", "QS", "spike_pen", "brent_q", "distillate_q", "gas_q"]
periods = ["1990-08","1990-10","1991-03","1998-12","2005-09","2008-07","2008-12","2011-04","2014-06","2016-01","2016-02","2019-09","2020-04","2021-12","2022-03","2022-06","2022-08","2023-06","2025-12","2026-02","2026-03","2026-04","2026-05","2026-06","2026-07","2026-08","2026-09","2026-10"]
print(pd.DataFrame({p: out.loc[p, cols].mean() for p in periods}).T.round(1).to_string())
print("\nWorst day per episode:")
for yr,(a,b) in {"1990 Gulf":("1990-08-01","1991-02-28"),"2008":("2008-01-01","2008-12-31"),"2011-14":("2011-01-01","2014-06-30"),"2014-16 low":("2014-07-01","2016-12-31"),"2020":("2020-01-01","2020-12-31"),"2022":("2022-01-01","2022-12-31"),"2026":("2026-01-01","2026-10-20")}.items():
    sl = out.loc[a:b]
    print(f"  {yr}: " + ", ".join(f"{c} min {sl[c].min():.1f} ({sl[c].idxmin().date()})" for c in ["current","Q","QS"]) + f" | Q max {sl.Q.max():.1f}")
for c in ["current","Q","QS"]:
    s = out[c]["2000":"2026-10-20"]
    print(f"{c}: days<=5 {(s<=5).mean()*100:.1f}%  days>=95 {(s>=95).mean()*100:.1f}%  median {s.median():.1f}  mean abs daily change {s.diff().abs().mean():.2f}")
# event reaction: score 5 bdays before, on, +5, +20 bdays
print("\nEvent reaction (score: t-5bd, t, t+5bd, t+20bd):")
for name, d in {"Iraq invades Kuwait 1990-08-02":"1990-08-02","Abqaiq attack 2019-09-16":"2019-09-16","Russia invades Ukraine 2022-02-24":"2022-02-24"}.items():
    i = out.index.get_indexer([pd.Timestamp(d)], method="bfill")[0]
    print(" ", name, {c: [round(out[c].iloc[j],1) for j in (i-5,i,i+5,i+20)] for c in ["current","Q","QS"]})
# 2026 onset: biggest 5-day Brent rise in Feb-Apr 2026
b = out.brent_nom["2026-02-01":"2026-04-30"]; r5 = np.log(b).diff(5)
d0 = r5.idxmax(); print("  2026 biggest 5-day Brent rise ends", d0.date(), f"+{(np.exp(r5.max())-1)*100:.0f}%")
sl = out.loc["2026-02-20":"2026-03-20", ["brent_nom","distillate_nom","gas_nom","current","Q","QS"]]
print(sl.round(2).to_string())
out.to_csv(OUT / "energy_daily_v2.csv", float_format="%.3f")
# today nowcast with futures (10-22) applied to FRED spot (10-20)
last = out.loc[:"2026-10-20"].iloc[-1]
fut = {"brent": yf("BZ=F"), "distillate": yf("HO=F")}
now = {}
for n, f in fut.items():
    ratio = f.iloc[-1] / f.loc["2026-10-20"]
    now[n] = last[f"{n}_nom"] * ratio
t, fx = yf("TTF=F"), yf("EURUSD=X"); now["gas"] = t.iloc[-1] * fx.iloc[-1] / 3.412
print("\nNowcast 2026-10-22:", {k_: round(v,3) for k_,v in now.items()})
sc = {}
for n in legs:
    a,b_,c = np.log(anch[n]); sc[n] = float(qmap(pd.Series([now[n]]), a, b_, c).iloc[0])  # real == nominal at latest CPI
Qnow = sum(sc[n]*WEIGHTS[n] for n in legs)
chg_now = sum(WEIGHTS[n]*(np.log(now[n]) - np.log(out[f"{n}_real"].iloc[-65])) for n in legs)  # approx
pen = float(np.clip(15*(chg_now-p90)/(p995-p90),0,15))
print("leg scores", {k_: round(v,1) for k_,v in sc.items()}, "Q", round(Qnow,1), "3m chg", round(chg_now,3), "pen", round(pen,1), "QS", round(Qnow-pen,1))
from energy_backtest import current_today
print("current method today (CL=F live", yf("CL=F").iloc[-1].round(2), "):", round(current_today(yf("CL=F").iloc[-1], fred("DCOILWTICO"), fred("GASDESW")),1))
print("current method with Brent instead of WTI (BZ=F live):", round(current_today(yf("BZ=F").iloc[-1], fred("DCOILBRENTEU"), fred("GASDESW")),1))
