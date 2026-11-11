# History Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public `/history` page that charts the Global index for every day since 2019-01-11, backed by a one-time backfill of the stored category scores.

**Architecture:** The existing rebuild script gains a guarded global-only backfill mode that writes 2019-01-11 to 2026-07-22. A loader reads the eight global category rows once per UTC day in the background cycle and keeps them in memory. A server-rendered Flask page builds the chart, the episode list and a CSV from that memory copy and the live snapshot, and never opens the database in a request.

**Tech Stack:** Python 3.13, Flask (inside Dash 4.4), Flask-Limiter, pandas, pytest, SQLite locally, Neon Postgres in production. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-10-history-page-design.md` (approved by Will 2026-11-10). Read it before any task.

## Global Constraints

- Every command runs with `DATABASE_URL= GSC_DISABLE_BACKGROUND=1` (SQLite). The local `.env` points at production. Only Task 12 touches production, and only at its marked steps.
- Tests: `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/<file> -q`. Run the whole `tests/` folder before each commit.
- Request handlers read memory only. No database call in `/history`, `/history.csv` or the page's render path.
- Runtime database reads happen at most once per clock hour, in the first cycle of the hour. `test_second_cycle_in_an_hour_opens_no_database_connection` stays green.
- A day is plotted only when all eight global category rows exist for it. Value = sum of `config.CATEGORY_WEIGHTS[cat] * score` (nominal weights), the same as `terminal_data.index_history`. Never read `daily_scores` for the page. Never fill a gap.
- No sector key, sector label or Bank of Japan data on the page or in the CSV. The backfill requests no sector provider.
- The PortWatch credit `data.providers.chokepoints.CREDIT` appears on the page and on every CSV row.
- Every number on the page is computed from data at request time. No hand-typed index value in a template or in config.
- All tunables live in `config.py`. Read them as `config.NAME` at call time so tests can monkeypatch.
- Copy rules: no em or en dashes, sentence-case headings that say what the section is, no sales language.
- Look: the Terminal shell of `api/report.py` (page `#000000`, pane `#07090C`, rules `#1D232B`, amber `#FFB020`, text `#F2F4F7`, dim `#8A94A3`, JetBrains Mono for numbers and labels, Inter for prose). Tier colors from `terminal_data.TIER_COLORS`.
- Commit locally after each task, message as one plain sentence ending in a period, plus the `Co-Authored-By` line. Never push. Push happens only in Task 12 after Will says "push it".

## Review Focus

1. History is loaded but the snapshot is `None` (cold start): the page renders the chart with no live point and "–" for today, never a 500. Test in Task 6.
2. The daily load fails or returns no rows: the page keeps the previous load and never blanks. Test in Task 4.
3. The loaded history holds a row dated today (loaded after the hourly write): today's value comes only from the live snapshot and appears once. Test in Task 3.
4. An episode date falls on a gap or after the last stored day: its row shows "–", it has no chart mark, the page still renders. Tests in Tasks 3 and 5.
5. The sign-up POST has no email field, a 300-character email, or junk UTM values: refused as invalid or stored with source `history`, never a 500 and never free text as the source. Test in Task 7.

## File Structure

| File | Responsibility |
|:---|:---|
| `data/providers/{energy,tariffs,freight,inputs,physical}.py` (modify) | Record which inputs failed in `fetch_history` |
| `scripts/rebuild_category_history.py` (modify) | Global-only backfill mode with start and end dates and two new write guards |
| `config.py` (modify) | `HISTORY_*` keys, `SITEMAP_PATHS` |
| `components/history_data.py` (create) | Pure math: aligned history, daily index, series, extremes, episode rows, CSV text |
| `data/long_history.py` (create) | Once-a-day loader, memory copy behind a lock, disk cache |
| `data/aggregator.py` (modify) | Call the loader in the first cycle of the hour |
| `components/history_chart.py` (create) | Chart markup (SVG line plus HTML labels) from a list of points |
| `api/history.py` (create) | `/history`, `/history.csv`, `POST /history/signup`, the page template |
| `app.py`, `api/share.py`, `components/terminal.py`, `api/docs.py` (modify) | Wiring, share title, header link, docs link |
| `tests/history_helpers.py` and five new test files (create) | Fixtures and tests |

---

### Task 1: Providers record which history inputs failed

**Files:**
- Modify: `data/providers/energy.py` (~line 316), `tariffs.py` (~225), `freight.py` (~207), `inputs.py` (~254), `physical.py` (~239)
- Test: `tests/energy_test.py`, `tariffs_test.py`, `freight_test.py`, `inputs_test.py`, `physical_test.py`

**Interfaces:**
- Produces: after `provider.fetch_history(days)` returns or raises, `provider.history_input_failures: dict[str, str]` maps each input key whose history failed to `"<ExceptionClass>: <message>"`. Empty dict when every input loaded.

- [ ] **Step 1: Write one failing test per provider.** In each test file, reuse that file's existing way of faking sources, make exactly one input of the history loop raise `RuntimeError("down")`, and assert:

```python
def test_history_records_the_failed_input(...):
    provider.fetch_history(60)
    assert list(provider.history_input_failures) == [failed_key]      # e.g. "ulsd", "tpu", "mississippi"
    assert provider.history_input_failures[failed_key] == "RuntimeError: down"

def test_history_records_nothing_when_every_input_loads(...):
    provider.fetch_history(60)
    assert provider.history_input_failures == {}
```

- [ ] **Step 2: Run them, expect FAIL** with `AttributeError: ... has no attribute 'history_input_failures'`.
- [ ] **Step 3: Implement.** In each of the five `fetch_history` methods, set `self.history_input_failures = {}` as the first statement, and in the existing `except` that logs "history unavailable" add `self.history_input_failures[key] = f"{type(exc).__name__}: {exc}"` (the loop variable is `leg` in energy). Nothing else changes.
- [ ] **Step 4: Run the five test files, expect PASS.**
- [ ] **Step 5: Commit** "Providers record which inputs failed when history is rebuilt."

---

### Task 2: Backfill mode in the rebuild script

**Files:**
- Modify: `scripts/rebuild_category_history.py`
- Test: `tests/rebuild_history_test.py`

**Interfaces:**
- Consumes: `provider.history_input_failures` (Task 1), `scripts.backtest_composite.widened_fred_windows` and `WIDE_FRED_DAYS` (import inside `run`, the modules import each other).
- Produces:
  - `rebuild_categories(sectors_only: bool = False, global_only: bool = False) -> tuple[str, ...]`
  - `run(..., global_only: bool = False, start: date | None = None, end: date | None = None) -> RebuildResult` (existing parameters unchanged)
  - `RebuildResult.global_only: bool`, `.failed_inputs: dict[str, dict[str, str]]` (category -> input -> reason), `.first_stored: dict[str, date]` (first stored row on or after the window start, per key, not cut at `end`), `.stored_without_new() -> list[tuple[date, str]]`
  - CLI: `--global-only`, `--start YYYY-MM-DD`, `--end YYYY-MM-DD`

**Rules:**
- With `start` and `end`: the window is every date from `start` to `end` inclusive, each provider is asked for `(today - start).days + EXTRA_FETCH_DAYS` days, and the fetch runs inside `widened_fred_windows()`. Without them the script behaves exactly as today.
- `global_only` covers the eight `CATEGORY_WEIGHTS` keys plus the composite. No sector provider's `fetch_history` is called.
- `WriteRefused` (nothing written, no backup file) when:
  - `start` or `end` is given without the other, `start > end`, or `end >= today` (these three argument checks raise in a dry run too)
  - `start` is given without `global_only`, or `global_only` with `sectors_only` (dry run too)
  - `allow_partial` is combined with `start` (dry run too)
  - any `failed_inputs` (unless `allow_partial`, which only exists in the plain `--days` mode). The message names each as `category.input`.
  - `start` is given and `stored_without_new()` is not empty: a stored composite or global-key row inside the window would keep its old value. The message gives the count and the first three.
