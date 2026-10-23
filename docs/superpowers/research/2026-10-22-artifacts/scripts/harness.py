"""Backtest harness: build candidate composites and score them on episodes.

Run:  ../env2/bin/python harness.py
Writes ../out/*.csv and ../out/metrics.txt
"""
from __future__ import annotations

import json
import os
import numpy as np
import pandas as pd
from scipy.optimize import nnls

import inputs as I

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
os.makedirs(OUT, exist_ok=True)
CATS = ["supply_chain", "freight", "energy", "tariffs"]
# Live weights for the four categories that have real history, renormalised
# (weather .10 and geopolitical .20 are left out: no real history exists).
W_CUR = pd.Series({"supply_chain": .25, "freight": .10, "energy": .20, "tariffs": .15})
W_CUR = W_CUR / W_CUR.sum()
W_EQ = pd.Series(0.25, index=CATS)

EPISODES = [  # name, start (event date), end of evaluation window
    ("GFC 2008", "2008-09-15", "2009-06-30"),
    ("Oil spike 2008", "2008-01-02", "2008-07-31"),
    ("Trade war 2018-19", "2018-03-01", "2019-12-31"),
    ("COVID 2020", "2020-01-23", "2020-06-30"),
    ("Suez block Mar-2021", "2021-03-23", "2021-04-30"),
    ("2021-22 peak", "2021-01-04", "2022-06-30"),
    ("Red Sea 2023-24", "2023-11-20", "2024-06-28"),
    ("Tariffs Apr-2025", "2025-04-02", "2025-06-30"),
    ("Hormuz 2026", "2026-02-27", "2026-10-22"),
]

lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


# ---------------------------------------------------------------- aggregation
def agg(df: pd.DataFrame, w: pd.Series, how: str = "arith", p: float = 1.0) -> pd.Series:
    """Weighted aggregation over available columns, weights renormalised per row."""
    cols = [c for c in w.index if c in df]
    x = df[cols]
    ww = pd.DataFrame(np.broadcast_to(w[cols].values, x.shape), index=x.index, columns=cols).where(x.notna())
    ww = ww.div(ww.sum(axis=1), axis=0)
    if how == "arith":
        return (x * ww).sum(axis=1, min_count=1)
    if how == "geo":  # floor at 1 so a single zero does not zero the index
        return np.exp((np.log(x.clip(lower=1.0)) * ww).sum(axis=1, min_count=1))
    if how == "power":
        return ((x.clip(lower=1.0) ** p) * ww).sum(axis=1, min_count=1) ** (1 / p)
    if how == "weakest":  # 75% weighted mean + 25% worst category
        return 0.75 * (x * ww).sum(axis=1, min_count=1) + 0.25 * x.min(axis=1)
    raise ValueError(how)


def ema(df: pd.DataFrame, halflife: float, cols=None) -> pd.DataFrame:
    out = df.copy()
    for c in (cols or df.columns):
        out[c] = df[c].ewm(halflife=halflife, ignore_na=True).mean().where(df[c].notna())
    return out


# ---------------------------------------------------------------- data
raw = I.load_raw()
cats = {m: I.categories(raw, m) for m in ["a", "b1", "b2"]}

# b3: like b2 but energy measured as the 52-week change in log real price
# (a shock gauge) instead of the real price level.
b3 = cats["b2"].copy()
wti = raw["wti"].clip(lower=1.0)
dsl = raw["diesel"]
wr = I.real_price(wti, raw["cpi"])
dr = I.real_price(pd.Series(dsl.values, index=dsl.index + pd.Timedelta(days=1)), raw["cpi"])
w_ch = np.log(wr).diff(252).dropna()
d_ch = np.log(dr).diff(52).dropna()
b3["energy"] = pd.concat([I.to_bdays(I.z_to_score(I.fixed_z(w_ch))),
                          I.to_bdays(I.z_to_score(I.fixed_z(d_ch)))], axis=1).mean(axis=1)
cats["b3"] = b3
for m, c in cats.items():
    c.to_csv(os.path.join(OUT, f"categories_{m}.csv"))

# chokepoints (PortWatch): per-strait score, 100 at >=90% of normal, 0 at <=30%
ck = I.chokepoints()
ck = ck.shift(4)  # PortWatch posts with a ~4 day lag (latest row 2026-10-18 on 10-22)
ck_s = ((ck - 0.3) / 0.6).clip(0, 1) * 100
straits = [c for c in ck_s.columns if not c.startswith("Cape")]  # Cape gains on reroutes
cap = pd.Series({"Bab el-Mandeb Strait": 3198751, "Gibraltar Strait": 3978835, "Malacca Strait": 7942166,
                 "Panama Canal": 875523, "Strait of Hormuz": 3800344, "Suez Canal": 3151207,
                 "Taiwan Strait": 5405307})  # 2022-23 mean daily capacity, PortWatch
