# gscindex — Rigor & Correctness Pass

**Date:** 2026-06-10
**Scope:** Methodology review, ruthless critique, strategic direction options, and a correctness/dead-code remediation pass on the existing build. No new categories, no new data sources, no methodology redesign in the code changes (those are deferred to a later pass).

This document is the durable record of a multi-part working session. It is organized in the order the work happened:

1. Purpose and audience assessment
2. Ruthless critique of the existing build (grounded in the actual code, not the README)
3. Strategic directions for where the project could go (3–5 distinct bets)
4. The recommendation
5. The decision to fix correctness first, before any redesign
6. The prioritized punch list of correctness and dead-code fixes
7. What was actually implemented, file by file
8. The unplanned discovery (GSCPI parser) and why it mattered
9. Verification evidence
10. Known follow-ups and deferred decisions

---

## 0. Context

`gscindex` is a real-time supply chain health dashboard built with Python/Dash. It aggregates six provider categories, computes a weighted composite index (0–100), and serves interactive visualizations plus a public JSON API. Core features: composite health index, six category breakdowns, a 37-port map, 90-day trend charts, news alerts, and a public JSON API.

The project's primary purpose is a **portfolio piece**. The author is finishing a supply chain degree and targeting sourcing/supply chain roles in manufacturing and aerospace. The optimization target is therefore **rigor and defensibility** in front of a technical reviewer or a domain-credible hiring manager, not growth or daily-user mechanics.

The review was explicitly asked to be skeptical and specific to this build, to reason from the actual data sources and scoring logic, and to flag anything that "would not survive a sharp interviewer asking why should I trust this number." No em dashes were used in the delivered analysis or in code.

---

## 1. Purpose and audience

**Honest conclusion: no one makes an operational decision from this composite number. It is a demonstration of skill.**

A sourcing manager at an aerospace supplier cares about their specific commodities (titanium, nickel, fasteners, castings), their lanes, and their suppliers' regions, not a single global mood-ring score. A global composite moving from 67 to 71 changes nothing they would do. Even the NY Fed's GSCPI, built by professional economists, is used for macro commentary rather than operational decisions.

This reframing matters because it sets the optimization target. The real audience is **a technical hiring manager or senior sourcing person spending about ten minutes on it**, and the real product is **the methodology and the engineering judgment visible through it**, not the index value. The engineering judgment in the build was already strong (threading model, cache fallback chain, atomic writes, provider abstraction). The methodology was the weak flank, so the work focused there.

---

## 2. Ruthless critique of the existing build

Ordered by how badly each item undermined credibility. Each was grounded in the actual code (scoring engine, config, providers, aggregator, database).

### 2.1 The geopolitical history chart was fabricated (worst issue)

`geopolitical.fetch_history()` returned the **VIX** (equity option volatility), normalized with `120 - 2*VIX`, then level-shifted by a constant so the last point equaled today's news score. The 90-day "Geopolitical Risk" trend was therefore the trend of US equity volatility, not of supply chain news sentiment, presented as if it were measurement. A code comment even claimed "the trend looks real (it is)," which was false. Trucking did a milder version of the same thing (heating oil futures plus a constant spread, presented as daily diesel).

Why it mattered: any reviewer opening that file sees synthesized history presented as measurement, which poisons trust in every other number on the dashboard. It was also unnecessary, because the schema already had a `daily_scores` table and could accumulate real history.

### 2.2 The geopolitical score measured feed volume, not risk

The score was `100 + sum(all negative VADER severities)` over the entire batch, unbounded, with no per-article cap, no volume normalization, and no source deduplication. Twenty mildly negative headlines at compound −0.4 contributed −48 points (score 52, "Stressed") from routine news. Whether the feed returned 20 or 50 items moved the score more than any actual event did. The module docstring also said the score "starts at 85" while the code started at 100 (doc-code drift in the scoring logic).

On signal quality: VADER on headlines carries very little of the signal you actually want. "Maersk reroutes around Cape of Good Hope" is operationally severe and sentimentally neutral. VADER was built for social-media valence, not event severity.

### 2.3 The WEI sign was backwards for supply chain health

`supply_chain` blended WEI (60%) and GSCPI (40%). WEI is a GDP-growth nowcast, and high growth historically coincides with supply chains breaking. Concrete backtest: in late 2021, WEI ran around +7 (wei_score pinned at 100) while GSCPI peaked at 4.31 (gscpi_score clipped to 0). The blend produced 0.6×100 + 0.4×0 = **60, "Stable," during the worst supply chain crisis in modern history.** That single example ends the index's credibility in an interview.

### 2.4 Cost-side normalization scored demand collapse as "healthy"