- File names in backfill mode: dry run `rebuild_dryrun_backfill_<today>.csv`, backup `category_scores_pre_backfill_<stamp>.csv`.
- `summarize` adds one `FAILED INPUT <category>.<input>: <reason>` line per failed input and, in backfill mode, one line `First stored row on or after <start>: <key> <date>, ...` from `first_stored`. Its existing "Stored rows left as they are" count uses `stored_without_new()`.
- `main` returns 2 with the logged reason on any `WriteRefused`; bad flag combinations are argparse errors.

- [ ] **Step 1: Write the failing tests** (reuse `FakeProvider`, `_providers`, `sqlite_db`, `_seed`, `_all_rows`, `TODAY = date(2026, 10, 22)`):

```python
GLOBAL = tuple(config.CATEGORY_WEIGHTS)
S, E = TODAY - timedelta(days=10), TODAY - timedelta(days=4)

def test_global_only_fetches_no_sector_provider(sqlite_db, tmp_path):
    providers = _providers()
    result = rebuild.run(days=5, providers=providers, today=TODAY, backup_dir=tmp_path, global_only=True)
    assert result.keys == (*GLOBAL, "composite")
    assert all(p.asked_days is None for cat, p in providers.items() if cat not in GLOBAL)

def test_start_and_end_are_inclusive_and_rows_after_end_stay(sqlite_db, tmp_path):
    after = (E + timedelta(days=1)).isoformat()
    _seed(sqlite_db, [(after, "energy", 10.0)], [(after, 11.0)])
    providers = _providers()
    result = rebuild.run(write=True, providers=providers, today=TODAY, backup_dir=tmp_path,
                         global_only=True, start=S, end=E)
    assert result.dates[0] == S and result.dates[-1] == E and len(result.dates) == 7
    assert providers["energy"].asked_days == 10 + rebuild.EXTRA_FETCH_DAYS
    cats, comp = _all_rows(sqlite_db)
    assert (after, "energy", 10.0) in cats and (after, 11.0) in comp
    assert result.written == 7 * 9 and result.backup_path.name.startswith("category_scores_pre_backfill_")
    assert result.csv_path.name == f"rebuild_dryrun_backfill_{TODAY.isoformat()}.csv"

def test_backfill_widens_fred_windows_only_during_the_fetch(sqlite_db, tmp_path, monkeypatch):
    from scripts import backtest_composite
    seen = []
    providers = _providers()
    real = providers["energy"].fetch_history
    providers["energy"].fetch_history = lambda days: (seen.append(config.ENERGY_FRED_LOOKBACK_DAYS), real(days))[1]
    before = config.ENERGY_FRED_LOOKBACK_DAYS
    rebuild.run(providers=providers, today=TODAY, backup_dir=tmp_path, global_only=True, start=S, end=E)
    rebuild.run(days=5, providers=providers, today=TODAY, backup_dir=tmp_path)
    assert seen == [backtest_composite.WIDE_FRED_DAYS, before] and config.ENERGY_FRED_LOOKBACK_DAYS == before

def test_backfill_refuses_when_a_stored_row_would_keep_its_old_value(sqlite_db, tmp_path):
    day = S + timedelta(days=2)
    _seed(sqlite_db, [(day.isoformat(), "energy", 10.0)], [(day.isoformat(), 11.0)])
    before = _all_rows(sqlite_db)
    providers = _providers(missing={"energy": {day}})
    with pytest.raises(rebuild.WriteRefused, match="2 stored rows"):
        rebuild.run(write=True, providers=providers, today=TODAY, backup_dir=tmp_path,
                    global_only=True, start=S, end=E)
    assert _all_rows(sqlite_db) == before and not list(tmp_path.glob("category_scores_pre_*"))

def test_write_refused_when_an_input_history_failed(sqlite_db, tmp_path):
    providers = _providers()
    providers["energy"].history_input_failures = {"ulsd": "TimeoutError: slow"}
    dry = rebuild.run(providers=providers, today=TODAY, backup_dir=tmp_path, global_only=True, start=S, end=E)
    assert dry.failed_inputs == {"energy": {"ulsd": "TimeoutError: slow"}}
    assert "FAILED INPUT energy.ulsd: TimeoutError: slow" in rebuild.summarize(dry)
    with pytest.raises(rebuild.WriteRefused, match="energy.ulsd"):
        rebuild.run(write=True, providers=providers, today=TODAY, backup_dir=tmp_path,
                    global_only=True, start=S, end=E)

@pytest.mark.parametrize("kwargs", [
    {"start": S}, {"end": E}, {"start": E, "end": S}, {"start": S, "end": TODAY},
    {"start": S, "end": E, "global_only": False}, {"sectors_only": True},
    {"start": S, "end": E, "allow_partial": True},
])
def test_bad_backfill_arguments_are_refused(kwargs, sqlite_db, tmp_path):
    args = {"global_only": True, "today": TODAY, "providers": _providers(), "backup_dir": tmp_path} | kwargs
    with pytest.raises(rebuild.WriteRefused):
        rebuild.run(**args)

def test_first_stored_shows_where_existing_rows_begin(sqlite_db, tmp_path):
    later = (E + timedelta(days=3)).isoformat()
    _seed(sqlite_db, [(later, "chokepoints", 90.0)], [])
    result = rebuild.run(providers=_providers(), today=TODAY, backup_dir=tmp_path, global_only=True, start=S, end=E)
    assert result.first_stored["chokepoints"] == E + timedelta(days=3)
    assert f"chokepoints {later}" in rebuild.summarize(result)

def test_main_passes_the_backfill_flags(monkeypatch, sqlite_db):
    seen = {}
    monkeypatch.setattr(rebuild, "run", lambda **kw: seen.update(kw) or rebuild.RebuildResult([S], {}, {}, {}, []))
    monkeypatch.setattr(rebuild, "summarize", lambda result: "")
    assert rebuild.main(["--global-only", "--start", "2019-01-11", "--end", "2026-07-22"]) == 0
    assert seen["global_only"] and seen["start"] == date(2019, 1, 11) and seen["end"] == date(2026, 7, 22)
    with pytest.raises(SystemExit):
        rebuild.main(["--start", "2019-13-40", "--end", "2026-07-22"])
```

- [ ] **Step 2: Run** `tests/rebuild_history_test.py`, expect the new tests to FAIL (unexpected keyword `global_only`).
- [ ] **Step 3: Implement** the interfaces and rules above. Read failed inputs with `getattr(provider, "history_input_failures", None) or {}` for each fetched category after its `fetch_history` call. Update the module docstring with the backfill mode and its command.
- [ ] **Step 4: Run** `tests/rebuild_history_test.py`, expect all PASS (the existing tests are unchanged and must still pass).
- [ ] **Step 5: Commit** "The history rebuild can backfill the global index from a start date to an end date."

---

### Task 3: Config keys and the history math

**Files:**
- Modify: `config.py` (next to `SITEMAP_PATHS` for the page keys)
- Create: `components/history_data.py`, `tests/history_helpers.py`, `tests/history_data_test.py`

**Interfaces:**
- Produces in `config.py`:

```python
HISTORY_START_DATE = "2019-01-11"          # first day with all eight categories; the page shows nothing older
HISTORY_BACKFILL_END_DATE = "2026-07-22"   # last day written by the backfill
HISTORY_BACKFILL_MONTH = "November 2026"   # when the backfill ran; printed on the page
HISTORY_LIVE_FROM_DATE = "2026-10-23"      # first live-recorded day; the chart's vertical rule
HISTORY_CHANGE_DAYS = 90                   # an episode's change is measured against this many days earlier
HISTORY_CACHE_KEY = "index_history_long_v1"
HISTORY_CACHE_MAX_AGE_SECONDS = 2 * 86400  # how old a disk copy may be to show at startup
HISTORY_SIGNUP_RATE_LIMIT = "5 per minute;30 per hour"
HISTORY_PAGE_TITLE = "Global Supply Chain Index history, daily since January 2019"
HISTORY_PAGE_DESCRIPTION = ("The Global Supply Chain Index for every day since 11 January 2019, "
                            "with six past disruptions marked and a CSV download.")
HISTORY_EPISODES: list[dict] = [           # the v2 research episodes; text and source_url are filled in Task 9
    {"date": "2020-04-15", "label": "COVID lockdowns", "text": "", "source_url": ""},
    {"date": "2021-03-29", "label": "Ever Given, Suez Canal", "text": "", "source_url": ""},
    {"date": "2021-12-15", "label": "NY Fed GSCPI record high", "text": "", "source_url": ""},
    {"date": "2024-02-15", "label": "Red Sea diversions", "text": "", "source_url": ""},
    {"date": "2025-04-15", "label": "US tariffs", "text": "", "source_url": ""},
    {"date": "2026-03-20", "label": "Hormuz", "text": "", "source_url": ""},
]
```

- Produces in `components/history_data.py` (no Flask, no database, no Dash):
  - `build_history(rows: list[tuple[date, str, float]], start: date, loaded_on: date) -> dict`: `{"loaded_on": iso, "start": iso, "dates": [iso, ...], "scores": {cat: [float | None, ...]}}`. `dates` is every calendar day from `start` to the last row date. Only the eight `CATEGORY_WEIGHTS` keys are kept. Rows before `start` and non-finite scores are dropped. No rows on or after `start` gives `dates == []`.
  - `daily_index(history: dict) -> list[float | None]`: one value per date, `None` unless all eight scores are present.
  - `series(history: dict, snapshot: dict | None) -> list[tuple[date, float | None]]`: the stored days. With a snapshot, days on or after the snapshot's UTC date (`terminal_data._today_utc`) are dropped, missing calendar days up to yesterday are added as `None`, and one live point `(today, snapshot_composite(snapshot))` is appended only when `excluded_categories` is empty and the composite is finite.
  - `extremes(points) -> dict`: `{"low": (date, value) | None, "high": (date, value) | None}` over the non-`None` points.
  - `episode_rows(history: dict, episodes: list[dict], change_days: int) -> list[dict]`: one per episode, in order: `n` (1-based), `date` (`date`), `label`, `text`, `source_url`, `index`, `tier` (`terminal_data.tier_for` or `None`), `change` (index minus the index `change_days` earlier, `None` if either is missing), `categories` (eight dicts in `CATEGORY_WEIGHTS` order: `cat`, `label` from `CATEGORY_LABELS`, `score`, `change`). Stored days only, never the live point.
  - `history_csv(history: dict, snapshot: dict | None) -> str`: header `date,index,<eight keys>,credit`; one row per `series` day; numbers as `f"{v:.2f}"`; empty cell for `None`; `credit` is `chokepoints.CREDIT` on every row; today's row takes its category cells from `snapshot["current_scores"]`.
- Produces in `tests/history_helpers.py`:

```python
CATS = list(config.CATEGORY_WEIGHTS)

def rows(first, days, score=60.0, missing=None, overrides=None):
    """(date, category, score) for the eight global categories on `days` consecutive dates.
    missing: {date: {categories without a row}}; overrides: {(date, category): score}."""

def snapshot(today, score=50.0, excluded=(), fallback=()):
    """A minimal dashboard snapshot: last_updated_utc at 12:00 UTC on `today`, current_scores for the
    categories not excluded, composite = score, the excluded/fallback/stale lists, empty metadata per
    category, and an empty daily_history."""
```

- [ ] **Step 1: Write `tests/history_helpers.py` and the failing tests** in `tests/history_data_test.py`:

```python
START = date(2019, 1, 11)
SECTOR_CATS = [c for s in config.SECTORS.values() for c in s["weights"]]

def test_build_history_keeps_the_eight_global_keys_from_the_start_date():
    data = rows(START - timedelta(days=3), 10, overrides={(START + timedelta(days=1), "energy"): float("nan")})
    data += [(START, "semis_memory_prices", 5.0), (START, "geo_register", 5.0)]
    h = hd.build_history(data, START, loaded_on=date(2026, 11, 10))
    assert h["dates"][0] == "2019-01-11" and len(h["dates"]) == 7 and h["loaded_on"] == "2026-11-10"
    assert set(h["scores"]) == set(CATS) and h["scores"]["energy"][1] is None
    assert hd.build_history(rows(START - timedelta(days=9), 5), START, START)["dates"] == []

def test_a_day_needs_all_eight_rows_and_matches_the_dashboard_sparkline():
    gap = START + timedelta(days=2)
    h = hd.build_history(rows(START, 5, missing={gap: {"physical"}}, overrides={(START, "energy"): 10.0}), START, START)
    index = hd.daily_index(h)
    assert index[2] is None and index[1] == pytest.approx(60.0) and index[0] == pytest.approx(52.5)
    snap = snapshot(START + timedelta(days=5)) | {"daily_history": {"dates": h["dates"], "scores": h["scores"]}}
    rounded = lambda values: [None if v is None else round(v, 6) for v in values]  # noqa: E731
    assert rounded(terminal_data.index_history(snap, "global", 6)[:-1]) == rounded(index)

def test_series_adds_the_live_point_only_without_an_exclusion():
    h = hd.build_history(rows(START, 5), START, START)
    today = START + timedelta(days=6)
    points = hd.series(h, snapshot(today, score=41.0))
    assert len(points) == 7 and points[-1] == (today, 41.0) and points[-2] == (today - timedelta(days=1), None)
    assert hd.series(h, snapshot(today, excluded=("energy",)))[-1][0] == today - timedelta(days=1)
    assert hd.series(h, None)[-1] == (START + timedelta(days=4), pytest.approx(60.0))

def test_a_stored_row_dated_today_never_replaces_the_live_value():
    today = START + timedelta(days=4)
    points = hd.series(hd.build_history(rows(START, 5), START, today), snapshot(today, score=41.0))
    assert [d for d, _ in points].count(today) == 1 and points[-1] == (today, 41.0)

def test_extremes_and_episode_rows_come_from_the_data():
    day, base = START + timedelta(days=95), START + timedelta(days=5)
    data = rows(START, 100, overrides={(day, c): 30.0 for c in CATS} | {(base, "energy"): 100.0})
    h = hd.build_history(data, START, START)
    ext = hd.extremes(hd.series(h, None))
    assert ext["low"] == (day, pytest.approx(30.0)) and ext["high"] == (base, pytest.approx(66.0))
    [row] = hd.episode_rows(h, [{"date": day.isoformat(), "label": "X", "text": "t", "source_url": "https://e.org"}], 90)
    assert row["n"] == 1 and row["date"] == day and row["index"] == pytest.approx(30.0)
    assert row["tier"]["label"] == "Critical" and row["change"] == pytest.approx(-36.0)
    energy = next(c for c in row["categories"] if c["cat"] == "energy")
    assert len(row["categories"]) == 8 and energy["score"] == 30.0 and energy["change"] == pytest.approx(-70.0)

def test_an_episode_on_a_gap_or_after_the_data_has_no_index():
    gap = START + timedelta(days=95)
    h = hd.build_history(rows(START, 100, missing={gap: {"freight"}}), START, START)
    blank = {"label": "A", "text": "", "source_url": ""}
    a, b = hd.episode_rows(h, [blank | {"date": gap.isoformat()}, blank | {"date": "2030-01-01"}], 90)
    assert a["index"] is None and a["tier"] is None and a["change"] is None
    assert next(c for c in a["categories"] if c["cat"] == "freight")["score"] is None
    assert b["index"] is None and all(c["score"] is None for c in b["categories"])

def test_csv_has_one_row_per_day_the_credit_and_empty_cells_for_gaps():
    gap = START + timedelta(days=1)
    h = hd.build_history(rows(START, 3, missing={gap: {"physical"}}), START, START)
    today = START + timedelta(days=3)
    lines = hd.history_csv(h, snapshot(today, score=41.0)).strip().splitlines()
    assert lines[0] == "date,index," + ",".join(CATS) + ",credit" and len(lines) == 5
    assert lines[1].startswith("2019-01-11,60.00,") and lines[4].startswith(f"{today.isoformat()},41.00,50.00,")
    cells = next(csv.reader([lines[2]]))
    assert cells[1] == "" and cells[2 + CATS.index("physical")] == "" and cells[-1] == CREDIT
    assert not any(key in "\n".join(lines) for key in SECTOR_CATS)
```

