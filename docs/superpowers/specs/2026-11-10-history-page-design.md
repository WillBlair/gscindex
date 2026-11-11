# History page: the Global index, daily since January 2019

- **Date:** 2026-11-10
- **Status:** draft for Will's review. Nothing is built.
- **Decided by Will in chat (2026-11-10):** the page is for practitioners (procurement and supply chain people deciding whether the daily email is worth it); the chart shows the full eight-category index only; Global only, no sector charts; the history is stored by a one-time backfill of the production database.
- **Everything else in this document is Claude's call** unless marked otherwise. The list is in "Calls made by Claude" at the end.
- **Method this builds on:** `docs/superpowers/specs/2026-10-22-score-rebuild-design.md` (methodology v2). No score, weight or anchor changes here.

## Why

- **The site never shows that the index tracks real events.** The readout stops at 90 days. `scripts/backtest_composite.py` computes the index at past episodes, but the result only prints to a terminal.
- **Search engines have almost nothing to index.** The sitemap has three paths (`/`, `/docs`, `/report`) and the dashboard renders in the browser.
- **Reach is the bottleneck.** 7 subscribers on 2026-10-28. A page that shows the record gives a visitor a reason to trust the number before signing up.

## What the data shows (local read-only run, 2026-11-10)

Every provider's `fetch_history` was run for 2,900 days against local SQLite with the FRED windows widened, global categories only. Nothing was written.

- **The full index exists from 2019-01-11.** That is the first day PortWatch chokepoint data has a 7-day mean plus its 4-day publication lag. The other seven categories reach further back.
- **2,861 days, no gaps.** Every day from 2019-01-11 through 2026-11-10 has all eight categories.
- **Range: 46.6 (2026-05-12) to 81.8 (2023-05-14).** 2,176 days Stable, 579 Stressed, 106 Healthy, 0 Critical.
- **Yearly means:** 2019 73.8, 2020 70.9, 2021 62.1, 2022 58.5, 2023 76.4, 2024 73.9, 2025 68.0, 2026 53.5 so far.
- **The 2021 to 2022 low is 48.7 on 2022-05-05.** The 2026 low (46.6) is below it. The index on 2026-11-10 is 48.8.

The run logged no "history unavailable" warning, so every input of every category loaded. Its numbers are the acceptance check for the builder's dry run (small differences from source revisions are expected).

The index at the six research episodes inside this range (the seventh, 2008, is before chokepoint data starts):

| Date | Episode (from the v2 spec) | Index | Change over the 90 days before |
|:---|:---|---:|---:|
| 2020-04-15 | COVID lockdowns | 70.7 | -1.1 |
| 2021-03-29 | Ever Given, Suez Canal | 67.9 | -6.1 |
| 2021-12-15 | NY Fed GSCPI record high | 51.6 | -5.4 |
| 2024-02-15 | Red Sea diversions | 72.8 | -1.9 |
| 2025-04-15 | US tariffs | 70.7 | -1.0 |
| 2026-03-20 | Hormuz | 49.8 | -14.8 |

The categories do register these events even when the index does not: Chokepoints fell 18.0 points in the 90 days to 2024-02-15 (98.7 average in October 2023, 78.6 in February 2024), and fell from about 80 to 62.9 in the ten days after the Ever Given grounding (the trough lands on 2021-04-02, after the 7-day mean and the 4-day publication lag).

**What this means for the page.** The index moves on broad, sustained stress (2021 to 2022, 2026). It stays Stable through four of the six episodes, including April 2020 and the Red Sea diversions. The page has to say that plainly, or a practitioner will conclude the index misses events. See "Honesty rules".

## Goals

- A public page at `/history` with one chart: the Global index for every day from 2019-01-11 to today.
- The six research episodes marked on the chart and listed below it, each with the index that day and all eight category scores. All numbers come from the stored data at request time.
- The chart extends by itself every day, from the scores the site already stores.
- Server-rendered HTML in the Terminal look, readable without JavaScript, so crawlers see the text and the chart.
- A sign-up form on the page.
- A CSV download of the daily history.

## Non-goals (not in this version)

- Semis and Aero history.
- Any day before 2019-01-11, and any partial (fewer than eight categories) line.
- Per-category charts, zoom, pan or range buttons.
- Any change to the dashboard readout, the 90-day sparkline, the API or the newsletter.
- Dataset markup for Google Dataset Search. Worth adding later.

