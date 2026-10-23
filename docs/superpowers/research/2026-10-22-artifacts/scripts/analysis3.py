"""Recommended mapping (anchored scale) vs current method, per input and per category.

Anchored scale on a stationary stress transform s (higher = worse):
  s <= p05_base           -> 100
  s == median_base        -> 75
  s >= worst_monthly_rec  -> 0
  piecewise linear between.
Baseline = full history through 2019-12. Worst = worst MONTHLY AVERAGE on record
through 2025-12 (frozen constant), so a single day cannot set the anchor.
"""
import numpy as np
import pandas as pd

D = "data"
pd.set_option("display.width", 220)
BASE_END = "2019-12-31"
FREEZE = "2025-12-31"


def fred(sid):
    s = pd.read_csv(f"{D}/{sid}.csv"); s.columns = ["date", sid]
    s["date"] = pd.to_datetime(s["date"]); s[sid] = pd.to_numeric(s[sid], errors="coerce")
    return s.set_index("date")[sid].dropna()


def yfc(t):
    h = pd.read_csv(f"{D}/yf_{t}.csv"); h["Date"] = pd.to_datetime(h["Date"].str[:10])
    return h.set_index("Date")["Adj Close"].dropna()


gscpi = pd.read_csv(f"{D}/gscpi_latest.csv", parse_dates=["Date"]).set_index("Date")["GSCPI"]
gscpi.index = gscpi.index.to_period("M").to_timestamp()
tsi = fred("TSIFRGHT"); epu = fred("EPUTRADE"); wti = fred("DCOILWTICO"); diesel = fred("GASDESW")
brent = fred("DCOILBRENTEU"); cpi = fred("CPIAUCSL")
bdry = yfc("BDRY"); iyt = yfc("IYT"); clf = yfc("CL_F")
epu_src = pd.read_csv(f"{D}/epu/eputrade_src.csv", parse_dates=["date"]).set_index("date")["EPUTRADE_src"]


def real(s):
    m = s.index.to_period("M").to_timestamp(); um = pd.DatetimeIndex(m.unique())
    cm = cpi.reindex(cpi.index.union(um)).ffill().reindex(um)
    return s * cpi.iloc[-1] / cm.reindex(m).values


yoy = (tsi.pct_change(12, fill_method=None) * 100).dropna()
wti_r = real(wti).clip(lower=1.0)
diesel_r = real(diesel)
brent_r = real(brent)


class Anchor:
    def __init__(self, name, s_stress):
        base = s_stress[:BASE_END]
        monthly = s_stress[:FREEZE].resample("MS").mean()
        self.name = name
        self.p05 = float(base.quantile(0.05))
        self.med = float(base.median())
        self.worst = float(monthly.max())
        self.worst_month = monthly.idxmax().strftime("%Y-%m")

    def score(self, v):
        if v <= self.med:
            return float(np.clip(75 + 25 * (self.med - v) / (self.med - self.p05), 0, 100))
        return float(np.clip(75 - 75 * (v - self.med) / (self.worst - self.med), 0, 100))


A = {
    "GSCPI": (Anchor("GSCPI", gscpi), gscpi, lambda v: v, lambda v: v),
    "TSIFRGHT YoY": (Anchor("TSI", -yoy), yoy, lambda v: -v, lambda v: v),
    "EPUTRADE": (Anchor("EPU", np.log(epu)), epu, np.log, lambda v: v),
    "WTI real": (Anchor("WTI", np.log(wti_r)), wti_r, np.log, lambda v: v),
    "Brent real": (Anchor("Brent", np.log(brent_r)), brent_r, np.log, lambda v: v),
    "Diesel real": (Anchor("Diesel", np.log(diesel_r)), diesel_r, np.log, lambda v: v),
}
print("=== Anchors (stress transform units; raw equivalents in brackets)")
for k, (a, raw, T, _) in A.items():
    inv = {"GSCPI": lambda x: x, "TSIFRGHT YoY": lambda x: -x}.get(k, np.exp)
    print(f"{k:13s} 100 at {inv(a.p05):9.3f} | 75 at {inv(a.med):9.3f} | 0 at {inv(a.worst):9.3f} (worst monthly avg {a.worst_month})")


