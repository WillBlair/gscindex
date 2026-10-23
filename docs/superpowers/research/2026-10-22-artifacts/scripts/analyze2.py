"""Candidate redesigned scores, evaluated at known episodes and today."""
import numpy as np
import pandas as pd

D = "data/"
pd.set_option("display.width", 220)

# ---------------- inputs
gd = pd.read_stata(D + "data_gpr_daily_recent.dta")
gd["date"] = pd.to_datetime(gd["DAY"].astype(int).astype(str)); gd = gd.set_index("date")
gpr30 = gd["GPRD"].rolling(30, min_periods=20).mean()
gpra30 = gd["GPRD_ACT"].rolling(30, min_periods=20).mean()
tpu_m = pd.read_excel(D + "tpu_web_latest.xlsx", "TPU_MONTHLY").set_index("DATE")["TPU"]
tpud = pd.read_excel(D + "tpu_web_latest.xlsx", "TPU_DAILY").set_index("DATE")["TPUD_index"]
tpu30 = tpud.rolling(30, min_periods=20).mean()
dts = pd.read_csv(D + "dts_customs.csv", parse_dates=["record_date"]).groupby("record_date").transaction_today_amt.sum()
imp = pd.read_csv(D + "fred_BOPGIMP.csv", parse_dates=["observation_date"]).set_index("observation_date").BOPGIMP
pw = pd.read_csv(D + "portwatch_chokepoints.csv", parse_dates=["date"])

def log_anchor_score(x, calm, extreme):
    """100 at `calm`, 0 at `extreme`, linear in log(x); clipped."""
    return np.clip(100 * (np.log(extreme) - np.log(x)) / (np.log(extreme) - np.log(calm)), 0, 100)

# ---------------- GPR score (fixed anchors from full history)
gpr_calm = float(gd["GPRD"]["1985":"2019"].median())        # typical pre-2020 day
gpr_ext = float(gpr30.max())                                 # worst 30-day window on record (Oct 2001)
print(f"GPR anchors: calm (1985-2019 daily median) {gpr_calm:.1f}; extreme (max 30d mean) {gpr_ext:.1f} on {gpr30.idxmax().date()}")
gpr_score = log_anchor_score(gpr30, gpr_calm, gpr_ext)

# ---------------- chokepoint score from PortWatch
pv = pw.pivot_table(index="date", columns="name", values="n_total", aggfunc="sum").sort_index()
cap = pw.pivot_table(index="date", columns="name", values="capacity", aggfunc="sum").sort_index()
pv7 = pv.rolling(7, min_periods=5).mean()
base_mask = pv.index.year.isin([2019, 2022, 2023])
clim = pv[base_mask].groupby(pv[base_mask].index.month).mean()
ratio = pd.DataFrame({c: pv7[c] / pv7.index.month.map(clim[c]).values for c in pv7.columns}, index=pv7.index)
straits = ["Hormuz", "Bab el-Mandeb", "Suez", "Panama", "Malacca", "Taiwan Strait", "Gibraltar"]
# weights: each strait's share of baseline (2019, 2022-23) carried deadweight capacity, from PortWatch itself
capw = cap[base_mask][straits].mean()
capw = capw / capw.sum()
print("Capacity weights (PortWatch baseline-period mean capacity share):", capw.round(3).to_dict())
short = (1 - ratio[straits]).clip(lower=0, upper=1)
wmean = (short * capw).sum(axis=1)
worst = short.max(axis=1)
# blend of breadth (capacity-weighted shortfall) and depth (worst single strait)
chk_score = (100 * (1 - (0.5 * wmean + 0.5 * worst))).clip(0, 100)

# ---------------- tariff burden: DTS customs deposits in month m+1 / goods imports in month m
# (~70% of a month's deposits settle on one day ~3 weeks after month end, so the
# series is monthly in substance; value for entry month m is "known" at end of m+1)
dm = dts.resample("MS").sum()
etr_m = (100 * dm.shift(-1) / imp).dropna()
etr_m = etr_m[etr_m.index < dm.index[-1] - pd.offsets.MonthBegin(1)]   # drop months whose m+1 is incomplete
known = etr_m.copy(); known.index = known.index + pd.offsets.MonthBegin(2) - pd.Timedelta(days=1)
etr_d = known.resample("D").ffill()
etr_d = etr_d.reindex(pd.date_range(etr_d.index[0], "2026-10-21")).ffill()
etr_calm = float(etr_m[:"2017"].median())
print(f"ETR (DTS m+1 / imports m) 2005-2017 median {etr_calm:.2f}%, max {etr_m.max():.2f}% ({etr_m.idxmax().date()}), latest {etr_m.iloc[-1]:.2f}% ({etr_m.index[-1].date()})")
# 0 anchor: 15% chosen as a round level above the 2025 collected peak; flagged as judgment
etr_score = np.clip(100 * (15 - etr_d) / (15 - etr_calm), 0, 100)