capw = cap / cap.sum()
ck_mean = (ck_s[straits] * capw[straits]).sum(axis=1, min_count=4)
ck_min = ck_s[straits].min(axis=1)
choke = {"mean": ck_mean, "min": ck_min, "half": 0.5 * ck_mean + 0.5 * ck_min}
# Put the chokepoint category on the same scale as the other categories,
# where a normal reading is ~50 (z = 0 / median): every strait at >=90% of
# normal -> 50, worst case -> 0. Above-normal traffic earns nothing (Cape
# reroutes, negative-only like the geopolitical rule).
choke = {k: I.to_bdays(v.dropna()) * 0.5 for k, v in choke.items()}
pd.DataFrame(choke).to_csv(os.path.join(OUT, "chokepoint_category.csv"))
log("Chokepoint category, latest:", {k: round(float(v.dropna().iloc[-1]), 1) for k, v in choke.items()})
log("Per-strait scores latest:", ck_s.dropna().iloc[-1].round(0).to_dict())
calm = slice("2022-01-01", "2023-10-31")
for k, v in choke.items():
    d = v[calm].diff().abs()
    log(f"  choke[{k}] calm 2022-01..2023-10: mean {v[calm].mean():.1f}, min {v[calm].min():.1f}, "
        f"mean |daily chg| {d.mean():.2f}")

# ---------------------------------------------------------------- outcomes (monthly)
def mz(s):
    return (s - s.mean()) / s.std()


dt = pd.concat([mz(raw["philly_dt"]), mz(raw["empire_dt"])], axis=1).mean(axis=1)
dt.index = dt.index + pd.offsets.MonthEnd(0)
outcomes = {
    "delivery_times(-)": -dt,  # regional Fed surveys; higher = slower = stress, so negate
    "truck_PPI_yoy(-)": -(raw["truck_ppi"].pct_change(12) * 100),
    "import_px_yoy(-)": -(raw["ir"].pct_change(12) * 100),
    "PPI_yoy(-)": -(raw["ppi"].pct_change(12) * 100),
}
for k in list(outcomes):
    s = outcomes[k]
    s.index = s.index + pd.offsets.MonthEnd(0)
    outcomes[k] = s[~s.index.duplicated()]
outcomes = pd.DataFrame(outcomes)


def monthly(s: pd.Series) -> pd.Series:
    return s.resample("ME").mean()


# ---------------------------------------------------------------- weights
def pca_weights(df: pd.DataFrame, period) -> tuple[pd.Series, float, pd.Series]:
    m = df[period[0]:period[1]].resample("ME").mean().dropna()
    z = (m - m.mean()) / m.std()
    vals, vecs = np.linalg.eigh(np.corrcoef(z.values.T))
    pc1 = pd.Series(vecs[:, -1], index=df.columns)
    if pc1.sum() < 0:
        pc1 = -pc1
    share = vals[-1] / vals.sum()
    w = pc1.clip(lower=0)
    return w / w.sum(), share, pc1


def outcome_weights(df: pd.DataFrame, y: pd.Series, period) -> pd.Series:
    m = df.resample("ME").mean()
    j = pd.concat([m, y.rename("y")], axis=1)[period[0]:period[1]].dropna()
    X = (j[df.columns] - j[df.columns].mean()) / j[df.columns].std()
    yy = (j["y"] - j["y"].mean()) / j["y"].std()
    coef, _ = nnls(X.values, yy.values)
    # convert standardized coefficients to weights on raw 0-100 scores
    w = pd.Series(coef, index=df.columns) / j[df.columns].std()
    if w.sum() == 0:
        return W_EQ
    return w / w.sum()


log("\n=== Category correlations (monthly means), b2 normalization, 2000-2026 ===")
log(cats["b2"].resample("ME").mean().corr().round(2).to_string())
log("\n=== Category correlations (monthly means), a (current), 2002-2026 ===")
log(cats["a"]["2002":].resample("ME").mean().corr().round(2).to_string())

W_PCA, share, pc1 = pca_weights(cats["b2"], ("2000-01-01", "2019-12-31"))
log(f"\nPCA on b2 monthly 2000-2019: PC1 share {share:.2f}, loadings {pc1.round(2).to_dict()}")
W_PCA_full, share_f, pc1_f = pca_weights(cats["b2"], ("2000-01-01", "2026-10-31"))
log(f"PCA on b2 monthly 2000-2026: PC1 share {share_f:.2f}, loadings {pc1_f.round(2).to_dict()}")
W_PCA_a, share_a, pc1_a = pca_weights(cats["a"], ("2002-01-01", "2019-12-31"))
log(f"PCA on a  monthly 2002-2019: PC1 share {share_a:.2f}, loadings {pc1_a.round(2).to_dict()}")

