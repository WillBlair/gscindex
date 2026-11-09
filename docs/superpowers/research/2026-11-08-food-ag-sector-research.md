# Food and Agriculture sector index: research

Date: 2026-11-08. Four research passes (data sources, codebase fit, audience and value, historical episodes). Every URL below was fetched on this date; computed numbers are our arithmetic on the downloaded files, not published figures. Nothing in the code was changed.

## 1. Verdict

A Food & Ag tab is buildable from free data with the existing sector plumbing, and nothing free gives a daily 0–100 that blends food prices, fertilizer, grain barge freight and drought with a public API. The build is about 2–3× the Aero sector (four non-FRED sources instead of zero) and takes 5–6 Claude sessions plus roughly 1–1.5 hours of Will's review across four checkpoints.

The honest downside: the audience (food procurement, grain merchandisers, ag lenders, ag journalists) is different from the semis and aero readers, the inputs are mostly monthly or weekly so the tab will read "stale" between releases, and a 7-subscriber site will only matter on the three or four spike days a year unless the distribution pitch is written at the same time.

## 2. What it would look like

Tab label "Food" or "Agri" (4 letters fit the header; "Food & Ag" overflows the desktop header between 1101 and about 1160px unless the wrap breakpoint moves). Four categories, equal weights, `min_categories` 3 of 4, like Aero.

| Category | Input(s) | Source | Direction | History | Anchor preview (computed) |
|---|---|---|---|---|---|
| `food_prices` Food Prices | FAO Food Price Index, YoY % | FAO CSV, monthly, ~6 day lag | lower = healthier | 1990– | p5 −18.4%, median +1.3% (=80), zero +63.3% (2008-03); latest +5.9% |
| `fertilizer_prices` Fertilizer | Urea, DAP, potash, log real $/mt (CPI to 2025-12), equal-weight | World Bank Pink Sheet xlsx, monthly, 2–3 day lag | lower = healthier | 1960/1967– | medians urea 187 / DAP 218 / potash 153 nominal; zeros 2022-04 (urea 925, potash 1,202), 2008-07 (DAP 1,076); latest 420 / 803 / 358 |
| `grain_freight` Grain Barge Freight | St. Louis downbound barge rate, % of 1976 tariff, 4-week mean, log | USDA AgTransport Socrata `deqi-uken` (same client as STB rail), weekly, 2 day lag | lower = healthier | 2004– | p5 174, median 308, zero 2,239 (2022-10); latest 564 |
| `crop_drought` Crop Drought | CONUS area in D2 or worse, 4-week mean | US Drought Monitor API, weekly, no key | lower = healthier | 2000– | p5 2.1%, median 16.4%, zero 44.5% (2012-08); latest 23.0% |

Alternatives on the table:
- Food prices: FRED `PFOODINDEXM` (IMF, 1992–) instead of FAO if the FAO license question is unresolved. Same basket; use one, not both.
- Fertilizer: FRED `WPU0652` (PPI fertilizer materials, 1933–) + `PCU325311325311` (nitrogenous fertilizer mfg, 1975–) YoY. US-only view, public domain, already plumbed.
- Fourth category: `food_throughput` = Fed G.17 `CAPUTLG311S` food manufacturing capacity utilization (1972–, higher = healthier, zero 2020-04 at 74.3%) instead of drought, if a throughput gauge in the Aero style is preferred. It is the only candidate that registers the 2020 meatpacking closures.
- Optional second freight input: BNSF/UP secondary railcar near-month bid (`cvu8-kpyk`, 1997–, identity transform because bids go negative).

### Share card and header
- `/og.png` lays out sector blocks 170px apart from y=140; a third block runs over the footer and needs a relayout (smaller type or 2×2).
- Phones at 375px: four tabs fit with room (about 85px each).
- Skeleton tab placeholder widens from 180 to about 240px.

## 3. What it would form into (backtest)

Months the index must read Stressed or Critical, and what each input showed:

| Episode | FFPI YoY | Urea / DAP / potash $/mt | Barge STL % tariff (monthly mean) | Drought | Notes |
|---|---|---|---|---|---|
| 2008-06 to 08 food crisis | +45% (Jun), +63% (Mar record) | 785 / 1,065 / 546 (Aug) | 432–463 | n/a | PPI grains +66% |
| 2011-02 wheat ban / Arab Spring | +38.7% (FFPI 137.7) | 298 / 414 / 374 | 458 | n/a | PPI grains +84 to +97% |
| 2012-07 to 12 US drought + low water | −7.2% to +0.7% | 383 / 505 / 478 | 506 (Dec), weekly 613 Illinois | 89% of corn in D1+ (Jul 24); CONUS D1+ 63.9% | Only drought and barge see it. A price-only index misses 2012 entirely |
| 2021-11 to 2022-05 fertilizer + Ukraine | +28% to +34.5% (FFPI record 160.2, Mar 2022) | 925 / 954 / 1,202 (Apr 2022 records) | 588–711 | — | TTF $42 at the same time (Energy already partly sees it) |
| 2022-10 Mississippi low water | +2.6% | 636 / 725 / 623 | 2,239 (weekly 2,653; $105.86/ton record) | 71% of corn (Nov 1) | Only barge and drought see it |
| 2023-09 low water | −11.4% | 380 / 528 / 352 | 912 | — | Barge only |
| 2026-03 to 05 Hormuz fertilizer | +1 to +2% | 857 / 725 / 401 (Apr) | 456 | 19% corn | TTF calm at $15.4, so Energy does NOT see it; fertilizer is not redundant with TTF |
| 2026-09 low water + harvest | +5.4% (cereals +16.7%) | 408 / 801 / 368 | 777 (weekly 835) | 21% corn, 50% winter wheat | PPI grains +31.6% |

Months the index must read Healthy or Stable: 2016-06 (FFPI 93.8, urea $143, barge 242), 2017-06 (FFPI 97.8, urea $191, barge 195, the p5 area), 2019-05 (FFPI −4.4%, 0% of corn in drought; barge 283–310 from flooding, a real disruption). 2023-06 is a judgment call: prices calm (FFPI −21%, barge 213) but 70% of corn in drought.

What the four inputs miss: the 2020 meatpacking closures (FFPI 91, farm PPI −14% read "healthy" while beef output was −20%; only `CAPUTLG311S` or PPI processed foods at +6.9% registers it) and the 2024–25 egg, cocoa and coffee records (FFPI has no beverages or eggs; eggs hit $6.23/doz, +108% YoY in Mar 2025). Both are disclosed limitations, same as the April 2020 note on /docs, unless a fifth input is added.

Demand-driven false positives: barge 868% in Oct 2014 (record crop, no river problem) is the pre-2020 maximum; ocean grain freight spikes in 2008 and 2021 were shipping booms. Pairing barge with the St. Louis gauge already in Physical would separate low water from demand, as a later refinement.

Redundancy: fertilizer correlates with TTF in 2021–22 but not in 2008 (TTF $14.6, urea $785) or 2026 (Hormuz), so it earns its place. PPI farm products is redundant with FFPI at every peak and misses 2012; left out. Ocean Gulf-to-Japan freight moves with the Baltic Dry Index (inside GSCPI) and bunker fuel (ULSD); the USDA weekly dataset for it was abandoned in 2021 anyway. Context only if at all.

## 4. Value and audience

The gap: no free, daily, single-number food supply chain stress index with an API exists. The closest things are FAO FFPI (monthly, one price number, no logistics), AMIS and World Bank Food Security Update (monthly prose), WFP (quarterly, developing-country hunger), IFPRI's futures-volatility flags (per commodity, public mirror frozen since 2022, tool URL 404 today), and paid feeds with no composite (Platts, Expana, Vesper, DTN, Green Markets, Argus). Gro Intelligence shut down in 2024.

Who would use it and where they are:
- Food and supply chain trade press: Food Dive (~88k subscribers), Supply Chain Dive (~67k), World-Grain, Feedstuffs (~11k), The Packer (18k). Journalists quoted Green Markets' weekly fertilizer index through 2021–22 because it was one number. Best citation bet.
- Ag econ faculty and students: farmdoc daily (U of Illinois) already wrote the 2026 Hormuz fertilizer pieces; K-State AgManager; r/farming ~220k, r/Commodities ~24k. Free API for class projects; citation only with the /docs methodology.
- Ag lenders: ABA Ag Bankers Conference and state banker ag conferences track commodity markets for loan committees; no free composite exists for them.
- Grain merchandisers already pay for DTN and Pro Farmer; they sign up only if barge + chokepoints in one place catches something their tools don't.

