# Sector indexes: Semis and Aero as separate tabs (project 3)

- **Date:** 2026-10-23
- **Status:** approved in chat. Will chose separate sector indexes as tabs, with Global staying the default view, and said "do what keeps the data defensible and accurate".
- **Research:** `docs/superpowers/research/2026-10-23-industry-profiles-research.md`. Scripts are in `docs/superpowers/research/2026-10-23-industry-artifacts/` (`aero/compute_proposed.py`, `semis/score_candidates.py`, `memory-alt/analyze.py`).
- **Global method this extends:** `docs/superpowers/specs/2026-10-22-score-rebuild-design.md`.

## Why

The Semis and Aero views are not defensible today.

- **The Semis inputs are estimates, and they don't move.**
  - The vendor builds them from press reports.
  - Fab utilization is stuck at 100 and scored in the wrong direction.
  - "Wafer prices" isn't a time series.
  - The license doesn't allow derived public dashboards.
  - Neutral 50s count as data.
  - As a result the Semis view reads 63.8 "Stable" while Global reads 46.9.
- **The Aero inputs are demand and contract signals, scored on rolling percentiles.**
  - Orders go negative when orders are cancelled.
  - The PPI follows contract escalation clauses.
  - Aluminum duplicates the global Input Costs category.
- **The current blend counts Asia twice.** It is 0.60 × Global plus 0.40 × sector, and GSCPI already includes the Taiwan and Korea PMIs.

## Goals

- **Two sector indexes, each independent of Global.** Semis and Aero are each built only from their own sector categories, the way S&P Global's sector PMIs are built only from their sector's responses.
- **Same methodology as the global categories.** Every sector input is a published, official, long-history series. It is scored through the same fixed anchors as v2: 100 = healthiest 5% of pre-2020 history, 80 = pre-2020 median, 0 = worst month on record through 2025. It uses the same freshness, fallback and exclusion rules, and nothing is invented.
- **UI:** Global stays the default tab and is unchanged. The Semis and Aero tabs show only their own index and categories.

## Non-goals

- Changing the global index or its categories.
- Blending sector signals into Global, or Global into the sectors.
- Lead-time data. No free periodic source exists.
- Korean data. Bank of Korea ECOS keys require Korean mobile-carrier identity verification, which Will cannot do.

## Anti-goals

- Vendor estimates or modelled data.
- Sources whose terms forbid derived public products.
- Neutral constants.
- Old `chip_*` and old `aero_*` history mixed into the new series.

## Constraints

These are the same as v2:

- Free sources only, with no accounts.
- All tunables in `config.py`. Anchors are generated offline into `data/score_anchors.json`.
- Develop with `DATABASE_URL=`.
- Commit locally. Push only when Will says "push it".

New constraints:

- **Bank of Japan API.**
  - Fetch at most once a day (24 h cache). The data is monthly, around the 10th business day. Do no heavy polling.
  - Credit verbatim on /docs: "This service uses the API provided by the 'Bank of Japan Time-Series Data Search.' The Bank of Japan does not guarantee the content of the service."
  - BOJ asks to be told about services built on its API. That email (post.rsd17@boj.or.jp, subject "[Release of the service using the API]") goes from Will. The builder drafts it into `docs/superpowers/plans/` and does not send it.
  - Commercial use (ads or a paid API) would need BOJ's permission in advance. Record this in CLAUDE.md.

## Design

### 1. Semis index: 3 categories, equal weight (1/3 each)

| Key | Label | Input (transform, direction) | Source |
|---|---|---|---|
| `semis_memory_prices` | Memory Chip Prices | BOJ CGPI import price index, MOS memory ICs, contract-currency basis, YoY % (lower is better) | BOJ API series `PRCG20_2500850005`, monthly from 2000-01 |
| `semis_logic_prices` | Logic Chip Prices | BOJ CGPI import price index, MOS logic ICs, contract-currency basis, YoY % (lower is better) | BOJ API series `PRCG20_2500850004` |
| `semis_fab_utilization` | Fab Utilization | Fed G.17 capacity utilization, semiconductors and electronic components, % (lower is better: spare capacity absorbs shocks) | FRED `CAPUTLG3344S`, from 1972 |