tpu_calm = float(tpu_m["1985":"2016"].median())
tpu_ext = float(tpu30.max())
print(f"TPU anchors: calm (1985-2016 monthly median) {tpu_calm:.1f}; extreme (max daily 30d mean) {tpu_ext:.1f} on {tpu30.idxmax().date()}")
tpu_score = log_anchor_score(tpu30, tpu_calm, tpu_ext)
tpu_score_m = log_anchor_score(tpu_m, tpu_calm, tpu_ext)

def at(s, d):
    s = s.dropna(); s = s[:pd.Timestamp(d)]
    return float(s.iloc[-1]) if len(s) else np.nan

dates = {
    "2003-04-01 Iraq invasion": "2003-04-01", "2014-03-31 Crimea": "2014-03-31",
    "2018-07-31 Sec 301 China tariffs": "2018-07-31", "2019-06-30 Gulf of Oman tankers": "2019-06-30",
    "2019-08-31 trade war peak": "2019-08-31", "2021-03-28 Ever Given": "2021-03-28",
    "2022-03-24 Ukraine +1 month": "2022-03-24", "2024-01-31 Red Sea": "2024-01-31",
    "2025-04-30 Liberation Day +4wk": "2025-04-30", "2025-10-31 tariff peak": "2025-10-31",
    "2026-03-31 Hormuz closure": "2026-03-31", "2026-06-30": "2026-06-30", "latest": "2026-10-21",
}
rows = []
for k, d in dates.items():
    g, c = at(gpr_score, d), at(chk_score, d)
    geo_new = 0.5 * g + 0.5 * c if not np.isnan(c) else g
    e, t = at(etr_score, d), at(tpu_score, d)
    if np.isnan(t):
        t = at(tpu_score_m, d)
    tar_new = 0.6 * e + 0.4 * t if not np.isnan(e) else t
    rows.append({"date": k, "GPR30": round(at(gpr30, d)), "GPR score": round(g, 1),
                 "chokepoint score": round(c, 1) if not np.isnan(c) else None,
                 "Hormuz %": round(100 * at(ratio["Hormuz"], d)) if d >= "2019-01-08" else None,
                 "BabelM %": round(100 * at(ratio["Bab el-Mandeb"], d)) if d >= "2019-01-08" else None,
                 "GEO new (.5/.5)": round(geo_new, 1),
                 "ETR %": round(at(etr_d, d), 2), "ETR score": round(e, 1),
                 "TPU30": round(at(tpu30, d)) if d >= "2015-02" else round(at(tpu_m, d)),
                 "TPU score": round(t, 1), "TARIFF new (.6/.4)": round(tar_new, 1)})
out = pd.DataFrame(rows).set_index("date")
print(out.to_string())
out.to_csv("candidate_scores_episodes.csv")

# noise check: day-to-day changes of the new candidates over the last 92 days vs current stored score
last = pd.Timestamp("2026-10-18")
win = slice(last - pd.Timedelta(days=91), last)
geo_new_d = (0.5 * gpr_score + 0.5 * chk_score).dropna()[win]
tar_new_d = (0.6 * etr_score.reindex(pd.date_range(*etr_score.index[[0, -1]]), method="ffill")
             + 0.4 * tpu_score.reindex(pd.date_range(*etr_score.index[[0, -1]]), method="ffill")).dropna()
tar_new_d = tar_new_d[slice(last - pd.Timedelta(days=91), pd.Timestamp("2026-10-19"))]
for lbl, s in [("GEO new", geo_new_d), ("TARIFF new", tar_new_d)]:
    print(f"{lbl}: last-92d mean {s.mean():.1f} sd {s.std():.1f} min {s.min():.1f} max {s.max():.1f} mean|dDay| {s.diff().abs().mean():.2f} lag1 ac {s.autocorr(1):.2f}")
# 2024-2026 monthly path of the new scores
m = pd.DataFrame({"GPR score": gpr_score, "chokepoint": chk_score, "GEO new": 0.5 * gpr_score + 0.5 * chk_score}).resample("MS").mean()
print((m["2023-10":]).round(1).to_string())
mt = pd.DataFrame({"ETR %": etr_d, "ETR score": etr_score, "TPU score": tpu_score}).resample("MS").mean()
mt["TARIFF new"] = 0.6 * mt["ETR score"] + 0.4 * mt["TPU score"]
print(mt["2024-10":].round(1).to_string())
