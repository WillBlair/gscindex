# Global Supply Chain Index

A real-time supply chain health dashboard. It scores eight categories from published data, combines them into a weighted composite index (0 to 100), and serves interactive views and a public JSON API. Two separate sector indexes, Semis and Aero, are built only from their own industry data.

Live site: [gscindex.com](https://gscindex.com)

## Terminal dashboard

The dashboard is a dense dark grid of panes, built to be read at a glance. It
works on desktop, tablet and phone.

- **Index readout:** the weighted index, its health tier, the change versus
  yesterday, a sparkline with a 7D / 30D / 90D selector, and each category's
  score and change.
- **Tabs:** switch between Global, Semis and Aero in the header. Global is the
  composite. Semis and Aero each show their own index and only their own
  categories, at equal weights. A sector index below its coverage minimum shows
  "Not enough data". The map, markets, headlines and briefing are the same on
  every tab.
- **Port map:** hover or tap a marker for its score, the composite and local
  weather behind it, and its disruption summary. On desktop, drag to pan and
  scroll to zoom. On phones and touch screens, drag and scroll zoom are off so
  swipes scroll the page.
- **Markets and chokepoints:** energy, shipping, metals and macro quotes, and
  transits through the main maritime chokepoints as a share of normal (Sources:
  UN Global Platform; IMF PortWatch).
- **Headlines:** sorted HIGH, then MED, then LOW, newest first within each.
  Search by text and filter by severity and topic. Filters, the trend range and
  the tab are remembered for the browser session.
- **Briefing:** the AI summary, with a link to the full report.
- **Category table:** weight, today's score as a bar with a tick for yesterday,
  change, effect on the index, a 30-day sparkline and the source. Hover a
  category name, or tap it on a phone, for each input with its as-of date and
  status, the raw values and the calculation.
- **Header actions:** Methodology (`/docs`), API (a modal), CSV (the selected
  tab's scores, nominal weights, contributions, status and as-of dates) and Subscribe
  (a small popover for the daily briefing email).
- **Refresh:** panes update in place every 5 minutes (every 20 seconds while
  warming up) and keep your filters and scroll position. Refreshing reads the
  latest cache; it does not trigger provider API calls.
- **Data quality:** "yesterday" is exactly the previous UTC date from stored daily
  scores. If that day is missing, the value shows a dash instead of a guess.
  Fallback and stale categories are marked in the table. Missing days are gaps
  in the sparkline, never a line drawn across.

For local use, install `requirements.txt` and run `python app.py` at
`http://127.0.0.1:8050`. FRED data uses the authenticated API when a key is configured, otherwise its
public CSV download. Set optional provider credentials in an untracked `.env`
file. Unavailable readings remain explicitly marked; history is never invented.
`GSC_DISABLE_BACKGROUND=1` disables background fetches when importing the app for
offline tests. Install `pytest` and run `python -m pytest tests/` for the suite.
`tests/test_claude_integration.py` makes paid Claude calls and only runs with
`RUN_LIVE_CLAUDE=1`. If `DATABASE_URL` is set, local runs and tests write to that
database; unset it to use SQLite.

## What It Does

The dashboard fetches economic, shipping, hazard and news data on a background thread (every 5 minutes), caches results in memory and on disk, and renders from cache on each page load. A single **Supply Chain Health Index** summarizes overall conditions, with eight category scores, a 37-port world map, a 7/30/90-day trend, news headlines and an AI briefing.

### Composite Score

The index is a weighted average of eight category scores (0 to 100, where **100 = healthiest**). The full methodology is at [`/docs`](https://gscindex.com/docs).

| Category | Weight | Data source |
|----------|--------|-------------|
| Supply Chain | 20% | NY Fed Global Supply Chain Pressure Index (GSCPI), monthly |
| Chokepoints | 15% | IMF PortWatch daily ship transits through eight corridors (Malacca, Taiwan Strait, Gibraltar, Hormuz, Dover, Red Sea, Bosporus, Panama) |
| Energy & Fuel | 15% | Real Brent, New York Harbor diesel and TTF gas prices (EIA and IMF via FRED), moved by live futures, with a penalty for fast price spikes |
| Trade & Tariffs | 15% | 60% tariff burden (Treasury customs deposits / Census goods imports) and 40% daily Trade Policy Uncertainty (Caldara et al.) |
| Geopolitical Risk | 10% | Caldara-Iacoviello daily Geopolitical Risk index, 30-day mean |
| Freight Volume | 10% | Year-over-year growth of the BTS Freight TSI and of weekly STB rail carloads plus intermodal units |
| Input Costs | 10% | Philadelphia, New York and Dallas Fed prices-paid surveys, real copper and aluminum prices |
| Physical Disruption | 5% | GDACS hazard alerts near the 37 ports, Mississippi River stage at St. Louis |

**Scale.** Most inputs are mapped through three fixed anchors from their own history: 100 = the healthiest 5% of months before 2020, 80 = the pre-2020 median ("normal"), 0 = the worst monthly average on record through 2025. Prices are inflation-adjusted and logged; volumes use year-over-year growth. Chokepoints and Physical Disruption are event scores where a normal day reads about 100. The anchors live in `data/score_anchors.json` and change only with a new methodology version.

**Fallbacks.** Each input has a stale limit and a drop limit, measured from the end of the period it covers. A category with some inputs missing uses the rest. A category with no inputs shows its last stored score, flagged stale and fallback, until that score passes the category's limit; then it is excluded and the composite renormalizes the remaining weights. The weights shown in the table, CSV and API stay nominal, so on those days they do not add up to the composite. History is recomputed from real source data only; gaps stay gaps.

**Claude** (Anthropic) scores headline severity, writes the briefing, the daily report and the port summaries, and keeps a disruption register. None of these feed a category score. The register is stored daily at 0% weight in Geopolitical Risk (shadow mode).

Health tiers: **Healthy** (80 to 100), **Stable** (60 to 79), **Stressed** (40 to 59), **Critical** (0 to 39).

### Sector Indexes

Semis and Aero are separate indexes, each the equal-weight mean of its own categories. They use the same anchored scale, freshness limits and fallback rules as the global categories. Global is never blended into them, and they never change the composite, its disruptions or its degraded flags.

| Index | Category | Data source |
|-------|----------|-------------|
| Semis | Memory Prices | Bank of Japan import price index for MOS memory chips (contract-currency basis), year over year |
| Semis | Logic Chip Prices | Bank of Japan import price index for MOS logic chips (contract-currency basis), year over year |
| Semis | Fab Utilization | Federal Reserve G.17 capacity utilization, semiconductors and electronic components (lower is better) |
| Aero | Aero Throughput | Federal Reserve G.17 capacity utilization, aerospace (higher is better) |
| Aero | Delivery Flow | Census M3 nondefense aircraft inventories over 3-month shipments |
| Aero | Mill Prices | BLS PPI for titanium and nickel-alloy mill shapes, year over year |
| Aero | Forgings & Castings | BLS PPI for titanium forgings, nonferrous forgings and steel investment castings, year over year |

The Semis index needs at least 2 of its 3 categories and the Aero index at least 3 of its 4; otherwise it shows "Not enough data". The Bank of Japan data is normally fetched about once a day, with a 6-hour wait after a failed request, and credited on `/docs`, in the CSV and in the API: "This service uses the API provided by the 'Bank of Japan Time-Series Data Search.' The Bank of Japan does not guarantee the content of the service." Commercial reuse of the memory and logic chip price scores requires the Bank of Japan's permission.

### Dashboard Features

- **Index readout**: score, health tier, same-tab change versus yesterday, and a 7, 30 or 90 day trend
- **Category table**: weight, score bar with yesterday's tick, change, effect on the index, 30-day sparkline, source with a stale or fallback suffix, and a hover or tap detail per category
- **World map**: 37 ports scored by the index composite (60%) + local weather from Open-Meteo (40%), minus one news or AI disruption penalty, with port conditions on hover
- **Headlines**: supply-chain articles with Claude severity (unscored without an API key), sorted by severity then recency, with search and filters
- **AI briefing**: Claude-generated summary (optional; refreshed daily)
- **Market indicators**: energy, shipping, metals and macro quotes via yfinance
- **Tabs**: the Global composite and the separate Semis and Aero sector indexes
- **CSV export**: the selected tab's scores, weights, status and as-of dates (sector exports add each input)
- **Newsletter signup**: email collection stored in PostgreSQL (prod) or SQLite (dev)
- **Auto-refresh**: panes update in place every 5 min, or every 20s while warming up

### Additional Pages

| URL | Description |
|-----|-------------|
| `/` | Main dashboard |
| `/docs` | Platform documentation |
| `/report` | Daily intelligence report (Claude-generated markdown) |
| `/health` | Operational health check (JSON) |
| `/unsubscribe` | Newsletter unsubscribe (signed link from the email) |

## Tech Stack

- **Framework:** Dash 4.4 (Flask), Dash Bootstrap Components (versions pinned in `requirements.txt`)
- **Visualizations:** Plotly
- **Data:** Pandas, NumPy
- **Production server:** Gunicorn (1 worker, 4 gthreads)
- **Database:** PostgreSQL (prod via Neon) / SQLite (dev fallback): subscribers, daily score history, latest dashboard snapshot, disruption register, river gauge readings
- **Data sources:** FRED, NY Fed GSCPI, IMF PortWatch, U.S. Treasury Fiscal Data, Caldara-Iacoviello GPR and TPU files, USDA AgTransport (STB rail), GDACS, USGS, Open-Meteo, yfinance, Bank of Japan Time-Series Data Search. All free; only FRED takes an optional key
- **AI:** Anthropic API (default model `claude-sonnet-5-5`), optional
- **Spreadsheets:** openpyxl reads the TPU workbook
- **Caching:** File-based with atomic writes (1-hour default TTL)
- **Rate limiting:** Flask-Limiter on `/api/v1/*`: 500/hour and 2000/day per visitor IP
- **Python:** 3.13.1 (`.python-version`)
- **Deployment:** Render

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/WillBlair/gscindex.git
   cd gscindex
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your keys (see table below).

5. **Run the application:**
   ```bash
   python app.py
   ```

6. **Open the dashboard:**
   Navigate to [http://127.0.0.1:8050](http://127.0.0.1:8050).

   For production-style serving:
   ```bash
   env -u GUNICORN_CMD_ARGS gunicorn app:server -c gunicorn.conf.py --access-logfile -
   ```

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `FRED_API_KEY` | Recommended | Uses the authenticated FRED API; public CSV downloads support keyless previews |
| `ANTHROPIC_API_KEY` | No | Claude headline severity, briefing, daily report, port summaries, disruption register |
| `ANTHROPIC_MODEL` | No | Claude model (default `claude-sonnet-5-5`) |
| `ANTHROPIC_EFFORT` | No | Claude effort level (default `medium`) |
| `AI_CACHE_TTL_SECONDS` | No | How long each daily Claude result is reused (default `86400`) |
| `NEWS_AI_REFRESH_SECONDS` | No | How often Claude scores new headlines (default `21600`) |
| `DATABASE_URL` | No | PostgreSQL for subscribers, score history, and the cold-start snapshot (omit for SQLite fallback) |
| `ADMIN_TOKEN` | No | `Authorization: Bearer` token for `/api/v1/newsletter-data` and `/api/v1/admin/*` |
| `NEWSLETTER_SECRET` | No | Signs unsubscribe links (falls back to `ADMIN_TOKEN`) |
| `NEWSLETTER_POSTAL_ADDRESS` | Newsletter | Postal address in the email footer (CAN-SPAM) |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `RECIPIENT_EMAIL`, `WEBSITE_URL` | Newsletter | Used by `scripts/send_newsletter.py` |
| `RUN_LIVE_CLAUDE` | No | Set to `1` to run the paid Claude integration tests |
| `GSC_DISABLE_BACKGROUND` | No | Set to `1` to skip the background updater on import |
| `PORT` | No | Gunicorn port (default `10000`); `python app.py` always uses `8050` |

The other sources (Open-Meteo, PortWatch, Treasury, GDACS, USGS, the Bank of Japan and the rest) need no key.

## API Endpoints

```
GET  /api/v1/latest              Public JSON: methodology_version, composite index, per-category objects, degradation flags, disruptions, map markers, sector indexes
GET  /api/v1/newsletter-data     Admin: scores + briefing (Authorization: Bearer ADMIN_TOKEN)
GET  /api/v1/admin/subscribers   Admin: subscriber list (Authorization: Bearer ADMIN_TOKEN)
GET  /unsubscribe?t=TOKEN        Unsubscribe confirmation page
POST /unsubscribe?t=TOKEN        Unsubscribe (also RFC 8058 one-click)
GET  /health                     Monitoring: state, data_age_seconds, last_fetch_status, fallback/stale/excluded categories, per-sector degraded and coverage
GET  /healthz                    Alias for /health
```

All `/api/v1/*` routes are limited to 500 requests per hour and 2000 per day per visitor IP. Admin routes accept the token only in the `Authorization` header.

`/api/v1/latest` returns `methodology_version` (2), `timestamp`, `composite_index` (the stored composite, renormalized under an exclusion), `categories` (per category: `score`, nominal `weight`, `as_of`, `source`, `is_stale`, `is_fallback`, `stored_on`, `inputs`), `degraded`, `fallback_categories`, `excluded_categories`, `stale_categories`, `disruptions`, `map_markers` and `sectors`. `categories` and the flag lists cover the eight global categories only. `sectors` has one block per sector index (`semiconductor`, `aerospace`) with its `index`, `tier`, `coverage`, `degraded`, its own flag lists, its `categories` and its `terms`. The global data is CC-BY-4.0. If you use the chokepoint data, credit "Sources: UN Global Platform; IMF PortWatch". The Semis `terms` carry the Bank of Japan credit and this note: "Commercial reuse of the memory and logic chip price scores requires the Bank of Japan's permission." The Aero data and Semis fab utilization are US government data, CC-BY-4.0 with credit.

## Project Structure

```
gscindex/
├── app.py                      # Entry point, background thread, Dash callbacks, health endpoint
├── config.py                   # Weights, freshness limits, tiers, colors, tunable constants
├── gunicorn.conf.py            # Production server config (Render)
├── .python-version             # Python 3.13.1
├── assets/                     # terminal.css (styles), terminal.js (touch and keyboard helpers)
├── components/                 # Dash UI (layout, terminal panes, terminal math, workspace helpers, map, skeleton)
├── data/
│   ├── aggregator.py           # Runs the providers, fallbacks and exclusions, stored composite
│   ├── score_anchors.json      # Frozen anchors (generated by scripts/compute_anchors.py)
│   ├── cache.py                # Atomic file-based TTL cache
│   ├── database.py             # PostgreSQL/SQLite abstraction (subscribers, score history, snapshot, register, gauges)
│   ├── gscpi_client.py         # NY Fed GSCPI loader
│   ├── portwatch.py            # IMF PortWatch chokepoint transits
│   ├── news_alerts.py          # Headlines (display only), incremental Claude scoring
│   ├── register.py             # Claude disruption register (shadow mode)
│   ├── rss_fetcher.py          # Shared RSS snapshot
│   ├── news_sources.py         # 17 RSS feeds
│   ├── ai_analyst.py           # Claude headline scoring, briefing, report
│   ├── port_analyst.py         # Claude per-port summaries + disruption penalties
│   ├── llm.py                  # Shared Anthropic client (model, effort, fallbacks)
│   ├── ports_data.py           # 37 major port definitions
│   ├── sources/                # Treasury DTS, TPU, GPR, STB rail, Fed surveys, GDACS, waterways, Bank of Japan, Yahoo helpers
│   └── providers/              # supply_chain, chokepoints, energy, tariffs, geopolitical, freight,
│                               # inputs, physical, weather (map only), semis and aero (sector indexes)
├── scoring/
│   ├── anchors.py              # Anchored 0-100 mapping
│   └── engine.py               # Weighted composite and weight renormalization
├── api/
│   ├── routes.py               # Public and newsletter API, rate limiter
│   ├── report.py               # /report page
│   ├── docs.py                 # /docs methodology page
│   ├── briefing.py             # On-demand briefing
│   ├── newsletter.py           # /unsubscribe
│   └── admin.py                # Admin routes
├── scripts/
│   ├── compute_anchors.py      # Rebuilds data/score_anchors.json (a deliberate, versioned change; --sectors-only adds sector anchors)
│   ├── rebuild_category_history.py  # Recomputes stored daily category scores (dry run by default)
│   ├── backtest_composite.py   # Prints the composite at past episodes
│   ├── send_newsletter.py      # Cron job for email delivery
│   └── refresh_fallback_snapshot.py  # Refreshes the committed cold-start snapshot
└── requirements.txt
```

## Architecture (Brief)

```
Background daemon thread (every 5 min)
  → 3-worker pool runs the 8 category providers + news + market data
    + port summaries + chokepoint traffic + the disruption register
  → a separate 2-worker pool runs the 7 sector providers (Semis, Aero)
  → failed categories: last stored score while recent, else excluded (weights renormalized)
  → scoring/engine.py computes the composite, stored in the snapshot
  → each sector index is computed from its own categories only
  → Writes to in-memory cache + disk (atomic)

Main thread (serves requests)
  → Reads from cache and never blocks on API calls
  → Dash callbacks render from cached snapshot
```

**Fallback chain on cold start:** in-memory cache → disk cache (24h TTL) → last snapshot saved in the database (at most hourly) → committed `data/fallback_snapshot_safe.json` if under 14 days old → loading skeleton that reloads once data is ready.

## Customization

- **Category weights:** Edit `CATEGORY_WEIGHTS` in `config.py` (must sum to 1.0). The sector indexes are set in `SECTORS` (equal weights per sector, and a coverage minimum); the header tabs come from `TABS`.
- **Anchors:** `scripts/compute_anchors.py` rewrites `data/score_anchors.json`. Anchors are frozen; regenerating them is a methodology change.
- **Health tiers and colors:** `HEALTH_TIERS` and `COLORS` in `config.py`.
- **New data provider:** Create a module in `data/providers/` inheriting from `BaseProvider`, register it in `data/aggregator.py`, and add its weight, freshness limits and drop limit in `config.py`.
- **Monetizing:** ads, a paid API or a paid tier would need the Bank of Japan's permission in advance, because the Semis memory and logic scores use its API.

## Deployment

**Render (primary):** Build with `pip install -r requirements.txt`, start with `env -u GUNICORN_CMD_ARGS gunicorn app:server -c gunicorn.conf.py --access-logfile -`, health check at `/health`. Use exactly **1 Gunicorn worker**, because the in-memory cache is worker-local. Clear Render's inherited preload option so the updater starts in the worker; see [memory operations](docs/render-memory.md).

## License

[MIT License](LICENSE)
