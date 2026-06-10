# Global Supply Chain Index

A real-time supply chain health dashboard that aggregates data from six provider categories, computes a weighted composite index (0–100), and serves both interactive visualizations and a public JSON API.

Live site: [gscindex.com](https://gscindex.com)

## What It Does

The dashboard fetches economic, weather, and news data on a background thread (every 5 minutes), caches results in memory and on disk, and renders instantly from cache on each page load. A single **Supply Chain Health Index** score summarizes overall stability, with six category breakdowns, a 37-port world map, 90-day trend charts, news alerts, and an optional AI briefing.

### Composite Score

The index is a weighted average of six category scores (0–100, where **100 = healthiest**):

| Category | Weight | Data Source |
|----------|--------|-------------|
| Weather Disruptions | 10% | [Open-Meteo](https://open-meteo.com/) at 37 major ports (no API key) |
| Supply Chain | 20% | NY Fed WEI + Global Supply Chain Pressure Index via [FRED](https://fred.stlouisfed.org/) |
| Energy Costs | 20% | Live WTI futures (yfinance) normalized against FRED trailing range |
| Trade & Tariffs | 15% | US Economic Policy Uncertainty Index (`USEPUINDXD`) via FRED |
| Inland Freight | 15% | Estimated daily diesel (Heating Oil futures + DOE weekly baseline) |
| Geopolitical Risk | 20% | [NewsAPI](https://newsapi.org/) + VADER sentiment, with optional Gemini AI analysis |

Health tiers: **Healthy** (80–100), **Stable** (60–79), **Stressed** (40–59), **Critical** (0–39).

### Dashboard Features

- **Composite gauge** — semi-circle visualization of the overall index
- **Category cards** — score, 30-day sparkline, delta, and clickable detail modal per category
- **World map** — 37 ports colored by blended local weather (55%) + regional macro (45%)
- **90-day trend chart** — multi-line history for all six categories
- **News alerts** — supply-chain articles scored by VADER negativity
- **AI briefing** — Gemini-generated summary (optional; cached ~24h)
- **Market indicators** — crude oil, natural gas, copper, gold, VIX via yfinance
- **Disruptions table** — auto-generated from categories scoring below 70
- **Newsletter signup** — email collection stored in PostgreSQL (prod) or SQLite (dev)
- **Auto-refresh** — page reloads every 5 min with fresh data, or every 20s while warming up

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
- **Database:** PostgreSQL (prod via Neon) / SQLite (dev fallback) — subscribers only
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
   gunicorn app:server -c gunicorn.conf.py
   ```

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `FRED_API_KEY` | Yes | Powers supply chain, energy, tariffs, and trucking categories |
| `NEWSAPI_KEY` | Yes | Geopolitical scoring, news alerts, and briefing input |
| `GEMINI_API_KEY` | No | AI briefing, daily report, and score validation |
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

**Render (primary):** Build with `pip install -r requirements.txt`, start with `gunicorn app:server -c gunicorn.conf.py`, health check at `/health`. Use exactly **1 Gunicorn worker** — the in-memory cache is worker-local.

**Vercel:** Serverless entry at `api/index.py` via `vercel.json`.

## License

[MIT License](LICENSE)