- [ ] **Step 2: Run** `tests/history_data_test.py`, expect FAIL (`No module named components.history_data`).
- [ ] **Step 3: Add the config keys and implement `components/history_data.py`** to the interfaces above.
- [ ] **Step 4: Run** `tests/history_data_test.py`, expect PASS.
- [ ] **Step 5: Commit** "History math: the daily index, episodes and CSV from stored category rows."

---

### Task 4: Once-a-day loader and the aggregator hook

**Files:**
- Create: `data/long_history.py`, `tests/long_history_test.py`
- Modify: `data/aggregator.py` (after `daily_history = _stored_daily_history()`, ~line 811), `app.py` (startup, after the startup-data block ends near line 240), `tests/aggregator_v2_test.py`, `tests/register_test.py`

**Interfaces:**
- Consumes: `history_data.build_history`, `database.export_category_rows(start, categories, strict=True)`, `cache.get_cached` / `cache.set_cached`.
- Produces in `data/long_history.py` (imports `cache` and `database` as modules):
  - `get() -> dict | None`: the memory copy. Never touches disk or the database.
  - `refresh_if_due(today: date | None = None) -> bool`: `True` when memory holds a load made on `today` (UTC) after the call. If memory is already from `today`, returns `True` and does nothing. Else uses the disk copy when its `loaded_on` is `today` and its `start` is `config.HISTORY_START_DATE`. Else reads the eight global keys from `HISTORY_START_DATE` with `strict=True`, builds the history, stores it in memory and on disk. A raised read or a history with no dates returns `False` and leaves memory as it was. Never raises.
  - `prime_from_disk() -> bool`: fills an empty memory from a disk copy up to `HISTORY_CACHE_MAX_AGE_SECONDS` old with a matching `start`. No database.
  - `reset() -> None`: clears memory (tests).
- Produces in `data/aggregator.py`: `_refresh_long_history() -> None`, which runs `_once_per_hour("long_history", long_history.refresh_if_due)` (looked up on the module at call time, so tests can replace it) and logs instead of raising. The returned snapshot gains no key. `_once_per_hour` remembers a `False` too, so a failed load is tried again in the next hour's first cycle, not the next 5-minute cycle.
- `app.py`: one call to `long_history.prime_from_disk()` at startup so a worker restart shows the last load at once.

- [ ] **Step 1: Write the failing tests** in `tests/long_history_test.py`:

```python
D = date(2026, 11, 10)

@pytest.fixture(autouse=True)
def store(monkeypatch):
    lh.reset()
    disk = {}
    monkeypatch.setattr(lh.cache, "get_cached", lambda key, ttl=3600: disk.get(key))
    monkeypatch.setattr(lh.cache, "set_cached", lambda key, data: disk.__setitem__(key, data))
    yield disk
    lh.reset()

def reads(monkeypatch, result):
    calls = []
    def export(start, categories, strict=False):
        calls.append((start, tuple(categories), strict))
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(lh.database, "export_category_rows", export)
    return calls

def test_reads_the_database_once_per_utc_day(monkeypatch):
    calls = reads(monkeypatch, rows(START, 5))
    assert lh.get() is None and lh.refresh_if_due(D) is True and lh.refresh_if_due(D) is True
    assert calls == [(date(2019, 1, 11), tuple(config.CATEGORY_WEIGHTS), True)]
    assert lh.refresh_if_due(D + timedelta(days=1)) is True and len(calls) == 2
    assert lh.get()["loaded_on"] == "2026-11-11"

def test_a_failed_or_empty_read_keeps_the_previous_history(monkeypatch):
    reads(monkeypatch, rows(START, 5)); lh.refresh_if_due(D)
    reads(monkeypatch, RuntimeError("down"))
    assert lh.refresh_if_due(D + timedelta(days=1)) is False and lh.get()["loaded_on"] == "2026-11-10"
    reads(monkeypatch, [])
    assert lh.refresh_if_due(D + timedelta(days=1)) is False and lh.get()["loaded_on"] == "2026-11-10"
    reads(monkeypatch, rows(START, 6))
    assert lh.refresh_if_due(D + timedelta(days=1)) is True and len(lh.get()["dates"]) == 6

def test_todays_disk_copy_skips_the_database(monkeypatch):
    reads(monkeypatch, rows(START, 5)); lh.refresh_if_due(D); lh.reset()
    calls = reads(monkeypatch, RuntimeError("must not be called"))
    assert lh.refresh_if_due(D) is True and calls == [] and len(lh.get()["dates"]) == 5

def test_prime_from_disk_shows_an_older_copy_until_the_next_load(monkeypatch):
    reads(monkeypatch, rows(START, 5)); lh.refresh_if_due(D); lh.reset()
    calls = reads(monkeypatch, rows(START, 6))
    assert lh.prime_from_disk() is True and len(lh.get()["dates"]) == 5 and calls == []
    assert lh.refresh_if_due(D + timedelta(days=1)) is True and len(calls) == 1

def test_a_disk_copy_for_another_start_date_is_ignored(monkeypatch, store):
    store[config.HISTORY_CACHE_KEY] = {"loaded_on": "2026-11-10", "start": "2020-01-01", "dates": ["2020-01-01"], "scores": {}}
    assert lh.prime_from_disk() is False and lh.get() is None
```

In `tests/aggregator_v2_test.py`: give `harness.run` a `history=None` parameter that sets `long_history.refresh_if_due` to `history or (lambda today=None: True)`; stub it the same way wherever `tests/register_test.py` calls `aggregate_data()`. Then add and extend:

```python
def test_long_history_refresh_runs_in_the_first_cycle_of_the_hour_only(harness):
    run, _ = harness
    calls = []
    run(history=lambda today=None: calls.append(1) or True)
    aggregator.aggregate_data()
    assert calls == [1]
```

In `test_second_cycle_in_an_hour_opens_no_database_connection`, after `run(providers)` restore the real `long_history.refresh_if_due` (keep a module-level reference taken at import), call `long_history.reset()`, and change the first assertion to `len(connections) >= 4`. The second cycle must still open none.