## Anti-goals

- **A made-up or filled point.** A day without all eight stored category scores is a gap in the line.
- **Picking episodes because the chart looks good there.** The episode list is the research list fixed in the v2 spec before this page existed. The page shows the ones where the index barely moved too.
- **Hand-typed index numbers.** Episode values, the low, the high and today are computed from the data.
- **A database call on a page request, or more than one history read a day.** See "Reading the history".
- **Mixing methodology v1 rows into the chart.**

## Constraints

- Free sources only. Develop with `DATABASE_URL=` (SQLite). The local `.env` points at production.
- Neon: every runtime database read happens at most once per clock hour, in the first cycle of the hour. `test_second_cycle_in_an_hour_opens_no_database_connection` must stay green.
- Request handlers read memory only.
- The PortWatch credit ("Sources: UN Global Platform; IMF PortWatch", `chokepoints.CREDIT`) appears on the page and in the CSV. The CSV stays free.
- No Bank of Japan data is on this page (Global only), so the BOJ terms are not triggered. The backfill must not request BOJ.
- All tunables in `config.py`.
- Commit locally. Push only when Will says "push it". A production write needs Will's approval in chat after he has seen the dry-run summary.

## Design

### 1. Backfill (one time)

Extend `scripts/rebuild_category_history.py`. It already recomputes category scores from each provider's `fetch_history`, dates them by publication lag, writes the composite only where all eight categories have a value, is dry-run by default, backs up the rows it overwrites and refuses a Postgres write without `CONFIRM_PROD_REBUILD=yes`.

Changes needed:

- **Global only.** A mode that fetches and writes the eight global categories and the composite, and no sector category. No BOJ request.
- **An end date.** The backfill writes 2019-01-11 through 2026-07-22. The rows from 2026-07-23 (the v2 rebuild of 2026-10-23) and the live-recorded rows from 2026-10-23 stay exactly as they are. The builder confirms 2026-07-22 from the dry run: it is the day before the first stored v2 row.
- **Wide FRED windows.** The runtime lookbacks are trimmed to 3 years. A long rebuild must widen them the way `backtest_composite.widened_fred_windows` does, and restore them.
- **No v1 row left in the range.** The site ran methodology v1 from February 2026 (composite writes began 2026-02-22), so the database holds v1 composites and v1 rows for five of the eight global keys up to 2026-07-22. The backfill overwrites them (after the existing verified backup). `--write` must refuse if any stored composite row, or any stored row for one of the eight global keys, inside the backfill range would be left without a new value.
- **Refuse on a failed input, not only a failed category.** Today the guard is per category. A provider's `fetch_history` logs "history unavailable" for a failed input, drops it and blends the rest (energy, tariffs, freight, inputs, physical), so one failed FRED or GDACS call would write 2,750 days of a category missing an input. The backfill must detect a failed input and refuse to write. How it detects it is the builder's call.
- **Same guards as today otherwise.** PortWatch dropped the connection on the first local run and worked on the second, so a retry is the expected fix.

Expected size, from the local run: 2,750 dates × 9 keys = about 24,750 rows upserted. The backup CSV of overwritten rows is written to `data/backups/`, which is local and not in git.

### 2. Reading the history

- `config.HISTORY_START_DATE = "2019-01-11"`. The page never shows a day before it.
- A loader reads the eight global category rows from `HISTORY_START_DATE` on (`database.export_category_rows` already returns this shape). About 23,000 rows.
- **Which days get a point.** A past day is plotted only when all eight category rows exist for it. Its value is the weighted sum of those eight rows at the nominal weights, the same rule and the same math as the dashboard sparkline (`terminal_data.index_history`). The page does not read `daily_scores`.
  - A day when a category was on a stored fallback or excluded has no row for that category, so it is a gap, as on the dashboard.
  - A v1 day has only five of the eight keys, so it can never be plotted, with or without the backfill.
