# Terminal redesign (gscindex)

Date: 2026-10-22. Owner: Will. Status: draft for approval.

## Intent and the why

gscindex is a global supply chain health console. Its point is one overall score that aggregates every category index, so a reader can see where the global supply chain stands at any moment, plus the reasons it is there. The current Dash UI looks dated and sloppy: the header mixes a profile dropdown, scroll-to tabs (Overview / News / Docs) and four scattered buttons (API, Subscribe, Refresh, CSV); the score panel explains itself ("0 to 100, higher is healthier"); news and the briefing sit below the fold.

Will reviewed six static mockups on 2026-10-22 and chose **Draft E, "Terminal"**, committed as the reference at `docs/superpowers/specs/terminal-draft/e-terminal.html` (with `common.js` and the real snapshot `data.json`; serve that folder with `python3 -m http.server 8765` to view it). He called it "honestly perfect and exactly what I'm going for." The redesign rebuilds the live Dash app to match that draft.

## Goals

- The live site at gscindex.com looks and behaves like Draft E, populated by the real snapshot (`_DATA_CACHE`), for all three industry profiles.
- It looks good on phones, not just usable.
- Every existing data feature that the draft keeps still works: port hover summaries, profile switching, CSV export, newsletter signup, API info, report page, auto-refresh.

## Non-goals

- No changes to scoring math, weights, providers, or what feeds the score. That is the next project ("make the score move with real events"), planned separately.
- No changes to the chip and aerospace providers (a later project).
- No deletions of features beyond what is listed here. Will decides cuts after seeing the new design live.

## Anti-goals (would be a failure even if it works)

- Anything that reads as a SaaS marketing page: light theme, floating rounded cards with soft shadows, gradient washes, frosted glass, pastel pills, colored left-border callouts, clip-art icons.
- Numbers that don't reconcile. The Index row in the category table must equal the weighted sum of the rows shown, using the same weights and the same scores.
- Placeholder or invented data. Unavailable values stay visibly unavailable (fallback categories keep a visible flag).

## Visual system (decided, from Draft E)

- Background pure black `#000000`; panes `#07090C`; rules `#1D232B`; text `#F2F4F7`; dim text `#8A94A3`.
- Amber `#FFB020` for section titles, the selected profile, and the Subscribe outline. Tier colors on the site: Healthy `#35D07F`, Stable `#F5C542`, Stressed `#FF8A3D`, Critical `#FF4D5E`. *(My call: apply these as a UI-only palette; leave `config.HEALTH_TIERS` colors and thresholds unchanged so the newsletter email and stored metadata are untouched. Restyling the email is a later decision.)*
- One continuous grid of panes separated by 1px rules (the grid background shows through 1px gaps). Square corners. No shadows.
- Type: JetBrains Mono for numbers, labels, tables and chrome; Inter for headlines and briefing prose. Load from Google Fonts (current site loads Satoshi/IBM Plex; replace).
- Map: Plotly scattergeo, natural earth projection, land `#151B22`, ocean `#07090C`, borders `#1E252E`, markers colored by tier, sized by risk.

## Layout (decided)

Desktop (three columns: 300px | flexible | 300px):

1. **Header row:** "GSCI Global Supply Chain Index" | profile switch (Global / Semis / Aero, segmented, amber when selected) | right side: "Updated N min ago", Methodology, API, CSV (quiet text links), Subscribe (amber outline, the only button). Remove: Refresh button, Overview/News/Docs scroll tabs, the profile dropdown, the "0 to 100, higher is healthier" text.
2. **Top row:** index readout pane (profile name and timestamp, large score colored by tier, tier word, change vs yesterday and yesterday's value, 30-day index sparkline, compact list of the profile's categories with score and change) | map pane | market quotes pane (crude, natural gas, copper, gold, VIX with change %).
3. **Second row:** headlines table spanning two columns (severity HIGH/MED/LOW colored, category, headline linking out, source, age) | briefing pane (the three Claude briefing bullets) with a "Read full report" link to `/report`.
4. **Third row:** one category table spanning the full width: category, weight, a horizontal bar of today's score with a tick at yesterday's value, today (tier colored), yesterday, change, effect on index (change x weight), 30-day sparkline, data source. Final row: Index, 100%, today, yesterday, change, effect.

Phone (under ~760px): single column in the same order (readout, map, quotes, headlines, briefing, categories). Header wraps to two lines: name + Subscribe, then the profile switch. Methodology/API/CSV move into a small overflow or below the header. Tables drop low-value columns (category, source, yesterday, sparkline) rather than scrolling sideways. No horizontal page scroll.

## Behavior (decided)