- [ ] **Step 2: Run** the three test files, expect FAIL (`No module named data.long_history`).
- [ ] **Step 3: Implement** `data/long_history.py`, `_refresh_long_history()` and its call right after `daily_history = _stored_daily_history()`, and the `prime_from_disk()` call in `app.py`. The history is not added to the snapshot.
- [ ] **Step 4: Run** `tests/long_history_test.py tests/aggregator_v2_test.py tests/register_test.py tests/sectors_aggregator_test.py`, expect PASS.
- [ ] **Step 5: Commit** "The long index history loads from the database once a day and is served from memory."

---

### Task 5: Chart markup

**Files:**
- Create: `components/history_chart.py`, `tests/history_chart_test.py`

**Interfaces:**
- Consumes: `terminal_data.TIER_COLORS`, `terminal_data.tier_for`.
- Produces: `chart_html(points: list[tuple[date, float | None]], episodes: list[dict], live_from: date) -> str`. `episodes` are `episode_rows` dicts (uses `n`, `date`, `index`). Returns `""` for no points.

**Layout (decided here so text stays readable at phone width):**
- One wrapper `<div class="hchart">`. Inside it an `<svg viewBox="0 0 1000 100" preserveAspectRatio="none">` that holds only lines, so it can stretch to any width. Strokes use `vector-effect="non-scaling-stroke"`.
- Point `i` of `n` sits at `x = i / (n - 1) * 1000` (500 when `n == 1`) and `y = 100 - value`, both printed with two decimals.
- The index is one `<path class="line" d="...">`. Each run of consecutive values starts with `M`; a run of one day is written `Mx yh0` and the line uses round caps so it draws a dot. A `None` day ends the run.
- Three `<line class="tier-rule">` at `y` 20, 40 and 60 (index 80, 60, 40).
- All text is HTML positioned by percentage over the SVG, so it does not stretch: the four tier names in their `TIER_COLORS`, a year label at each 1 January in range, one `<a class="mark" href="#ep-N" style="left:X%;top:Y%">N</a>` per episode that has an index and a date in range, and when `live_from` is in range one vertical rule with the label "recorded live from here".
- Hover: `<script type="application/json" id="hchart-data">{"start": "<first date>", "values": [...]}</script>` (`null` for a gap), an empty `<p id="hchart-readout">`, and a short inline script that, on pointer move or touch over the chart, writes the date, value and tier of the nearest day into the readout. The chart is complete without the script.

- [ ] **Step 1: Write the failing tests:**

```python
LIVE = date(2026, 10, 23)

def pts(values, first=date(2026, 10, 20)):
    return [(first + timedelta(days=i), v) for i, v in enumerate(values)]

def line(html):
    return re.search(r'<path class="line"[^>]* d="([^"]+)"', html).group(1)

def test_a_missing_day_breaks_the_line():
    html = chart.chart_html(pts([60.0, 61.0, None, 62.0, 63.0]), [], LIVE)
    assert line(html).count("M") == 2 and "None" not in html and "nan" not in html.lower()

def test_the_y_axis_is_fixed_and_a_lone_day_still_draws():
    html = chart.chart_html(pts([80.0, None, 40.0]), [], LIVE)
    assert line(html) == "M0.00 20.00h0M1000.00 60.00h0"
    assert 'viewBox="0 0 1000 100"' in html and 'preserveAspectRatio="none"' in html

def test_episode_marks_are_numbered_and_skip_an_episode_without_a_value():
    points = pts([60.0] * 5)
    eps = [{"n": 1, "date": points[1][0], "index": 60.0}, {"n": 2, "date": points[3][0], "index": None},
           {"n": 3, "date": date(2030, 1, 1), "index": 50.0}]
    html = chart.chart_html(points, eps, LIVE)
    assert html.count('class="mark"') == 1 and 'href="#ep-1"' in html and "left:25.00%;top:40.00%" in html

def test_labels_the_live_rule_and_the_hover_data():
    points = pts([60.0] * 699 + [None], first=date(2025, 1, 1))
    html = chart.chart_html(points, [], LIVE)
    assert html.count("recorded live from here") == 1 and ">2025<" in html and ">2026<" in html
    assert all(name in html for name in ("Healthy", "Stable", "Stressed", "Critical"))
    data = json.loads(re.search(r'id="hchart-data">(.*?)</script>', html, re.S).group(1))
    assert data["start"] == "2025-01-01" and len(data["values"]) == 700 and data["values"][-1] is None
    assert "recorded live from here" not in chart.chart_html(pts([60.0] * 3, first=date(2020, 1, 1)), [], LIVE)
    assert chart.chart_html([], [], LIVE) == ""
```

- [ ] **Step 2: Run** `tests/history_chart_test.py`, expect FAIL (module missing).
- [ ] **Step 3: Implement `chart_html`** to the layout above. Sizes, line weight and the readout's look are yours; keep the class names and ids used in the tests.
- [ ] **Step 4: Run** `tests/history_chart_test.py`, expect PASS.
- [ ] **Step 5: Commit** "Chart markup for the index history: one line, tier rules, numbered episode marks."

---

### Task 6: The `/history` page and `/history.csv`

**Files:**
- Create: `api/history.py`, `tests/history_page_test.py`
- Modify: `app.py` (next to `register_share_routes`, after the limiter exists)

**Interfaces:**
- Consumes: `long_history.get()`, `history_data.*`, `history_chart.chart_html`, `terminal_data.index_summary`, `config.HISTORY_*`, `chokepoints.CREDIT`.
- Produces: `register_history_routes(server: Flask, get_snapshot: Callable[[], tuple[dict | None, bool]], limiter: Limiter) -> None`, registering `GET /history` and `GET /history.csv` (Task 7 adds the POST). `app.py` calls it with the same `get_snapshot` and `limiter` it already has.

**Page, top to bottom** (one pane, `max-width` about 1100px, single column on phones):

1. Top bar: brand linking to `/`, then "Dashboard" (`/`) and "Methodology" (`/docs`).
2. `<h1>`: `Global Supply Chain Index, daily since 11 January 2019` (date formatted from `HISTORY_START_DATE`).
3. Numbers row: "Today" (value and tier from `index_summary(snapshot, "global")`, "–" when there is none; when `excluded_categories` is not empty add `Excluded today: <category labels>`), "Lowest" and "Highest" (value and date from `extremes(series(...))`). One decimal. Dates as `16 April 2019`.
4. `<section id="chart">` with `chart_html(...)`.
5. One sentence: `The index moves when several categories are under stress for weeks. A single event shows in its own category and can leave the index Stable.`
6. `<section id="episodes">`, title "Six episodes" (use the count), intro `These dates were fixed in the methodology research before this page existed. The index was Stable on {n} of the {total}.` with `n` counted from the rows. One row per episode with `id="ep-N"`: number, date, label, the `text` with a "Source" link to `source_url` (both omitted when empty), index and tier, `{change:+.1f} over 90 days` ("–" when `None`). Each row has `<details><summary>All eight categories</summary>` with a table of label, score and 90-day change.
7. `<section id="how">`, title "How this history was made", four paragraphs:
   - `Recomputed, then recorded. Days before {live_from} were calculated afterwards from the source data, so they include later revisions and are not what a live site showed that day. Days from {start} to {backfill_end} were calculated in {HISTORY_BACKFILL_MONTH}. Days from 23 July 2026 to 22 October 2026 were calculated on 23 October 2026. Monthly and weekly figures sit on the day they were published. Daily figures (oil and diesel prices, the geopolitical risk and trade policy uncertainty indexes) sit on their own day.`
   - `The scale was set on this same history. In each category, 0 is the worst month on record through 2025, so the worst months of 2021 score near 0 in their category by construction. The chart shows how the scale reads the past. It is not a test of prediction.`
   - `A demand collapse reads as healthy costs. On 15 April 2020 the index was {value}, because oil and metal prices fell.` then a link `Limitations` to `/docs`. `{value}` is `daily_index` on 2020-04-15; when that day has no value the sentence is `In a demand collapse oil and metal prices fall, so the cost categories read as healthy.`
   - `Chokepoint traffic is compared with 2022 to 2023 volumes for every year, including 2019 to 2021.`
