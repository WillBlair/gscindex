# Score inputs research (2026-10-22)

Six research passes over the composite score: long-run scaling, maritime sources, geopolitical and tariff sources, energy and inputs, composite methodology with a backtest, and a live-site audit. All figures come from data fetched on 2026-10-22, or from the sources cited. The scripts and raw data were in the session scratchpad (`scratchpad/{scaling,maritime,geo-tariffs,energy-inputs,methodology,site-audit}/`) and may not survive the session.

## The core problem

Every percentile-based category (energy, tariffs, BDRY, IYT) is ranked inside a rolling 2-year window. That window forgets what normal looks like:

- **Tariffs.** EPUTRADE at 1,213 (Aug 2026) sits at the 95.2nd percentile of all months since 1985, but the window median is 2,401, so it scores 87.5 ("calm"). The window has flipped twice: 220 in Feb 2024 scored 0, and 1,712 in Apr 2026 scored 60. As coverage fades, the score rises (73.5 → 91.3 from Jul to Oct) while the collected tariff rate holds near 7.8%, about 4× the 2005–17 norm.
- **Energy.** It hit 0.0 at the worst of 2008, 2011–14, 2022 and 2026, so it cannot rank them. It scored 98.2 in Apr 2020, which raised the composite during COVID. The live CL=F futures price is scored against FRED spot history, and the two currently differ by $6–7. It is WTI-only, while Brent ran $25 over WTI in October 2026. It ignores gas (TTF rose from $11.06 to $29.73 since Feb).
- **No common "normal".** An average GSCPI (z = 0) scores 50 ("Stressed"). 76.5% of months since 1997 fall in Stressed, and supply chain could never reach 80. Flat freight volume scores 72, and 52% of months score 80+. Percentile categories center on 50. Together these put a built-in downward pull on the composite.

## Findings by category

**supply_chain** (GSCPI + BDRY)
- GSCPI already contains the Baltic Dry Index, so blending in BDRY double counts dry bulk.
- BDRY trades about 30% below the real BDI per point compared with 2021–24 (roll decay or ship-size mix).
- BDRY gives the wrong sign in demand shocks: it scored 98.8 in Apr 2020.
- BDRY history starts only in 2018.

**freight** (TSIFRGHT + IYT)
- IYT is a stock price: its correlation with GSCPI is −0.008. It scored 98 at the Dec 2021 peak and reads 84.9 today, while freight volume is −2.0% YoY.
- TSIFRGHT data is about 83 days old.
- The 72 / 6.5 constants are generous: the median month scores 80.6, and 20.5% of months are pinned at 100.
- Throughput correlates negatively with delivery-time stress (−0.29), so it is a goods-moving or demand gauge rather than a stress gauge.

**geopolitical** (news tone + port blend)
- It drives about 76% of the composite's daily-change variance. It moves 8.5 points a day, with a day-to-day autocorrelation of 0.16.
- After 1 hour, VADER (×6 scale) overwrites Claude's daily scoring (±10 scale) at `geopolitical.py:308-337`, and the web-search articles drop out. The stored daily value is the late-day VADER reading.
- VADER scores "Iran closes Strait of Hormuz to shipping" at 0.00, and "Shipping lines extend Cape diversions" at +4.55.
- The score depends on how many articles it sees: 500 random 30-article subsets of one snapshot range from 74.8 to 91.6.
- Every category's news counts against it, and 5 of the 17 feeds are weather feeds.
- Tagging matches substrings: "port" in "report", "war" in "warehouse", "duty" in "heavy-duty", "oman" in "woman".
- Attention fades while the disruption persists: GDELT Hormuz coverage fell 81% from Mar to Oct 2026 while transits stayed near 4% of normal.

**weather**
- Over two years it has a mean of 89.5 and an sd of 1.67, effectively a constant of about 9 composite points.
- Typhoon Ragasa (Hong Kong, 2025-09-24) moved the average only to 87.3.
- The precipitation ramp expects daily totals, but the feed sends 15-minute amounts, so it never triggers.
- Wind uses sustained speed, not gusts.
- It misses a RED GDACS typhoon (Champi) and the Rhine at Kaub sitting at 26 cm (record low water is 25 cm).

