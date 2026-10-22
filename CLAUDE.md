# CLAUDE.md — Global Supply Chain Index

## Project Overview

Real-time supply chain health dashboard built with Python/Dash. Aggregates data from 6 baseline categories (plus optional semiconductor and aerospace industry profiles), computes a weighted composite index (0–100), and serves both interactive visualizations and a public JSON API.

## Tech Stack

- **Framework:** Dash 4.4 (wraps Flask), Dash Bootstrap Components (versions pinned in `requirements.txt`)
- **Visualizations:** Plotly
- **Data:** Pandas, NumPy
- **Production server:** Gunicorn (1 worker, 4 gthreads, 120s timeout)
- **Databases:** PostgreSQL (prod via Neon) / SQLite (dev fallback). Subscribers, daily score history, latest dashboard snapshot, newsletter send log
- **External APIs:** FRED, NY Fed GSCPI CSV, Open-Meteo (free, no key), yfinance, Silicon Analysts, Anthropic API (Claude, default model `claude-sonnet-5-5`)
- **Sentiment:** VADER (local, no API)
- **Caching:** File-based with atomic writes, 1-hour default TTL
- **Rate limiting:** Flask-Limiter on `/api/v1/*` only: 500/hour and 2000/day per visitor IP
- **Python:** 3.13.1 (`.python-version`)
- **Deployment:** Render

## Running the App

```bash
python app.py                                    # Dev: http://127.0.0.1:8050
gunicorn app:server -c gunicorn.conf.py          # Prod
python -m pytest tests/                          # Tests (pytest is not in requirements.txt)
RUN_LIVE_CLAUDE=1 python -m pytest tests/test_claude_integration.py   # Paid: real Claude calls
```

`GSC_DISABLE_BACKGROUND=1` stops the background updater when the app is imported (tests, local previews).

## Environment Variables

```bash
FRED_API_KEY              # Recommended. Without it FRED series come from the public CSV download
DATABASE_URL              # PostgreSQL (omit for SQLite fallback)
ADMIN_TOKEN               # Bearer token for /api/v1/newsletter-data and /api/v1/admin/*
ANTHROPIC_API_KEY         # Optional. AI news scoring, briefing, report, port summaries, score explanation
ANTHROPIC_MODEL           # Default claude-sonnet-5-5
ANTHROPIC_EFFORT          # Default medium
AI_CACHE_TTL_SECONDS      # Default 86400 (one Claude run per component per day)
AI_FAILURE_RETRY_SECONDS  # Default 3600
SILICON_ANALYSTS_API_KEY  # Optional. Raises the Silicon Analysts daily request cap
NEWSLETTER_SECRET         # Signs unsubscribe links (falls back to ADMIN_TOKEN)
NEWSLETTER_POSTAL_ADDRESS # Footer address for the newsletter (CAN-SPAM)
SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, RECIPIENT_EMAIL, WEBSITE_URL  # Newsletter cron
RUN_LIVE_CLAUDE           # Set to 1 to run the paid Claude integration tests
PORT                      # Server port (default 10000)
```

Other tunables read from the environment in `config.py`: `NEWS_RSS_REFRESH_SECONDS`, `FRED_SCORE_LOOKBACK_DAYS`, `GSCPI_SCORE_SCALE`, `SUPPLY_CHAIN_PROXY_WEIGHT`, `TARIFFS_PROXY_WEIGHT`, `FREIGHT_PROXY_WEIGHT`, `PORT_DISRUPTION_WEIGHT`, `INDUSTRY_PROVIDER_CACHE_TTL`, `FREIGHT_YOY_BASELINE`, `FREIGHT_YOY_SLOPE`.

## Project Structure

