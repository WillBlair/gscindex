# Global Supply Chain Index

A real-time supply chain health dashboard that aggregates data from six provider categories, computes a weighted composite index (0–100), and serves both interactive visualizations and a public JSON API.

Live site: [gscindex.com](https://gscindex.com)

## Monitoring workspace

The dashboard now provides a responsive overview, ranked pressure drivers, and
industry-specific scorecards. The existing provider calculations and profile
weights are preserved.

- **Port map:** hover or tap a marker for its score, regional pressures,
  disruption summary, and related reporting. Drag to pan, scroll to zoom, or use
  the zoom/reset controls. Bright colors show relative risk.
- **Market ticker:** continuously scrolling quotes; hover or focus to pause.
- **Trend periods:** choose 7, 30, or 90 days; toggle signals through the legend.
  Missing history remains a gap, and sparse series display individual points.
- **Intelligence:** search news by headline, description, or source and filter
  by severity and topic. Headlines are shown first, with descriptions and the
  briefing expanded by default. News rows stay compact with optional details.
  RSS markup is converted to readable text.
- **Export CSV:** download the selected profile's scores, weights, weighted
  contributions, source timestamps, and fallback status.
- **Refresh:** updates panels in place and preserves filters and scroll position.
  Manual refresh reads the latest cache; it does not trigger provider API calls.
- **Data quality:** snapshot timestamps, cached-data notices, and fallback/missing
  categories are explicit. Daily comparisons use the same profile's weights and
  require consecutive, complete observations. Map colors compare relative risk;
  each hover shows the absolute score and health tier alongside port conditions.

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

The dashboard fetches economic, weather, and news data on a background thread (every 5 minutes), caches results in memory and on disk, and renders instantly from cache on each page load. A single **Supply Chain Health Index** score summarizes overall stability, with six category breakdowns, a 37-port world map, 90-day trend charts, news alerts, and an optional AI briefing.

### Composite Score

The index is a weighted average of six category scores (0–100, where **100 = healthiest**):

| Category | Weight | Data Source |
|----------|--------|-------------|
| Weather Disruptions | 10% | [Open-Meteo](https://open-meteo.com/) at 37 major ports (no API key) |
| Supply Chain | 25% | NY Fed GSCPI (monthly), supplemented by a minority daily BDRY proxy |
| Energy & Fuel | 20% | Crude and diesel cost pressure, relative to trailing 2-year ranges |
| Trade & Tariffs | 15% | Trade Policy Uncertainty categorical index (`EPUTRADE`) via [FRED](https://fred.stlouisfed.org/), monthly, plus a daily tariff news nowcast that can only lower the score |
| Freight Flow | 10% | BTS freight throughput growth, supplemented by a minority daily transportation proxy |
| Geopolitical Risk | 20% | 17 RSS feeds ([NewsAPI](https://newsapi.org/) fallback) scored by Claude, or VADER without it, blended 85/15 with an AI port-disruption signal |

Energy & Fuel is a cost-pressure gauge; Freight Flow measures throughput growth. Geopolitical history accumulates from real stored daily scores — there is no proxy backfill. If a provider fails, its category serves a neutral fallback and is flagged in `fallback_categories` (UI badge, `/api/v1/latest`, and `/health`).

Health tiers: **Healthy** (80–100), **Stable** (60–79), **Stressed** (40–59), **Critical** (0–39).

### Dashboard Features

- **Composite overview**: readable score, health band, same-profile daily comparison, and ranked pressure drivers
- **Category cards**: score, 30-day sparkline, 30-day range, delta, and clickable detail modal per category
- **World map**: 37 ports scored by local weather (40%) + regional macro (60%), minus structural risk and news or AI disruption penalties
- **Trend chart**: 7, 30, or 90 days of history for the selected profile's categories
- **News alerts**: supply-chain articles scored by Claude severity (VADER when Claude is unavailable)
- **AI briefing**: Claude-generated summary (optional; cached ~24h)
- **Market indicators**: crude oil, natural gas, copper, gold, VIX via yfinance
- **Port conditions**: source-provided disruption context directly on map hover
- **Newsletter signup**: email collection stored in PostgreSQL (prod) or SQLite (dev)
- **Auto-refresh**: panels update in place every 5 min, or every 20s while warming up

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
- **Database:** PostgreSQL (prod via Neon) / SQLite (dev fallback): subscribers, daily score history, latest dashboard snapshot
- **External APIs:** FRED, NY Fed GSCPI, Open-Meteo (free, no key), yfinance, Silicon Analysts, NewsAPI (fallback), Anthropic API (default model `claude-sonnet-5-5`)
- **Sentiment:** VADER (local, no API)
- **Caching:** File-based with atomic writes (1-hour default TTL)
- **Rate limiting:** Flask-Limiter on `/api/v1/*`: 500/hour and 2000/day per visitor IP
- **Python:** 3.13.1 (`.python-version`)
- **Deployment:** Render (primary), Vercel (serverless alt)

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
| `NEWSAPI_KEY` | No | News fallback, used only when every RSS feed returns nothing |
| `ANTHROPIC_API_KEY` | No | Claude news scoring, briefing, daily report, port summaries, score explanation |
| `ANTHROPIC_MODEL` | No | Claude model (default `claude-sonnet-5-5`) |
| `ANTHROPIC_EFFORT` | No | Claude effort level (default `medium`) |
| `AI_CACHE_TTL_SECONDS` | No | How long each Claude result is reused (default `86400`) |
| `SILICON_ANALYSTS_API_KEY` | No | Raises the Silicon Analysts request cap (semiconductor profile) |
| `DATABASE_URL` | No | PostgreSQL for subscribers, score history, and the cold-start snapshot (omit for SQLite fallback) |
| `ADMIN_TOKEN` | No | `Authorization: Bearer` token for `/api/v1/newsletter-data` and `/api/v1/admin/*` |
| `NEWSLETTER_SECRET` | No | Signs unsubscribe links (falls back to `ADMIN_TOKEN`) |
| `NEWSLETTER_POSTAL_ADDRESS` | Newsletter | Postal address in the email footer (CAN-SPAM) |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `RECIPIENT_EMAIL`, `WEBSITE_URL` | Newsletter | Used by `scripts/send_newsletter.py` |
| `RUN_LIVE_CLAUDE` | No | Set to `1` to run the paid Claude integration tests |
| `GSC_DISABLE_BACKGROUND` | No | Set to `1` to skip the background updater on import |
| `PORT` | No | Gunicorn port (default `10000`); `python app.py` always uses `8050` |

Weather data uses Open-Meteo and requires no API key.

## API Endpoints

```
GET  /api/v1/latest              Public JSON: composite index, categories, fallback flags, disruptions, map markers
GET  /api/v1/newsletter-data     Admin: scores + briefing (Authorization: Bearer ADMIN_TOKEN)
GET  /api/v1/admin/subscribers   Admin: subscriber list (Authorization: Bearer ADMIN_TOKEN)
GET  /unsubscribe?t=TOKEN        Unsubscribe confirmation page
POST /unsubscribe?t=TOKEN        Unsubscribe (also RFC 8058 one-click)
GET  /health                     Monitoring: state, data_age_seconds, last_fetch_status
GET  /healthz                    Alias for /health
```

All `/api/v1/*` routes are limited to 500 requests per hour and 2000 per day per visitor IP. `/api/v1/latest` returns a simplified snapshot suitable for embedding in other projects. Admin routes accept the token only in the `Authorization` header.

## Project Structure

```
gscindex/
├── app.py                      # Entry point, background thread, Dash callbacks, health endpoint
├── config.py                   # Weights, tiers, colors, regions, tunable constants
├── gunicorn.conf.py            # Production server config (Render)
├── .python-version             # Python 3.13.1
├── assets/style.css            # Global stylesheet
├── components/                 # Dash UI (layout, workspace, cards, charts, gauge, feed, market panel)
├── data/
│   ├── aggregator.py           # Orchestrates providers via ThreadPoolExecutor
│   ├── cache.py                # Atomic file-based TTL cache
│   ├── database.py             # PostgreSQL/SQLite abstraction (subscribers, score history, snapshot)
│   ├── gscpi_client.py         # NY Fed GSCPI loader
│   ├── rss_fetcher.py          # Shared RSS snapshot
│   ├── news_sources.py         # 17 RSS feeds
│   ├── ai_analyst.py           # Claude news analysis and briefing
│   ├── port_analyst.py         # Claude per-port summaries + disruption penalties
│   ├── llm.py                  # Shared Anthropic client (model, effort, fallbacks)
│   ├── ports_data.py           # 37 major port definitions
│   └── providers/              # weather, supply_chain, freight, energy, tariffs, geopolitical,
│                               # BDRY/IYT/tariff-news proxies, silicon_analysts, aerospace
├── scoring/
│   └── engine.py               # Weighted composite index calculation
├── api/
│   ├── routes.py               # Public and newsletter API, rate limiter
│   ├── report.py               # /report page
│   ├── docs.py                 # /docs page
│   ├── briefing.py             # On-demand briefing
│   ├── newsletter.py           # /unsubscribe
│   └── admin.py                # Admin routes
├── scripts/
│   ├── send_newsletter.py      # Cron job for email delivery
│   └── refresh_fallback_snapshot.py  # Refreshes the committed cold-start snapshot
└── requirements.txt
```

## Architecture (Brief)

```
Background daemon thread (every 5 min)
  → 3-worker pool fetches 8 providers (6 baseline + 2 industry) + news + market data + port summaries
  → scoring/engine.py computes composite
  → Writes to in-memory cache + disk (atomic)

Main thread (serves requests)
  → Reads from cache — never blocks on API calls
  → Dash callbacks render from cached snapshot
```

**Fallback chain on cold start:** in-memory cache → disk cache (24h TTL) → last snapshot saved in the database (at most hourly) → committed `data/fallback_snapshot_safe.json` if under 14 days old → loading skeleton that reloads once data is ready.

## Customization

- **Category weights:** Edit `CATEGORY_WEIGHTS` and the matching `INDUSTRY_PROFILES` weights in `config.py` (each set must sum to 1.0).
- **Health tiers and colors:** `HEALTH_TIERS` and `COLORS` in `config.py`.
- **New data provider:** Create a module in `data/providers/` inheriting from `BaseProvider`, register it in `data/aggregator.py`, and add a weight in `config.py`.

## Deployment

**Render (primary):** Build with `pip install -r requirements.txt`, start with `env -u GUNICORN_CMD_ARGS gunicorn app:server -c gunicorn.conf.py --access-logfile -`, health check at `/health`. Use exactly **1 Gunicorn worker** — the in-memory cache is worker-local. Clear Render's inherited preload option so the updater starts in the worker; see [memory operations](docs/render-memory.md).

**Vercel:** Serverless entry at `api/index.py` via `vercel.json`.

## License

[MIT License](LICENSE)