- **Today.** The live point is the snapshot composite, shown only when no weighted category is excluded. Under an exclusion the line ends at the last stored day. The "today" figure in the numbers row is the dashboard readout's value (`index_summary`), with the same excluded note the dashboard shows.
- It runs in the background fetch cycle, **once per UTC day**, in a first-cycle-of-the-hour slot so the database is already awake. A failed read is retried in the next hour's first cycle.
- The result is kept in memory behind a lock and written to the disk cache (`index_history_long_v1`), so a restart inside the same Render session does not read again that day.
- It is **not** added to the dashboard snapshot, so the hourly snapshot write and `/api/v1/latest` do not grow.
- Before the first load after a deploy, the page shows a one-line "history is loading" state. No error page, no partial chart passed off as the full one.

### 3. The page (`/history`, new `api/history.py`)

Same shell as `/docs` and `/report`: black page, `#07090C` pane, 1px `#1D232B` rules, amber pane titles, JetBrains Mono for numbers and labels, Inter for prose. Top bar with the brand, a Dashboard link and a Methodology link.

Top to bottom:

1. **Heading.** "Global Supply Chain Index, daily since 11 January 2019".
2. **Three numbers in one row,** all computed: today (value, tier), lowest (value, date), highest (value, date).
3. **The chart.** Inline SVG built in Python, full pane width, y axis fixed at 0 to 100.
   - Tier boundaries at 80, 60 and 40 as faint horizontal rules, labelled with the tier names in `TIER_COLORS`.
   - The index as one line. A missing day breaks the line.
   - Each episode is a numbered tick on the line (1 to 6). The number matches the list below, so a phone-width chart carries no long labels.
   - One vertical rule at 2026-10-23, labelled "recorded live from here". Left of it the line is recomputed from source data.
   - A small inline script shows the date and value under the cursor or finger. The chart is complete without it.
4. **One sentence under the chart** that says how to read it: the index moves on broad, sustained stress across categories; a single event shows in its category and may leave the index Stable.
5. **Episodes.** One row per episode: number, date, a one-sentence description with a source link, the index and tier that day, and the index change over the 90 days before. Each row opens (HTML `<details>`, no JavaScript) to all eight categories with the score that day and the change over the same 90 days. Showing all eight means no rule picks which categories look relevant. On phones each episode stacks.
6. **How this history was made.** Short, four points. See "Honesty rules".
7. **Sign-up form.** FREE badge, the same pitch as the dashboard bar, email box, "Sign up free".
8. **Download and credits.** "Download CSV" link, CC-BY-4.0, the PortWatch credit, a link to `/docs`.

### 4. Episode content

`config.HISTORY_EPISODES`: a list of date, short label, one-sentence description and source URL. The six dates are the ones in the table above.

- The description states what happened and when, in one sentence, with a link to a primary or major source. It makes no claim about what the index "caught".
- The builder drafts the six sentences with sources. **Will approves the wording before it ships.** Claude has no verified source yet for the March 2026 Hormuz episode; the builder must find one and must not write it from memory.
- The chokepoint score is a 7-day mean dated 4 days after the transits, so on 2021-03-29 it has only begun to fall. The Ever Given sentence gives the event dates (23 to 29 March 2021) and says the traffic drop shows in the following week. Whether that row should also show the category low in the days after is a question for the screenshot review with Will.

### 5. Honesty rules ("How this history was made")

The page states, in plain words:

- **Recomputed, then recorded.** Days before 2026-10-23 were calculated afterwards from the source data, so they include later revisions and are not what a live site showed that day. (2019-01-11 to 2026-07-22 is calculated on the backfill date; 2026-07-23 to 2026-10-22 was calculated on 2026-10-23.) Monthly and weekly figures are placed on the day they were published. Daily figures (oil and diesel prices, the geopolitical risk and trade policy uncertainty indexes) are placed on their own day.
- **The scale was set on this same history.** 0 is the worst month on record through 2025, so the worst months of 2021 score near 0 in their category by construction. The chart shows how the scale reads the past. It is not a test of prediction.
- **Demand collapses read as healthy costs.** April 2020 reads 70.7 because oil and metal prices fell. Link to the Limitations section of `/docs`.
- **Chokepoint traffic is compared with 2022 to 2023 volumes** for every year, including 2019 to 2021.

### 6. Sign-up

- A plain HTML form posts the email to a new endpoint on this blueprint. It uses `share.valid_email` and `database.add_subscriber`, the same as the dashboard handlers.
- `source` is `signup_source` of the page's query string when it has UTM tags, otherwise `history`, so signups from this page can be counted.
- The endpoint is rate limited per visitor IP (same key function as the API limiter).
- After the post the visitor lands back on `/history` with a confirmation or error line at the form. No JavaScript needed.