```
app.py                    # Entry point, startup layers, background thread, Dash callbacks, /health, security headers
config.py                 # ALL tunable constants: weights, profiles, tiers, colors, AI/cache settings
gunicorn.conf.py          # 1 worker, 4 threads, gthread
assets/style.css          # Global stylesheet (:root tokens kept in sync with config.COLORS)
data/
  aggregator.py           # Orchestrates providers via RefreshTasks(max_workers=3)
  cache.py                # Atomic file-based TTL cache
  database.py             # PostgreSQL/SQLite lazy-resolved abstraction
  status.py               # Loading status messaging
  runtime.py              # RefreshTasks executor, @serialized, memory usage
  llm.py                  # Shared Anthropic client used by every AI call
  ai_analyst.py           # Claude news scoring + briefing, full report, score explanation, newsletter briefing
  port_analyst.py         # Claude per-port summaries + disruption penalties, aggregate port score
  gscpi_client.py         # NY Fed GSCPI CSV loader (6h cache, 60-day stale fallback)
  rss_fetcher.py          # Shared 5-minute RSS snapshot (4 feeds at a time)
  news_sources.py         # 17 RSS feeds
  news_selection.py       # Low-signal filtering, dedupe, newsletter article selection
  ports_data.py           # 37 major ports (name, lat, lon, keywords)
  unsubscribe.py          # HMAC-signed unsubscribe tokens
  providers/
    base.py               # Abstract BaseProvider interface
    weather.py            # Open-Meteo: all 37 ports, linear deductions
    supply_chain.py       # NY Fed GSCPI + daily BDRY proxy; WEI fetched for context only
    freight_rate_proxy.py # BDRY dry-bulk ETF, inverse percentile (supply_chain proxy)
    freight.py            # BTS Freight TSI (TSIFRGHT) YoY + daily IYT proxy
    transport_equity_proxy.py  # IYT transportation ETF, direct percentile (freight proxy)
    energy.py             # WTI crude (CL=F live, DCOILWTICO history) + DOE diesel (GASDESW)
    tariffs.py            # EPUTRADE (monthly) + tariff news nowcast that can only lower the score
    tariff_news_nowcast.py # VADER score of tariff-tagged RSS articles
    geopolitical.py       # RSS + Claude/VADER severity, port-disruption blend
    silicon_analysts.py   # Semiconductor profile: 4 chip categories
    aerospace.py          # Aerospace profile: 4 aero categories
    fred_client.py        # Shared FRED API wrapper (public CSV when no key)
  fallback_snapshot_safe.json  # Committed cold-start fallback (only cache file in git)
components/
  layout.py               # Main dashboard assembly, API and newsletter modals
  workspace.py            # Overview, pressure drivers, freshness, CSV export, profiles
  workspace_callbacks.py  # In-place refresh callbacks
  cards.py                # Category health cards with sparklines
  charts.py               # Trend lines + world map
  gauge.py                # Composite gauge
  feed.py                 # News alerts + AI briefing panel
  market_costs.py         # Market indicators (oil, gas, copper, gold, VIX)
  skeleton.py             # Loading skeleton UI
scoring/
  engine.py               # Weighted composite with validation
  explanation.py          # Score explanation helpers
api/
  routes.py               # /api/v1/latest (public), /api/v1/newsletter-data (admin), limiter setup
  admin.py                # /api/v1/admin/subscribers, verify_admin()
  newsletter.py           # /unsubscribe (GET confirm page, POST unsubscribe)
  briefing.py             # On-demand AI briefing (button)
  report.py               # /report page
  docs.py                 # /docs page
scripts/
  send_newsletter.py      # Cron job for email delivery
  refresh_fallback_snapshot.py  # Rewrites data/fallback_snapshot_safe.json from DB/disk
```

---

## Architecture

### Data Flow

```
Background daemon thread (every 5 min)
  → RefreshTasks pool (3 workers) runs 8 providers (6 baseline + 2 industry) + news + market + port summaries
  → Geopolitical score taken from the fresh news result, blended with the port-disruption signal
  → scoring/engine.py computes composite
  → Writes to _DATA_CACHE (memory, protected by _LOCK) + disk (atomic)
  → Writes daily scores and the dashboard snapshot to the database (each at most hourly)

Main thread (serves requests)
  → Reads _DATA_CACHE under _LOCK — NEVER blocks on API calls
  → Dash callbacks render from cached snapshot
  → serve_layout() called on every page load (re-reads the disk cache if memory is stale or older)
```