def window_at(s, d, days=730):
    """Repo _score_window: trailing 730 days ending at the last observation <= d (inclusive)."""
    h = s[:d]
    end = h.index.max()
    return h[h.index >= end - pd.Timedelta(days=days)]


def roll_pct_at(s, d, invert=True):
    w = window_at(s, d)
    v = s[:d].iloc[-1]
    p = (w <= v).mean()
    return (1 - p) * 100 if invert else p * 100


def anchor_at(k, d):
    a, raw, T, _ = A[k]
    v = raw[:d].iloc[-1]
    return a.score(T(v)), v


# category-level current vs recommended at a date
def categories(d, epu_override=None, crude_live=None):
    d = pd.Timestamp(d)
    out = {}
    # supply chain
    g = gscpi[:d].iloc[-1]
    g_cur = float(np.clip(50 - 12.5 * g, 0, 100))
    b = roll_pct_at(bdry, d) if d >= bdry.index[0] + pd.Timedelta(days=30) else np.nan
    sc_cur = g_cur if np.isnan(b) else 0.7 * g_cur + 0.3 * b
    sc_rec, _ = anchor_at("GSCPI", d)
    out["supply_chain"] = (round(sc_cur, 1), round(sc_rec, 1), f"GSCPI {g:+.2f}")
    # freight
    y = yoy[:d].iloc[-1]
    t_cur = float(np.clip(72 + 6.5 * y, 0, 100))
    i = roll_pct_at(iyt, d, invert=False) if d >= iyt.index[0] + pd.Timedelta(days=30) else np.nan
    fr_cur = t_cur if np.isnan(i) else 0.7 * t_cur + 0.3 * i
    fr_rec, _ = anchor_at("TSIFRGHT YoY", d)
    out["freight"] = (round(fr_cur, 1), round(fr_rec, 1), f"TSI YoY {y:+.1f}%")
    # energy
    cw = roll_pct_at(wti, d) if crude_live is None else (1 - (window_at(wti, d) <= crude_live).mean()) * 100
    dd = roll_pct_at(diesel, d)
    en_cur = (cw + dd) / 2
    w_rec, wv = anchor_at("WTI real", d); d_rec, dv = anchor_at("Diesel real", d)
    out["energy"] = (round(en_cur, 1), round((w_rec + d_rec) / 2, 1), f"WTI ${wti[:d].iloc[-1]:.0f} (real ${wv:.0f}), diesel ${diesel[:d].iloc[-1]:.2f} (real ${dv:.2f})")
    # tariffs
    e = epu[:d].iloc[-1] if epu_override is None else epu_override
    w = window_at(epu, d)
    ta_cur = (1 - (w <= e).mean()) * 100
    ta_rec = A["EPUTRADE"][0].score(np.log(e))
    out["tariffs"] = (round(ta_cur, 1), round(ta_rec, 1), f"EPUTRADE {e:.0f}")
    return out


EP = {
    "2008-07 (oil peak)": "2008-07-15",
    "2008-12 (GFC)": "2008-12-31",
    "2020-04 (COVID)": "2020-04-30",
    "2021-03 (Suez)": "2021-03-31",
    "2021-12 (GSCPI record)": "2021-12-31",
    "2022-06 (diesel peak)": "2022-06-30",
    "2024-02 (Red Sea)": "2024-02-29",
    "2025-04 (tariffs)": "2025-04-30",
    "2026-04 (2026 oil spike)": "2026-04-30",
    "Today (2026-10-22)": "2026-10-22",
}
W = {"supply_chain": 0.25, "freight": 0.10, "energy": 0.20, "tariffs": 0.15}
rows = []
for lab, d in EP.items():
    c = categories(d, crude_live=99.32 if lab.startswith("Today") else None)
    for k, (cur, rec, note) in c.items():
        rows.append(dict(episode=lab, category=k, current=cur, recommended=rec, inputs=note))
    cur4 = sum(W[k] * c[k][0] for k in W) / sum(W.values())
    rec4 = sum(W[k] * c[k][1] for k in W) / sum(W.values())
    rows.append(dict(episode=lab, category="4-category weighted avg", current=round(cur4, 1), recommended=round(rec4, 1), inputs="(weather, geopolitical excluded)"))