Energy and trucking scored inverse to price against a trailing 2-year min/max. Two problems:
- **Demand-collapse blindness:** April 2020 WTI at −$37 would read as the healthiest possible energy reading while supply chains were in free fall.
- **Moving target:** trailing min/max means a score of 0 is "2-year high," not "crisis," and the same $85 barrel scores differently as the window rolls. Min/max is also dominated by single outlier prints.

### 2.5 Weights were arbitrary and categories were not independent

10/20/20/15/15/20 had no derivation. Worse, CL=F (energy) and HO=F (trucking) are crack-spread cousins with correlation north of 0.9, so energy (0.20) plus trucking (0.15) is effectively a **0.35 weight on petroleum**. Meanwhile GSCPI, the only input purpose-built to measure supply chain pressure, had an effective weight of 0.20 × 0.4 = **0.08**. The index was roughly one-third oil price and one-twelfth actual supply chain pressure.

### 2.6 Re-aggregating GSCPI added no value as built

GSCPI is the professional version of the whole project (PCA over transport costs and PMI components across seven economies). Wrapping it at 8% effective weight inside noisier, sign-confused signals strictly degrades it. The only defensible relationships to GSCPI are to nowcast it, to benchmark against it, or to measure something it does not (sector or event resolution). "Blend it in at 8%" was none of these.

### 2.7 No backtesting, so the number meant nothing

There was zero evidence the composite moved on real disruptions, and it could not even be backtested because two category histories were synthetic. The event library to test against is public and short (Suez 2021, Shanghai 2022, Red Sea 2023+, Baltimore 2024, ILA strike 2024, plus tariff windows), roughly 15–20 dated events.

### 2.8 Smaller but real

- Tariffs used general EPU (`USEPUINDXD`), which spikes on debt ceilings, elections, and Fed drama, while the label promised tariffs.
- The AI validator computed an adjustment, clamped it to ±5, cached it, stored it, and **never applied it** (and, on inspection, never rendered it either). Dead compute with an API bill.
- The port map (the flashiest feature) had the least data behind it: 55% local weather + 45% regional macro, no dwell times, no vessel queues, no throughput.
- Silent provider fallbacks injected 50/75/85 into the composite with no degradation flag anywhere.

---

## 3. Strategic directions (distinct bets, not variations)

All preserve the core features (composite, six categories, map, trends, alerts, API).

### Direction A: The validated index ("show your work")
Same scope, but every number earns its place: weights justified, normalizations anchored, history real, and a published backtest against known disruption events. Store real daily scores, fix the WEI sign and demand-collapse blindness, replace min/max with percentile or anchored z-scores, run PCA and sensitivity analysis on weights, publish a `/methodology` page with the backtest chart. Effort: 3–5 weeks. Biggest risk: the backtest reveals the index is mostly oil price, though that is survivable as an honest finding.

### Direction B: Aerospace and manufacturing supply chain monitor
Stop measuring "the global supply chain" (GSCPI already does that better) and measure the industrial base the author wants to work in. Categories become sector-relevant: raw materials (LME/COMEX nickel, aluminum, copper, titanium proxies), industrial energy and freight, real trade-policy tracking, production activity (Census M3 aerospace orders/backlog, PPI `336411`, ISM supplier deliveries), chokepoints weighted by aerospace exposure, weather at the hubs that matter to aero logistics. Effort: 4–6 weeks, mostly data sourcing. Biggest risk: the most valuable data (lead times, supplier-level signals) is paywalled, leaving proxies of proxies.

### Direction C: Daily GSCPI nowcast
Invert the GSCPI relationship: use daily signals to predict the next monthly GSCPI print and score yourself against every release. The composite becomes "estimated current GSCPI." Falsifiable by construction. Effort: 3–4 weeks for v1. Biggest risk: monthly ground truth means "is it working" takes a quarter to answer, and it reads as an econometrics project more than an operations project.

### Direction D: Event-driven disruption intelligence
The product becomes a structured, provenance-tracked disruption event database (what Everstream and Resilinc actually sell), with the index derived from active events plus macro background. Replace the VADER sum with typed event extraction (event class, chokepoint/region, mode, severity, dates, status, source URLs) using Gemini against a fixed schema and a hand-labeled eval set so precision/recall can be stated. Effort: 5–8 weeks, the heaviest. Biggest risk: extraction quality, which makes the labeled eval set non-negotiable.

---

## 4. Recommendation