### Fallback Chain (cold-start resilience)

1. In-memory `_DATA_CACHE` (current session)
2. Disk cache via `get_cached_dashboard()` (< 24h TTL)
3. Database snapshot via `load_dashboard_snapshot()` (`dashboard_snapshot` table, saved at most hourly and only when no baseline category is on a fallback)
4. `data/fallback_snapshot_safe.json` (committed), only if younger than `FALLBACK_SNAPSHOT_MAX_AGE_DAYS` (14). Alerts, briefing, report, and disruptions are cleared on load
5. `build_skeleton_layout()` (polls every 1s and reloads the page once data is ready)

Startup data older than 2 hours is marked provisional (`_DATA_IS_FRESH = False`).

### Threading Model

```python
_DATA_CACHE = None           # Latest snapshot
_LAST_UPDATE = None          # UTC datetime
_DATA_IS_FRESH = False       # True after first successful fetch
_LAST_FETCH_STATUS = "starting"  # starting|running|ok|failed
_LAST_FETCH_ERROR = None     # Exception class name only (public on /health)
_LAST_FETCH_DURATION_SECONDS = None
_FETCH_STARTED_AT = None     # Start of the fetch in progress
_HAS_FETCHED_OK = False      # Any successful fetch since boot
_LOCK = threading.Lock()     # Protects ALL globals above
```

All global state reads/writes MUST use `with _LOCK:`. The background thread runs as a daemon and sleeps 300s between fetches (60s on error).

### Auto-Refresh

- Panels update in place (no page reload) via `refresh-interval` in `components/workspace_callbacks.py`, which keeps filters and scroll position
- **Provisional** (stale startup data): every 20s
- **Fresh data**: every 5 min
- The manual Refresh button re-reads the cache; it does not call providers
- Only the skeleton screen does a full `window.location.reload()` (clientside callback) once data is ready

---

## Scoring System

### Weights (config.py — must sum to exactly 1.0)

```python
CATEGORY_WEIGHTS = {
    "weather":       0.10,
    "supply_chain":  0.25,
    "freight":       0.10,
    "energy":        0.20,
    "tariffs":       0.15,
    "geopolitical":  0.20,
}
```

The engine validates `sum(weights) ≈ 1.0` (atol=0.01) and raises `ValueError` if not. It does NOT auto-normalize.

`INDUSTRY_PROFILES` holds per-profile weights (each must sum to 1.0) and `card_categories`:
- `baseline`: same weights as `CATEGORY_WEIGHTS`
- `semiconductor`: weather 0.05, supply_chain 0.15, freight 0.05, energy 0.10, tariffs 0.10, geopolitical 0.15, chip_fab_util 0.20, chip_memory_prices 0.10, chip_lead_times 0.05, chip_wafer_prices 0.05
- `aerospace`: weather 0.05, supply_chain 0.10, freight 0.10, energy 0.10, tariffs 0.10, geopolitical 0.15, aero_metals 0.15, aero_orders 0.10, aero_production 0.10, aero_ppi 0.05

### Daily Proxy Blends

| Category | Monthly anchor | Daily proxy | Proxy weight |
|----------|----------------|-------------|--------------|
| supply_chain | NY Fed GSCPI | BDRY (inverse percentile) | `SUPPLY_CHAIN_PROXY_WEIGHT` 0.30 |
| freight | TSIFRGHT YoY | IYT (direct percentile) | `FREIGHT_PROXY_WEIGHT` 0.30 |
| tariffs | EPUTRADE | Tariff news nowcast, only when it is below the EPUTRADE score | `TARIFFS_PROXY_WEIGHT` 0.30 |
| geopolitical | News severity score | Aggregate AI port-disruption score | `PORT_DISRUPTION_WEIGHT` 0.15 |