t = pd.DataFrame(rows)
t.to_csv("out/category_episodes.csv", index=False)
print(t.to_string(index=False))

print("\n=== Tariffs with Sep 2026 EPUTRADE from policyuncertainty.com (1494.2, not yet on FRED)")
print(categories("2026-10-22", epu_override=float(epu_src.iloc[-1]), crude_live=99.32)["tariffs"])

# full composite today with weather 97 and geopolitical 71 held at production values
c = categories("2026-10-22", crude_live=99.32)
cur = 0.10 * 97 + 0.20 * 71 + sum(W[k] * c[k][0] for k in W)
rec = 0.10 * 97 + 0.20 * 71 + sum(W[k] * c[k][1] for k in W)
print("\nComposite today, weather 97 / geopolitical 71 held fixed: current", round(cur, 1), " recommended", round(rec, 1))

# distribution of recommended scores over 2005-2025 (monthly), to show 'normal' sits near 75
print("\n=== Monthly score distribution 2005-01..2025-12 under recommended vs current")
months = pd.date_range("2005-01-31", "2025-12-31", freq="ME")
recs = {k: [] for k in W}; curs = {k: [] for k in W}
for d in months:
    c = categories(d)
    for k in W:
        curs[k].append(c[k][0]); recs[k].append(c[k][1])
for k in W:
    cs, rs = pd.Series(curs[k]), pd.Series(recs[k])
    print(f"{k:13s} current: median {cs.median():5.1f} p10 {cs.quantile(.1):5.1f} p90 {cs.quantile(.9):5.1f} | recommended: median {rs.median():5.1f} p10 {rs.quantile(.1):5.1f} p90 {rs.quantile(.9):5.1f}")
pd.DataFrame({**{f"cur_{k}": curs[k] for k in W}, **{f"rec_{k}": recs[k] for k in W}}, index=months).to_csv("out/monthly_category_scores_2005_2025.csv")

# ---------------------------------------------------------------- per-input current vs recommended
print("\n=== PER-INPUT: current method vs recommended (anchored), today and episodes")
def cur_input(k, d):
    d = pd.Timestamp(d)
    if k == "GSCPI":
        return float(np.clip(50 - 12.5 * gscpi[:d].iloc[-1], 0, 100))
    if k == "TSIFRGHT YoY":
        return float(np.clip(72 + 6.5 * yoy[:d].iloc[-1], 0, 100))
    if k == "EPUTRADE":
        return roll_pct_at(epu, d)
    if k == "WTI real":  # current method scores NOMINAL spot vs 2y nominal window
        return roll_pct_at(wti, d)
    if k == "Brent real":
        return roll_pct_at(brent, d)
    if k == "Diesel real":
        return roll_pct_at(diesel, d)

rows = []
for k in A:
    for lab, d in EP.items():
        rec, v = anchor_at(k, d)
        rows.append(dict(input=k, when=lab, raw=round(float(v), 2), current=round(cur_input(k, d), 1), recommended=round(rec, 1)))
for lab, d in EP.items():
    if pd.Timestamp(d) < bdry.index[0] + pd.Timedelta(days=30):
        continue
    rows.append(dict(input="BDRY (current only)", when=lab, raw=round(float(bdry[:d].iloc[-1]), 2), current=round(roll_pct_at(bdry, d), 1), recommended=None))
for lab, d in EP.items():
    rows.append(dict(input="IYT (current only)", when=lab, raw=round(float(iyt[:d].iloc[-1]), 2), current=round(roll_pct_at(iyt, d, invert=False), 1), recommended=None))
pi = pd.DataFrame(rows)
pi.to_csv("out/per_input_episodes.csv", index=False)
print(pi.pivot_table(index=["input", "when"], values=["raw", "current", "recommended"], sort=False).to_string())