Stories 2024–26 a daily number could have been quoted on: eggs $4.95 retail record Jan 2025 and HPAI; Mississippi draft restrictions Aug 2023, Sep 2024, Feb and Sep 2025; Panama Canal transits capped at 22 then 18 a day in Dec 2023 to Feb 2024; Red Sea grain rerouting from Dec 2023; cocoa ~$12,500/t Dec 2024, arabica record Feb 2025; 17% duty on Mexican tomatoes July 2025; Hormuz closure Feb 2026 with retail urea $858/t by mid April and 70% of farmers unable to afford all the fertilizer they needed.

Monetization constraints: FAO is CC BY 4.0 but adds "shall not be used for or in conjunction with the promotion of a commercial enterprise" and a mandated citation; World Bank is CC BY 4.0 (fertilizer series are republished Green Markets quotes, catalog license field unverified today, API rate-limited); USDA is public domain; Drought Monitor explicitly allows commercial use with a fixed credit line. Only FAO would add a BOJ-style second credit and permission question.

## 5. What Claude does alone and what Will does

Claude alone:
- Four `data/sources/*.py` modules (FAO CSV, Pink Sheet xlsx, AgTransport barge, Drought Monitor) with fail-closed parsers, versioned caches, one verified live call each, tests.
- `data/providers/food.py`, config entries (SECTORS, FRESHNESS, PUBLICATION_LAG_DAYS, labels, colors, timeouts), aggregator registration, a per-category drop-window override for the weekly inputs.
- `compute_anchors.py --sectors-only` run and `git diff` check (additions only).
- API `SECTOR_TERMS`, CSV credits, /docs cards and the hardwired two-sector sentences, share card relayout, header CSS, skeleton width, every enumerating test, local preview at desktop and 375px.
- Rebuild dry run (SQLite then Neon read-only), CLAUDE.md and README, commits.

Will:
1. Approve the spec: categories, directions, FAO vs IMF-on-FRED for food prices, Pink Sheet vs PPI for fertilizer, drought vs food throughput as the fourth, tab label, 3 of 4 coverage.
2. See the anchor table before the anchors commit (frozen-anchors rule; `--sectors-only` leaves every global value byte-identical).
3. Decide on the FAO license question and send any notice email (or pick the IMF/FRED alternative and skip it). Confirm the Pink Sheet catalog license field.
4. Approve the production backfill after reading the dry-run summary (`CONFIRM_PROD_REBUILD=yes`). Note: `--sectors-only` today also rewrites the Semis and Aero rows; a `--sector food` flag should be added first.
5. "push it" for the code; after the first production snapshot, "push it" again for the refreshed `fallback_snapshot_safe.json`.
6. Money: none. All sources free. More jobs per cycle on Render, no plan change.

## 6. Effort and order

Rough size: 25–30 files, 1,300–1,900 lines (the two-sector build was ~3,400 net new code lines; Aero alone +681 but FRED-only).

