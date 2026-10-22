# Terminal Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the gscindex Dash UI to match the chosen "Terminal" mockup, backed by stored daily scores so every number reconciles.

**Architecture:** A pure data module computes per-profile rows, yesterday comparisons and index history from the snapshot; a new `components/terminal.py` builds every pane from those views; `components/layout.py` and `components/workspace_callbacks.py` are rewritten to assemble and refresh the terminal grid; one new stylesheet replaces the old one. The background refresh loads stored daily scores into the snapshot so callbacks never query the database.

**Tech Stack:** Python 3.13, Dash 4.4, dash-bootstrap-components 2.0 (Tooltip, Popover, Modal), Plotly 7.1, pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-terminal-redesign-design.md`. Visual reference: `docs/superpowers/specs/terminal-draft/e-terminal.html` (serve the folder with `python3 -m http.server 8765`; `common.js` holds the reference math).

## Global Constraints

- Colors: background `#000000`, panes `#07090C`, rules `#1D232B`, text `#F2F4F7`, dim `#8A94A3`, amber `#FFB020`; site tier colors Healthy `#35D07F`, Stable `#F5C542`, Stressed `#FF8A3D`, Critical `#FF4D5E`. Tier colors are UI-only: do not edit `config.HEALTH_TIERS` or `config.COLORS`.
- Fonts: JetBrains Mono (numbers, labels, tables, chrome) and Inter (headlines, briefing prose), from Google Fonts. Remove Satoshi and IBM Plex.
- One continuous grid of panes split by 1px rules, square corners, no shadows, no gradients, no colored left-border callouts.
- Remove: Refresh button, Overview/News/Docs scroll tabs, profile dropdown, "0 to 100, higher is healthier" text, Generate briefing button, "Main pressures" block, category details modal, footer "Email updates" button, the multi-line category trend chart.
- "Yesterday" is the previous calendar date only; a missing value renders as "–" and blanks change/effect; never reach back further.
- The Index row must equal the weighted sum of the rows shown for the selected profile.
- Callbacks read `_DATA_CACHE` via `get_snapshot()` only; no DB, provider or Claude calls in callbacks.
- Local preview: `GSC_DISABLE_BACKGROUND=1 ./venv/bin/gunicorn -b 127.0.0.1:8050 --threads 4 app:server` (local `.env` points at production Neon; never run `python app.py`).
- Tests: `./venv/bin/python -m pytest -q tests/ -p no:cacheprovider` must pass at the end of every task. Commit per task; do not push.

## Review Focus

- A category with no stored row for yesterday (fallback day, or a chip/aero provider that failed): its row shows dashes and the Index change shows a dash, no exception, no zero.
- Profile switch while yesterday is complete for baseline but not for Semis: Semis shows dashes, baseline still shows numbers.
- A snapshot from before this change (no `daily_history` key, e.g. loaded from the DB snapshot or the committed fallback file): page renders with dashes and empty sparklines, not a crash.
- Very long headline titles and source names on a 375px phone: no horizontal page scroll.
- Fallback categories: visibly flagged in the category table (dim row, "fallback" in the source column), never presented as measured.

---

### Task 1: Stored daily history in the snapshot

**Files:**
- Modify: `data/database.py` (add function at end)
- Modify: `data/aggregator.py` (add `daily_history` to the result dict built near the end of `aggregate_data`)
- Test: `tests/terminal_data_test.py` (new)

**Interfaces:**
- Produces: `get_daily_category_scores(days: int) -> dict` in `data/database.py`, returning `{"dates": ["YYYY-MM-DD", ...ascending], "scores": {category: [float | None, ...aligned to dates]}}` covering the last `days` calendar days through today; empty `{"dates": [], "scores": {}}` when no DB or on error.
- Produces: snapshot key `daily_history` with that shape (days=91), set in `aggregate_data`'s result. JSON-safe as-is.

- [ ] **Step 1: Write failing tests** in `tests/terminal_data_test.py` using a temporary SQLite DB (monkeypatch `data.database._resolve_db_config` to return `("sqlite", None)` and `data.database.SQLITE_PATH` to a tmp file, call `init_db()`, insert rows into `daily_category_scores`):
  - `test_daily_scores_align_and_mark_missing_days`: rows for `energy` on D-2 and D-0 only → `result["scores"]["energy"][-2] is None`, `[-1]` and `[-3]` are the inserted floats, `len(result["dates"]) == len(result["scores"]["energy"])`.
  - `test_daily_scores_empty_without_db`: `_resolve_db_config` returns `("none", None)` → `{"dates": [], "scores": {}}`.
