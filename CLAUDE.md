# CLAUDE.md — Global Supply Chain Index

## Project Overview

Real-time supply chain health dashboard built with Python/Dash. Aggregates data from 6 provider categories, computes a weighted composite index (0–100), and serves both interactive visualizations and a public JSON API.

## Tech Stack

- **Framework:** Dash 2.14+ (wraps Flask), Dash Bootstrap Components
- **Visualizations:** Plotly
- **Data:** Pandas, NumPy
- **Production server:** Gunicorn (1 worker, 4 gthreads)
- **Databases:** PostgreSQL (prod via Neon) / SQLite (dev fallback) — subscribers only
- **External APIs:** FRED, NewsAPI, Open-Meteo (free, no key), yfinance, Google Generative AI
- **Sentiment:** VADER (local, no API)
- **Caching:** File-based with atomic writes, 1-hour default TTL
- **Rate limiting:** Flask-Limiter (2000/day, 500/hour)
- **Python:** 3.11
- **Deployment:** Render (primary), Vercel (serverless alt)

## Running the App

```bash
python app.py                                    # Dev: http://127.0.0.1:8050
gunicorn app:server -c gunicorn.conf.py          # Prod
```

## Environment Variables

```bash
FRED_API_KEY        # Required — powers 5 of 6 categories
NEWSAPI_KEY         # Required — geopolitical scoring + alerts
DATABASE_URL        # PostgreSQL (omit for SQLite fallback)
ADMIN_TOKEN         # Protects /api/v1/newsletter-data
GEMINI_API_KEY      # Optional — AI briefing + score validation
PORT                # Server port (default 10000)
```

## Project Structure

```
app.py                    # Entry point, background thread, Dash callbacks, health endpoint
config.py                 # ALL tunable constants: weights, tiers, colors, regions
data/
  aggregator.py           # Orchestrates providers via ThreadPoolExecutor(max_workers=3)
  cache.py                # Atomic file-based TTL cache
  database.py             # PostgreSQL/SQLite lazy-resolved abstraction
  status.py               # Loading status messaging
  providers/
    base.py               # Abstract BaseProvider interface
    weather.py            # Open-Meteo: 14 shipping hubs, linear deductions
    supply_chain.py       # NY Fed WEI via FRED
    energy.py             # WTI crude (yfinance) normalized against FRED 5yr range
    tariffs.py            # Policy Uncertainty Index via FRED
    trucking.py           # Diesel PPI via FRED
    geopolitical.py       # NewsAPI + VADER, three-tier fallback
    fred_client.py        # Shared FRED API wrapper
  fallback_snapshot_safe.json  # Committed cold-start fallback (only cache file in git)
components/
  layout.py               # Main dashboard assembly
  cards.py                # Category health cards with sparklines
  charts.py               # 90-day trend lines + world map
  gauge.py                # Semi-circle composite gauge
  feed.py                 # News alerts + AI briefing panel
  market_costs.py         # Market indicators (oil, gas, copper, gold, VIX)
  skeleton.py             # Loading skeleton UI
scoring/
  engine.py               # Weighted composite with validation
api/
  routes.py               # /api/v1/latest (public), /api/v1/newsletter-data (admin)
  briefing.py             # AI briefing generation
  report.py               # Report endpoints
  admin.py                # Admin routes
  docs.py                 # API documentation
scripts/
  send_newsletter.py      # Cron job for email delivery
```

---

## Architecture

### Data Flow

```
Background daemon thread (every 5 min)
  → ThreadPoolExecutor fetches 6 providers + news + market data in parallel
  → scoring/engine.py computes composite
  → Writes to _DATA_CACHE (memory, protected by _LOCK) + disk (atomic)

Main thread (serves requests)
  → Reads _DATA_CACHE under _LOCK — NEVER blocks on API calls
  → Dash callbacks render from cached snapshot
  → serve_layout() called on every page load
```

### Fallback Chain (cold-start resilience)