TRAIN, TEST = ("2002-01-01", "2015-12-31"), ("2016-01-01", "2026-10-31")
W_OUT = outcome_weights(cats["b2"], outcomes["delivery_times(-)"], TRAIN)
log(f"NNLS weights vs delivery times (train {TRAIN[0][:4]}-{TRAIN[1][:4]}, b2): {W_OUT.round(3).to_dict()}")
W_OUT_PPI = outcome_weights(cats["b2"], outcomes["truck_PPI_yoy(-)"], TRAIN)
log(f"NNLS weights vs trucking PPI YoY (train, b2): {W_OUT_PPI.round(3).to_dict()}")
log(f"PCA weights (b2, 2000-2019, negative loadings set to 0): {W_PCA.round(3).to_dict()}")

log("\n=== Single-category correlation with outcomes (monthly, b2, 2002-2026) ===")
mb2 = cats["b2"].resample("ME").mean()
tab = pd.DataFrame({o: {c: mb2[c].corr(outcomes[o]) for c in CATS} for o in outcomes})
log(tab.round(2).to_string())
log("\n=== Single-category correlation with outcomes (monthly, a, 2002-2026) ===")
ma = cats["a"].resample("ME").mean()
tab = pd.DataFrame({o: {c: ma[c].corr(outcomes[o]) for c in CATS} for o in outcomes})
log(tab.round(2).to_string())

# ---------------------------------------------------------------- candidates
cand: dict[str, pd.Series] = {}
cand["A current (2y pct, live wts, mean)"] = agg(cats["a"], W_CUR)
cand["B1 expanding pct"] = agg(cats["b1"], W_CUR)
cand["B2 fixed 2000-19 z"] = agg(cats["b2"], W_CUR)
cand["B3 fixed z, energy=1y change"] = agg(cats["b3"], W_CUR)
cand["C0 B2 equal wts"] = agg(cats["b2"], W_EQ)
cand["C1 B2 PCA wts"] = agg(cats["b2"], W_PCA)
cand["C2 B2 outcome wts"] = agg(cats["b2"], W_OUT)
cand["D1 B2 geometric"] = agg(cats["b2"], W_CUR, "geo")
cand["D2 B2 power p=0.5"] = agg(cats["b2"], W_CUR, "power", 0.5)
cand["D3 B2 weakest-link 25%"] = agg(cats["b2"], W_CUR, "weakest")
cand["D4 A geometric"] = agg(cats["a"], W_CUR, "geo")
cand["E1 A + EMA hl5"] = agg(ema(cats["a"], 5), W_CUR)
cand["E2 B2 + EMA hl5"] = agg(ema(cats["b2"], 5), W_CUR)
cand["E3 B2 + EMA hl10"] = agg(ema(cats["b2"], 10), W_CUR)
# F: add the chokepoint category (exists only from 2022, see report on the
# 2019-21 AIS coverage break). Weight 0.15 of the 4-category total, judgment.
W_F = pd.concat([W_CUR * 0.85, pd.Series({"chokepoints": 0.15})])
for k in ["mean", "half"]:
    dfF = cats["b2"].copy()
    dfF["chokepoints"] = choke[k]["2022-01-01":]
    cand[f"F B2 + chokepoints[{k}] 15%"] = agg(dfF, W_F)
dfF = cats["a"].copy()
dfF["chokepoints"] = choke["half"]["2022-01-01":]
cand["F' A + chokepoints[half] 15%"] = agg(dfF, W_F)
# R: recommended package. Long-run anchored categories (b3), EMA half-life
# 5 business days on the daily-moving categories, chokepoints (from 2022),
# proposed live weights restricted to the categories with real history.
W_REC_LIVE = pd.Series({"supply_chain": .25, "energy": .20, "tariffs": .15, "chokepoints": .15,
                        "geopolitical": .10, "freight": .10, "weather": .05})
W_R = W_REC_LIVE.drop(["geopolitical", "weather"])
W_R = W_R / W_R.sum()
dfR = ema(cats["b3"], 5, ["supply_chain", "freight", "energy"])
dfR["chokepoints"] = choke["half"]["2022-01-01":]
cand["R recommended (b3+EMA5+choke, new wts)"] = agg(dfR, W_R)
dfR1 = ema(cats["b3"], 5, ["supply_chain", "freight"])
dfR1["chokepoints"] = choke["half"]["2022-01-01":]
cand["R1 R but no EMA on energy"] = agg(dfR1, W_R)
cand["R0 R without chokepoints"] = agg(dfR.drop(columns="chokepoints"), W_R.drop("chokepoints"))
dfR.to_csv(os.path.join(OUT, "categories_R.csv"))
# weight sensitivity (OECD/JRC step 7): Dirichlet draws around W_R
rng = np.random.default_rng(0)
draws = rng.dirichlet(W_R.values * 40, 2000)
latest = dfR.dropna().iloc[-1][W_R.index].values
vals = draws @ latest
base_m = agg(dfR, W_R)
log(f"\nR weight sensitivity (2000 Dirichlet draws, concentration 40): latest {base_m.iloc[-1]:.1f}, "
    f"5-95% {np.percentile(vals,5):.1f}-{np.percentile(vals,95):.1f}")
