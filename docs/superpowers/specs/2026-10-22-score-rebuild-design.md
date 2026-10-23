# Score rebuild: anchored categories, better sources (project 2)

Date: 2026-10-22. Status: approved by Will in chat ("make all the fixes ... they're all probably logical").
Research behind every decision: `docs/superpowers/research/2026-10-22-score-inputs-research.md`.

## Why

The composite is the product. It barely reacts to real events, and several of its categories read the opposite of reality:

- Hormuz transits are at 4% of normal, Brent is around $115 and diesel is $6.28, yet the index sits near 50.
- Trade policy uncertainty is at the 95th percentile since 1985, yet tariffs scores 87.5 ("calm").

There are four root causes:

1. **Rolling 2-year percentiles.** They normalize a crisis that lasts longer than the window, and they saturate at 0 so severity can't be ranked.
2. **The headline-tone geopolitical score.** VADER overwrites Claude hourly, the result depends on which articles happen to be in the feeds, and attention fades while a disruption persists. It produces about 75% of the composite's daily movement and none of it is signal.
3. **Missing inputs.** Chokepoint flow is missing, the weather input is ~97 almost every day, and the inputs don't measure what their labels say (IYT is a stock price, BDRY double-counts GSCPI).
4. **No common "normal".** An average GSCPI scores 50 ("Stressed") while flat freight volume scores 72.

## Goals

- Every category is a defensible reading of a named, published measurement, ranked against that input's long-run history with fixed anchors.
- The index reacts to real events the same day where the data allows (live energy futures) and within days otherwise (PortWatch, GPR), and stays down while a disruption lasts.
- Normal conditions read the same across categories.
- Every number on the site carries its source, as-of date, and stale/fallback status.

## Non-goals

- Redesigning the Semis and Aero industry views (project 3). They only get mechanical weight updates here.
- UI redesign. The Terminal layout only needs to fit the new rows.
- Giving the Claude disruption register a weight in the score. It runs in shadow mode first.

## Anti-goals (a failure even if it "works")

- Any invented or backfilled history. Recomputing past days from the real source series with the new formula is allowed. Proxy series, level-shifting, and filling gaps with today's value are not.
- Any rolling window that decides what "normal" is.
- Silent fallbacks or stale data shown as live.
- Headline sentiment in the score.

## Constraints

- Free sources only, no new accounts. Yahoo (yfinance) stays: Will chose to keep it despite its terms. Every Yahoo input needs an official fallback (FRED or IMF).
- Render runs 1 worker with limited memory (`docs/render-memory.md`). Anchors are computed offline, so runtime never downloads decades of history.
- The local `.env` `DATABASE_URL` is production. Develop and test with `DATABASE_URL=` (SQLite). Preview with `GSC_DISABLE_BACKGROUND=1 gunicorn`, never `python app.py`.
- Commit locally. Never push or deploy; Will says "push it".
- All tunables live in `config.py`. Generated anchors live in a committed JSON file loaded by `config.py`.
- PortWatch terms require crediting "Sources: UN Global Platform; IMF PortWatch" wherever its data appears. The API must stay free.

## Decided design

### 1. Anchored scale (all "level" inputs)

Each input is transformed first (log for EPU/GPR-type indices and commodity prices, CPI-deflated with CPIAUCSL for prices, YoY % for volumes). Then it is mapped piecewise-linearly through three fixed anchors on the transformed value:

- **100** = the healthiest 5% of pre-2020 history (5th or 95th percentile, depending on direction)
- **80** = the pre-2020 median ("normal")
- **0** = the worst monthly average on record through 2025

Values beyond either end are clipped to 0–100. Anchors are frozen. Re-anchoring is a deliberate, versioned change, never automatic.

Normal is 80 rather than 75 (my call). That way "normal" sits at the bottom of Healthy for every category. It also matches the event categories (chokepoints, physical disruption), whose normal is 95–100 by construction. With every input at normal the composite reads about 84.

Implementation:
- `scripts/compute_anchors.py` downloads full histories (FRED fredgraph CSV, NY Fed GSCPI CSV, Caldara-Iacoviello files, IMF monthly commodity series via FRED, PortWatch) and writes `data/score_anchors.json`.
- For each input the JSON records: transform, direction, the three anchor values, baseline period, source URLs, generated date, and `method_version`.
- `config.py` loads it as `SCORE_ANCHORS`.
- One shared pure function, `scoring/anchors.py: anchored_score(value, anchor)`, does every mapping.

