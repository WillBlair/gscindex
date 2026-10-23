# Score rebuild: rulings made during the build (2026-10-22/23)

Every decision the build controller took on Will's behalf, in order. Each line: what was decided, why, and the cost if wrong.

- Ruling: T3 backtest test uses docs/superpowers/research/2026-10-22-artifacts/outputs/chokepoint_ratio_rows.json (row 2026-10-18 → k3 36.097) instead of out_recommended_daily.csv — the CSV has no ratio columns — costs nothing if wrong (test data only).
- Ruling: T14 also updates the aggregator call site to the new 3-tuple fetch_supply_chain_news return (not only imports) — required for the app to run — if wrong, a reviewer flags scope creep.
- Ruling: Work on local branch score-rebuild instead of a worktree, because the venv and .env live in this checkout — merging to main is left to the finish step.
- Ruling: NaN guard (anchored_score raises ValueError on non-finite; blend_inputs ignores non-finite scores) added in Task 2's dispatch — protects Review Focus 1 for every provider — costs a slightly wider Task 2 diff if wrong
- Ruling: InputReading normalizes non-finite score to score=None,status="missing" in __post_init__ (carried into Task 3 dispatch) — prevents NaN in metadata JSON — costs a tiny extra diff in Task 3 if wrong
- Ruling: Task 12 must emit chokepoint_baseline for all 10 series (8 corridors' components incl. BabM, Suez, Cape) — carried into Task 12 dispatch — else RedSea/Cape NaN
- Ruling: promoted Task 4 Minor "runtime pulls full FRED histories" to a fix — spec Constraints forbid decades of history at runtime — costs one extra fix round if wrong
- Ruling: Task 12 must emit brent/ulsd/ttf/ttf_monthly anchors in $/bbl, $/gal, $/MMBtu real terms plus cpi_reference{series,date,value} — carried to Task 12
- Ruling: fetch_fred_series cache key must include lookback_days (fred_<ID>_<days>d) so providers with different windows don't share a truncated cache — carried into Task 5 dispatch — costs a cold cache after deploy if wrong
- Ruling: tariff burden pairs customs deposits of month m+1 with imports of month m (deposits lag imports ~1 month; matches research's 0.996 fit to PWBM) — deviates from plan's same-month wording — costs a slightly different burden level if wrong
- Ruling: Task 12 must build tariff_burden and tpu anchors with data.sources.treasury.tariff_burden_series (shifted) and the 30-day mean TPU — carried to Task 12
- Ruling: GPR history uses the file's own dates (no PUBLICATION_LAG shift) — the file is the publication; shifting would post-date real observations — costs a few days of look-ahead realism if wrong
- Ruling: promoted Task 7 minors 1-3 (partial-update zeroing, duplicate opens, prompt escaping) to fixes — the shadow register's only value is accurate persisted data — costs one extra fix round if wrong
- Ruling: Task 17 brief must cover README.md, api/docs.py and CLAUDE.md stale category text — carried to Task 17
- Ruling: Task 12 fits rail anchors on rail.rail_yoy (2018-04..2019-12 pre-2020 window, ~90 weeks; document) — carried to Task 12
- Ruling: KC Fed prices-paid survey omitted; composite = Philly, Empire, Dallas — scraping HTML would break the "no scraping" constraint — costs a 3-survey instead of 4-survey composite
- Ruling: promoted Task 9 future-as_of, hover grammar, cpi_reference date guard to fixes — visible on site / crash — costs one extra fix round if wrong
- Ruling: Task 12 prices_paid_stats = {philly, empire, dallas: [mean, sd]} over 2004–2019 — carried to Task 12
- Ruling: Mississippi low-water threshold = St. Louis gauge historical 10th percentile from Task 12 (no citable Corps/USCG stage found) — costs a statistically rather than operationally defined threshold
- Ruling: keep Gatun Lake level as a score input pending Will's decision — ACP page asks written consent before redistribution — flag in final report; if Will says no, drop gatun and reweight physical
- Ruling: Task 13 must give the physical provider (GDACS up to ~83 s + 3 gauges serial) and freight (Socrata 120 s) a longer timeout or run off the hot path — carried to Task 13
- Ruling: Task 12 must emit SCORE_ANCHORS["waterways"] {gatun_record_low, mississippi_record_low, mississippi_threshold} and port_throughput_share, then recheck HAZARD_SCALE — carried to Task 12
- Ruling: rail_volume anchored on FRED BTS monthly RAILFRTCARLOADSD11+RAILFRTINTERMODALD11 combined YoY 2001–2019 (STB weekly history too short and centered on the 2019 rail recession); provider still scores weekly STB YoY (corr 0.953) — costs some weekly noise at the tails
- Ruling: prices_paid worst computed only over months where all three surveys report (avoids Philly-only 1974 record) — costs a less extreme zero point
- Ruling: HAZARD_RADIUS_KM["TC"] = 450 (judgment; a Red typhoon 358 km from Kaohsiung with gale winds within 80 km must register); HAZARD_SCALE recalibrated to 5000 against real port shares — costs over-penalizing when one storm spans two big ports
- Ruling: accepted freight 77.2 today — rail volume genuinely +5.8% YoY; research's 55–60 used TSIFRGHT alone
- Ruling: accepted IMF commodity baselines 1992–2019 (FRED IMF series start 1992) and tariff worst 19.8% (USITC 1933)
- Ruling: stored-fallback as_of shown as None with "stored <date>" text, and snapshot_composite rejects bool — carried into Task 16 (API exposes as_of) — costs nothing if wrong
- Ruling: accepted Task 14 deviations — topic regex adds no-hyphen-before + optional plural "s"; unmatched headlines tagged "other"; Claude category enum = the 8 site keys; snapshot key news_scoring carries the stale label
- Ruling: accepted app.py _has_current_categories (keeps snapshots with excluded categories) and committed .claude/launch.json
- Ruling: promoted Task 17 doc inaccuracies (TTF conversion, Kaub wording, Hormuz 61 comment, unused gpr/tpu lags) to fixes — public methodology must match code — costs one extra round if wrong
- Ruling: GeopoliticalProvider.fetch_history carries the last GPR value to today within FRESHNESS["gpr"] drop days — supersedes the Task 6 "never past file end" ruling; matches what the live score shows — costs nothing if wrong (real carried value)
- Ruling: promoted --write partial-fetch refusal, --days validation, backtest SQLite-only to fixes alongside the two Important backup findings — production safety — costs one round if wrong
- Final: parked — mixed case (one input fetch-fails while others aged out) excludes the category even if yesterday's stored row came from fresh data — Ruling: keep; errs toward never showing old data; Will can relax later — costs an occasional unnecessary exclusion
- Final: parked — Kaub marker set_cached outside try can fail Physical on a disk error — Ruling: real, low likelihood (atomic local write), follow-up — costs a Physical fallback on a disk failure
- Final: parked — Gatun Lake (ACP) redistribution consent — Ruling: Will decides before deploy; fallback = drop gatun from PHYSICAL_WEIGHTS

## Deferred minor items (triaged by the final review as safe to wait)

- Task 1: minor (deferred): transform_value/score_raw weak errors on bad input (log of <=0, missing "transform" key)
- Task 1: minor (deferred): blend_inputs KeyError for unweighted reading untested; period_end D/W/Dec/leap untested
- Task 2: minor (deferred): close_on 5-day lookback not asserted in test; no == boundary test; scale_live doesn't check official_value finiteness
- Task 3: minor (deferred): history dated data+4 may land after today (check aggregator reindex drops future dates in Task 13/18); baseline null month TypeError; RedSea NaN error message blames data; unused logger; epoch-ms date branch untested; weights keys/sum unchecked
- Task 4: minor (deferred): live-TTF spike ref uses quote_date−91d (≤5d shift); history CPI dated by obs month not publication (small look-ahead); no test for CPI failure / history missing anchor; double rounding; cpi_reference.date read unguarded; api/docs.py energy text stale (Task 17)
- Task 5: minor (deferred): DTS total-pages missing key stops paging silently; renamed 4th DTS category would understate a month; TPU rolling counts rows not days; missing-input reason not in metadata; CLAUDE.md tariffs text stale (Task 17)
- Task 6: minor (deferred): description/source built from "used" not weighted readings (unreachable at weight 0); tests/check_fred_gpr.py stale manual script; rolling counts rows; PUBLICATION_LAG_DAYS["gpr"] unused
- Task 7: minor (deferred): register collected before composite with 240 s wait (delays publish) — revisit in Task 13; AI_WEB_SEARCH=0 branch untested; cap-dropped event untested; DB load error→failure marker untested; same-day slug collision; duplicate matching merges same-region same-corridor events; no-key path reads DB each cycle
- Task 8: minor (deferred): one missing anchor blocks both freight inputs; Socrata 120 s timeout > 45 s provider timeout; lookback arg not asserted; off-grid week KeyError latent
- Task 9: minor (deferred): composite has no minimum survey count and steps when Dallas arrives; calc text states nominal weights; _missing/_safe_score/_monthly_daily duplicated with energy; energy monthly legs lack as_of clamp
- Task 10: minor (deferred): settled-chunk cache can miss last days after downtime; stl_stage cache key moves daily; ffill bridges gauge gaps; Kaub date local not UTC; weather precip_mm default 0; CLAUDE.md weather cache key example (Task 17)
- Task 11: minor (deferred): latest_published_gscpi dead code; WEI/BDRY context undated; context fetches serial inside provider timeout; "updated" now wall clock vs as_of data date; month-start key path untested
- Task 12: minor (deferred): waterway record lows/threshold not cut at 2025; weekly vs monthly rail spread unchecked; GPR "October 2001" hardcoded in text; worst month parsed from string; chokepoint baseline no dedupe; physical test monkeypatch.undo pattern; builder functions untested; FRED inputs lack URLs in sources
- Task 13: minor (deferred): drop limit measured from storage date not data age (decision for Will); routes stale comment (Task 16); deadlines include queue time; local vs UTC today; unused numpy import
- Task 14: minor (deferred): report re-called when only briefing fails; RSS outage resets claude_ok_at and scored_titles; api/docs.py/CLAUDE.md/README still mention VADER (Task 17); missing tests for full-run backdating and no-key→key transition; hash(title) nondeterministic
- Task 15: minor (deferred): "cristobal"/"balboa" keywords ambiguous (storm names); test name test_casablanca_maps_to_casablanca misleading; whitespace noise; weather batch failure swallowed → ports equal composite
- Task 16: minor (deferred): index_history past days not renormalized under exclusion (hist[-2] != yday); API/CSV weight nominal under exclusion (document in Task 17); launch.json gunicorn entry untested in runner; INVALIDATING CACHE log omits excluded
- Task 17: minor (deferred): CLAUDE.md internal en/em dashes; WORST_MONTHS hand-typed (test-pinned); new weighted category without docs card → 500 (add test); README still shows python app.py; newsletter has no category labels (nothing to change)
- Task 18: minor (deferred): provider returning empty/all-NaN history not flagged as failed (partial guard misses it); count check not atomic with upsert; run() library call with days=0; two upsert transactions; backtest COVID 2020-04 composite 69.8 (cost gauges read demand collapse as healthy — report to Will)
- Task 19: minor (deferred): CLAUDE.md says "source column" but sources/as-of live in hover tooltips; industry categories return as_of null / empty inputs in API while docs describe as_of per category