- **Baselines:**
  - BOJ series: 2001–2019. YoY needs 12 months, so the baseline starts in 2001.
  - G.17: the full span before 2020.
- **Expected readings today** (research):
  - Memory: about 0 (+316% YoY, a record).
  - Logic: about 66.
  - Fab utilization: about 85.
  - Index: about 50.
- **Reference readings:** 2021-12 shortage = memory 30, logic 48. 2023-03 glut = memory 99.
- **Disclosed limitation** (same as Energy): a price glut or demand collapse reads as healthy.
- **Builder checks:** confirm the BOJ series codes and API format live with one call, and record the exact request URL.

### 2. Aero index: 4 categories, equal weight (1/4 each)

All inputs are US government data, in the public domain.

| Key | Label | Input (transform, direction) | Source |
|---|---|---|---|
| `aero_throughput` | Aerospace Throughput | Capacity utilization, NAICS 3364-9, % (higher is better) | FRED `CAPUTLG3364T9S` |
| `aero_flow` | Delivery Flow | log(nondefense aircraft inventories ÷ 3-month mean shipments), months (lower is better) | FRED `ANAPTI` ÷ `ANAPVS` (Census M3) |
| `aero_mill_prices` | Titanium & Nickel Alloy Prices | Mean of the input scores for titanium mill shapes and nickel-alloy mill shapes PPI, YoY % (lower is better) | FRED `WPU102504`, `WPU102505` (builder confirms which is which) |
| `aero_forge_cast` | Forgings & Castings Prices | Mean of the input scores for titanium forgings, nonferrous forgings and steel investment castings PPI, YoY % (lower is better) | FRED `PCU33211233211242`, `PCU332112332112`, `PCU3315123315120` (builder confirms) |

- **Reference implementation:** `docs/superpowers/research/2026-10-23-industry-artifacts/aero/compute_proposed.py`. Its anchors are in `aero/proposed_anchors.json`. Reproduce them through `scripts/compute_anchors.py`.
- **Expected readings today:**

  | Category | Score |
  |---|---|
  | Throughput | 80 |
  | Flow | 76 |
  | Mill prices | 74 |
  | Forge/cast | 37 |
  | **Index** | **about 64** |

- **Backtest targets:**

  | Episode | Index |
  |---|---|
  | 2019-06 (737 MAX) | 74.0 |
  | 2020-06 | 39.4 |
  | 2022-06 | 41.5 |
  | 2023-09 | 64.8 |
  | 2024-10 (strike) | 62.5 |

- **Backlog is not scored.** It is ambiguous: high backlog means strong demand and also constrained supply. It may appear in the throughput hover as context.

### 3. Sector index rules

- **Index = equal-weight mean of the categories that have a measured or stale score.**
  - Categories that are excluded or missing don't count.
  - A stored fallback counts and is flagged.
- **Coverage rule:** the index shows a number only when at least 2 of 3 (Semis) or 3 of 4 (Aero) categories are present. Otherwise the readout shows "Not enough data" (judgment call).
- **Past days follow the same rules** (mean of the present categories plus the coverage rule). This applies to both "yesterday" and the sparkline history.
- **Category and input freshness:** monthly limits are stale after 75 days and dropped after 150. Ages are counted from period end, as in v2.
- **Fallback behavior is the v2 aggregator behavior:**
  - A fetch failure uses the last stored score within the drop window, flagged stale and fallback.
  - Expired inputs exclude the category immediately.
  - There is never a neutral 50.
- **Sector problems don't touch Global.** They do not set the global `degraded` flag or appear in global `fallback_categories` or `stale_categories`. Each sector has its own `degraded`, `stale_categories` and `excluded_categories` under its sector block.
- **Sector providers have their own timeouts** in config and run in the same refresh cycle. Any provider that does more than one network call keeps its total time under its timeout.

### 4. Code changes (builder decides the layout, following v2 patterns)