- **Profile switch** recalculates the whole page for that profile's weights (readout, category list, table, index row), as in the draft. Ports, headlines, quotes and briefing stay global.
- **Port hover** shows today's summary as on the current site: score and tier, region and macro score, top risk, the Claude port status line, and matched headlines. On touch devices, tap shows the same.
- **Category row hover** shows that category's detail: source, raw value and its label (for example GSCPI 1.28), last updated, description and calculation text from `category_metadata`. Tap on touch devices.
- **Subscribe** opens a small inline email box anchored to the button (not a full modal): email field, submit, and the existing success/error messages from `add_subscriber`. Escape or click-away closes it.
- **CSV** downloads the selected profile's table (existing `snapshot_csv`).
- **API** opens the existing API info (can stay a modal, restyled).
- **Auto-refresh** keeps the current in-place refresh every 5 minutes (20s while provisional); "Updated N min ago" reflects the snapshot time.
- **Report and docs pages** (`/report`, `/docs`) adopt the same terminal look (black, rules, mono/Inter, amber titles).
- **Loading state** (skeleton while the first fetch runs) uses the same grid with dim placeholders, not the old skeleton styling.

## Data needed that the current snapshot lacks

*(My calls, settled after the builder review.)*

- **Yesterday** means the previous calendar date only, read from `daily_category_scores`. Never reach back further. If a category has no row for yesterday (fallback scores are never stored), that row shows a dash for yesterday, change and effect, and the Index row shows a dash for change and effect. The label stays "vs yesterday". Yesterday's index is computed from yesterday's stored rows with the selected profile's weights, so the table reconciles.
- **30-day lines (index and each category)** come from `daily_category_scores` too, not from `category_history`, so a sparkline's previous point always matches the Yesterday column. Today's point is the live score. Coverage checked 2026-10-22: every baseline, chip and aero category has 29-31 stored days in the last 30. Missing days render as gaps.
- These should be loaded by the background refresh and stored in the snapshot (not queried inside callbacks), consistent with the "callbacks read `_DATA_CACHE` only" rule.

## Existing features the draft doesn't show

*(My calls. Will said cuts come after he sees the new design live, so nothing useful is deleted; superseded pieces are folded in.)*

- **News search and the severity/category filters:** kept, as a single compact filter row in the Headlines pane header. The pane lists all tracked headlines in a scrollable table (top 10 visible on desktop), not just the top 10.
- **Trend chart (7/30/90 days):** kept by folding it into the readout pane: a 7/30/90 toggle on the index line. The separate multi-line category trend chart is not carried over; each category row has its own 30-day line.
- **"Main pressures" drivers:** superseded by the category table's Effect column (sorted by weight as in the draft). Not kept as a separate block.
- **Category details modal:** replaced by the category row hover/tap detail (decided above).
- **Generate briefing button:** removed. The briefing is always populated (Claude, or the deterministic fallback), so the button only appeared in an edge case.
- **Freshness line ("N estimated"):** replaced by "Updated N min ago" in the header plus a visible fallback flag on any category serving a fallback value (dim row, "fallback" label in the source column).
- **Footer "Email updates" button:** replaced by the header Subscribe box.

## Bundled small fix

- **News relevance:** "El Nino delays Magic: The Gathering trading cards" (NPR) was scored Medium and shown. Tighten relevance so consumer product availability stories don't pass: add hobby/collectible/consumer-goods terms to the irrelevance filter in `data/providers/geopolitical.py` and state in the Claude analysis prompt (`data/ai_analyst.py` SYSTEM_PROMPT) that consumer product shortages and delays are irrelevant unless they name a port, carrier, chokepoint or trade policy.

## Constraints

- Stay on Dash/Plotly/Flask in this repo; one gunicorn worker; callbacks read from `_DATA_CACHE` only (never call providers or Claude in a callback).
- Local runs: `.env` `DATABASE_URL` points at production Neon. Preview locally with `GSC_DISABLE_BACKGROUND=1` and gunicorn (`GSC_DISABLE_BACKGROUND=1 ./venv/bin/gunicorn -b 127.0.0.1:8050 --threads 4 app:server`), never `python app.py` (its debug path starts the background loop).
- Tests: `./venv/bin/python -m pytest -q tests/ -p no:cacheprovider` must pass; existing UI tests in `tests/workspace_test.py` and `tests/test_ui_palette.py` will need updating where they assert old layout or colors.
- Commit locally; Will pushes with "push it".

## Left to the builder

- How the Dash component tree is organized (new modules vs rewriting `components/layout.py`, `workspace.py`, `cards.py`, `feed.py`, `charts.py`, `gauge.py`, `market_costs.py`, `skeleton.py`) and which old components are deleted.
- Tooltip implementation for category hover (CSS-only, dbc Tooltip, or a small clientside callback), as long as it works on hover and tap and is keyboard reachable.
- Exact spacing, font sizes and breakpoints, matched to Draft E.