Where an input's in-sample record is the current regime (tariff burden), the zero anchor is a documented historical reference instead, with a cited source. The builder records this in the JSON.

### 2. Categories and weights

| Key | Label | Weight | Inputs |
|---|---|---|---|
| `supply_chain` | Supply Chain | .20 | NY Fed GSCPI (monthly), anchored. BDRY leaves the score and stays as hover context. |
| `chokepoints` (new) | Chokepoints | .15 | IMF PortWatch daily transits (design §3) |
| `energy` | Energy & Fuel | .15 | Brent, NY Harbor ULSD and TTF (design §4) |
| `tariffs` | Trade & Tariffs | .15 | 0.6 tariff burden + 0.4 trade policy uncertainty (design §5) |
| `geopolitical` | Geopolitical Risk | .10 | Caldara-Iacoviello GPR; Claude register in shadow (design §6) |
| `freight` | Freight Volume | .10 | 0.5 BTS TSIFRGHT YoY + 0.5 weekly STB rail carloads+intermodal YoY, both anchored. IYT leaves the score. |
| `inputs` (new) | Input Costs | .10 | 0.5 regional Fed prices-paid composite + 0.25 copper + 0.25 aluminum (design §7) |
| `physical` (replaces `weather` in the composite) | Physical Disruption | .05 | 0.5 natural hazards near ports + 0.5 waterways (design §8) |

- The aggregation stays a weighted arithmetic mean, so the category table's "change × weight" stays exact. `CATEGORY_WEIGHTS` must sum to 1.0.
- **Freight** is described honestly on the site as a goods-moving / demand gauge, where a contraction is bad. Higher YoY scores higher, capped by the 100 anchor.
- **Industry profiles**, temporary until project 3: the baseline share of both semiconductor and aerospace is 0.60. Their baseline-category weights are the new baseline weights × 0.60 (supply_chain .12, chokepoints .09, energy .09, tariffs .09, geopolitical .06, freight .06, inputs .06, physical .03). The industry categories keep their current weights, which sum to 0.40.
- **Fallbacks.** When a category's provider fails, it uses its last stored real score while that score is within the category's max age, flagged stale. Beyond that the category is excluded from the composite: the remaining weights are renormalized explicitly in the aggregator (the engine still validates the sum) and the snapshot is flagged `degraded`. The hardcoded neutral 50/85 fallbacks and the unused `DEFAULT_FALLBACK_SCORES` are removed.

### 3. Chokepoints

- **Source:** PortWatch `Daily_Chokepoints_Data` (the endpoint already in `data/portwatch.py`).
- **Corridors and weights:** 8 corridors, weighted by PortWatch estimated tonnage over the baseline period. The weights are computed in `compute_anchors.py` and stored in the JSON. The corridors are Malacca, Taiwan Strait, Gibraltar, Hormuz, Dover, Red Sea, Bosporus and Panama.
- **Red Sea corridor:** the worse of Bab el-Mandeb and Suez.
- **Cape of Good Hope:** excluded from the score because more traffic there means rerouting. It is shown as context.
- **Baseline:** for each corridor, the same calendar month's average daily transits over Jan 2022–Oct 2023. Pre-2022 has a coverage break, and post-Oct-2023 is crisis-era.
- **Recent value:** the 7-day average of the latest available data. Its as-of date is the latest PortWatch date.
- **Per corridor:** s = min(1, (recent/normal) ÷ 0.90), so traffic down to 90% of normal is treated as noise.
- **Score:** 100 − 300 × Σ(weight × (1 − s)), clipped 0–100. This is the exact formula from the research backtest, `docs/superpowers/research/2026-10-22-artifacts/scripts/cp_backtest.py` (`agg_k`, k=3).
- **Backtest targets** from the research: calm 2022–23 ≈ 99, Ever Given ≈ 80, Red Sea 2024 ≈ 82, Hormuz Mar 2026 ≈ 48, 2026-10-18 ≈ 36. Small differences are fine, but a big deviation means a bug.
- **History** is real, recomputed from PortWatch daily data back to 2022.
- **Max age:** 14 days.

The existing chokepoint panel keeps working and shows the credit line.

### 4. Energy

- **Legs:**
  - Brent, 35%: FRED `DCOILBRENTEU`.
  - NY Harbor ULSD, 40%: FRED `DDFUELNYH`, back-filled before 2006 with `DHOILNYH` × 1.0824 for the anchor history only.
  - European gas (TTF), 25%: FRED IMF monthly `PNGASEUUSDM` for history. The builder confirms the series ID.