- [ ] **Step 2: Run** `./venv/bin/python -m pytest -q tests/terminal_data_test.py -p no:cacheprovider` → FAIL (function missing).
- [ ] **Step 3: Implement** `get_daily_category_scores(days)` (one query over `daily_category_scores` for `date >= today - days`, both postgres and sqlite placeholders, build the date axis with Python `date` arithmetic so missing days are present as `None`). In `aggregate_data`, add `"daily_history": get_daily_category_scores(91)` to `result`, wrapped so an exception yields the empty shape.
- [ ] **Step 4: Run** the same command → PASS; then the full suite → PASS.
- [ ] **Step 5: Commit** `git add data/database.py data/aggregator.py tests/terminal_data_test.py && git commit -m "Load stored daily category scores into the snapshot"`

### Task 2: Terminal view math

**Files:**
- Create: `components/terminal_data.py`
- Test: `tests/terminal_data_test.py` (extend)

**Interfaces:**
- Consumes: snapshot dict with `current_scores`, `category_metadata`, `fallback_categories`, `daily_history` (Task 1), `config.INDUSTRY_PROFILES`, `config.CATEGORY_LABELS`, `config.HEALTH_TIERS` (thresholds only).
- Produces (all pure, no Dash imports):
  - `TIER_COLORS: dict[str, str]` = the four site tier colors from Global Constraints.
  - `tier_for(score: float) -> dict` → `{"label": str, "color": str}` using `HEALTH_TIERS` thresholds and `TIER_COLORS`.
  - `category_rows(data: dict, profile_key: str) -> list[dict]` sorted by weight descending; each row: `cat, label, weight, today, yday (float|None), change (float|None), effect (float|None), history (list[float|None], last 30 days, today's point = live score), is_fallback (bool), source, raw_value, raw_label, updated, description, calculation`.
  - `index_summary(data: dict, profile_key: str) -> dict` → `today, yday (float|None), change (float|None), tier (dict from tier_for)`.
  - `index_history(data: dict, profile_key: str, days: int) -> list[float|None]` (days in {7, 30, 90}; a day is None unless every profile category has a stored score; last point = live index).

- [ ] **Step 1: Write failing tests** with a hand-built snapshot (two dates: yesterday and today, baseline categories):
  - `test_index_row_equals_weighted_rows`: `index_summary(...)["today"] == pytest.approx(sum(r["weight"] * r["today"] for r in category_rows(...)))`, same for `yday`, and `change == today - yday`.
  - `test_missing_yesterday_blanks_row_and_index_change`: remove `tariffs` yesterday value → that row's `yday`, `change`, `effect` are `None`; `index_summary(...)["yday"] is None` and `["change"] is None`; other rows still numeric.
  - `test_profiles_use_their_own_weights`: semiconductor rows' weights equal `INDUSTRY_PROFILES["semiconductor"]["weights"]`.
  - `test_snapshot_without_daily_history_renders_dashes`: snapshot lacking `daily_history` → every `yday is None`, every history is `[None]*29 + [today]`.
  - `test_fallback_flag`: category listed in `fallback_categories` → `is_fallback is True`.
  - `test_tier_colors_are_ui_only`: `tier_for(85)["color"] == "#35D07F"` and `config.HEALTH_TIERS[0]["color"]` unchanged from its current value.
- [ ] **Step 2: Run** `./venv/bin/python -m pytest -q tests/terminal_data_test.py -p no:cacheprovider` → FAIL (module missing).
- [ ] **Step 3: Implement** `components/terminal_data.py`. Today's date is the UTC date of the snapshot's `last_updated_utc`; yesterday is the `daily_history` value at exactly today minus one day, else `None`.
- [ ] **Step 4: Run** → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `git commit -m "Add terminal view math: rows, yesterday, index history"`

### Task 3: News relevance fix

**Files:**
- Modify: `data/providers/geopolitical.py` (`_IRRELEVANT_TERMS`)
- Modify: `data/ai_analyst.py` (`SYSTEM_PROMPT` relevance rules)
- Test: `tests/score_integrity_test.py` (extend)

- [ ] **Step 1: Write failing tests:** `test_hobby_and_collectible_stories_are_irrelevant`: `_is_irrelevant_article("el nino delays magic: the gathering trading cards")` is True, and so is `"pokemon cards sell out"`; `_is_irrelevant_article("port strike halts container terminal")` is False. `test_analysis_prompt_rules_out_consumer_product_delays`: `"consumer product" in SYSTEM_PROMPT.lower()`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** add terms `"trading card", "magic: the gathering", "pokemon", "collectible", "board game", "video game", "toy"` to `_IRRELEVANT_TERMS`; add to the IRRELEVANT rule in `SYSTEM_PROMPT`: "Consumer product shortages, launches or delivery delays (games, toys, collectibles, gadgets) unless the story names a port, carrier, chokepoint or trade policy." Bump `NEWS_BRIEFING_CACHE_KEY` in `config.py` to `newsapi_briefing_v18`.
- [ ] **Step 4: Run** → PASS; full suite → PASS.
- [ ] **Step 5: Commit** `git commit -m "Keep consumer product stories out of supply chain news"`

