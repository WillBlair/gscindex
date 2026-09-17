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
offline tests. Install `pytest` and run `python -m pytest tests/workspace_test.py`
for the monitoring behavior tests. Gemini integration tests require credentials.

## What It Does

The dashboard fetches economic, weather, and news data on a background thread (every 5 minutes), caches results in memory and on disk, and renders instantly from cache on each page load. A single **Supply Chain Health Index** score summarizes overall stability, with six category breakdowns, a 37-port world map, 90-day trend charts, news alerts, and an optional AI briefing.

### Composite Score

The index is a weighted average of six category scores (0–100, where **100 = healthiest**):

| Category | Weight | Data Source |
|----------|--------|-------------|
| Weather Disruptions | 10% | [Open-Meteo](https://open-meteo.com/) at 37 major ports (no API key) |
| Supply Chain | 25% | NY Fed GSCPI (monthly), supplemented by a minority daily BDRY proxy |
| Energy & Fuel | 20% | Crude and diesel cost pressure, relative to trailing 2-year ranges |
| Trade & Tariffs | 15% | Trade Policy Uncertainty categorical index (`EPUTRADE`) via [FRED](https://fred.stlouisfed.org/), monthly |
| Freight Flow | 10% | BTS freight throughput growth, supplemented by a minority daily transportation proxy |
| Geopolitical Risk | 20% | RSS/[NewsAPI](https://newsapi.org/) + VADER severity, with optional Gemini AI analysis |

Energy & Fuel is a cost-pressure gauge; Freight Flow measures throughput growth. Geopolitical history accumulates from real stored daily scores — there is no proxy backfill. If a provider fails, its category serves a neutral fallback and is flagged in `fallback_categories` (UI badge, `/api/v1/latest`, and `/health`).

Health tiers: **Healthy** (80–100), **Stable** (60–79), **Stressed** (40–59), **Critical** (0–39).

### Dashboard Features

- **Composite overview** — readable score, health band, same-profile daily comparison, and ranked pressure drivers
- **Category cards** — score, 90-day sparkline, 30-day range, delta, and clickable detail modal per category
- **World map** — 37 ports colored by blended local weather (40%) + regional macro (60%)
- **90-day trend chart** — multi-line history for all six categories
- **News alerts** — supply-chain articles scored by VADER negativity
- **AI briefing** — Gemini-generated summary (optional; cached ~24h)
- **Market indicators** — crude oil, natural gas, copper, gold, VIX via yfinance
- **Port conditions** — source-provided disruption context directly on map hover
- **Newsletter signup** — email collection stored in PostgreSQL (prod) or SQLite (dev)
- **Auto-refresh** — panels update in place every 5 min, or every 20s while warming up

### Additional Pages

| URL | Description |
|-----|-------------|
| `/` | Main dashboard |
| `/docs` | Platform documentation |
| `/report` | Daily intelligence report (Gemini-generated markdown) |
| `/health` | Operational health check (JSON) |

## Tech Stack

- **Framework:** Dash 2.14+ (Flask), Dash Bootstrap Components
- **Visualizations:** Plotly
- **Data:** Pandas, NumPy
- **Production server:** Gunicorn (1 worker, 8 gthreads)
- **Database:** PostgreSQL (prod via Neon) / SQLite (dev fallback) — subscribers + daily score history
- **External APIs:** FRED, NewsAPI, Open-Meteo (free, no key), yfinance, Google Generative AI
- **Sentiment:** VADER (local, no API)
- **Caching:** File-based with atomic writes (1-hour default TTL)
- **Rate limiting:** Flask-Limiter (2000/day, 500/hour)
- **Python:** 3.11
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
| `NEWSAPI_KEY` | Yes | Geopolitical scoring, news alerts, and briefing input |
| `GEMINI_API_KEY` | No | AI briefing, daily report, and news analysis |
| `DATABASE_URL` | No | PostgreSQL for newsletter subscribers (omit for SQLite fallback) |
| `ADMIN_TOKEN` | No | Protects `/api/v1/newsletter-data` and admin endpoints |
| `PORT` | No | Server port (default `10000` in prod, `8050` in dev) |

Weather data uses Open-Meteo and requires no API key.

## API Endpoints

```
GET /api/v1/latest              Public JSON: composite index, categories, disruptions, map markers
GET /api/v1/newsletter-data     Admin: full briefing snapshot (?token=ADMIN_TOKEN)
GET /api/v1/admin/subscribers   Admin: subscriber list (Bearer ADMIN_TOKEN)
GET /health                     Monitoring: state, data_age_seconds, fetch_status
GET /healthz                    Alias for /health
```

The public `/api/v1/latest` response is rate-limited and returns a simplified snapshot suitable for embedding in other projects.

## Project Structure

```
gscindex/
├── app.py                      # Entry point, background thread, Dash callbacks, health endpoint
├── config.py                   # Weights, tiers, colors, regions, tunable constants
├── gunicorn.conf.py            # Production server config (Render)
├── components/                 # Dash UI (layout, cards, charts, gauge, feed, market panel)
├── data/
│   ├── aggregator.py           # Orchestrates providers via ThreadPoolExecutor
│   ├── cache.py                # Atomic file-based TTL cache
│   ├── database.py             # PostgreSQL/SQLite abstraction (subscribers)
│   ├── ai_analyst.py           # Gemini news analysis and briefing
│   ├── ai_validator.py         # Gemini score validation
│   ├── ports_data.py           # 37 major port definitions
│   └── providers/              # weather, supply_chain, energy, tariffs, trucking, geopolitical
├── scoring/
│   └── engine.py               # Weighted composite index calculation
├── api/
│   ├── routes.py               # Public and newsletter API
│   ├── report.py               # /report page
│   ├── docs.py                 # /docs page
│   └── admin.py                # Admin routes
├── scripts/
│   └── send_newsletter.py      # Cron job for email delivery
└── requirements.txt
```

## Architecture (Brief)

```
Background daemon thread (every 5 min)
  → ThreadPoolExecutor fetches 6 providers + news + market data in parallel
  → scoring/engine.py computes composite
  → Writes to in-memory cache + disk (atomic)

Main thread (serves requests)
  → Reads from cache — never blocks on API calls
  → Dash callbacks render from cached snapshot
```

**Fallback chain on cold start:** in-memory cache → disk cache (24h TTL) → loading skeleton with 20s auto-reload.

## Customization

- **Category weights:** Edit `CATEGORY_WEIGHTS` in `config.py` (must sum to 1.0).
- **Health tiers and colors:** `HEALTH_TIERS` and `COLORS` in `config.py`.
- **New data provider:** Create a module in `data/providers/` inheriting from `BaseProvider`, register it in `data/aggregator.py`, and add a weight in `config.py`.

## Deployment

**Render (primary):** Build with `pip install -r requirements.txt`, start with `env -u GUNICORN_CMD_ARGS gunicorn app:server -c gunicorn.conf.py --access-logfile -`, health check at `/health`. Use exactly **1 Gunicorn worker** — the in-memory cache is worker-local. Clear Render's inherited preload option so the updater starts in the worker; see [memory operations](docs/render-memory.md).

**Vercel:** Serverless entry at `api/index.py` via `vercel.json`.

## License

[MIT License](LICENSE)