- **Live value per leg:** the last official spot × (live Yahoo futures ÷ futures close on that spot date), using BZ=F, HO=F and TTF=F, with TTF converted to $/MMBtu. This fixes today's bug of scoring futures against spot history. If Yahoo fails, the leg uses the official spot and the metadata says so.
- **Transform:** log of the CPI-real price, anchored (§1) on 1990+ history.
- **Spike penalty** for each leg: up to 15 points, linear between a +20% and a +82% 3-month real price rise. It is weighted like the legs and subtracted after anchoring.
- **Expected readings:** today about 20–30, ranking 2022 ≥ 2008 ≥ 2026 in severity, with a strong Hormuz reaction (Feb 27 → Mar 20 2026).
- **Max age:** 10 days for the official spot.
- **Hover detail:** crack spreads, the Brent–WTI spread and WTI are shown as context only.

### 5. Tariffs

- **Burden:** trailing 3-month US customs duties deposits from the Daily Treasury Statement (fiscaldata.treasury.gov, free API) ÷ trailing 3-month goods imports (FRED `BOPGIMP`).
  - Normal anchor: the pre-2018 median (about 1.84%).
  - Zero anchor: a cited historical reference (the research used 15%; the builder documents its source or picks a better cited one).
  - Deposits are gross of the IEEPA refunds, and the description says so.
  - Max age: 60 days.
- **TPU:** the Caldara et al. daily Trade Policy Uncertainty index, as a 30-day mean on a log scale.
  - Anchors come from the monthly TPU over 1985–2019. The builder verifies the daily and monthly scales are comparable before reusing anchors, or derives them from the daily file since 2015, documenting which.
  - Max age: 14 days.
- **Score:** 0.6 × burden score + 0.4 × TPU score.
- **Removed:** the EPUTRADE percentile and the VADER tariff nowcast (`tariff_news_nowcast.py`). EPUTRADE may stay as hover context.

### 6. Geopolitical

- **Scored now:** the Caldara-Iacoviello daily GPR (matteoiacoviello.com/gpr.htm), as a 30-day mean on a log scale.
  - Anchors from the monthly GPR 1985–2019. The zero anchor is the record monthly value.
  - Updated weekly. Max age: 14 days.
- **Removed from the score:**
  - the headline-severity sum (`_risk_score_from_alerts`)
  - the port-disruption blend (`blend_port_disruption`), whose role chokepoints now plays
  - all VADER use
- **Claude disruption register (shadow mode):**
  - Once a day Claude, with web search, maintains a persistent list of active supply-chain disruptions. It opens new events, updates existing ones, and closes an event only when evidence shows it has resolved.
  - Each event records: id, title, region, affected corridors/categories, severity 0–10, estimated share of world trade affected (with a basis), opened, last updated, closed, evidence URLs and rationale.
  - It is stored in a new DB table, `disruption_events`.
  - A register score (100 − f(open events)) is computed daily and stored under a non-weighted key, `geo_register`, in `daily_category_scores`.
  - Its weight inside geopolitical is `GEO_REGISTER_WEIGHT`, default **0.0**. Will turns it on (planned 0.5) after 2–3 weeks of comparison against PortWatch and GPR.
  - It follows the existing `data/llm.py` patterns: JSON schema output, clamped values, failure caching and a deterministic no-key path (the register is simply left unchanged).
- **Max age** for the register: 3 days.

### 7. Input costs (new)

- **Prices paid:** a composite of regional Fed manufacturing prices-paid indexes: Philadelphia and Empire on FRED, and Dallas and Kansas City from their published spreadsheets. It is the average of whichever are available for the month, and the builder confirms the series and URLs. If a spreadsheet fetch fails, the remaining surveys are used and the metadata lists the missing ones.
- **Copper and aluminum:**
  - History: FRED IMF monthly `PCOPPUSDM` and `PALUMUSDM`.
  - Live: Yahoo HG=F and ALI=F, scaled onto the last official value the same way as energy.
  - Transform: log of the CPI-real price.
- **Score:** 0.5 × prices paid + 0.25 × copper + 0.25 × aluminum, each anchored.
- **Context only, not scored:** supplier delivery times (they overlap GSCPI), shown in hover detail.
- **Max age:** 60 days for the surveys.

### 8. Physical disruption (replaces weather in the composite)