### Task 4: Terminal panes

**Files:**
- Create: `components/terminal.py`
- Modify: `components/charts.py` (`build_world_map` colors only)
- Test: `tests/terminal_ui_test.py` (new)

**Interfaces:**
- Consumes: Task 2 functions; existing `components.charts._port_hover_text`, `components.workspace.plain_text`, `safe_url`, `select_news`.
- Produces (each returns a Dash component; ids are fixed because Task 5 wires callbacks to them):
  - `build_header(updated_label: str) -> html.Header` with `dcc.RadioItems(id="profile-switch")` (options Global/Semis/Aero → baseline/semiconductor/aerospace), `html.Span(id="updated-label")`, links Methodology (`/docs`), API (`html.Button(id="api-btn")`), CSV (`html.Button(id="export-btn")`), Subscribe (`html.Button(id="newsletter-btn")`) plus `dbc.Popover(target="newsletter-btn", trigger="legacy", id="newsletter-popover")` containing `dcc.Input(id="newsletter-email", type="email")`, `html.Button(id="newsletter-submit")`, `html.Div(id="newsletter-feedback")`.
  - `build_readout(data, profile_key, days=30) -> html.Section` (children of `id="readout"`; includes `dcc.RadioItems(id="trend-range", options 7/30/90)` that persists across re-renders by living outside the replaced children; put the RadioItems in the layout, not in this builder).
  - `build_quotes(market_data: dict) -> html.Div`.
  - `build_headlines(alerts: list[dict]) -> html.Table` (columns Sev, Category, Headline link, Source, Age; HIGH/MED/LOW labels colored by severity; source strips " (web search)").
  - `build_briefing(briefing: str) -> html.Div` with a "Read full report" link to `/report`.
  - `build_category_table(data, profile_key) -> html.Table` with one row per `category_rows` entry plus an Index row; each row label is `html.Button(id=f"cat-detail-{cat}", className="cat-name")` with a `dbc.Tooltip(target=f"cat-detail-{cat}", trigger="hover focus")` showing source, raw value and label, updated, description, calculation; fallback rows get class `is-fallback` and "fallback" appended to the source cell; missing numbers render as "–".
  - `build_world_map(markers)` keeps all hover text and marker sizing logic; only colors change to the Global Constraints palette (land `#151B22`, ocean `#07090C`, borders `#1E252E`, tier colors from `TIER_COLORS`).

- [ ] **Step 1: Write failing tests** in `tests/terminal_ui_test.py` (walk component trees with a small helper that collects text and ids):
  - `test_header_has_one_button_and_no_removed_controls`: ids `profile-switch`, `updated-label`, `api-btn`, `export-btn`, `newsletter-btn`, `newsletter-popover` present; ids `refresh-btn`, `profile-selector` absent; text "higher is healthier" absent.
  - `test_category_table_index_row_matches_summary`: last row's today text equals `f"{index_summary(...)['today']:.1f}"`.
  - `test_missing_yesterday_shows_dash`: snapshot without `daily_history` → the table text contains "–" and no "0.0" in the change column.
  - `test_every_category_row_has_hover_detail`: for each row cat, a `dbc.Tooltip` with `target == f"cat-detail-{cat}"` exists and its text contains the metadata source.
  - `test_headlines_link_out_and_strip_web_search_label`: source "Reuters (web search)" renders "Reuters"; unsafe URL (`javascript:`) renders no link.
  - `test_map_keeps_port_hover_text`: existing hover strings from `tests/workspace_test.py` still appear in `build_world_map(...)` trace text.
- [ ] **Step 2: Run** `./venv/bin/python -m pytest -q tests/terminal_ui_test.py -p no:cacheprovider` → FAIL.
- [ ] **Step 3: Implement** `components/terminal.py` and the map color change, matching the reference HTML's structure and class names (`pane`, `ttl`, `num`, etc.).
- [ ] **Step 4: Run** → PASS; full suite → PASS (fix only color/text assertions in `tests/workspace_test.py` that the map palette change breaks).
- [ ] **Step 5: Commit** `git commit -m "Add terminal panes"`

### Task 5: Layout, callbacks and stylesheet