8. `<section id="signup">`: `FREE` badge, `Get this index in your inbox every day. Today's score and a short briefing on the news behind it.`, a form with `method="post" action="/history/signup"`, an email input named `email` (`type="email"`, `autocomplete="email"`, a visually hidden label), and the button `Sign up free`.
9. `<section id="download">`: link `Download CSV` to `/history.csv`, `License: CC-BY-4.0`, the PortWatch credit, a link to `/docs`.

`<title>` is `config.HISTORY_PAGE_TITLE`; `<meta name="description">` is `config.HISTORY_PAGE_DESCRIPTION`. All config and data text goes through Jinja autoescape.

**States:**
- `long_history.get()` is `None` or has no dates: status 200 with the heading, the line `History is loading. Reload in a minute.`, the sign-up and download sections. No numbers row, chart or episodes. `/history.csv` answers 503 with the plain text `History is loading.`
- Snapshot is `None`: the page renders from the stored days alone.
- `/history.csv`: `text/csv`, `Content-Disposition: attachment; filename="gscindex-history.csv"`, `Cache-Control: public, max-age=3600`.

- [ ] **Step 1: Write the failing tests:**

```python
START, TODAY = date(2019, 1, 11), date(2019, 7, 30)        # 200 stored days, then today
DAY, BASE = START + timedelta(days=95), START + timedelta(days=5)
EPISODES = [{"date": DAY.isoformat(), "label": "Test event", "text": "X happened.", "source_url": "https://example.org/x"}]
SECTOR_WORDS = [c for s in config.SECTORS.values() for c in s["weights"]] + ["Semis", "Aero", "Bank of Japan"]

def history():
    data = rows(START, 200, overrides={(DAY, c): 30.0 for c in CATS} | {(BASE, "energy"): 100.0})
    return hd.build_history(data, START, TODAY)

def client(monkeypatch, hist, snap, episodes=EPISODES):
    monkeypatch.setattr(config, "HISTORY_EPISODES", episodes)
    monkeypatch.setattr(long_history, "get", lambda: hist)
    monkeypatch.setattr(database, "get_connection", lambda: pytest.fail("database opened in a request"))
    app = Flask(__name__)
    history_page.register_history_routes(app, lambda: (snap, True), get_limiter(app))
    return app.test_client()

def test_page_shows_the_chart_numbers_and_episode_from_the_data(monkeypatch):
    body = client(monkeypatch, history(), snapshot(TODAY, score=41.0)).get("/history").get_data(as_text=True)
    assert "Global Supply Chain Index, daily since 11 January 2019" in body and '<path class="line"' in body
    assert "41.0" in body and "30.0" in body and "16 April 2019" in body and "66.0" in body and "16 January 2019" in body
    assert 'id="ep-1"' in body and "X happened." in body and 'href="https://example.org/x"' in body
    assert "-36.0 over 90 days" in body and "All eight categories" in body
    assert all(config.CATEGORY_LABELS[c] in body for c in CATS)
    assert "The index was Stable on 0 of the 1." in body
    assert CREDIT in body and "CC-BY-4.0" in body and 'href="/history.csv"' in body
    assert 'action="/history/signup"' in body and "Sign up free" in body
    assert not any(word in body for word in SECTOR_WORDS)

def test_page_without_history_says_it_is_loading(monkeypatch):
    for hist in (None, hd.build_history([], START, TODAY)):
        c = client(monkeypatch, hist, snapshot(TODAY))
        resp = c.get("/history")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200 and "History is loading. Reload in a minute." in body
        assert "<svg" not in body and 'id="episodes"' not in body and 'action="/history/signup"' in body
        assert c.get("/history.csv").status_code == 503

def test_page_without_a_snapshot_renders_the_stored_days(monkeypatch):
    resp = client(monkeypatch, history(), None).get("/history")
    assert resp.status_code == 200 and "<svg" in resp.get_data(as_text=True)

def test_an_exclusion_is_named_and_adds_no_live_point(monkeypatch):
    body = client(monkeypatch, history(), snapshot(TODAY, excluded=("energy",))).get("/history").get_data(as_text=True)
    assert f"Excluded today: {config.CATEGORY_LABELS['energy']}" in body
    data = json.loads(re.search(r'id="hchart-data">(.*?)</script>', body, re.S).group(1))
    assert len(data["values"]) == 200

def test_an_episode_without_a_value_shows_a_dash_and_no_mark(monkeypatch):
    eps = EPISODES + [{"date": "2030-01-01", "label": "Later", "text": "", "source_url": ""}]
    body = client(monkeypatch, history(), snapshot(TODAY), eps).get("/history").get_data(as_text=True)
    assert 'id="ep-2"' in body and 'href="#ep-2"' not in body and "Six episodes" not in body and "Two episodes" in body

def test_csv_is_served_from_memory_with_a_one_hour_cache(monkeypatch):
    resp = client(monkeypatch, history(), snapshot(TODAY, score=41.0)).get("/history.csv")
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert resp.mimetype == "text/csv" and resp.headers["Cache-Control"] == "public, max-age=3600"
    assert lines[1].startswith("2019-01-11,60.00,") and len(lines) == 202 and lines[-1].startswith("2019-07-30,41.00,")

def test_the_routes_are_on_the_real_app():
    import app
    assert {"/history", "/history.csv"} <= {rule.rule for rule in app.server.url_map.iter_rules()}
```

- [ ] **Step 2: Run** `tests/history_page_test.py`, expect FAIL (module missing).
- [ ] **Step 3: Implement** `api/history.py` and the `app.py` call. Reuse the CSS values of `api/report.py`; write the count in the episodes title as a word up to ten.
- [ ] **Step 4: Run** `tests/history_page_test.py`, expect PASS.
- [ ] **Step 5: Commit** "A public history page charts the Global index for every day since January 2019."

---

### Task 7: Sign-up on the page

**Files:**
- Modify: `api/history.py`, `tests/history_page_test.py`

**Interfaces:**
- Consumes: `share.valid_email`, `share.signup_source`, `database.add_subscriber(email, source)` (called as `database.add_subscriber`), `database._OPTED_OUT_RESULT`, `config.HISTORY_SIGNUP_RATE_LIMIT`, the `limiter` passed to `register_history_routes`.
- Produces: `POST /history/signup`, limited with `limiter.limit(config.HISTORY_SIGNUP_RATE_LIMIT)` (the limiter already keys on the visitor IP).

**Rules:**
- Email: `request.form.get("email", "")`, stripped and lowercased, checked with `valid_email`.
- Source: `signup_source` applied to a query string built from the form's `utm_source` and `utm_campaign`, or `"history"` when that gives `None`.
- Always answers `303` to `/history?signup=<code>#signup` with code `ok`, `invalid` (bad or missing email, nothing stored), `optout` (the result is the opted-out result) or `error`.
- `GET /history?signup=<code>` shows one line in the sign-up section, `role="status"`: `ok` "You're subscribed to the daily briefing.", `invalid` "Please enter a valid email address.", `optout` the message of `database._OPTED_OUT_RESULT`, `error` "An error occurred while subscribing." Any other value shows nothing and is never echoed.
- `GET /history` with valid `utm_source` (and `utm_campaign`) in its query string carries them into the form as hidden inputs, each value checked through `signup_source` first. Invalid values add no hidden input.