**Direction B, built on Direction A's discipline.** A sector-focused monitor with validated methodology underneath. It is the only direction where the project title alone does career work in a screening call, it answers the GSCPI redundancy question cleanly (sector resolution), and it still requires A's backtest, anchored normalization, and real stored history. The flagged assumption was that free sector-specific data (Census M3, BLS PPI for 336411, LME proxies, ISM components) is rich enough to fill six categories without paywalled lead-time data.

**The author's stated lean is Direction D**, to be kept in mind but not yet built.

---

## 5. Change of plan: correctness first

Before any redesign, the decision was made to **fix the broken logic and cut dead/dumb code that already exists**, so the existing thing stops lying and stops carrying useless code. Categories and data sources stay as-is for this pass. Direction D being the likely future shaped one specific call: do not build a careful band-aid on the geopolitical score that D will delete; do the minimal "make it not wrong" version instead.

---

## 6. The prioritized punch list

Ordered by a mix of damage and dependency. The fabricated-history fix went first because real history has to start accumulating regardless of direction.

1. **Fabricated histories** (geopolitical VIX level-shift, trucking HO+spread). Replace with real stored daily history. Direction D keeps this entirely, so do it fully.
2. **WEI sign error.** Remove WEI from the score (GSCPI only); no linear sign is correct in both booms and recessions.
3. **Geopolitical score = feed volume.** Dedup, top-N, floor. This is the explicit band-aid case: minimal version only, because D replaces the whole path.
4. **Silent fallbacks.** Tag at source, propagate to snapshot, expose in API/health/cards.
5. **AI validator.** Delete (computed, clamped, cached, stored, never applied, never rendered).
6. **Cost-side normalization.** Minimal version: reframe as cost-pressure (the formula is correct for a cost gauge, the framing was the lie) and swap min/max for rolling percentile rank.
7. **Tariffs.** Swap `USEPUINDXD` for trade-policy-specific `EPUTRADE` (verify the series resolves first).
8. **Severity label scale.** `_sentiment_label` interpreted a −6..0 severity scale as if it were −1..+1 VADER compound, so everything read "Very negative."
9. **Doc-code drift.** 85-vs-100 docstring, map blend (README/CLAUDE say 55/45, code is 40/60), gthreads (README 8 vs CLAUDE 4), trucking's chat-transcript comments, the "real data only" map docstring.
10. **Dead code.** `_REGIONAL_PENALTY`, `normalize_series_direct`, `chokepoint` config entries, `REGIONS`, the `_scd` aliased import, the commented-out adjustment block, the duplicate color banner.

Plus cache-key bumps for the news payload and the dashboard snapshot, since items 3/4/5 change cached schema.

---

## 7. What was implemented, file by file

### `data/database.py`
- Added the `daily_category_scores` table (Postgres and SQLite) with `PRIMARY KEY (date, category)`. This is the real measurement history behind the trend charts.
- Replaced `record_daily_score(score)` with `record_daily_scores(composite, category_scores)`. It upserts the composite into `daily_scores` and each category into `daily_category_scores`. Guard changed from once-per-calendar-day to **once-per-hour**, so the stored row converges to the day's last reading instead of freezing the first post-midnight value.
- Added `get_category_score_history(category, days)` returning a `pd.Series` with a `DatetimeIndex`, covering only days actually measured (may be short or empty while history accumulates).

### `data/providers/geopolitical.py`
- Rewrote the module docstring to describe the real formula (was the false "starts at 85").
- Added `_risk_score_from_alerts(alerts)`: dedup by normalized title, keep the 10 most severe negatives (`_RISK_TOP_N = 10`), floor the total deduction at −60 (`_RISK_FLOOR`), subtract from 100. Positive sentiment never inflates.
- `_build_vader_alerts` now returns just the alert list (dropped the unbounded `severity_sum`).
- All three scoring paths (`fetch_supply_chain_news`, `_refresh_cached_news_from_rss`, the live-VADER fallback in `fetch_current`) now use `_risk_score_from_alerts`.
- `fetch_history` deleted the VIX level-shift entirely and now reads `get_category_score_history("geopolitical", days)`.
- Updated the calculation metadata string to match.

### `data/providers/supply_chain.py` (rewritten)
- Score is now GSCPI only: `score = 50 - GSCPI*25`, clipped 0–100. If GSCPI fails, the provider fails and the aggregator flags the category (no silent stand-in).
- WEI is fetched for the metadata description only and contributes nothing to the score. Deleted `_wei_to_score` and `_blend_scores`.
- `fetch_history` is GSCPI scores resampled to daily with forward fill.