If a proxy fails, the category uses its anchor alone.

### Health Tiers (higher score = healthier)

```python
HEALTH_TIERS = [
    {"min": 80, "max": 100, "label": "Healthy",  "color": "#3d9b6e"},
    {"min": 60, "max": 79,  "label": "Stable",   "color": "#c4a35a"},
    {"min": 40, "max": 59,  "label": "Stressed", "color": "#c47a3a"},
    {"min": 0,  "max": 39,  "label": "Critical", "color": "#c44d5f"},
]
```

The map uses separate high-contrast colors (`MAP_HEALTH_COLORS`, `MAP_RISK_SCALE`); tier thresholds still come from `HEALTH_TIERS`.

### Composite Calculation (scoring/engine.py)

```python
composite = sum(weights[cat] * scores[cat] for cat in weights)
return float(np.clip(composite, 0.0, 100.0))
```

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

The industry adapters (`ChipFabUtilProvider`, `AeroMetalsProvider`) return one primary category and pack the other three under `metadata["additional_scores"]` / `metadata["additional_history"]`; the aggregator pops and unpacks them.

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

**Weather**: continuous linear deductions (not binary thresholds), averaged across all 37 ports:
```python
score = 100.0
score -= _wmo_deduction(wmo_code)      # Up to -30 (thunderstorm)
score -= _wind_deduction(wind_kmh)     # Linear ramp 10–80 km/h, max -30
score -= _precip_deduction(precip_mm)  # Linear ramp 0–50 mm, max -25
score -= _temp_deduction(temp_c)       # Extremes both ends, max -15
return max(0.0, min(100.0, score))
# Max total deduction: 30+30+25+15 = 100
```

**Supply chain**: `50 - GSCPI × GSCPI_SCORE_SCALE` (12.5), clipped 0–100, blended 70/30 with BDRY. WEI is shown in metadata only.

**Freight**: `FREIGHT_YOY_BASELINE + YoY% × FREIGHT_YOY_SLOPE` (72 + YoY% × 6.5), clipped 0–100, blended 70/30 with IYT.

**Tariffs**: inverse percentile of EPUTRADE in the trailing `FRED_SCORE_LOOKBACK_DAYS` (730). The nowcast (100 + sum of the 5 most negative VADER severities of tariff-tagged articles, floored at 50; neutral 85 with no matches) is blended at 30% only when articles matched and it is below the EPUTRADE score. `fetch_history()` returns EPUTRADE scores only.

**Geopolitical**: three-tier fallback on the provider path, negative-only, volume-invariant scoring:
```
Tier 1: Cached news payload (NEWS_BRIEFING_CACHE_KEY, usable up to 7 days)
Tier 2: Live RSS + VADER (no AI)
Tier 3: Neutral baseline 85.0, flagged is_fallback

Score = 100 + sum(10 most severe negative severities)   # dedup by title,
# total deduction floored at -60. Only negative news reduces the score.
# Claude severities are clamped to ±AI_SEVERITY_MAX (10).
```
The aggregator overrides the provider score each cycle with the fresh news result and blends it 85/15 with the aggregate port-disruption score (`100 - 2 × mean port penalty`) via `blend_port_disruption()`.
History comes from `daily_category_scores` in the database — real stored
measurements only, no proxy series.

**Energy**: cost-pressure gauge (NOT a demand gauge). Average of two inverse
percentiles (WTI crude and DOE diesel, each within its trailing 2-year range).
A price collapse from demand destruction reads as low cost pressure; demand
health is not measured.

**FRED-based providers** (energy, tariffs, aerospace) use the shared `fred_client.py` and `normalize_series_inverse()`:
```python
def normalize_series_inverse(series):
    """Lower raw value → Higher score (0–100), rolling percentile rank."""
    pct = series.rolling(f"{days}D", min_periods=12).rank(pct=True)
    return ((1 - pct) * 100).round(1).clip(0.0, 100.0)
```