- [ ] **Step 1: Write the failing tests:**

```python
def signup(monkeypatch, result=None, **form):
    calls = []
    monkeypatch.setattr(database, "add_subscriber",
                        lambda email, source=None: calls.append((email, source)) or (result or {"success": True}))
    resp = client(monkeypatch, history(), snapshot(TODAY)).post("/history/signup", data=form)
    return resp, calls

def test_a_valid_email_is_stored_with_the_source_history(monkeypatch):
    resp, calls = signup(monkeypatch, email=" A@Example.com ")
    assert resp.status_code == 303 and resp.headers["Location"].endswith("/history?signup=ok#signup")
    assert calls == [("a@example.com", "history")]

def test_utm_tags_become_the_source_and_junk_does_not(monkeypatch):
    assert signup(monkeypatch, email="a@b.co", utm_source="reddit", utm_campaign="test1")[1] == [("a@b.co", "reddit/test1")]
    assert signup(monkeypatch, email="a@b.co", utm_source="<script>", utm_campaign="x y")[1] == [("a@b.co", "history")]

@pytest.mark.parametrize("form", [{}, {"email": "nope"}, {"email": "a" * 300 + "@b.co"}, {"email": "a@b.co, c@d.co"}])
def test_a_bad_or_missing_email_stores_nothing(monkeypatch, form):
    resp, calls = signup(monkeypatch, **form)
    assert resp.status_code == 303 and "signup=invalid#signup" in resp.headers["Location"] and calls == []

def test_opt_out_and_failure_get_their_own_lines(monkeypatch):
    assert "signup=optout" in signup(monkeypatch, database._OPTED_OUT_RESULT, email="a@b.co")[0].headers["Location"]
    assert "signup=error" in signup(monkeypatch, {"success": False, "message": "x"}, email="a@b.co")[0].headers["Location"]
    c = client(monkeypatch, history(), snapshot(TODAY))
    assert "You&#39;re subscribed to the daily briefing." in c.get("/history?signup=ok").get_data(as_text=True)
    assert "unsubscribed earlier" in c.get("/history?signup=optout").get_data(as_text=True)
    assert "alert(1)" not in c.get("/history?signup=<script>alert(1)</script>").get_data(as_text=True)

def test_the_form_carries_valid_utm_tags_only(monkeypatch):
    c = client(monkeypatch, history(), snapshot(TODAY))
    tagged = c.get("/history?utm_source=reddit&utm_campaign=test1").get_data(as_text=True)
    assert 'name="utm_source" value="reddit"' in tagged and 'name="utm_campaign" value="test1"' in tagged
    assert 'name="utm_source"' not in c.get("/history?utm_source=%3Cx%3E").get_data(as_text=True)

def test_signups_are_rate_limited_per_visitor(monkeypatch):
    monkeypatch.setattr(config, "HISTORY_SIGNUP_RATE_LIMIT", "2 per minute")
    monkeypatch.setattr(database, "add_subscriber", lambda email, source=None: {"success": True})
    c = client(monkeypatch, history(), snapshot(TODAY))
    codes = [c.post("/history/signup", data={"email": "a@b.co"}).status_code for _ in range(3)]
    assert codes == [303, 303, 429]
```

Add `"/history/signup"` to the route set in `test_the_routes_are_on_the_real_app`.

- [ ] **Step 2: Run** `tests/history_page_test.py`, expect the new tests to FAIL (405 or 404 on the POST).
- [ ] **Step 3: Implement** the route and the status line to the rules above.
- [ ] **Step 4: Run** `tests/history_page_test.py`, expect PASS.
- [ ] **Step 5: Commit** "Visitors can sign up for the daily email from the history page."

---

### Task 8: Links, sitemap and share title

**Files:**
- Modify: `config.py` (`SITEMAP_PATHS`), `api/share.py` (`_PAGE_TITLES`, description), `components/terminal.py:188`, `api/docs.py` (section 11, Limitations)
- Test: `tests/share_test.py`, `tests/terminal_ui_test.py`, `tests/docs_page_test.py`

**Interfaces:**
- `config.SITEMAP_PATHS = ("/", "/docs", "/report", "/history")`, which also turns on the share tags and the analytics beacon for the page.
- `api/share.py`: `_PAGE_TITLES["/history"] = f"History since 2019 | {APP_TITLE}"`; new `_PAGE_DESCRIPTIONS = {"/history": HISTORY_PAGE_DESCRIPTION}` used by `share_tags` before `share_description(numbers)`.
- Dashboard header: `html.A("History", href="/history", className="opt")` right after the Methodology link.
- `/docs` Limitations gains: `The [history page](/history) shows the index for every day since January 2019, including April 2020.`

- [ ] **Step 1: Write the failing tests:**

```python
# tests/share_test.py  (add "/history" to the paths _client registers)
def test_history_is_in_the_sitemap_with_its_own_title_and_description():
    assert "/history" in config.SITEMAP_PATHS
    assert f"<loc>{config.SITE_URL}/history</loc>" in _client(None).get("/sitemap.xml").get_data(as_text=True)
    body = _client(_snapshot()).get("/history").get_data(as_text=True)
    assert 'property="og:title" content="History since 2019 | Global Supply Chain Index"' in body
    assert f'property="og:description" content="{config.HISTORY_PAGE_DESCRIPTION}"' in body

# tests/terminal_ui_test.py  (next to the existing /docs header assertion, same `walk` helper)
    assert any(isinstance(c, html.A) and c.href == "/history" and c.children == "History" for c in walk(header))

# tests/docs_page_test.py
def test_docs_limitations_link_to_the_history_page(body):
    assert '<a href="/history">history page</a>' in body
```

- [ ] **Step 2: Run** the three files, expect the new assertions to FAIL.
- [ ] **Step 3: Make the four edits.**
- [ ] **Step 4: Run** the three files plus `tests/history_page_test.py`, expect PASS. Check the header still fits on one line at 1280px and wraps cleanly at 760px (Task 11 screenshots cover it).
- [ ] **Step 5: Commit** "The dashboard, the methodology page and the sitemap link to the history page."

---

### Task 9: Episode sentences and sources

**Files:**
- Modify: `config.py` (`HISTORY_EPISODES` `text` and `source_url`), `tests/history_page_test.py`

**Rules for each sentence:**
- One sentence that says what happened and when. No claim about what the index did.
- One source per episode: a primary source (canal authority, NY Fed, White House or USTR, IMF PortWatch, UNCTAD, WHO) or a major outlet. Open the page and confirm it states the date and the fact before using it. Never write a sentence from memory.
- The Ever Given sentence gives the event dates (23 to 29 March 2021) and says the traffic drop shows in the following week.
- The 2021-12-15 sentence states the GSCPI value for December 2021 as the NY Fed's current file gives it (read it from `data/gscpi_client.py`'s source, not from memory).
- 2026-03-20 Hormuz: if no source can be found and verified, stop and ask Will. Do not ship a sentence without one.
- No em or en dashes. Check all six against `~/.claude/taste/writing-tells.md`.

- [ ] **Step 1: Write the failing test:**

```python
def test_every_episode_has_one_sentence_and_an_https_source():
    assert [e["date"] for e in config.HISTORY_EPISODES] == [
        "2020-04-15", "2021-03-29", "2021-12-15", "2024-02-15", "2025-04-15", "2026-03-20"]
    for episode in config.HISTORY_EPISODES:
        assert 40 <= len(episode["text"]) <= 240 and episode["text"].endswith(".")
        assert "—" not in episode["text"] and "–" not in episode["text"]
        assert episode["source_url"].startswith("https://")
```

