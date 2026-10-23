# Industry profiles research, project 3 (2026-10-23)

This document records four research passes: a Semis audit, Semis sources, an Aero audit with sources, and profile design. All figures come from data fetched on 2026-10-23 or from the sources cited.

Scripts and raw data were saved in the session scratchpad at `scratchpad/p3/{semis-audit,semis-sources,aero,profiles}/`. They may not outlive the session.

## Current Semis inputs (Silicon Analysts): replace all four

**The data is estimates, not measurements.** The vendor builds it from press reports and rates its own confidence as Low or Medium. Its terms say "for educational and estimation purposes only". The newest sources are dated:

| Series | Last source date |
|---|---|
| Fab utilization | 2026-07-01 |
| Lead times | 2026-03-01 |
| Wafer prices | 2026-03-01 |
| HBM | 2026-10-01 |

**History is too short to anchor.** Anonymous access returns only a slice (for fab utilization, 11 of 23 points). The series begin in 2022, so there is no pre-2020 period to anchor against.

**The license is a risk.** "Derived databases, dashboards" fall under a commercial license that the vendor does not sell yet, and the site publishes a dashboard derived from this data.

**Why the scores sit flat:**
- Fab utilization reads exactly 100 because its newest point is the 2024 annual 100%, scored as (100−50)×2.
- Lead times read 49 because the code averages every point from Q2 2024 to Q1 2026; every point carries `is_recent=True`, so nothing is filtered out.
- The "wafer prices" series is each node's launch price, not a price over time. The 3nm filter reads the wrong field, so the code always scores 5nm at the 2020 price.

**Some scoring runs the wrong way.**
- Fab utilization scores 100% utilization as healthy. For buyers, full fabs mean tight supply.
- The HBM score is a bell curve centered on an unstated $15/GB, and it ignores HBM4.

**Fallbacks count as real data.** A failed source returns a neutral 50 flagged `is_fallback`. That 50 is still weighted into the Semis index, and nothing is ever flagged stale.

**Effect on the index.** The four Semis categories supply 35.7 of their 40 possible points. That makes the Semis view read 63.8 (Stable) while Global reads 46.9 (Stressed).

## Proposed Semis categories (3)

Each category is the equal mean of its inputs. Every input is scored with the v2 anchor rule through the repo's own `compute_input_anchor` and `anchored_score`.

| Category | Inputs | Direction |
|---|---|---|
| Memory prices | Bank of Korea export price index (USD) for DRAM (from 1990) and flash (from 2000), YoY % | lower is better |
| Logic prices | Bank of Korea system semiconductor export price (from 1990) and BLS import price index for semiconductors, IR21320 (from 1984), YoY % | lower is better |
| Fab utilization | Fed G.17 capacity utilization CAPUTLG3344S (from 1972) and the Statistics Korea semiconductor utilization index (2005–19 baseline) | lower is better (more slack) |

Anchors (best / normal / worst):

| Input | Best | Normal | Worst |
|---|---|---|---|
| DRAM | −73 | −15 | +151 |
| NAND | −66 | −23 | +160 |
| Korea system semis | −15.6 | −3.1 | +10.3 (2021-12) |
| US import price | −12.6 | −3.0 | +16.2 |
| US utilization | 64.8 | 80.1 | 93.2 |
| Korea utilization | 74.2 | 88.5 | 124.6 |

Category scores at past dates and today:

| Category | 2021-06 | 2021-12 | 2022-06 | 2023-03 | 2024-06 | Latest |
|---|---|---|---|---|---|---|
| Memory | 70 | 65 | 76 | 91 | 33 | 0 |
| Logic | 41 | 25 | 59 | 75 | 71 | 22 |
| Fab utilization | 34 | 18 | 23 | 68 | 63 | 82 |
| Block | 49 | 37 | 52 | 78 | 54 | 36 |

- **Memory reads 0 today.** In Sep 2026 the DRAM export price was up 248% YoY, past the 2010-01 record of +151%. This is the HBM-driven memory squeeze.
- **Logic is between 22 and 44 today.** IR21320 includes memory, so it partly double counts the memory squeeze. On Korea system semis alone, logic reads 44.
- **Known limit:** a glut or a demand collapse reads as healthy. For example, 2023 scores 89–93. This is the same documented limitation as the global Energy category.

**Rejected sources:**
- **Ambiguous sign:** TSMC revenue, WSTS sales, Korea export volume and Taiwan export orders. They also rise during shortages; for example, Korea IC volume reads 81 (healthy) in 2021-06.
- **Terms forbid reuse:** WSTS ("reproduction ... prohibited"), DRAMeXchange (no derivative works) and SEAJ.
- **Peaks too late:** US semis PPI. It scores 39 in 2023-03, during the glut.
- **Never moves:** the Census M3 backlog ratio, which stays at 4.9–5.1.
- **No free periodic source:** lead times and fab-input prices (neon, helium, gallium, germanium).