**Other defects found**
- The map counts chokepoint risk three times: geopolitical, the vulnerability penalty and the port AI penalty.
- `ports_data.py:93` maps Casablanca to Port Said.
- A 7-day-old geopolitical score and a 60-day-old GSCPI are served without a fallback flag.
- The API returns no as-of dates.
- `DEFAULT_FALLBACK_SCORES` is never used.
- The docs say "25 newest" articles (the code uses 35) and describe a hover explanation the UI doesn't have.
- The disruptions list mixes 0–10 and 0–100 impact scales.
- Yahoo's terms prohibit automated collection, and yfinance feeds BDRY, IYT, live crude, the Markets pane and aerospace.

## Candidate sources (tested)

| Source | Use | Access | Frequency, lag | History |
|---|---|---|---|---|
| IMF PortWatch chokepoints and ports (ArcGIS) | Chokepoint flow, port calls | Free, no key; credit IMF; resale needs permission | Daily, updated weekly, 2–9 day lag | 2019 (pre-2022 coverage break) |
| Caldara–Iacoviello GPR | Geopolitical risk | Free | Daily (updated Mondays) | Daily since 1985, monthly since 1900 |
| Caldara et al. TPU | Trade policy uncertainty | Free | Daily | Daily since 2015, monthly since 1960 |
| Daily Treasury Statement customs deposits ÷ BOPGIMP | Effective tariff burden | Free API | Effectively monthly, about 3 weeks | 2005; 0.996 correlation with Penn Wharton's effective tariff rate (about 0.7 pt high) |
| policyuncertainty.com daily trade EPU | Daily trade uncertainty | Free | Daily | Only 0.58 log-correlation with EPUTRADE |
| FRED DCOILBRENTEU, DDFUELNYH (DHOILNYH backfill), CPIAUCSL | Energy legs, deflator | Free | Daily, about 1 week | 1987 / 1986 |
| TTF (TTF=F; IMF monthly before 2017) | European gas | Yahoo terms issue | Daily | 2017 daily |
| Regional Fed prices paid (Philly, Empire, Dallas, KC) | Input costs | Free | Monthly | 2004+ |
| STB weekly rail carloads and intermodal (USDA AgTransport) | Freight volume, weekly | Free | Weekly, 5 days | Carload YoY tracks TSIFRGHT at 0.71 (IYT 0.34) |
| USDA reefer truck rates | Truck cost | Free | Weekly, 2 days | |
| MARAD/BTS containerships waiting at US ports | US port congestion | Free | Weekly, 2 days | Peak 155 (Feb 2022); now 5 |
| INE container freight futures (EC) | Asia–Europe container rates | Free (terms to confirm) | Daily | Only since Aug 2023, so the whole history is crisis-era |
| GDACS events API | Natural hazards near ports | Free | Live | About 2 years via queries |
| ACP Gatun Lake, USGS Mississippi, PEGELONLINE Kaub | Waterways | Free | Daily | 1965 / 1990 / 31 days (Kaub needs a longer source) |

Rejected for scoring:
- Too noisy: daily US EPU.
- GDELT: rate limited, tone always negative, no measure of magnitude.
- Licensed or paywalled: ACLED, Global Trade Alert, Drewry, Freightos, Xeneta, Cass, DAT, ISM, S&P PMI, real BDI history.
- Redundant with ULSD: jet fuel.
- Stale on yfinance: JKM, HRC.
- Activity gauges with no defensible sign: industrial production, capacity utilization.

## Candidate designs and backtest results

- **Normalization.** Fixed anchors: 100 = healthiest 5% of pre-2020 history, 75 = pre-2020 median, 0 = worst monthly average on record. Inputs are transformed first: log for EPU-type indices, log of real price for commodities. No rolling windows.
  - A pre-2020 z-score is rejected: GSCPI's calm-era sd is 0.47, so all of 2020–22 scores 0.
  - A fixed percentile is rejected: today ties with COVID at about 0.
  - Under fixed anchors, today: supply chain (GSCPI) 49.3, freight 57.3, energy 27.6 (WTI and diesel), tariffs (EPUTRADE) 30.0.