- **Remove** `data/providers/silicon_analysts.py`, `data/providers/aerospace.py`, their config (`INDUSTRY_PROVIDER_CACHE_TTL` if unused, `SILICON_ANALYSTS_API_KEY`) and their tests.
- **Config:**
  - Add `SECTORS` with `semiconductor` and `aerospace`, each with a label, tab label, its category keys and equal weights, and coverage minimums.
  - Replace `INDUSTRY_PROFILES` (keep the name only if callers need it) so that tabs map to: Global (`CATEGORY_WEIGHTS`), Semis (`SECTORS["semiconductor"]`) and Aero (`SECTORS["aerospace"]`).
- **New providers** (one per sector, or one per category; builder's call) subclass `BaseProvider`, use `readings`/`anchors`, and produce the v2 metadata (`as_of`, `is_stale`, `inputs`).
  - New source module: `data/sources/boj.py`, with a pure parser and a fetcher on a 24 h cache.
  - FRED series use `fetch_fred_series` with a trimmed runtime lookback and `fetch_fred_full` offline.
- **Snapshot:**
  - `current_scores` and `category_metadata` include the sector categories.
  - New `sectors: {semiconductor: {index, tier, coverage, degraded, stale_categories, excluded_categories}, aerospace: {...}}`.
  - Global keys are unchanged.
- **UI (Terminal look, unchanged style):**
  - The existing profile switch becomes the tabs: Global / Semis / Aero, with Global the default.
  - On Semis or Aero, the readout and category table show only that sector's index and categories, with equal weights and the effect column computed with those weights.
  - The map, markets, headlines and briefing panes stay as they are on every tab.
  - The sparkline draws real gaps (no line across missing days) on every tab.
- **API:** `/api/v1/latest` adds the `sectors` block, with each sector's categories as v2 category objects. `/health` adds per-sector `degraded`. The CSV export follows the active tab.
- **Docs:**
  - `/docs` gets a Sector indexes section: what each category measures, sources, transforms, anchors from config, coverage rule, limitations, and credits (BOJ verbatim line, Federal Reserve G.17, Census M3, BLS PPI).
  - Remove every Silicon Analysts mention.
  - Update CLAUDE.md and README.
- **Anchors:** `scripts/compute_anchors.py` gains the 7 new sector inputs and their aero sub-inputs. Regenerate only by adding keys. Existing global anchor values must stay byte-identical (verify with git diff).
- **History:**
  - New keys mean no mixing with old rows.
  - `scripts/rebuild_category_history.py` gains the sector categories, with the same safety rules: dry run by default, verified backup, `CONFIRM_PROD_REBUILD`.
  - Old `chip_*`, `aero_metals`, `aero_orders`, `aero_production` and `aero_ppi` rows stay in the database untouched and are no longer read.
  - `scripts/backtest_composite.py` prints both sector indexes at the episodes above.

### 5. Acceptance

- The full suite passes with `DATABASE_URL=`.
- New tests cover:
  - the BOJ parser
  - each sector provider, including empty or reshaped payloads that must raise
  - the coverage rule
  - sector isolation from global degraded and fallback
  - tabs rendering only their categories
  - API sector blocks
  - sparkline gaps
- The backtest reproduces the research targets within about ±3 points (Aero episodes above; Semis memory 2021-12 ≈ 30, 2023-03 ≈ 99).
- A local preview shows all three tabs at desktop and at 375 px.
- A production dry run of the rebuild completes before any write. The write happens after Will's "push it" (he approved the write workflow for v2; repeat the dry-run summary to him).

## Judgment calls (Will can override)

- Semis has 3 categories, not 4 (no defensible fourth). All categories within a sector have equal weight.
- Coverage minimums are 2 of 3 and 3 of 4.
- Semis uses BOJ import prices (contract-currency basis) rather than Korean export prices.
- Fab utilization treats lower as better (spare capacity).
- Aero uses the PPI's YoY change rather than real price levels (real levels missed the 2022–23 squeeze).
- The non-global panes stay the same on every tab.