1. Spec and plan, 0.5–1 session.
2. Sources, 1.5–2 sessions.
3. Provider, config, anchors, 1 session (Will reviews the anchor table).
4. Aggregator, API, CSV, docs, share card, CSS, tests, preview, 1 session.
5. Backfill and ship, 0.5–1 session (Will's go on the write, two "push it"s, phone check).

## 7. Codebase risks

- `SECTOR_DROP_AFTER_DAYS` is one constant (150) for every sector category. A weekly barge or drought category whose source fails would serve a stored score up to 149 days old. Needs a per-category override like the global chokepoints (42) and the rail freshness (14, 45).
- Semis/Aero helpers (`monthly_daily`, `yoy_percent`, `period_end(..., "M")`) are monthly-only. Weekly inputs must use the freight `_carry` pattern dated by week-ending.
- Keep one cadence per category; mixing a monthly and a weekly input in one category makes it flag stale on the weekly one's 14-day window.
- `_SECTOR_TASKS` has 2 workers; 11 sector jobs with deadlines from cycle start means `max_workers=3` and timeout overrides for the xlsx download and the Socrata query. A 150s barge override could delay the Global refresh by up to 150s on a hang.
- The BOJ credit is hand-coded in three places (`aggregator._stored_fallback_metadata`, `workspace._CSV_CREDITS`, `routes`). A second credited source (FAO or USDM) means a per-category credit map, not a second special case.
- Drought has a seasonal cycle (a normal August reads worse than a normal March). Either disclose it or use same-calendar-month baselines like chokepoints.
- Pink Sheet CDN served a file 5 days stale on first fetch; fetch with a cache-buster and check the "Updated on" cell. The doc-id path segment changes yearly; scrape the link from the Commodity Markets page.
- FAO CSV: two title rows, header on row 3, blank row 4, trailing empty columns, prior month revised each release.
- `scripts/backtest_composite.py` raises KeyError until `SECTOR_EPISODE_MONTHS` has entries for the new sector (candidates: 2008-06, 2012-08, 2022-04, 2022-10, 2026-04).
- Tests that hardcode the three tabs: `aggregator_v2_test`, `terminal_ui_test`, `compute_anchors_test`, `docs_page_test`, `api_v2_test`, `sectors_aggregator_test`, `workspace_test`, `terminal_data_test`, `rebuild_history_test`. New anchor keys must be prepended in `SECTOR_INPUTS` or the key-order test fails.

## 8. Rejected inputs

IMF fertilizer series (not on FRED; IMF blocks automated download of its own file); IMF beef and rice (2010 start), poultry (2003); egg prices (one commodity, YoY −75% to +281% would swamp a category; hover context at most); HPAI flock counts (2022 start); Ag in Drought crop percentages (2012 start, PDFs and chart images only); NASS prices-paid fertilizer (key by email, monthly history before 2016 unverified); AMS MARS (terms and history unverified); Panamax Gulf-to-Japan (annual, abandoned 2021); fertilizer rail and ammonia pipeline tariffs (2021 and 2025 starts); Grain Transportation Cost Indicators (2017 base, paid ocean legs, overlaps barge); PPI farm products (redundant with FFPI, misses 2012); Baltic, Platts, Argus, DTN, Green Markets (paid); World Bank Fertilizers index as a level (runs from 1960, pre-2020 median 35.7, useless anchor).

## 9. Sources

- FAO FFPI page and CSV: https://www.fao.org/worldfoodsituation/foodpricesindex/en/ ; https://www.fao.org/media/docs/worldfoodsituationlibraries/wfs-library/food_price_indices_data.csv ; terms https://www.fao.org/contact-us/terms/db-terms-of-use
- World Bank Pink Sheet: https://www.worldbank.org/en/research/commodity-markets ; licenses https://datacatalog.worldbank.org/public-licenses
- USDA AgTransport barge rates: https://agtransport.usda.gov/resource/deqi-uken.json ; railcar bids `cvu8-kpyk`; GTR datasets https://www.ams.usda.gov/services/transportation-analysis/gtr-datasets
- US Drought Monitor API: https://usdmdataservices.unl.edu/api/USStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=conus&startdate=1/1/2000&enddate=11/8/2026&statisticsType=1 ; permission https://droughtmonitor.unl.edu/About/Permission.aspx
- FRED: PFOODINDEXM, PWHEAMTUSDM, PMAIZMTUSDM, PSOYBUSDM, WPU01, WPU012, WPU02, WPU0652, PCU325311325311, CAPUTLG311S, APU0000708111, CPIAUCSL
- Episodes: FAO 2008 freight note https://www.fao.org/4/ai482e/ai482e11.htm ; 2012 drought https://drought.unl.edu/Publications/News.aspx?id=40 ; 2022 corn drought https://www.agrimarketing.com/s/145888 ; 2023 low water https://farmpolicynews.illinois.edu/2023/10/usda-explores-third-quarter-barged-grain-movements-on-the-mississippi-river/ ; 2020 slaughter https://esmis.nal.usda.gov/sites/default/release-files/rx913p88g/b85167397/qn59qp928/lstk0420.pdf ; Hormuz fertilizer https://www.wto.org/english/blogs_e/data_blog_e/blog_dta_10jul26_451_e.htm and https://farmdocdaily.illinois.edu/2026/04/middle-east-ceasefire-fails-to-ease-u-s-fertilizer-price-pressure-on-farmers.html ; 2026 low water https://www.hoosieragtoday.com/2026/05/25/low-mississippi-river-water-levels-raise-shipping-costs-for-farmers/
- Landscape: Gro shutdown https://techcabal.com/2024/06/02/kenya-data-analytics-gro-intelligence-shuts-down/ ; IFPRI tool mirror https://data.harvestportal.org/dataset/ifpri-excessive-food-price-variability-early-warning-system ; Green Markets record https://www.bloomberg.com/news/articles/2021-11-12/fertilizer-prices-rocket-to-new-record-for-second-week ; Food Dive audience https://www.studioid.com/Food-snapshot-2022/ ; Supply Chain Dive https://supplychaindive.com/advertise/