**Files:**
- Modify (rewrite): `components/layout.py` (`build_layout` keeps its signature)
- Modify (rewrite): `components/workspace_callbacks.py` (`register_workspace_callbacks(app, get_snapshot)` keeps its signature)
- Modify: `app.py` (fonts in `external_stylesheets`; delete the Generate briefing, category modal open/close, newsletter modal toggle callbacks and `_build_category_modal_body`; keep API modal toggle and `handle_newsletter_submit`)
- Create: `assets/terminal.css`; Delete: `assets/style.css`
- Delete: `components/cards.py`, `components/gauge.py`, `components/market_costs.py`, and the now-unused builders in `components/feed.py`/`workspace.py`/`charts.py` (keep `plain_text`, `safe_url`, `select_news`, `snapshot_csv`, `_port_hover_text`, `build_world_map`)
- Test: `tests/workspace_test.py` (update), `tests/test_ui_palette.py` (update)

**Interfaces:**
- Consumes: all Task 4 builders and ids.
- Layout grid order (desktop columns 300px | 1fr | 300px): header; readout | map (`dcc.Graph(id="world-map")`) | quotes (`id="quotes"`); headlines pane (search `dcc.Input(id="news-search")`, `dcc.Dropdown`/`dbc.Select` ids `news-severity`, `news-category`, results `id="news-results"`, count `id="news-results-count"`, spans two columns) | briefing (`id="briefing"`); category table (`id="category-table"`, full width); `dcc.Interval(id="refresh-interval")`, `dcc.Store(id="profile-store")`, `dcc.Download(id="snapshot-download")`, the existing API modal (restyled).
- Callbacks: profile-switch → profile-store; profile-store/refresh/trend-range → readout + category table; refresh → map, quotes, briefing, updated label, interval (300000 fresh / 20000 provisional); filters/refresh → news results + count (all alerts, newest first); export-btn → CSV (existing `snapshot_csv`).

- [ ] **Step 1: Update tests first:** in `tests/workspace_test.py`, rewrite `test_workspace_callbacks_render_all_profiles_and_export` to drive the new callbacks for each profile and assert the category table index text matches `index_summary`; delete tests for removed features (Refresh button, drivers, modal); keep news filter, export, map, newsletter validation tests. In `tests/test_ui_palette.py`, assert `assets/terminal.css` contains `#000000`, `#FFB020`, `#35D07F` and that `assets/style.css` does not exist.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** layout, callbacks, app.py removals and `assets/terminal.css` (copy values and structure from the reference HTML; responsive rules in Task 6).
- [ ] **Step 4: Run** full suite → PASS. Then start the local preview (Global Constraints command) and confirm in a browser at 1440px: header single row, readout | map | quotes, headlines + briefing, category table; profile switch recalculates; hovering a port and a category row shows details; Subscribe opens the small box; CSV downloads.
- [ ] **Step 5: Commit** `git commit -m "Switch the dashboard to the terminal layout"`

### Task 6: Phones, loading state, report and docs pages

**Files:**
- Modify: `assets/terminal.css` (breakpoint under 760px)
- Modify (rewrite): `components/skeleton.py` (`build_skeleton_layout()` signature kept)
- Modify: `api/report.py` (`_REPORT_TEMPLATE` styles), `api/docs.py` (page styles only)
- Test: `tests/terminal_ui_test.py` (extend)

- [ ] **Step 1: Write failing tests:** `test_skeleton_uses_terminal_grid` (skeleton tree contains class `pane` and no class names from the deleted stylesheet such as `overview-card`); `test_report_and_docs_use_terminal_palette` (Flask test client GET `/report` and `/docs` → body contains `#000000` and `JetBrains Mono`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** phone layout per spec (single column in order readout, map, quotes, headlines, briefing, categories; header wraps to name + Subscribe then the switch; Methodology/API/CSV move below the header; tables hide Category, Source, Yesterday and 30-day columns; no horizontal page scroll); skeleton with dim placeholder panes in the same grid; report and docs restyled with the palette and fonts.
- [ ] **Step 4: Run** full suite → PASS. Preview at 375px wide: no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`), all panes in order, Subscribe box usable, tapping a category shows its detail.
- [ ] **Step 5: Commit** `git commit -m "Terminal layout on phones, loading state, report and docs"`

### Task 7: Docs and final check

**Files:**
- Modify: `CLAUDE.md` (UI Patterns section), `README.md` (feature list)

- [ ] **Step 1:** Update CLAUDE.md "UI Patterns" (palette, fonts, terminal components, callbacks, hover details, Subscribe popover, `daily_history` in the snapshot) and README features to match what was built. No em dashes in new prose.
- [ ] **Step 2: Run** full suite → PASS; preview at 1440px and 375px once more; `grep -rn "style.css\|Satoshi\|IBM Plex" components app.py assets` returns nothing.
- [ ] **Step 3: Commit** `git commit -m "Document the terminal UI"`