1. In-memory `_DATA_CACHE` (current session)
2. Disk cache via `get_cached_dashboard()` (< 24h TTL)
3. `data/fallback_snapshot_safe.json` (committed, days old but always present)
4. `build_skeleton_layout()` (shown during initial fetch, triggers 20s auto-reload)

### Threading Model

```python
_DATA_CACHE = None           # Latest snapshot
_LAST_UPDATE = None          # UTC datetime
_DATA_IS_FRESH = False       # True after first successful fetch
_LAST_FETCH_STATUS = "starting"  # starting|running|ok|failed
_LOCK = threading.Lock()     # Protects ALL globals above
```

All global state reads/writes MUST use `with _LOCK:`. The background thread runs as a daemon and sleeps 300s between fetches (60s on error).

### Auto-Refresh

- **Provisional** (skeleton/stale data): page reloads every 20s via `dcc.Interval`
- **Fresh data**: page reloads every 5 min
- Uses `clientside_callback` to trigger `window.location.reload()`

---

## Scoring System

### Weights (config.py — must sum to exactly 1.0)

```python
CATEGORY_WEIGHTS = {
    "weather":       0.10,
    "supply_chain":  0.20,
    "energy":        0.20,
    "tariffs":       0.15,
    "trucking":      0.15,
    "geopolitical":  0.20,
}
```

The engine validates `sum(weights) ≈ 1.0` (atol=0.01) and raises `ValueError` if not. It does NOT auto-normalize.

### Health Tiers (higher score = healthier)

```python
HEALTH_TIERS = [
    {"min": 80, "max": 100, "label": "Healthy",   "color": "#00d97e"},
    {"min": 60, "max": 79,  "label": "Stable",    "color": "#f6c343"},
    {"min": 40, "max": 59,  "label": "Stressed",  "color": "#fd7e14"},
    {"min": 0,  "max": 39,  "label": "Critical",  "color": "#e63757"},
]
```

### Composite Calculation (scoring/engine.py)

```python
composite = sum(weights[cat] * scores[cat] for cat in weights)
return float(np.clip(composite, 0.0, 100.0))
```

Also provides `compute_composite_series()` for time-series variant used in sparklines.

---

## Provider Contract

### BaseProvider Interface (data/providers/base.py)

```python
class BaseProvider(ABC):
    category: str = ""  # Must match a key in CATEGORY_WEIGHTS

    @abstractmethod
    def fetch_current(self) -> tuple[float, dict]:
        """Return (score: 0–100 where 100=healthiest, metadata: dict)"""

    @abstractmethod
    def fetch_history(self, days: int) -> pd.Series:
        """Return scores indexed by pd.DatetimeIndex"""
```

### Required Metadata Keys

```python
{
    "source": "API name",
    "raw_value": "123.45",
    "raw_label": "What raw_value represents",
    "description": "Why this affects supply chains...",
    "calculation": "Score = formula...",
    "updated": "2026-03-10 15:30:00",
}
```

### Provider-Specific Patterns

**Weather** — Continuous linear deductions (not binary thresholds):
```python
score = 100.0
score -= _wmo_deduction(wmo_code)      # Up to -60
score -= _wind_deduction(wind_kmh)     # Linear ramp, max -25
score -= _precip_deduction(precip_mm)  # Linear ramp, max -90
score -= _temp_deduction(temp_c)       # Extremes both ends, max -50
return max(0.0, min(100.0, score))
```

**Geopolitical** — Three-tier fallback, negative-only scoring:
```
Tier 1: Cached Gemini AI analysis (4h cache)
Tier 2: Live RSS + VADER sentiment (2–3 seconds)
Tier 3: Neutral baseline 85.0

Score = 100.0 + sum(negative_severity_scores)  # Only negative news reduces score
```

**Energy** — yfinance real-time price normalized against FRED 5-year range (inverse: lower price = higher score)

**FRED-based providers** (supply_chain, tariffs, trucking) — use shared `fred_client.py` and `normalize_series_inverse()`:
```python
def normalize_series_inverse(series):
    """Lower raw value → Higher score. Returns 0–100 Series."""
    return ((1 - (series - min) / (max - min)) * 100).round(1)
```

### Error Handling