### Error Handling

Provider failures never crash the app:
```python
try:
    score, metadata = provider.fetch_current()
except Exception as exc:
    logger.error("Provider %s failed: %s", cat, exc)
    score = 50.0  # Neutral fallback
    metadata = _fallback_metadata(str(exc))  # is_fallback=True, full key shape
```

Fallback categories are flagged: `metadata["is_fallback"]`, snapshot keys
`degraded` / `fallback_categories`, a card badge, `/api/v1/latest`, and
`/health`. Fallback scores are never written to the daily score history.

---

## Caching (data/cache.py)

### Core API

```python
get_cached(key, ttl=3600)           # Returns None if missing or expired
set_cached(key, data)                # Atomic: temp file → fsync → os.replace
get_cached_dashboard()               # 24h TTL (stale data > no data)
set_cached_dashboard(data)           # Converts Pandas types to JSON-safe
dashboard_to_safe_dict(data)         # JSON-safe copy (also used for the DB snapshot)
reconstruct_dashboard_state(data)    # Rebuilds Pandas types from JSON
```

### TTL Defaults

| Data | TTL |
|------|-----|
| RSS article snapshot | 5 min |
| Weather (port batch) | 4 hours |
| FRED series | 1 hour |
| BDRY / IYT / market data | 1 hour |
| NY Fed GSCPI | 6 hours (stale copy reused up to 60 days if the CSV fetch fails) |
| Silicon Analysts | `INDUSTRY_PROVIDER_CACHE_TTL` (24 hours; 1 hour after a failed fetch) |
| Aerospace | 1 hour |
| Claude news analysis | `AI_CACHE_TTL_SECONDS` (24 hours), tracked by `ai_generated_at` inside the payload |
| News alerts re-score (RSS + VADER, no API cost) | `NEWS_RSS_REFRESH_SECONDS` (1 hour) |
| News payload as fallback | `NEWS_CACHE_MAX_AGE_SECONDS` (7 days) |
| Port summaries, score explanation, on-demand briefing | `AI_CACHE_TTL_SECONDS` (24 hours) |
| Failed Claude call | retried after `AI_FAILURE_RETRY_SECONDS` (1 hour) |
| Dashboard snapshot | 24 hours |

### Critical Rules

- Cache keys are versioned (e.g., `weather_batch_ports_v2`, `newsapi_briefing_v17`, `ai_port_summaries_v5`). Bump the version to bust stale cache on schema changes
- Always use `set_cached()` / `_write_text_atomic()`, never write cache files directly
- Cache dir: `data/.cache/`
- Only `fallback_snapshot_safe.json` is committed to git. The app never rewrites it; refresh it with `python scripts/refresh_fallback_snapshot.py` and commit

---

## Aggregator (data/aggregator.py)

### Parallel Execution

```python
RefreshTasks(max_workers=3)   # data/runtime.py; one outstanding job per task key, reused across cycles
# Timeouts: providers=45s, news AI=120s, market=30s, port summaries=120s
```

### Series Alignment (critical for sparklines)

```python
dates = pd.date_range(end=today, periods=HISTORY_DAYS, freq="D")
aligned = hist_series.reindex(dates, method="ffill")
aligned.iloc[-1] = current_score  # Force last point = today's live score
```

This prevents sparklines from showing yesterday's stale value as today.
Dates BEFORE the first real observation stay NaN — never backfill them with
the current score; charts must render unmeasured history as a gap.

### Map Markers

Per port: 40% local weather score + 60% regional macro score (region-specific category weights; regional macro alone if weather is missing), minus a structural vulnerability penalty (0–10 pts), minus `max(news penalty, AI penalty)`. The news penalty is the largest matched-article penalty (high 30, medium 15, low 5) plus 20% of the rest, capped at 50; the AI penalty is Claude's per-port `disruption_penalty`, clamped 0–50. 37 ports total. Generated in `_derive_map_markers()`.