- **Hazards (half):** GDACS events API, Orange and Red alerts for tropical cyclones, floods, earthquakes and volcanoes.
  - An event counts when its alert geometry or a set radius around its center is within range of one of the 37 ports. The radius per hazard type is the builder's call, documented in config.
  - Penalty = alert level × the port's share of throughput (PortWatch port calls, computed offline into the anchors JSON).
  - Calibrate so a quiet month reads about 95 and a Red typhoon over a top-10 port reads about 50.
  - NHC is optional extra detail for US ports.
- **Waterways (half):**
  - Panama Canal Gatun Lake level (ACP daily CSV): 100 at or above 85 ft (full 50 ft draft), falling to 0 at the record low.
  - Mississippi at St. Louis (USGS daily): 100 above the low-water navigation threshold, falling to 0 at the record low. The builder cites the threshold source.
  - Kaub (Rhine) is collected daily into a new `gauge_readings` table but not scored until 1 year of history exists.
- **History:** real values are recomputed for as far back as GDACS and the gauges allow. Earlier days stay as gaps.
- **Max age:** 3 days.
- **The `weather` provider stays for the map only**, with two fixes:
  - precipitation uses the right unit: the feed sends 15-minute amounts, so use the daily or hourly total
  - wind uses gusts
  The `weather` key is not in `CATEGORY_WEIGHTS`, and old `weather` rows in the DB are left untouched.

### 9. News and Claude (display only)

- **VADER is removed entirely**, including the `vaderSentiment` dependency.
- **Claude scores news incrementally:** every `NEWS_AI_REFRESH_SECONDS` (default 6 h), and only articles it hasn't scored yet. Earlier severities and summaries are kept.
- **If a run fails**, the last Claude result stays up, flagged stale, for up to 7 days.
- **With no API key**, headlines show without a severity.
- **Topic tagging uses word-boundary matching**, so "port" no longer matches "report", "war" no longer matches "warehouse", and "duty" no longer matches "heavy-duty".
- **The daily score explanation (`generate_score_explanation`, `score_explanation`) is removed**, since no UI shows it. That cuts one paid call a day.

### 10. Map

- **Remove the fixed vulnerability penalty and `_REGION_PROFILES`.** They double-count and are hidden judgment.
- **Port score** = 60% composite + 40% local weather (or the composite alone if weather is missing), minus max(news penalty, AI port penalty), using the existing caps.
- **Fix port keywords:**
  - match on word boundaries ("oman" must not match "woman")
  - fix `ports_data.py:93`, which maps Casablanca to Port Said
  - remove the regional-keyword half-penalty that the docs describe but that doesn't exist

### 11. Data hygiene and transparency

- **Every category's metadata includes** `as_of` (date of the underlying data), `source`, `is_stale` (past its max age but within its hard limit) and `is_fallback`. Each category's max age is set in config.
- **`/api/v1/latest`** returns these per category plus `methodology_version: 2`.
- **`/health`** lists stale and fallback categories.
- **The category table** shows a "stale" suffix the same way it shows "fallback".
- **The disruptions list** uses one 0–100 impact scale: categories as (100 − score), news as severity × 10.
- **GSCPI** served past its max age (75 days) and the cached news payload are flagged instead of silently reused.
- **The `/docs` methodology page is rewritten** to match the new design exactly. It covers sources, anchors, weights, lags and credits (PortWatch, Caldara-Iacoviello, NY Fed, BTS, STB, the regional Feds, IMF, Treasury, GDACS, ACP and USGS). It removes the claims about a hover explanation and "25 newest".
- **Every other place the categories appear is updated:** newsletter, `/report`, CSV export, `CATEGORY_LABELS`, `CATEGORY_COLORS`, the readout and the category table.
- **`CLAUDE.md` is updated** at the end to describe the new system.

### 12. History rebuild

- **`scripts/rebuild_category_history.py`** recomputes the new-method daily scores for the last 92 days, for every category whose source series allows it. It also recomputes the composite (`daily_scores`) for dates where every weighted category has a value.
- **Default is a dry run** that writes a CSV and prints a diff against the stored rows. Writing needs an explicit `--write` flag.
- **It upserts and never deletes.**
- **Running it against production requires Will's explicit OK in chat**, after he has seen the dry-run CSV.
- **Afterwards**, refresh `data/fallback_snapshot_safe.json` with `scripts/refresh_fallback_snapshot.py`.

### 13. Freshness, partial inputs, dating (settled after the builder check)