Provider failures never crash the app:
```python
try:
    score, metadata = provider.fetch_current()
except Exception as exc:
    logger.error("Provider %s failed: %s", cat, exc)
    score = 50.0  # Neutral fallback
```

---

## Caching (data/cache.py)

### Core API

```python
get_cached(key, ttl=3600)           # Returns None if missing or expired
set_cached(key, data)                # Atomic: temp file → fsync → os.replace
get_cached_dashboard()               # 24h TTL (stale data > no data)
set_cached_dashboard(data)           # Converts Pandas types to JSON-safe
reconstruct_dashboard_state(data)    # Rebuilds Pandas types from JSON
```

### TTL Defaults

| Data | TTL |
|------|-----|
| Weather | 30 min |
| FRED series | 1 hour |
| News/RSS | 4 hours |
| Dashboard snapshot | 24 hours |

### Critical Rules

- Cache keys are versioned (e.g., `weather_current_v2`, `newsapi_briefing_v14`) — bump the version to bust stale cache on schema changes
- Always use `set_cached()` / `_write_text_atomic()`, never write cache files directly
- Cache dir: `data/.cache/` (dev) or `/tmp/supply_chain_cache/` (Vercel/Lambda)
- Only `fallback_snapshot_safe.json` is committed to git

---

## Aggregator (data/aggregator.py)

### Parallel Execution

```python
ThreadPoolExecutor(max_workers=3)
# Timeouts: providers=45s, news AI=120s, market=30s, port summaries=60s
```

### Series Alignment (critical for sparklines)

```python
dates = pd.date_range(end=today, periods=HISTORY_DAYS, freq="D")
aligned = hist_series.reindex(dates, method="ffill")
aligned = aligned.fillna(current_score)
aligned.iloc[-1] = current_score  # Force last point = today's live score
```

This prevents sparklines from showing yesterday's stale value as today.

### Map Markers

60% local weather score + 40% global macro score per port. 37 ports total with lat/lon, score, description. Generated in `_derive_map_markers()`.

### Post-Processing

- Fresh news score overwrites geopolitical history's last point
- AI validation via Gemini (optional, stored but not applied)
- Disruptions generated from any category scoring < 70

---

## Dashboard Snapshot Structure

The `_DATA_CACHE` dict returned by `aggregate_data()`:

```python
{
    "last_updated_utc": "2026-03-10T15:30:00Z",
    "dates": pd.DatetimeIndex,                       # 90 daily dates
    "category_history": dict[str, pd.Series],        # 6 series, one per category
    "current_scores": dict[str, float],              # 6 scores
    "category_metadata": dict[str, dict],            # 6 metadata dicts
    "map_markers": list[dict],                       # 37 ports: name, lat, lon, score, description
    "alerts": list[dict],                            # Up to 30: timestamp, severity, title, body, category, url
    "briefing": str,                                 # AI-generated bullet points
    "full_report": str,                              # Markdown report
    "disruptions": list[dict],                       # event, region, impact_score, categories
    "provider_errors": dict[str, str | None],        # None = OK, str = error message
    "market_data": dict,                             # Crude Oil, Gas, Copper, Gold, VIX: price, prev, change_pct
    "ai_validation": dict,                           # score, reasoning, adjustment
}
```

---

## UI Patterns (components/)

### Styling

- Dark theme: background `#0f1117`, cards `#1a1d26`, text `#e1e4ea`, grid `#1e2130`
- All colors defined in `config.py` `COLORS` and `CATEGORY_COLORS` dicts
- Dash Bootstrap Components + inline styles only — no separate CSS files
- Plotly charts use `dragmode=False`, transparent backgrounds, `hovermode="x unified"`

### Cards (cards.py)

Each card shows: label, weight badge, score (colored by tier), delta arrow, 30-point sparkline, 30-day min/max range. Cards are clickable (`id=f"card-{cat}"`, `n_clicks=0`) and open a details modal.

### Charts (charts.py)

90-day trend chart: one `go.Scatter` per category, lines colored by `CATEGORY_COLORS`. World map: `go.Scattergeo` with port markers colored/sized by score.