- **Long-run anchoring vs the current method** (2002–26 backtest): daily noise 0.74 → 0.22–0.26. Correlation with Fed delivery-time surveys 0.48 → 0.54, or 0.69 with fuel scored as a 1-year real change. The current method's 20-day drops land in episode windows no more often than chance (25% vs 29% of days).
- **Data-driven weights fail.** Categories are nearly uncorrelated (|r| ≤ 0.20). PC1 explains 34–40%. Outcome-fit weights are circular: they put 77% on GSCPI and miss the tariff episodes.
- **Aggregation.** Keep the weighted arithmetic mean. The geometric mean is worst on percentile scores and no better on anchored scores. Put weakest-link logic inside the chokepoint category instead.
- **Chokepoints** (maritime design):
  - Eight corridors weighted by PortWatch tonnage (Hormuz 13%, Panama 3%). Bab el-Mandeb and Suez count as one corridor at the worse of the two. Cape of Good Hope is excluded (rerouting).
  - Baseline: the same calendar month in Jan 2022–Oct 2023.
  - Down to 90% of normal still scores 100. Score = 100 − 3 × the weighted shortfall.
  - Backtest: calm 98.9, Ever Given low 79.7, Red Sea 2024 average 81.9, Hormuz Mar 2026 48.5. Today 36.1 (a record low: Hormuz 4%, Bab el-Mandeb 35%, Bosporus 51%).
- **Energy** (energy design):
  - Legs: Brent 35%, NY Harbor ULSD 40%, TTF 25%. Each is the log of its real price, anchored on 1990+ history.
  - Spike penalty: up to 15 points for a 3-month real rise between +20% and +82%.
  - Today about 22, with episodes ranked in order (2022 0.0, 2008 6.8, 2026 8.1). Across settings, today ranges 19–34.
- **Geopolitical** (geo design):
  - 0.5 × chokepoint flow + 0.5 × GPR (daily 30-day mean, log scale, anchored 1985–2019).
  - Today 53.1. Daily move 0.39 vs 8.5.
  - Episodes: Iraq 2003 30.5, Hormuz 2026 39.2, Ukraine 2022 64.8, Red Sea 2024 71.8.
- **Tariffs** (geo design):
  - 0.6 × burden (customs deposits ÷ goods imports; 1.84% → 100, 15% → 0) + 0.4 × TPU (daily 30-day mean, log scale).
  - Today 51.0. Episodes: 2019 67.5, Apr 2025 45.2, Oct 2025 22.4.
- **Inputs category** (energy design):
  - 0.5 × regional Fed prices paid + 0.25 copper + 0.25 aluminum. Today 30.5.
  - Correlates 0.52 with GSCPI and 0.27 with energy. Prices paid leads PPI by about 3 months.
  - Don't score supplier delivery times: 0.72 correlation with GSCPI, so show them as context.
- **Physical disruption** (site-audit design): half GDACS Orange/Red hazards near ports, weighted by throughput, half waterways (Gatun, Kaub, Mississippi) against operational thresholds. 5% weight until backtested.
- **Smoothing.** Not needed once geopolitical uses GPR's 30-day mean and news leaves the score. Never smooth energy or chokepoints (it slows the Hormuz response).

## Methodology references

- NY Fed GSCPI ([Liberty Street 2022](https://libertystreeteconomics.newyorkfed.org/2022/01/a-new-barometer-of-global-supply-chain-pressures/), [SR1017](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1017.pdf))
- OECD/JRC Handbook on Constructing Composite Indicators ([pdf](https://knowledge4policy.ec.europa.eu/sites/default/files/jrc47008_handbook_final.pdf))
- UNDP HDI fixed goalposts ([hdr.undp.org](https://hdr.undp.org/data-center/human-development-index))
- Caldara–Iacoviello GPR ([matteoiacoviello.com/gpr.htm](https://www.matteoiacoviello.com/gpr.htm)) and TPU ([tpu.htm](https://www.matteoiacoviello.com/tpu.htm))
- Baker–Bloom–Davis categorical EPU ([policyuncertainty.com](https://www.policyuncertainty.com/categorical_epu.html))
- IMF PortWatch ([portwatch.imf.org](https://portwatch.imf.org))
- FRED notice on removing ISM data ([2016](https://news.research.stlouisfed.org/2016/06/institute-for-supply-management-data-to-be-removed-from-fred/))