Region profiles still list a legacy `trucking` weight; it is folded into `energy` at import.

### Post-Processing

- Fresh news score (blended with the port-disruption signal) overwrites the geopolitical score and history's last point
- Claude score explanation for the gauge hover (cached 24h, reused only while the tier is unchanged)
- Disruptions generated from measured (non-fallback) categories scoring < `DISRUPTION_SCORE_THRESHOLD` (70), plus high-severity news alerts
- Measured (non-fallback) daily scores persisted via `record_daily_scores()` (at most hourly)
- Dashboard snapshot saved to the database via `save_dashboard_snapshot()` (at most hourly, skipped when a baseline category is on a fallback)

---

## Dashboard Snapshot Structure

The `_DATA_CACHE` dict returned by `aggregate_data()`:

```python
{
    "last_updated_utc": "2026-03-10T15:30:00Z",
    "dates": pd.DatetimeIndex,                       # 90 daily dates
    "category_history": dict[str, pd.Series],        # 6 baseline + industry categories
    "current_scores": dict[str, float],              # 6 baseline + chip_* and aero_* when available
    "category_metadata": dict[str, dict],            # one per category
    "map_markers": list[dict],                       # 37 ports: name, lat, lon, score, description
    "alerts": list[dict],                            # timestamp, severity, title, body, category, sentiment, url, source
    "briefing": str,                                 # AI-generated bullet points
    "full_report": str,                              # Markdown report
    "disruptions": list[dict],                       # event, region, impact_score, categories, started, status
    "provider_errors": dict[str, str | None],        # None = OK, str = error message
    "market_data": dict,                             # Crude Oil, Natural Gas, Copper, Gold, VIX: price, prev, symbol, change_pct
    "score_explanation": str,                        # Claude gauge hover text (may be empty)
    "degraded": bool,                                # True if any category is serving a fallback
    "fallback_categories": list[str],                # categories with is_fallback metadata
}
```

---

## UI Patterns (components/)

### Styling

- Dark theme: background `#0a0a0b`, cards `#111113`, text `#ececef`, grid `#1e1e22`
- Colors defined in `config.py` `COLORS` and `CATEGORY_COLORS`; keep `COLORS` in sync with the `:root` tokens in `assets/style.css`
- Fonts: Satoshi / IBM Plex Sans / IBM Plex Mono (`FONT_*` in `config.py`, since Plotly ignores CSS variables)
- Dash Bootstrap Components (DARKLY) + `assets/style.css` + some inline styles
- Trend chart uses `dragmode=False`, `hovermode="x unified"`; the world map uses `dragmode="pan"`

### Cards (cards.py)

Each card shows: label, weight badge, score (colored by tier), delta arrow, sparkline of the last 30 points, 30-day min/max range. Cards are clickable (pattern-matching id `{"type": "category-card", "index": cat}`) and open a details modal. Fallback categories show "History unavailable" instead of a sparkline.

### Charts (charts.py)

Trend chart (7, 30, or 90 days): one `go.Scatter` per category, lines colored by `CATEGORY_COLORS`. World map: port markers colored/sized by score.

### Callbacks (app.py, components/workspace_callbacks.py)

- Modal callback: uses `ctx.triggered_id` with pattern-matching `ALL` to detect which card was clicked
- Newsletter callback: validates email, calls `add_subscriber()`
- All callbacks read from `_DATA_CACHE` — never trigger fetches
- Use `dash.no_update` to skip outputs that shouldn't change

---

## API Endpoints

