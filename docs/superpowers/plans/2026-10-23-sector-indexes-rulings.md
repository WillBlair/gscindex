# Sector indexes: rulings made during the build (2026-10-23)

Every decision the build controller made for Will, in order. Each line gives what was decided, why, and the cost if wrong.

- Ruling: T4 leaves INDUSTRY_PROFILES in config untouched (only removes the old adapters and their unpacking); T5 replaces INDUSTRY_PROFILES/DEFAULT_PROFILE usage with the tab model and deletes it — keeps the UI importable between tasks — costs a brief window where Semis/Aero tabs show blank rows on the branch
- Ruling: build on local branch sector-indexes in this checkout (venv/.env live here)
- Ruling: promoted Task 1 minors (BOJ NEXTPOSITION guard, fab utilization weak-demand caveat) alongside the Important helper dedup — fail-closed data + honest public text — costs one extra round if wrong
- Ruling: Task 3 maps research anchor names (cu_aero, inv_ship, ti_mill_yoy, ni_mill_yoy, ti_forg_yoy, nf_forg_yoy, inv_cast_yoy) to runtime keys (aero_caputl, aero_inv_ship, ppi_ti_mill, ppi_ni_mill, ppi_ti_forge, ppi_nonferrous_forge, ppi_steel_invest_cast) — carried to Task 3
- Ruling: aero_caputl and fab_util_3344 G.17 history counted from 1972 (CAPUTLG3344S start; 1948–50 postwar period not comparable; full-history worst would be 1950-03 and break the backtests) — documented in worst_basis — costs a slightly less extreme zero point
- Ruling: ppi_ni_mill / ppi_ti_forge anchors use the providers' date-based YoY (research used positional YoY across gaps) — anchors on the scored quantity per spec — costs tiny anchor differences vs research
- Ruling: accepted config.RETIRED_CATEGORIES + daily_history filter + app._migrate_keys stripping (review focus 4)
- Ruling: promoted Task 4 minors to fixes — old-snapshot disruptions/degraded cleanup, separate 2-worker sector executor (structural isolation per spec), cold-start timing check — costs one round if wrong
- Ruling: Task 5 must read sector fallback/stale/excluded state from snapshot["sectors"] / category metadata (category_rows reads only global lists today), replace INDUSTRY_PROFILES, update test_weights_sum_and_profiles — carried to Task 5
- Ruling: Task 6 must filter sector categories out of /api/v1/latest top-level categories, document _SECTOR_TASKS and remove Silicon Analysts / INDUSTRY_PROVIDER_CACHE_TTL / additional_scores mentions in CLAUDE.md and README — carried to Task 6
- Ruling: promoted Task 5 minors — BOJ credit only on BOJ rows, PortWatch fixture key revert, sector change only when the same category set is present both days, hide tier/change below coverage — accuracy of public numbers/credits — costs one round if wrong
- Ruling: promoted Task 6 minors — BOJ 6 h failure cache + shared fetch (makes the "about once a day" claim to BOJ true), dated memory example, one BOJ_COMMERCIAL_NOTE constant, retired labels removed — costs one round if wrong
- Ruling: Task 7 must update CLAUDE.md/README lines describing rebuild/backtest as global-only — carried to Task 7
- Ruling: promoted Task 7 minors (lag keys derived from providers, numeric/date-specific test assertions) with the Important collect/render dedup — costs one round if wrong
- Final: parked — a hung sector job can still delay snapshot publication up to 120 s (values/flags/health unaffected) and two comments ("never delay Global") overclaim — Ruling: accept; publishing sectors separately is a later change — costs up to 120 s later Global refresh when a sector source hangs
- Final: parked — spec text predates --sectors-only — Ruling: CLAUDE.md/README document it; spec is historical

## Deferred minor items (triaged by the final review as safe to wait)

- Task 1: minor (deferred): BOJ no stale-cache fallback (aggregator stored fallback covers it); cache round-trip untested through real data.cache; QUARTERLY test payload literal; SEMIS_FRED_LOOKBACK_DAYS annotation; inputs.py continuation alignment; boj docstring line length
- Task 2: minor (deferred): aero/semis provider structure repeats (shared base later); bare except turns code errors into "missing"; July assertion at rounding tolerance boundary
- Task 3: minor (deferred): build_sectors/_sector_measures untested offline; print_sectors mutates config.SCORE_ANCHORS; memory pinned at 0 above +57% YoY (by design, disclose in Task 6)
- Task 4: minor (deferred): two hung sector jobs can starve the other sector categories (they fall back; isolated from Global); no direct sector-timeout test; one cold timing sample
- Task 5: minor (deferred): Global CSV profile label "Baseline (Global)" kept for byte-identical export; CSS pinned by exact string test
- Task 6: minor (deferred): disk-cache hit re-stamps memory time (series can be ~48 h old; monthly data, harmless); API modal doesn't mention sectors; docs test name overstates check