**Age** is measured from the end of the period an observation covers: the last day of the month for monthly data, the week-ending date for weekly data, the day itself for daily data.

Each input has two limits in config:
- `stale_after_days`: past this, flag stale.
- `drop_after_days`: past this, treat the input as missing.

The single "max age" figures in §3–§8 are the `stale_after_days` values for the main input. Defaults:

| Input type | Stale after | Drop after |
|---|---|---|
| Daily | that figure | 3× it |
| Weekly | 14 days | 45 days |
| Monthly | 75 days | 150 days |
| TSIFRGHT | 120 days | 200 days (its normal lag is ~80–90 days) |

**Partial inputs.** If one input inside a multi-input category is missing:
- Drop it and renormalize the remaining input weights within the category.
- The category is stale if any input it uses is stale.
- The metadata lists each input with its as-of date and live/stale/missing status.
- The category counts as failed only when every input is missing. It then follows §2: last stored score while it is younger than the category's `drop_after_days`, otherwise excluded.
- Energy's monthly TTF fallback and the monthly metals fallback use the monthly limits.

**Dating in rebuilt history and the backtest.** A monthly or weekly value belongs to the day the site could have known it, using fixed per-series publication lags in config, so history matches live behaviour:

| Series | Lag (days after period end) |
|---|---|
| GSCPI | 5 |
| TSIFRGHT | 80 |
| Regional Fed surveys | 0 (released within the month) |
| IMF monthly commodities | 35 |
| DTS deposits | 1 |
| BOPGIMP | 35 |
| GPR daily | up to 7 (updated weekly; use the actual file) |

**Composite storage.** `daily_scores` and the dashboard snapshot are written only when no weighted category is excluded. Stale is fine; excluded is not. On degraded days the live site still shows the renormalized composite, flagged `degraded`, but the history keeps a gap.

**Rebuild order and safety.**
- Old-method rows under reused keys are overwritten for the last 92 days, which is everything the site displays.
- Before any write, the rebuild script exports the existing rows it will touch to `data/backups/category_scores_pre_v2_<date>.csv` (gitignored), so the old values are recoverable.
- The sequence: Will says "push it" → deploy → run the dry run against production (read-only) → Will reviews → `--write`. This keeps the mixed-method window to the minutes between deploy and write.
- Rows older than 92 days stay as they are (not displayed).

**Register score formula** (shadow, calibrated during the comparison period):
- penalty = 0.3 × Σ over open events of (severity 0–10 × estimated share of world trade affected, %), capped at 100
- register score = 100 − penalty

## Acceptance

- `python -m pytest tests/` passes, with `DATABASE_URL=` set.
- New pure-function tests cover:
  - `anchored_score`
  - chokepoint scoring, against fixture rows that reproduce the research backtest values
  - the energy live-scaling and spike penalty
  - the tariff burden
  - the GPR and TPU transforms
  - inputs
  - physical disruption
  - weight renormalization on fallback
  - word-boundary tagging
- A backtest script (`scripts/backtest_composite.py`) prints the new composite and each category at the research episodes, and today. It covers 2008, 2020-04, 2021-12, 2021-03 Ever Given, 2024 Red Sea, 2025-04 and 2026-03 Hormuz, wherever each category's history allows. The results are recorded in the plan's final report.
- A local preview (`GSC_DISABLE_BACKGROUND=1`) renders all 8 categories with sources, as-of dates and the credits.
- All work is committed locally, nothing is pushed, and the production DB is not written until Will approves the rebuild.

## Left to the builder

- The module and file layout for new providers (following `BaseProvider`).
- Exact series IDs and URLs where the research didn't pin them, with a check that each fetch works.
- GDACS proximity radii and the waterway thresholds, with a cited source for each.
- How to store the register prompt.
- The UI fit for 8 rows.
- Anything marked "builder's call" above.

## Judgment calls made by Claude (for Will to check)

- Normal = 80, not 75.
- Weights: .20 / .15 / .15 / .15 / .10 / .10 / .10 / .05.
- Freight is 50/50 between TSIFRGHT and rail.
- Tariffs are 60/40 burden/TPU. Energy legs are 35/40/25, with a spike cap of 15.
- Chokepoints: dead band at 90%, slope 3.
- The register runs in shadow mode at weight 0 first.
- Industry profiles get the baseline × 0.60 interim weights.
- Physical disruption weight is 0.05.
- News is re-scored by Claude every 6 h.
- The vulnerability penalty is removed from the map.