**Access:**
- **FRED and BLS:** public domain, already keyed.
- **Bank of Korea ECOS:** the public sample key is limited to 10 rows per call, so production needs a free ECOS key. The terms page was not found, so the terms are unconfirmed.

## Current Aero inputs: replace all four

- **aero_orders:** this is demand, not supply health. ANAPNO goes negative on cancellations (−$6.1B in 2020-06).
- **aero_production:** the 2-year percentile misranks it. 2023-09 scores 100 even though output was below 2018.
- **aero_ppi:** aircraft prices follow contract escalation clauses, so the index is not a health signal.
- **aero_metals:** the IMF aluminum series duplicates the global Input Costs category, and the IMF nickel series is copyrighted.

## Proposed Aero categories (4)

All inputs are public domain: Fed G.17, Census M3 and BLS PPI.

| Category | Input and transform | Direction | Anchors (best / normal / worst) |
|---|---|---|---|
| aero_throughput | Capacity utilization, NAICS 3364-9 (aerospace is 79% of this industry's weight) | higher is better | 85.8 / 73.8 / 46.8 |
| aero_flow | log(nondefense aircraft inventories ÷ 3-month average shipments) | lower is better | 3.5 / 4.7 / 15.9 months |
| aero_mill_prices | YoY change in titanium and nickel-alloy mill-shape PPIs | lower is better | — |
| aero_forge_cast | YoY change in titanium forgings, nonferrous forgings and steel investment castings PPIs | lower is better | — |

Category scores at past dates and today:

| Category | Latest | 2019-06 | 2020-06 | 2022-06 | 2023-09 | 2024-10 |
|---|---|---|---|---|---|---|
| Throughput | 80.0 | 70.8 | 21.4 | 44.8 | 58.4 | 37.3 |
| Flow | 76.2 | 65.7 | 3.8 | 41.8 | 60.4 | 63.5 |
| Mill prices | 74.3 | 80.8 | 82.3 | 57.6 | 81.8 | 80.4 |
| Forge/cast | 37.3 | 78.8 | 50.0 | 21.9 | 58.7 | 69.0 |
| Block | 63.9 | 74.0 | 39.4 | 41.5 | 64.8 | 62.5 |

- **Backlog is not scored.** It signals both strong demand and a supply constraint. Today it equals about 42 months of shipments, which is evidence that output is limited by supply.
- **Flow peaks at known disruptions:** the 2008 strike (5.0), the 787 delays (6.3), the 737 MAX grounding (7.3), 2020 (15.9), the 2022 787 pause (9.1) and the 2024 strike (8.2).
- **Nonferrous forgings are up 11.4% YoY today,** above the 2022 record. This is real data, and it is why forge/cast reads 37.

**Rejected sources:**
- **Terms ban republishing:** Boeing and Airbus delivery data.
- **Quarterly:** Census QPC.
- **Annual:** USGS titanium sponge price.
- **Demand, not supply:** air cargo.
- **Too smooth:** engine-parts PPI.

## Profile design

**Recommendation: show each sector index alongside Global rather than blending the two.**
- S&P Global sector PMIs are built only from that sector's survey responses, and GEP publishes its regional indices separately.
- Blending Global into Semis would count Asia twice, because GSCPI already includes the Taiwan and Korea PMIs.
- Exposure-based tilts moved the result less than 3 points and rest mostly on judgment.

**Code and UI defects found:**
- Neutral 50 fallbacks are weighted into the profile index.
- A slow industry source blanks the whole profile index, because industry categories never fall back and are never excluded.
- Industry outages set the global `degraded` flag.
- Industry categories have no as_of date and no drop limit.
- Past days use raw weights while today uses renormalized weights.
- The sparkline draws a straight line across gaps.
- The API exposes no weights for industry categories and no profile composite.
- `/docs` never mentions the profiles.
- Old `chip_*` rows from before 2026-10-22 may include unflagged 50s.

**History:**
- New category keys keep the new data separate from the old `chip_*` and `aero_*` rows.
- Extend the rebuild to the new industry categories. FRED, BLS and ECOS all have real history.
- Apply the same exclusion and coverage rule to past days as to today, and draw gaps as gaps.

**Exposure (UN Comtrade, US imports 2024):**

| Product | Top sources |
|---|---|
| Integrated circuits | Taiwan 28.1%, Malaysia 23.8%, Israel 10.4%, Korea 6.0%, China 3.6% |
| Aircraft parts | UK 14.3%, Canada 13.5%, France 12.8%, Japan 11.0% |
| Unwrought aluminum | Canada 70.7% |
| Titanium | Japan 32.7%, China 8.5% |