```
GET  /api/v1/latest              # Public: composite, categories, degraded, fallback_categories, disruptions, map_markers
GET  /api/v1/newsletter-data     # Admin: Authorization: Bearer ADMIN_TOKEN
GET  /api/v1/admin/subscribers   # Admin: Authorization: Bearer ADMIN_TOKEN
GET  /unsubscribe?t=TOKEN        # Confirmation page (does not unsubscribe; mail scanners prefetch)
POST /unsubscribe?t=TOKEN        # Unsubscribes; also serves RFC 8058 one-click
GET  /docs, /report              # Public pages
GET  /health                     # Monitoring: state, data_age_seconds, last_fetch_status, fallback_categories
GET  /healthz                    # Alias for /health
```

Admin auth accepts only the `Authorization: Bearer` header (no query-string token), compared in constant time.

Rate limits (`API_RATE_LIMIT = "500 per hour;2000 per day"`) apply to the `/api/v1/*` blueprints only, keyed on `CF-Connecting-IP` (falls back to the socket address), in-memory storage. Dash pages, callbacks, `/health`, and `/unsubscribe` are not limited.

Health: HTTP 200 `warming_up` (no successful fetch since boot and the current fetch has run ≤10 min), HTTP 200 `healthy`, HTTP 503 `degraded` (no data, data > 30 min old, or a fetch running > 10 min). `last_fetch_error` exposes only the exception class name.

Security headers on every response: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: SAMEORIGIN`, `Content-Security-Policy: frame-ancestors 'self'`, `Strict-Transport-Security: max-age=31536000; includeSubDomains`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`.

---

## Database (data/database.py)

Lazy dual-backend: resolves PostgreSQL vs SQLite at connection time, not import time. This lets `dotenv` load environment variables first.

Tables:
- `subscribers` (email, subscribed_at, is_active, unsubscribed_at). Unsubscribed addresses cannot be re-added from the form
- `daily_scores` (date, score)
- `daily_category_scores` (date, category, score). The real measurement history behind trend charts, written at most hourly via `record_daily_scores()`, fallback values excluded)
- `dashboard_snapshot` (id=1, payload, updated_at). Cold-start layer, written at most hourly
- `newsletter_sends` (send_date, email). Stops a retried cron run from emailing someone twice

---

## AI (data/llm.py, data/ai_analyst.py, data/port_analyst.py)

All Claude calls go through `data/llm.py`: model `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`), effort `ANTHROPIC_EFFORT` (default `medium`), 90s timeout, no retries, server-side fallback beta. `complete_json` uses a JSON schema output format. Every caller has a deterministic fallback when the key is missing or the call fails.

Call types:
- `analyze_news_batch()`: severity + summary for up to 25 articles and the 3-bullet briefing, in one call
- `generate_full_report()`: Markdown report for `/report` (up to 50 articles)
- `generate_port_summaries()`: summary + `disruption_penalty` (0–50) for all 37 ports, from up to 100 RSS articles
- `generate_score_explanation()`: gauge hover text
- `generate_briefing()`: on-demand briefing button, only when the cached payload has no briefing
- `generate_newsletter_briefing()`: newsletter cron

---

## Development Guidelines

### Adding a New Provider

1. Create `data/providers/my_provider.py` inheriting `BaseProvider`
2. Set `category = "my_category"` matching a key in `CATEGORY_WEIGHTS`
3. Implement `fetch_current()` → `tuple[float, dict]` with required metadata keys
4. Implement `fetch_history(days)` → `pd.Series` with `DatetimeIndex`
5. Register in `data/aggregator.py`'s `_PROVIDERS` list
6. Add weight in `config.py` `CATEGORY_WEIGHTS` and every `INDUSTRY_PROFILES` weight set (adjust others so each sums to 1.0), plus `card_categories` where it should show
7. Add to `CATEGORY_LABELS`, `CATEGORY_COLORS` in `config.py`
8. Check `components/cards.py` and `components/charts.py` render it

### Modifying the UI