### `data/providers/trucking.py` (rewritten)
- Removed all the first-person chat-transcript comments. Clean module docstring stating the method.
- Current score: nowcast diesel = live HO=F + retail spread (spread = latest weekly DOE print minus the HO=F close nearest that date, with a `$1.30` fallback), scored by `inverse_percentile_value` against the trailing DOE distribution. Explicitly labeled a cost-pressure gauge.
- `fetch_history`: official weekly DOE retail diesel, scored and forward-filled to daily. No synthetic daily series.

### `data/providers/energy.py`
- Docstring reframed as a cost-pressure gauge (not demand health).
- Scoring switched from min/max bounds to `inverse_percentile_value` against the trailing FRED distribution. Noted the small CL=F (future) vs DCOILWTICO (spot) basis.

### `data/providers/tariffs.py` (rewritten)
- Series swapped from `USEPUINDXD` to `EPUTRADE` (Trade Policy categorical EPU). Verified live on FRED (monthly, last updated 2026-06-01). Metadata text updated; history forward-filled to daily.

### `data/providers/fred_client.py`
- `normalize_series_inverse` now uses rolling **percentile rank** (`rolling(...).rank(pct=True)`) instead of min/max, robust to single outliers. `min_periods` lowered to 12 so monthly series (EPUTRADE, etc.) still score within a 2-year window.
- Added `inverse_percentile_value(value, series, lookback_days)` for scoring a single current value by its percentile in the trailing window.
- Deleted `normalize_series_direct` (no callers) and the old `normalization_bounds` / `inverse_normalize_value` min/max helpers.

### `data/aggregator.py`
- Removed the `validate_score` import and the entire AI-validation block (including the commented-out adjustment application).
- `_make_fallback_series` now returns NaN for all days except today (was a flat fabricated line).
- Added `_fallback_metadata(reason)` returning the full required-key metadata shape with `is_fallback=True`, so the detail modal renders properly on failure.
- `_fetch_provider_data` sets `is_fallback` (True on failure/non-finite, False on success).
- History alignment no longer backfills leading NaNs with today's score (`fillna(score)` removed); dates before the first real observation stay NaN and render as a gap.
- The missing-provider backfill loop now attaches flagged fallback metadata.
- Computes `fallback_categories` and adds `degraded` / `fallback_categories` to the snapshot.
- Persists only **measured** (non-fallback) scores via `record_daily_scores`, so fallbacks never pollute real history.
- Renamed `_sentiment_label` to `_severity_label` with thresholds on the actual −6..0 severity scale (Severe / Significant / Minor), and tooltips now print severity, not mislabeled sentiment.
- Deleted `_REGIONAL_PENALTY` and the `_scd` aliased import.
- `get_safe_fallback_data` now includes `degraded: True` and all categories in `fallback_categories`.

### `scoring/engine.py`
- Deleted `compute_composite_series` (no callers anywhere, confirmed by grep) and the now-unused `pandas` import.

### `data/cache.py`
- Introduced versioned `_DASHBOARD_SNAPSHOT_KEY = "dashboard_snapshot_safe_v2"` used by both read and write, busting old-schema snapshots.

### `config.py`
- Removed `SUPPLY_CHAIN_WEI_WEIGHT` / `SUPPLY_CHAIN_GSCPI_WEIGHT`, the `chokepoint` entries in `CATEGORY_LABELS` and `CATEGORY_COLORS`, the unused `REGIONS` list, and the duplicate "Color Palette" banner.
- Bumped `NEWS_BRIEFING_CACHE_KEY` to `newsapi_briefing_v16`.

### `api/routes.py`
- `/api/v1/latest` now includes `degraded` and `fallback_categories`.

### `app.py`
- `/health` (and `/healthz`) now report `fallback_categories` from the in-memory snapshot.

### `components/cards.py`
- `_sparkline` is NaN-safe: drops NaN, renders an empty figure when there is nothing to show, and switches to markers when only one point exists.
- Card stats and the day-over-day delta compute from the last two real (non-NaN) observations.
- Added a small orange `FALLBACK` badge in the card header when `is_fallback` is set.

### `data/ai_validator.py`
- Deleted entirely.

### Docs (`README.md`, `CLAUDE.md`)
- Category source table rewritten (GSCPI monthly, EPUTRADE, percentile scoring, DOE weekly diesel + HO nowcast, cost-pressure framing).
- Map blend corrected to 40/60. gthreads aligned to 8. `GEMINI_API_KEY` purpose changed from "score validation" to "news analysis." `FRED_API_KEY` scope corrected.
- Snapshot structure updated (`ai_validation` removed; `degraded` / `fallback_categories` added).
- Database section documents the new `daily_category_scores` table.
- Added "things that will break" guard rails: never fabricate history, and do not put WEI back into the supply chain score.

---

## 8. The unplanned discovery: GSCPI parser