mu_r = base_m["2000":"2019"].mean(); sd_r = base_m["2000":"2019"].std()
log(f"R 2000-2019 mean {mu_r:.1f} sd {sd_r:.1f}; latest re-standardised as 50 + 12.5 z = {50 + 12.5*(base_m.iloc[-1]-mu_r)/sd_r:.1f}")
C = pd.DataFrame(cand)
C.to_csv(os.path.join(OUT, "composites.csv"))

# ---------------------------------------------------------------- metrics
log("\n=== Latest value (2026-10-22) and noise ===")
rows = []
for k, s in C.items():
    s2 = s["2010-01-01":].dropna()
    d = s2.diff().dropna()
    rows.append({"candidate": k, "latest": s.dropna().iloc[-1], "mean_2010+": s2.mean(), "sd_level": s2.std(),
                 "mean|d1|": d.abs().mean(), "p95|d1|": d.abs().quantile(.95), "sd_d1": d.std(),
                 "pct_days<40": (s2 < 40).mean() * 100})
noise = pd.DataFrame(rows).set_index("candidate")
log(noise.round(2).to_string())
noise.to_csv(os.path.join(OUT, "noise.csv"))

log("\n=== Episodes: base = mean of 60 business days before start; drop = base - min in window ===")
log("    z_min = (min - 2010+ mean) / 2010+ level sd; drop/sd_d1 = drop / sd of daily change (2010+); t_1sd = bdays until index is one level-sd below base")
ep_rows = []
for k, s in C.items():
    sd1 = noise.loc[k, "sd_d1"]
    for name, a, b in EPISODES:
        st = pd.Timestamp(a)
        pre = s[:st - pd.Timedelta(days=1)].dropna().tail(60)
        win = s[a:b].dropna()
        if len(pre) < 30 or win.empty:
            continue
        base = pre.mean()
        trough = win.min()
        mu, sdl = noise.loc[k, "mean_2010+"], noise.loc[k, "sd_level"]
        below = win[win <= base - sdl]
        t1 = int(np.searchsorted(win.index, below.index[0])) if len(below) else None
        ep_rows.append({"candidate": k, "episode": name, "base": base, "min": trough, "drop": base - trough,
                        "z_min": (trough - mu) / sdl, "drop/sd_d1": (base - trough) / sd1,
                        "t_1sd_bdays": t1, "min_date": win.idxmin().date()})
EP = pd.DataFrame(ep_rows)
EP.to_csv(os.path.join(OUT, "episodes.csv"), index=False)
for name, _, _ in EPISODES:
    sub = EP[EP.episode == name].set_index("candidate").drop(columns="episode")
    if sub.empty:
        continue
    log(f"\n--- {name} ---")
    log(sub.round(1).to_string())

log("\n=== Concurrent validity: corr(monthly composite, outcome), 2002-2026 and test 2016-2026 ===")
val = {}
for k, s in C.items():
    m = monthly(s)
    val[k] = {f"{o} all": m["2002":].corr(outcomes[o]) for o in outcomes}
    val[k].update({f"{o} test": m[TEST[0]:].corr(outcomes[o]) for o in ["delivery_times(-)", "truck_PPI_yoy(-)"]})
V = pd.DataFrame(val).T
log(V.round(2).to_string())
V.to_csv(os.path.join(OUT, "validity.csv"))

log("\n=== Lead test: corr(composite at t, delivery times at t+3 months), 2002-2026 ===")
for k, s in C.items():
    m = monthly(s)
    log(f"  {k:40s} {m['2002':].corr(outcomes['delivery_times(-)'].shift(-3)):.2f}")

# weights used
json.dump({"W_CUR": W_CUR.round(4).to_dict(), "W_PCA": W_PCA.round(4).to_dict(),
           "W_OUT_delivery": W_OUT.round(4).to_dict(), "W_OUT_truckppi": W_OUT_PPI.round(4).to_dict(),
           "W_F": W_F.round(4).to_dict(), "W_R": W_R.round(4).to_dict(), "W_REC_LIVE": W_REC_LIVE.to_dict()}, open(os.path.join(OUT, "weights.json"), "w"), indent=1)
open(os.path.join(OUT, "metrics.txt"), "w").write("\n".join(lines))