- Layout structure: `components/layout.py`
- Cards: `components/cards.py` — follow existing card pattern (score + delta + sparkline)
- Charts: `components/charts.py` — use `go.Scatter` with `CATEGORY_COLORS`
- Callbacks: `app.py` and `components/workspace_callbacks.py`. Use `ctx.triggered_id`, return `dash.no_update` for unchanged outputs
- Styling: `assets/style.css` tokens and `config.py` colors

### Editing Scores and Thresholds

All tunable values live in `config.py`. Never put magic numbers in provider or component code.

---

## Deployment

### Render (primary)

- Deploy from `main` branch
- Build: `pip install -r requirements.txt`
- Start: `env -u GUNICORN_CMD_ARGS gunicorn app:server -c gunicorn.conf.py --access-logfile -` (clears Render's inherited `--preload`; see `docs/render-memory.md`)
- Python version from `.python-version` (3.13.1)
- Health check: `/health`
- Ephemeral filesystem — disk cache only survives within a session
- Newsletter: separate cron running `python scripts/send_newsletter.py` (needs the SMTP vars, `ADMIN_TOKEN`, `DATABASE_URL`, `NEWSLETTER_POSTAL_ADDRESS`)

### Boot Sequence on Render

1. Disk cache empty → load the database snapshot (at most about an hour old)
2. No database snapshot → load `fallback_snapshot_safe.json` if under 14 days old, else show the skeleton
3. Background thread fetches fresh data
4. Provisional panels refresh in place every 20s; the skeleton reloads the page once data is ready

---

## Things That Will Break If You're Not Careful

- **Local runs write production**: the local `.env` `DATABASE_URL` points at the production Neon database. `python app.py`, scripts, and tests that call `init_db()` or `record_daily_scores()` write real rows. Unset `DATABASE_URL` to use SQLite.
- **Multiple Gunicorn workers** — `_DATA_CACHE` is worker-local. Each worker fetches independently and serves inconsistent data. Always use 1 worker.
- **Blocking the main thread** — callbacks must read from cache only. Any API call in a callback will hang the page.
- **Weights not summing to 1.0** — engine raises `ValueError`. No silent failure, but tests won't catch it if you forget.
- **Writing cache files directly** — bypasses atomic write protection. Use `data/cache.py` helpers.
- **Forgetting `aligned.iloc[-1] = current_score`** — sparklines will show yesterday's value as today. Always force the last point.
- **Not bumping cache key version** — old schema data will be deserialized into new code. Bump the version suffix when changing what's cached.
- **Geopolitical score direction**: only negative news reduces the score (from base 100). Don't add positive sentiment boosts. The same applies to the tariff nowcast, which may only lower the tariffs score.
- **Provider return type** — must return `tuple[float, dict]`, not bare `float`. The aggregator handles both for legacy reasons but new providers should always use the tuple.
- **Never fabricate history** — `fetch_history()` must return only real measurements (stored daily scores or the actual source series). No proxy series level-shifted to match the current score, no backfilling leading NaNs with today's value. Short series render as gaps; that is correct.
- **Don't put WEI back in the supply chain score** — WEI is a GDP-growth nowcast; high growth coincides with supply chain stress (2021), so it has no defensible sign in a linear health blend. Context only.
- **Paid tests**: `RUN_LIVE_CLAUDE=1` makes billed Claude calls and writes the cache.

## Known Inconsistencies

- ~~Some providers use hardcoded fallback scores~~ — now configurable via `DEFAULT_FALLBACK_SCORES` in `config.py`.
- `_KEY_MIGRATIONS` in app.py maps legacy category names ("ports"→"supply_chain", "shipping"→"trucking"). `trucking` is no longer a category, so the second mapping is dead. This should live in a migration module.
- `_REGION_PROFILES` in the aggregator still lists `trucking` weights, folded into `energy` at import.
- The `supply_chain.py` module docstring says `GSCPI * 25`; the code uses `GSCPI_SCORE_SCALE` (12.5).
- ~~Weather provider has 14 hubs hardcoded~~ — now derived from `ports_data.MAJOR_PORTS` (37 ports).
