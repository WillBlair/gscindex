# Sector Indexes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Semis and Aero profile blends with two independent sector indexes. Semis has 3 categories and Aero has 4. All come from official long-history sources scored on the v2 anchors, and each is shown on its own tab beside an unchanged Global tab.

**Architecture:** One `BaseProvider` per sector category, on the v2 helpers (`scoring/anchors.py`, `data/providers/readings.py`). A new `data/sources/boj.py` fetches Bank of Japan series. `config.SECTORS` defines the sectors. The aggregator runs sector providers in the same cycle with the v2 fallback and exclusion rules, but keeps them fully out of the global composite and global flags. It publishes a `sectors` snapshot block. The UI tabs read Global from `CATEGORY_WEIGHTS` and sectors from `SECTORS`.

**Tech Stack:** Python 3.13, pandas, Dash, requests. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-23-sector-indexes-design.md`. Research: `docs/superpowers/research/2026-10-23-industry-profiles-research.md` and `docs/superpowers/research/2026-10-23-industry-artifacts/`.

## Global Constraints

- **Environment:** run everything with `DATABASE_URL=` (empty) and `GSC_DISABLE_BACKGROUND=1`, using `venv/bin/python`. `tests/conftest.py` already blanks `DATABASE_URL`. Never touch the production DB. Never run `--write`.
- **Tests:** `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/<file> -v`. Tests never hit the network.
- **Commits:** commit after each task. Never push.
- **Global index unchanged:** `CATEGORY_WEIGHTS`, the global categories, the global anchors and global behavior stay as they are. Existing global anchor values in `data/score_anchors.json` must stay byte-identical. New keys are added only.
- **Scoring rule:** 100 = healthiest 5% of pre-2020 history, 80 = pre-2020 median, 0 = worst month through 2025, through `anchored_score`. Anchors are frozen. Never invent or backfill history.
- **Category keys:**
  - Semis: `semis_memory_prices`, `semis_logic_prices`, `semis_fab_utilization`.
  - Aero: `aero_throughput`, `aero_flow`, `aero_mill_prices`, `aero_forge_cast`.
- **Input keys:**
  - Semis: `boj_memory`, `boj_logic`, `fab_util_3344`.
  - Aero: `aero_caputl`, `aero_inv_ship`, `ppi_ti_mill`, `ppi_ni_mill`, `ppi_ti_forge`, `ppi_nonferrous_forge`, `ppi_steel_invest_cast`.
- **Freshness:** monthly inputs are `(75, 150)`. Sector category drop: 150 days.
- **BOJ credit, verbatim:** `This service uses the API provided by the 'Bank of Japan Time-Series Data Search.' The Bank of Japan does not guarantee the content of the service.` BOJ fetches are cached for 24 h.
- **Isolation:** sector categories never appear in the global `disruptions`, the top-level `/api/v1/latest` `categories`, the global `degraded` / `fallback_categories` / `stale_categories` / `excluded_categories`, or `/health` HTTP status.
- **Writing style:** user-facing text uses plain short sentences, no em dashes, and none of the tells in `/Users/williamcblair/.claude/taste/writing-tells.md`.

## Review Focus

1. **A BOJ response that is HTTP 200 but empty or reshaped** (wrong `SERIES_CODE`, missing `VALUES`, an error JSON). The input must count as missing and must never score 0 or 100. Pinned in Task 1.
2. **Fewer categories present than the coverage minimum,** today or on a past day. The readout must show "Not enough data" and the sparkline must show a gap, never a 1-category "index". Pinned in Task 5.
3. **A sector outage or a sector category below 70** must leave the global composite, `disruptions`, `degraded` and `/health` status unchanged. Pinned in Task 4.
4. **Old `chip_*` / `aero_metals|orders|production|ppi` rows** in the DB or an old disk snapshot must never feed a sector tab. Startup with an old snapshot must not crash. Pinned in Tasks 4 and 5.
5. **Aero flow at a near-zero shipments month** (division blow-up) must count as missing, not as an extreme score. Pinned in Task 2.

---

### Task 1: Sector config, BOJ source, Semis providers

**Files:**
- Create: `data/sources/boj.py`, `data/providers/semis.py`
- Modify: `config.py`, adding a "Sector indexes" section with `SECTORS`, `FRESHNESS` entries, `SECTOR_DROP_AFTER_DAYS`, `SECTOR_PROVIDER_TIMEOUT_SECONDS`, `BOJ_CREDIT`, `SEMIS_FRED_LOOKBACK_DAYS`, plus `CATEGORY_LABELS`/`CATEGORY_COLORS`/`INPUT_LABELS` for the 3 Semis keys
- Test: `tests/semis_test.py`

**Interfaces:**
- Produces: `config.SECTORS`:
  ```python
  {
    "semiconductor": {"label": "Semis", "title": "Semiconductor", "weights": {semis keys: 1/3 each}, "min_categories": 2},
    "aerospace":     {"label": "Aero",  "title": "Aerospace",     "weights": {aero keys: 1/4 each},  "min_categories": 3},
  }
  ```
  An import-time check asserts that each sector's weights sum to 1.
- Produces: `boj.parse_series(payload: dict, code: str) -> pd.Series`, a monthly series indexed by month start. It raises `ValueError` on a missing or empty series or a mismatched code.
- Produces: `boj.fetch_series(code: str) -> pd.Series`, cached 24 h under key `boj_<code>_v1`, stored as dates and values. Verify the BOJ API endpoint and its JSON shape with one real call per series. Record the exact URL in a module constant. The research call is in `docs/superpowers/research/2026-10-23-industry-artifacts/memory-alt/analyze.py` and the scratchpad `boj_data.json` shape.
- Produces: `semis.MemoryPricesProvider`, `semis.LogicPricesProvider`, `semis.FabUtilizationProvider`.
  - Each is a `BaseProvider` whose `category` is its sector key.
  - Inputs:
    - memory and logic: YoY % of BOJ `PRCG20_2500850005` and `PRCG20_2500850004`
    - fab utilization: FRED `CAPUTLG3344S` level %
  - Anchors come from `get_anchor(<input key>)`.
  - `as_of` = `min(period_end(month), today)`. History is dated at period end + `PUBLICATION_LAG_DAYS[...]` (BOJ 12, G.17 16) and filled forward within the drop window.
  - The metadata includes `BOJ_CREDIT` in the description of the two BOJ categories.

- [ ] **Step 1: Write the failing tests.**
  - `test_boj_parse_reshaped_raises`: a payload without `VALUES`, an error payload and a wrong code all raise `ValueError`.
  - `test_boj_parse_monthly_index`: a fixture copied from the scratchpad shape parses into a month-start index.
  - `test_memory_yoy_and_anchor`: with a monkeypatched anchor `{"transform":"identity","direction":"lower_better","best":-36.3,"normal":-11.8,"worst":57.4}`, YoY of +31.3 → ≈30.2 and YoY of −35.4 → ≈99.3.
  - `test_fab_util_lower_is_better`: a lower utilization gives a higher score.
  - `test_semis_empty_payload_counts_missing_and_raises`.
  - `test_sectors_config_weights`: `SECTORS["semiconductor"]["weights"]` sum to 1.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass,** then run the full suite.
- [ ] **Step 5: Commit.** Message: "Semis sector: BOJ memory and logic prices, Fed chip capacity utilization."

### Task 2: Aero providers

**Files:**
- Create: `data/providers/aero.py`
- Modify: `config.py` (labels, colors, input labels, `AERO_FRED_LOOKBACK_DAYS`)
- Test: `tests/aero_test.py`

**Interfaces:**
- Produces 4 providers:
  - `aero.ThroughputProvider`: `CAPUTLG3364T9S`, higher is better.
  - `aero.FlowProvider`: log(`ANAPTI` ÷ 3-month mean `ANAPVS`) in months, lower is better.
  - `aero.MillPricesProvider`: mean of the input scores for the titanium and nickel-alloy mill shape PPIs, YoY.
  - `aero.ForgeCastProvider`: mean of the input scores for titanium forgings, nonferrous forgings and steel investment castings PPIs, YoY.
- Series mapping: confirm from `docs/superpowers/research/2026-10-23-industry-artifacts/aero/compute_proposed.py` which of `WPU102504`/`WPU102505`/`PCU33211233211242`/`PCU332112332112`/`PCU3315123315120` is which. Verify each on FRED with one call.
- Within-category input blending uses `blend_inputs` with equal weights. History follows the publication lags (G.17 16, M3 35, PPI 15 days) and is filled forward within the drop window.
- **Flow guard:** if the 3-month mean of shipments is ≤ 0 or non-finite, the flow input is missing.

- [ ] **Step 1: Write the failing tests.**
  - `test_flow_ratio_and_direction`: inventories 47 and shipments [10, 10, 10] → log(4.7) months, which scores at the anchor's normal (80) given anchor normal = log(4.7).
  - `test_flow_zero_shipments_is_missing`.
  - `test_mill_prices_mean_of_inputs`.
  - `test_forge_cast_one_input_missing_renormalizes`.
  - `test_aero_reference_today`: use the research `proposed_scores_monthly.csv` latest row values as literals (copy the numbers into the test). With the research anchors from `aero/proposed_anchors.json` monkeypatched, the four categories reproduce 80.0 / 76.2 / 74.3 / 37.3 within ±0.5.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass,** then run the full suite.
- [ ] **Step 5: Commit.** Message: "Aero sector: throughput, delivery flow, mill prices, forgings and castings."

### Task 3: Sector anchors

**Files:**
- Modify: `scripts/compute_anchors.py`, `data/score_anchors.json` (keys added only)
- Test: `tests/compute_anchors_test.py`

**Interfaces:**
- Adds every input key from the Global Constraints list to `SCORE_ANCHORS["inputs"]`, built with `compute_input_anchor` on exactly the quantity each provider scores. The provider and source functions are reused.
- Baselines:
  - BOJ: 2001–2019.
  - G.17 and PPI: pre-2020 span, per the research (`semis/candidate_anchors.json`, `aero/proposed_anchors.json`).
  - Worst: through 2025.
- Add a `--sectors-only` mode that merges the sector keys into the existing JSON without recomputing global keys. Use it.

- [ ] **Step 1: Write the failing test.** `test_sectors_only_merge_keeps_global_keys_identical`: on a temp JSON with dummy global keys, the merge leaves them byte-identical and adds the sector keys.
- [ ] **Step 2: Run the test and confirm it fails.**
- [ ] **Step 3: Implement.** Then run `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/compute_anchors.py --sectors-only`.
- [ ] **Step 4: Verify the output.**
  - `git diff data/score_anchors.json` shows additions only.
  - The printed today scores are close to the research: memory ≈0, logic ≈66, fab ≈85, throughput ≈80, flow ≈76, mill ≈74, forge/cast ≈37.
  - Investigate anything more than 10 points off.
- [ ] **Step 5: Commit.** Message: "Sector anchors (added keys only)."

### Task 4: Aggregator, snapshot and isolation; remove old industry adapters

**Files:**
- Modify: `data/aggregator.py`, `config.py` (remove `INDUSTRY_PROFILES` industry parts, `INDUSTRY_PROVIDER_CACHE_TTL` and `SILICON_ANALYSTS_API_KEY` usage)
- Delete: `data/providers/silicon_analysts.py`, `data/providers/aerospace.py`, `tests/industry_profiles_test.py` (replace with new tests)
- Test: `tests/sectors_aggregator_test.py`

**Interfaces:**
- **Providers:** `_PROVIDERS` = the 8 global providers plus the 7 sector providers. Remove the `additional_scores` / `additional_history` unpacking.
- **Fallback, per sector category, same rules as global:**
  - A fetch failure uses the last stored score within `SECTOR_DROP_AFTER_DAYS` (flagged fallback and stale).
  - `InputsExpired` or too old means excluded.
  - Timeouts come from `SECTOR_PROVIDER_TIMEOUT_SECONDS`.
- **Snapshot:** `result["sectors"] = {sector: {"index": float|None, "tier": label|None, "coverage": n_present, "degraded": bool, "stale_categories": [...], "excluded_categories": [...], "fallback_categories": [...]}}`.
  - The index is the equal-weight mean of present categories, or None below `min_categories`.
  - Sector keys are absent from the global lists and from global `disruptions`.
- **History:** stored daily rows for sector categories are recorded through `record_daily_scores` with measured values only. The global composite is unaffected.
- **Old keys:** `chip_*`, `aero_metals`, `aero_orders`, `aero_production` and `aero_ppi` are never produced or read. `app.py` `_has_current_categories` must still accept a v2 global snapshot that lacks sector keys, and an old snapshot must not crash startup.

- [ ] **Step 1: Write the failing tests.**
  - `test_sector_outage_leaves_global_untouched`: global composite, `degraded`, `disruptions` and global lists are unchanged.
  - `test_sector_below_70_not_in_disruptions`.
  - `test_sector_index_mean_and_coverage`: 3 of 4 Aero gives the mean, 2 of 4 gives None.
  - `test_sector_stored_fallback_and_expiry`.
  - `test_no_old_industry_keys`.
  - `test_old_snapshot_startup_ok`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite** and fix the tests that asserted the old profiles.
- [ ] **Step 5: Run a live smoke test.** `DATABASE_URL= ANTHROPIC_API_KEY= venv/bin/python -c "from data.aggregator import aggregate_data; d=aggregate_data(); print(round(d['composite'],1), d['sectors'])"`. Expected: global ≈47, Semis ≈50, Aero ≈64.
- [ ] **Step 6: Commit.** Message: "Aggregator: independent sector indexes; remove Silicon Analysts and old aerospace adapters."

### Task 5: Tabs, readout, category table, sparkline gaps, CSV

**Files:**
- Modify: `components/terminal_data.py`, `components/terminal.py`, `components/layout.py`, `components/workspace.py`, `components/workspace_callbacks.py`, `assets/terminal.css` (only if needed)
- Test: `tests/terminal_data_test.py`, `tests/terminal_ui_test.py`, `tests/workspace_test.py`

**Interfaces:**
- **Tab keys:** `"global"` is the default and maps to `CATEGORY_WEIGHTS`. `"semiconductor"` and `"aerospace"` map to `SECTORS`. Keep the `profile-switch` and `profile-store` component ids. `persistence_type="session"` continues.
- **Tab labels:** Global / Semis / Aero.
- **`category_rows`, `index_summary`, `index_history`:**
  - For a sector, today's index = `data["sectors"][key]["index"]`.
  - Yesterday and past days = the equal-weight mean of the sector categories stored that day, or None below `min_categories`.
  - The effect column uses that sector's equal weights.
  - Global behavior is unchanged.
- **`sparkline_svg`:** None values split the path into segments, so a gap is drawn as a gap and is never joined. This applies to every tab.
- **CSV export:** follows the active tab. For sectors it includes `as_of`, status and inputs, and the BOJ terms note on Semis rows.
- **Other panes:** map, markets, headlines and briefing are unchanged on all tabs.

- [ ] **Step 1: Write the failing tests.**
  - `test_semis_tab_rows_only_semis`.
  - `test_aero_tab_index_from_snapshot_sectors`.
  - `test_sector_yesterday_needs_coverage`.
  - `test_sparkline_breaks_at_gaps`: the path has 2 segments around a None.
  - `test_global_tab_unchanged`: snapshot equality against current behavior.
  - `test_csv_semis_has_boj_terms`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass,** then run the full suite.
- [ ] **Step 5: Preview the site.**
  - Start the local gunicorn with `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 ANTHROPIC_API_KEY=` from a shell in the background, after a fresh SQLite smoke snapshot.
  - Screenshot all 3 tabs at desktop and at 375 px. Stop the server and reset the viewport.
- [ ] **Step 6: Commit.** Message: "Tabs: Global, Semis, Aero as separate indexes; sparkline draws gaps."

### Task 6: API, health, docs, CLAUDE.md, README, BOJ notice draft

**Files:**
- Modify: `api/routes.py`, `app.py` (`/health`), `api/docs.py`, `CLAUDE.md`, `README.md`
- Create: `docs/superpowers/plans/2026-10-23-boj-api-notice-email.md` (a draft for Will to send; do not send)
- Test: `tests/api_v2_test.py`, `tests/docs_page_test.py`

**Interfaces:**
- **`/api/v1/latest` adds `sectors`:** `{sector: {"index", "tier", "coverage", "degraded", "categories": {key: v2 category object}, "terms"}}`.
  - The Semis `terms` credits BOJ verbatim and states that commercial reuse of memory and logic scores requires the Bank of Japan's permission.
  - The Aero `terms` is CC-BY-4.0 with credit to the Federal Reserve, Census and BLS.
  - Top-level `categories` stays global-only.
- **`/health` adds:** `sectors: {sector: {"degraded", "coverage"}}`. The HTTP status logic is unchanged.
- **`/docs`:** a "Sector indexes" section covering:
  - why the indexes are separate
  - each category's source, transform, direction, anchors (read from config and the anchors file) and freshness
  - the coverage rule
  - limitations: a glut reads as healthy for chip prices; memory reads 0 above +57% YoY
  - credits: BOJ verbatim, Federal Reserve G.17, Census M3, BLS PPI

  Remove every Silicon Analysts and old aero text.
- **CLAUDE.md and README:** update the profiles, providers, env vars and Things That Will Break. Note that BOJ commercial-use permission is needed if the site is ever monetized.
- **Email draft:** to post.rsd17@boj.or.jp, subject "[Release of the service using the API]", from Will Blair. Body: the site URL, what is used (2 CGPI import price series, daily cached fetch), and the credit placement. Write it in the user's voice: plain, warm, "Hey" is not appropriate for a central bank, so use "Hello,". Sign off "Will Blair".

- [ ] **Step 1: Write the failing tests.**
  - `test_latest_has_sectors_and_global_categories_unchanged`.
  - `test_semis_terms_boj_verbatim`.
  - `test_health_sectors_block_and_status_unaffected`.
  - `test_docs_sector_section_and_no_silicon_analysts`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass,** then run the full suite.
- [ ] **Step 5: Commit.** Message: "API, health and docs for sector indexes; BOJ notice draft."

### Task 7: History rebuild and backtest for sectors

**Files:**
- Modify: `scripts/rebuild_category_history.py`, `scripts/backtest_composite.py`
- Test: `tests/rebuild_history_test.py`

**Interfaces:**
- **Rebuild:** covers the 7 sector categories alongside the 8 global ones, with the same safety rules: dry run by default, strict verified backup, `CONFIRM_PROD_REBUILD`, refusal on partial or empty history. No composite rows for sectors; sector indexes are computed from category rows.
- **Backtest:** prints both sector indexes (with the coverage rule) at:
  - Semis: 2021-06, 2021-12, 2022-06, 2023-03, 2024-06, and today.
  - Aero: 2019-06, 2020-06, 2022-06, 2023-09, 2024-10, and today.

- [ ] **Step 1: Write the failing tests.**
  - `test_rebuild_includes_sector_categories`.
  - `test_rebuild_sector_partial_refused`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backtest.** Targets:
  - Aero: 74.0 / 39.4 / 41.5 / 64.8 / 62.5 within ±3.
  - Semis memory: 2021-12 ≈30, 2023-03 ≈99.
- [ ] **Step 5: Run the SQLite dry run.**
- [ ] **Step 6: Commit.** Message: "Rebuild and backtest cover the sector indexes."

### Task 8: Final verification

- [ ] **Step 1: Full suite.** It must pass both with `DATABASE_URL=` and with `DATABASE_URL=postgresql://invalid.invalid/x`.
- [ ] **Step 2: Live smoke test.** Global ≈47, sectors present, no sector key in global lists.
- [ ] **Step 3: Preview.** All 3 tabs at desktop and at 375 px, plus `/docs`, `/api/v1/latest` and `/health`.
- [ ] **Step 4: Backtest output.**
- [ ] **Step 5: Status check.** `git status` is clean. Report local state only.