### Callbacks (app.py)

- Modal callback: uses `ctx.triggered_id` to detect which card was clicked
- Newsletter callback: validates email, calls `add_subscriber()`
- All callbacks read from `_DATA_CACHE` — never trigger fetches
- Use `dash.no_update` to skip outputs that shouldn't change

---

## API Endpoints (api/routes.py)

```
GET /api/v1/latest              # Public: composite, categories, disruptions, map_markers
GET /api/v1/newsletter-data     # Admin: requires ?token=ADMIN_TOKEN
GET /health                     # Monitoring: state, data_age_seconds, fetch_status
GET /healthz                    # Alias for /health
```

Health returns HTTP 200 for healthy/warming_up, HTTP 503 for degraded (data > 30 min old).

---

## Database (data/database.py)

Lazy dual-backend: resolves PostgreSQL vs SQLite at connection time, not import time. This lets `dotenv` load environment variables first.

Tables: `subscribers` (email, subscribed_at, is_active) and `daily_scores` (date, score).

---

## Development Guidelines

### Adding a New Provider

1. Create `data/providers/my_provider.py` inheriting `BaseProvider`
2. Set `category = "my_category"` matching a key in `CATEGORY_WEIGHTS`
3. Implement `fetch_current()` → `tuple[float, dict]` with required metadata keys
4. Implement `fetch_history(days)` → `pd.Series` with `DatetimeIndex`
5. Register in `data/aggregator.py`'s `_PROVIDERS` list
6. Add weight in `config.py` (adjust others so sum stays 1.0)
7. Add to `CATEGORY_LABELS`, `CATEGORY_COLORS` in `config.py`
8. Add card in `components/cards.py`, line in `components/charts.py`

### Modifying the UI

- Layout structure: `components/layout.py`
- Cards: `components/cards.py` — follow existing card pattern (score + delta + sparkline)
- Charts: `components/charts.py` — use `go.Scatter` with `CATEGORY_COLORS`
- Callbacks: bottom of `app.py` — use `ctx.triggered_id`, return `dash.no_update` for unchanged outputs
- Styling: inline styles using `config.py` colors, never separate CSS

### Editing Scores and Thresholds

All tunable values live in `config.py`. Never put magic numbers in provider or component code.

---

## Deployment

### Render (primary)

- Deploy from `main` branch
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:server -c gunicorn.conf.py`
- Health check: `/health`
- Ephemeral filesystem — disk cache only survives within a session

### Boot Sequence on Render

1. Disk cache empty → load `fallback_snapshot_safe.json`
2. Show skeleton UI (provisional)
3. Background thread fetches fresh data (~50–60s)
4. Auto-reload at 20s interval picks up fresh data

---

## Things That Will Break If You're Not Careful

- **Multiple Gunicorn workers** — `_DATA_CACHE` is worker-local. Each worker fetches independently and serves inconsistent data. Always use 1 worker.
- **Blocking the main thread** — callbacks must read from cache only. Any API call in a callback will hang the page.
- **Weights not summing to 1.0** — engine raises `ValueError`. No silent failure, but tests won't catch it if you forget.
- **Writing cache files directly** — bypasses atomic write protection. Use `data/cache.py` helpers.
- **Forgetting `aligned.iloc[-1] = current_score`** — sparklines will show yesterday's value as today. Always force the last point.
- **Not bumping cache key version** — old schema data will be deserialized into new code. Bump the version suffix when changing what's cached.
- **Geopolitical score direction** — only negative news reduces the score (from base 100). Don't add positive sentiment boosts.
- **Provider return type** — must return `tuple[float, dict]`, not bare `float`. The aggregator handles both for legacy reasons but new providers should always use the tuple.

## Known Inconsistencies

- Some providers use hardcoded fallback scores (75.0 for weather, 85.0 for geopolitical, 50.0 for others). These should be configurable but aren't yet.
- `_KEY_MIGRATIONS` in app.py maps legacy category names ("ports"→"supply_chain"). This should live in a migration module.
- Weather provider has 14 hubs hardcoded in the file. Should be in config.py.