- [ ] **Step 2: Run it, expect FAIL** (empty text).
- [ ] **Step 3: Research and write the six sentences and sources** into `config.HISTORY_EPISODES`.
- [ ] **Step 4: Run** `tests/history_page_test.py`, expect PASS.
- [ ] **Step 5: Commit** "Six sourced episode descriptions for the history page." The wording is final only after Will approves it in Task 11.

---

### Task 10: Documentation and housekeeping

**Files:**
- Modify: `scripts/backtest_composite.py` (docstring), `CLAUDE.md`, `README.md`, `api/docs.py`

- [ ] **Step 1: Fix the backtest docstring.** Replace `(chokepoints start in 2022, physical about 2024, TPU daily 2015+, and so on)` with `(chokepoints start on 2019-01-11, the other seven categories reach further back)`.
- [ ] **Step 2: Update `CLAUDE.md`:**
  - Project Structure: `api/history.py`, `components/history_data.py`, `components/history_chart.py`, `data/long_history.py`.
  - API Endpoints: `GET /history`, `GET /history.csv`, `POST /history/signup` and its limit; the rate-limit paragraph (the sign-up endpoint is the one limited route outside `/api/v1/*`).
  - Caching table: `index_history_long_v1`, read from the database once per UTC day, disk copy shown at startup up to 2 days old.
  - Data Flow and the Neon rule: the long history read runs in the first cycle of the hour, once per UTC day.
  - History rebuild: the backfill command, its two extra refusals, the file names.
  - Config keys `HISTORY_*`; `SITEMAP_PATHS` now has four paths.
  - Things That Will Break: never plot from `daily_scores` or fewer than eight rows; no hand-typed numbers on the page; `HISTORY_EPISODES` wording is Will's.
- [ ] **Step 3: Update `README.md`:** the endpoint table, the project tree, the header actions line and one sentence on the history page and its CSV.
- [ ] **Step 4: Add the history page to `/docs`** where the API and CSV are described: one sentence and the `/history.csv` columns. Run `tests/docs_page_test.py`, expect PASS.
- [ ] **Step 5: Run the whole suite** (`DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/ -q`), expect PASS, then commit "Docs cover the history page, its loader and the backfill mode."

---

### Task 11: Local backfill, preview and Will's review

No production access in this task.

- [ ] **Step 1: Local dry run.**

```bash
DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/rebuild_category_history.py --global-only --start 2019-01-11 --end <yesterday UTC>
```

Expected: no `FAILED` line, `Dates without a composite: 0`. If PortWatch drops the connection, run it again.

- [ ] **Step 2: Check the dry-run CSV against the design's numbers.** From the `composite` rows: first date 2019-01-11; no missing date; 2020-04-15 = 70.7, 2021-03-29 = 67.9, 2021-12-15 = 51.6, 2024-02-15 = 72.8, 2025-04-15 = 70.7, 2026-03-20 = 49.8, each within 1.0; lowest about 46.6 on 2026-05-12, highest about 81.8 on 2023-05-14. A larger difference means an input is short: stop and report which category differs.
- [ ] **Step 3: Local write** (same command plus `--write`; SQLite, so no confirmation variable). Expected: `Rows upserted:` about 25,700.
- [ ] **Step 4: Fill the disk copy and start the preview.**

```bash
DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -c "from data import long_history; print(long_history.refresh_if_due())"
```

Expected `True`. Then start the `gscindex-local` preview (`.claude/launch.json`) and open `/history`.

- [ ] **Step 5: Verify in the browser.** No console errors; the chart starts at 2019 and has six marks; hover shows a date and value; each episode opens to eight categories; `/history.csv` downloads; a sign-up with a test address lands on the confirmation line (local SQLite); the dashboard header shows "History". Check 1280px and 375px widths: no horizontal scroll, labels readable.
- [ ] **Step 6: Fix what the check found, rerun the suite, commit.**
- [ ] **Step 7: STOP. Show Will** a desktop and a phone screenshot, the six episode sentences with their sources, and the one open question from the design: should the Ever Given row also show the chokepoint low in the days after (62.9 on 2021-04-02)? Apply his changes, rerun the tests, commit.

---

### Task 12: Production backfill, push and live check

Each step marked STOP needs Will's answer in chat. Nothing here runs without it.

- [ ] **Step 1: Production dry run** (reads production, writes nothing; note there is no `DATABASE_URL=` here):

```bash
GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/rebuild_category_history.py --global-only --start 2019-01-11 --end 2026-07-22
```

- [ ] **Step 2: Check the summary.** No `FAILED` or `FAILED INPUT` line. `Stored rows left as they are: 0`. The `First stored row on or after 2019-01-11` line shows 2026-07-23 for the keys methodology v1 never stored, which confirms 2026-07-22 as the end date; if it shows another date, stop and report. Rows to write about 24,750. Repeat the Step 2 check of Task 11 on this CSV.
- [ ] **Step 3: STOP. Give Will the summary:** rows to write, how many stored v1 rows will be overwritten (the rows with an old value, by key), the date range of those rows, and that the backup goes to `data/backups/` on this Mac. Ask for his go-ahead.
- [ ] **Step 4: Production write, only after Will says yes.** Run in the background; the upsert sends one row per round trip and can take 15 minutes or more.

```bash
CONFIRM_PROD_REBUILD=yes GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/rebuild_category_history.py --global-only --start 2019-01-11 --end 2026-07-22 --write
```

Expected: `Rows upserted: <the dry run's count>` and a `category_scores_pre_backfill_*.csv` whose row count equals the overwritten count from Step 3. On `database upsert failed`, the transaction rolled back: report it, then rerun.

- [ ] **Step 5: Confirm the write.** Run the Step 1 dry run again. Expected: every key shows `changed` 0 and `no old` 0.
- [ ] **Step 6: If the month is no longer November 2026, update `HISTORY_BACKFILL_MONTH`.** Run the suite, commit.
- [ ] **Step 7: STOP. Wait for Will to say "push it".** Then `git push`. Report local, pushed and live separately.
- [ ] **Step 8: Live check after the Render deploy.** `/history` returns 200 and, within a few minutes of the first cycle, shows the chart; the first row of `/history.csv` is 2019-01-11; no empty `index` cell before 2026-10-23 (report any, do not fill); the six episode values are within rounding of the design's table; `/sitemap.xml` lists `/history`; `/health` is `healthy`.
- [ ] **Step 9: The next day, check Neon compute hours** against the baseline in the infra memory note. The history read adds one query a day in a cycle that already reads.

`data/fallback_snapshot_safe.json` needs no refresh: it holds the last 91 days, and the backfill ends before them.

## Calls made in this plan (check these)

- Providers report a failed history input through a `history_input_failures` attribute, and the script refuses on it. The design left the method open.
- The backfill cannot be combined with `--allow-partial`.
- The chart is an SVG that holds only lines, with all text as HTML on top, so labels stay readable on a phone.
- A disk copy of the history up to 2 days old is shown at startup, so a restart does not show "History is loading" until the first cycle ends.
- Today's CSV row mirrors the live snapshot (index under the no-exclusion rule, category cells from the current scores).
- Sign-up limit: 5 a minute and 30 an hour per visitor.
- The page says the backfill was calculated "in November 2026" from one config value.
- `/history` gets its own share title and description.
- The production write stays on the existing, tested row-by-row upsert and may take 15 minutes or more.