Removing the WEI mask immediately surfaced a real, previously hidden bug. The NY Fed changed the GSCPI CSV export so column headers are now **Excel serial dates** (e.g., `44562`) instead of `"%b-%y"` strings (`"Jan-22"`). The old parser threw `time data "44562" doesn't match format "%b-%y"` on every fetch. This had been failing silently for an unknown period, because the failure path substituted the WEI score, exactly the masking pattern the WEI removal was meant to eliminate.

Fix in `data/gscpi_client.py`:
- Added `_parse_month_column` handling both header formats (`%b-%y` strings and Excel serials via the 1899-12-30 epoch), with sanity bounds (1995-01-01 to next year) that reject mis-parses and unparseable columns rather than crashing.
- Bumped the GSCPI cache key to `nyfed_gscpi_monthly_v2`.

After the fix: 54 monthly vintages parse cleanly through 2026-06-30, latest published GSCPI +1.82, scoring 4.4.

### Effect on the headline number
The composite dropped from the low 60s to **39 ("Critical")**. This is not a regression, it is the honest reading:
- GSCPI at +1.82 sigma scores 4.4 under `50 - 25z`. The old blend reported ~64 only because WEI at +3.2 was drowning GSCPI out, which is the exact 2021-pattern failure identified in the critique.
- Energy (11.5) and trucking (13.3) are percentile scores reflecting prices near the top of their 2-year distributions.

---

## 9. Verification evidence

- **Imports:** all touched modules import cleanly.
- **Unit checks (synthetic):**
  - Geopolitical risk score is volume-invariant (30 mild items → 82), deduplicates (20 identical severe → 95), and floors (30 severe → 40); empty and positive-only inputs return 100.
  - Percentile normalization scores rising prices low; monthly series score within the window (the `min_periods=12` fix); `inverse_percentile_value` returns expected extremes.
  - Fallback series is NaN except today; severity labels map correctly; fallback metadata has the full key shape.
  - Composite engine still validates and computes.
- **DB round trip (SQLite temp):** `record_daily_scores` writes, `get_category_score_history` reads back with a DatetimeIndex, the hourly guard skips the second write, and an unknown category returns empty.
- **NaN-safe sparkline:** short, single-point, and empty series all render without error; single-point uses markers.
- **Live boot (real keys, full cycle):** fetch completed in ~33s with **zero errors and zero fallback categories**; `/health` healthy; `/api/v1/latest` serving the new fields; first real daily-history rows confirmed in Neon Postgres (`geopolitical 74.0`, `supply_chain 4.4` for 2026-06-10).
- **Linters:** no errors across `data/`, `components/`, `scoring/`, `api/`, `app.py`, `config.py`.
- **Servers:** both smoke-test servers stopped; port 8050 free.

### Expected cosmetics going forward
- The geopolitical trend line starts as a single point and grows one real point per day.
- Trucking shows weekly steps instead of daily wiggles.

Both are correct. The wiggle was the bug.

---

## 10. Known follow-ups and deferred decisions

These were intentionally **not** done in this pass (they are redesign, not correctness):

- **GSCPI calibration:** `50 - 25z` saturates at ±2 sigma, so GSCPI will pin near 0 while pressure stays elevated. This is a calibration choice for the methodology pass.
- **Weights:** still 10/20/20/15/15/20 with no derivation, and energy+trucking still co-load on petroleum. PCA and sensitivity analysis belong to Direction A.
- **Backtesting:** real history now accumulates from day one (2026-06-10), which is the prerequisite. The actual backtest against the disruption event library is future work.
- **Port map:** still 40% weather + 60% regional macro with no operational port data.
- **Demand vs cost:** energy and trucking remain cost gauges. Distinguishing demand-driven price moves needs a second signal (new data), which was out of scope.
- **Tariffs and supply chain cadence:** both are now monthly by design, so those trend lines move slowly. This is honest, not a defect.

### If pursuing Direction D next
- Keep the geopolitical scoring as the deliberately minimal band-aid it now is; D will replace the whole path with typed event extraction.
- The non-negotiable first artifact for D is a hand-labeled eval set (~100 articles) so extraction precision/recall can be stated.
- Real stored history (shipped in this pass) is the backbone for any direction, including D.

### Immediate concrete first move (from the recommendation)
Two small parallel tracks: (1) keep persisting real daily scores (now live), and (2) run a data inventory for the chosen direction, checking frequency, lag, history depth, and license for candidate series and overlaying them on the 15–20 event windows. Success signal within a few weeks: at least 4 of 6 redesigned categories have free, 2-year-plus, weekly-or-better data, and at least two series visibly move in the event windows.