### 7. CSV (`/history.csv`)

- One row per day from `HISTORY_START_DATE` to today: `date`, `index`, the eight category keys, `credit`.
- `credit` carries the PortWatch line on every row, following the existing CSV export.
- `index` follows the chart: empty unless all eight categories have a value that day. Category cells show whatever is stored.
- Served from memory with a one-hour cache header.

### 8. Links and search

- "History" link in the dashboard header next to "Methodology" (`components/terminal.py`).
- A link from the Limitations section of `/docs`.
- `/history` added to `config.SITEMAP_PATHS`, which also turns on the share tags and the analytics beacon for it. A page title for it in `api/share.py`.
- `<title>` and meta description that say what the page is: the Global Supply Chain Index for every day since January 2019.

### 9. Housekeeping in the same change

- The `backtest_composite.py` docstring says chokepoints start in 2022 and physical about 2024. The data starts 2019-01-11 and physical has real GDACS readings from 2019. Correct it.
- Update `CLAUDE.md`, the README and `/docs` for the new page, the loader, the config keys and the endpoint.

## Tests

- The page renders from a fixture history with no database connection opened in the request.
- A missing day is a break in the SVG path and an empty CSV cell.
- A day with fewer than eight category rows (a fallback day, a v1 day) is a gap, even when `daily_scores` has a composite for it.
- No live point when a weighted category is excluded.
- No day before `HISTORY_START_DATE` appears, even if the fixture has older rows.
- Episode values, 90-day changes, low, high and today match the fixture.
- The loader reads once per UTC day, and the second cycle in an hour opens no connection (existing guard test).
- No sector key appears on the page or in the CSV.
- The PortWatch credit is on the page and in the CSV.
- Sign-up: valid email is stored with source `history`; an invalid email is refused; the limiter applies.
- Backfill script: global-only mode fetches no sector provider; the end date is respected; `--write` refuses when a stored composite or global-key row in range has no new value, and when any input's history failed.
- `/sitemap.xml` lists `/history`.

## Rollout

1. Script changes, then a local dry run and local write on SQLite.
2. Page, loader, CSV and sign-up built against the local SQLite history.
3. Will sees a screenshot of the page at desktop and phone width, and the episode wording, before anything is final.
4. Production dry run. Will sees the summary (rows to write, v1 rows that will be overwritten, the backup path).
5. Will approves in chat. Production write with `CONFIRM_PROD_REBUILD=yes`.
6. Push when Will says "push it", and only after step 5. Before the backfill the page would open on a chart that starts 2026-07-23 with no episodes on it. (The eight-rows rule in section 2 keeps v1 numbers off the chart either way.)
7. After the deploy, check the live page: first day 2019-01-11, no gaps before 2026-10-23, the six episode values within rounding of the table above.

## Left to the builder

- Flag names and internals of the backfill mode.
- Where the loader lives and how the once-a-day slot is tracked, within the rules in section 2.
- SVG details: sizes, line weight, how the hover readout looks, the phone layout of the episode list.
- The rate limit number for the sign-up endpoint.

## Calls made by Claude (check these)

- The page lives at `/history` as a Flask page like `/docs`, not as a Dash view.
- The chart is inline SVG, not Plotly, so the page is light and readable without JavaScript.
- The history is kept out of the dashboard snapshot and loaded once a day.
- The backfill stops at 2026-07-22 and leaves the existing v2 and live rows untouched.
- v1 composite rows from February to July 2026 are overwritten by the backfill (backed up to a local CSV first).
- The episode list is the six research episodes, including the four where the index stayed Stable.
- Each episode shows all eight categories (score and 90-day change) instead of a picked two.
- A day is plotted only when all eight category rows exist, computed like the dashboard sparkline. Fallback days are gaps.
- The backfill refuses to write when any single input failed, and the page is pushed only after the production backfill.
- A "recorded live from here" rule on the chart at 2026-10-23.
- The sign-up form is on the page, with a new rate-limited endpoint, instead of a link back to the dashboard.
- A CSV download is included.
- No range buttons, category lines or dataset markup in this version.
