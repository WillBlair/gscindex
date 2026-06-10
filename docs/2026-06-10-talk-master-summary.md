# Global Supply Chain Index — Master Talk Reference

**Date:** 2026-06-10
**Purpose:** A single, exhaustive reference for a long-form talk about how and why this project was built. It covers the origin story, the purposes it could serve, every feature, the full scoring logic behind each feature, the architecture, and every external tool and service it depends on (Neon Postgres, Render, the FRED API, the NY Fed, Open-Meteo, NewsAPI, RSS, VADER, Google Gemini, yfinance, and more).

This is written to be read top to bottom or skimmed by section. Each section is self-contained so you can pull a single topic for a slide. Where there is a strong story or a "why," it is called out, because those are the moments a technical audience remembers.

No em dashes are used, consistent with the rest of the project's written deliverables.

---

## Table of Contents

1. The one-sentence pitch and the honest version
2. Origin story: why this was built
3. Who it is for: audiences and purposes you can talk about
4. The product in plain language
5. The composite index: concept and philosophy
6. Feature catalog (everything the user can see and touch)
7. Scoring logic, category by category
8. The two ideas that hold the whole methodology together
9. External data sources and services (the "stack" in depth)
10. Architecture: how data flows and why it never blocks
11. The caching system and the cold-start fallback chain
12. The provider pattern and how to extend it
13. The database layer (Neon Postgres and SQLite)
14. The AI layer (Google Gemini) and the cost-control design
15. The news pipeline (RSS, NewsAPI, VADER, selection, dedupe)
16. The map: 37 ports, regional risk, and how each dot is colored
17. The frontend (Dash, Plotly, callbacks, the dark theme)
18. The newsletter system (SMTP, subscribers, cron)
19. The public API and integrations
20. Deployment and operations (Render, Gunicorn, Vercel)
21. The rigor story: the bugs that were found and fixed
22. Known limitations to own on stage
23. Strategic directions (where it could go next)
24. Talking points and likely Q&A
25. Glossary of every term and series used

---

## 1. The one-sentence pitch and the honest version

**The pitch:** The Global Supply Chain Index is a real-time dashboard that aggregates six categories of economic, weather, and news data, computes a single weighted 0 to 100 "Supply Chain Health Index," and serves it through interactive visualizations and a public JSON API. It runs live at gscindex.com.

**The honest version (and the better talk):** No one makes an operational decision from this single composite number, and that is fine, because the real product is the engineering and the methodology behind it. A sourcing manager at an aerospace supplier cares about their specific commodities, lanes, and suppliers, not a single global mood ring. Even the NY Fed's own GSCPI, built by professional economists, is used for macro commentary rather than operational decisions. So the project's optimization target is rigor and defensibility in front of a technical reviewer, not daily-user growth. That reframing is the spine of a good talk: it is a demonstration of skill, and the interesting content is the judgment visible through it.

This duality is worth opening with. It signals self-awareness, which is exactly what a sharp interviewer is listening for.

---

## 2. Origin story: why this was built

The author is finishing a supply chain degree and targeting sourcing and supply chain roles in manufacturing and aerospace. The project is a portfolio piece designed to prove three things at once:

1. **Domain literacy.** It speaks the language of supply chains: GSCPI, trade policy uncertainty, diesel cost pressure, chokepoints (Suez, Hormuz, Malacca, Panama, Bab el-Mandeb), port congestion, and disruption events.
2. **Engineering ability.** It is a production web service with a background data thread, a thread-safe in-memory cache, an atomic disk cache, a dual-backend database, a parallel data aggregator with per-source timeouts, a public rate-limited API, and a real deployment.
3. **Judgment.** This is the differentiator. The project went through a deliberate "rigor and correctness pass" where the author tore apart their own methodology, found that two of the six category histories were synthetic, that one category's sign was backwards, and that the headline number was being propped up by a masking bug. They fixed all of it and let the honest number stand even though it dropped the headline score from the low 60s to 39 ("Critical").

The phrase to keep in your pocket: the build was asked to survive "a sharp interviewer asking why should I trust this number." Most of the talk is the answer to that question.

---

## 3. Who it is for: audiences and purposes you can talk about

You asked for all the options of what to talk about. Here is the full menu of purposes and framings. Pick whichever fits your room.

### 3.1 As a portfolio and hiring artifact
The primary purpose. The real audience is a technical hiring manager or a senior sourcing person spending about ten minutes on it. The deliverable is the methodology and the engineering judgment, not the index value.

### 3.2 As a macro-awareness tool
A single glance tells you whether the global goods economy is calm or stressed, broken into six interpretable drivers (weather, supply chain pressure, energy cost, trade policy, freight cost, geopolitics). It is a teaching tool as much as a monitoring tool.

### 3.3 As a news and disruption monitor
It continuously ingests supply chain news from roughly 18 specialized RSS feeds plus NewsAPI, scores each article for severity, classifies it into a category, and surfaces the most severe items as alerts and as an AI-written daily intelligence report.

### 3.4 As a data product / API
The public `/api/v1/latest` endpoint returns the composite, the six category scores, the disruptions list, and the 37 port markers, licensed CC-BY-4.0, so other dashboards or research projects can embed it.

### 3.5 As a methodology demonstrator
The detail modal behind every category card shows the raw value, the data source, the human description, and the literal scoring formula. The project is transparent about how every number is produced, which is rare and is itself the point.

### 3.6 As an engineering reference
The threading model, the cache fallback chain, the atomic writes, and the provider abstraction are reusable patterns. The codebase is a worked example of "how to serve live external data on an ephemeral host without ever blocking a page load."

### 3.7 As a launchpad for a sharper product
Several distinct future directions exist (a validated index with a published backtest, an aerospace-specific monitor, a daily GSCPI nowcast, or an event-driven disruption intelligence database). These are covered in section 23 and make a strong "where this goes next" closer.

---

## 4. The product in plain language

The dashboard fetches economic, weather, and news data on a background thread every five minutes, caches the results in memory and on disk, and renders instantly from cache on each page load. The page never waits on an external API.

What a visitor sees on the main page, top to bottom:

- A header with the title, the author's name (linked), the last-updated time in Mountain Time, a data-age readout, a Docs link, an API button, a Newsletter button, and a live or "updating" status dot.
- A hero row with the composite gauge on the left and the world port map on the right.
- A horizontally scrolling market ticker (crude oil, natural gas, copper, gold, VIX).
- A row of six category cards, each clickable to open a detail modal.
- A bottom row with the AI Daily Briefing on the left and the Recent Alerts feed on the right.
- A middle row with horizontal category health bars on the left and the 90-day multi-line trend chart on the right.
- A footer crediting the data sources.
- Three modals (category detail, API info, newsletter signup) and a newsletter toast.

There are also standalone pages: `/report` (a long-form AI intelligence report styled like an article), `/docs` (platform documentation), and `/health` plus `/healthz` (JSON operational checks).

---

## 5. The composite index: concept and philosophy

### 5.1 The scale
Every category produces a score from 0 to 100 where **100 means healthiest / least disrupted**. This single convention is enforced everywhere, which is what lets six very different signals be blended at all. A high score is always good news, whether it comes from calm weather, cheap diesel, low trade-policy uncertainty, or quiet news.

### 5.2 The weighted average
The composite is a plain weighted average:

```
composite = Σ (weight_i × score_i)  for each category i
```

The weights live in `config.py` and must sum to exactly 1.0. The scoring engine validates this within a tolerance of 0.01 and raises a `ValueError` if it fails. It does **not** auto-normalize, on purpose: a silent re-normalization would hide a configuration mistake. The result is clipped to the 0 to 100 range.

```python
def compute_composite_index(category_scores, weights=None):
    weights = weights or CATEGORY_WEIGHTS
    weight_sum = sum(weights.values())
    if not np.isclose(weight_sum, 1.0, atol=0.01):
        raise ValueError(...)
    missing = set(weights) - set(category_scores)
    if missing:
        raise ValueError(...)
    composite = sum(weights[cat] * category_scores[cat] for cat in weights)
    return float(np.clip(composite, 0.0, 100.0))
```

### 5.3 The current weights
```
weather        0.10
supply_chain   0.20   (NY Fed GSCPI)
energy         0.20   (WTI crude cost pressure)
tariffs        0.15   (Trade Policy Uncertainty)
trucking       0.15   (diesel cost pressure)
geopolitical   0.20   (news severity)
```

Be honest about these on stage: they are not derived from data. They are reasonable priors. Section 22 covers the known caveat that energy and trucking both load on petroleum, so the index carries an effective weight on oil that is larger than any single line suggests.

### 5.4 The health tiers
The composite (and every category) maps to a label and color, evaluated top down, first match wins:

```
Healthy    80 to 100   green   #00d97e
Stable     60 to 79    yellow  #f6c343
Stressed   40 to 59    orange  #fd7e14
Critical    0 to 39    red     #e63757
```

---

## 6. Feature catalog (everything the user can see and touch)

This section is a checklist you can read almost verbatim as a "tour" slide.

### 6.1 Composite gauge
A Plotly semicircular `go.Indicator` in gauge mode. The needle and number are colored by the current tier. It shows a day-over-day delta (versus the previous stored daily score) when the data is fresh, and suppresses the delta when the data is provisional (loaded from cache or fallback rather than a live fetch this session), because a stale delta would be misleading. The arc has faint colored bands for each tier and a white threshold line at the current value.

### 6.2 Category cards
Six "tech HUD" style cards, one per category. Each shows the label, an optional raw sub-label, a weight badge (for example `W:20%`), the score colored by tier, a 24-hour delta with an up or down arrow, a 30-day low and high, and a 30-point sparkline. The sparkline is colored green or red to match the trend direction and is NaN-safe: if real history is short it draws markers instead of a line, and if there is nothing to show it renders an empty figure rather than crashing. If a category is serving a fallback value (its provider failed), a small orange `FALLBACK` badge appears in the header. Each card is clickable and opens a detail modal.

### 6.3 The detail modal
Clicking a card opens a large modal showing: the score with a colored progress bar, the tier badge, the raw value, the data source, the human-readable analysis ("description"), and the literal scoring formula ("calculation") rendered in a monospace code block, plus the raw label and last-updated timestamp. This is the transparency feature: it shows the math behind every number.

### 6.4 World map
A `go.Scattergeo` natural-earth projection plotting all 37 major ports. Each dot is colored on a green to red continuous scale by its blended port score and sized inversely to its score (troubled ports are large, healthy ports are tiny, so your eye is drawn to problems). Hover shows a rich tooltip with the region, the macro score, the top regional risk, an AI status line, and up to three matched news headlines with severity tags. Markers are drawn healthiest first so the large red dots sit on top and reliably catch hover events.

### 6.5 90-day trend chart
A multi-line Plotly chart with one line per category, each in its category color, over the trailing 90 days. Pan and zoom are disabled, the y-axis is locked to 0 to 100, and hover is unified across the x-axis. Lines render gaps honestly where there is no measured history (this matters; see section 8.3).

### 6.6 Category health bars
A compact panel of horizontal bars, one per category, each filled to its score width and colored by category color, with the numeric score colored by tier. A quick "at a glance" alternative to the cards.

### 6.7 News alerts feed
A list of recent supply chain alerts. Each item has a severity badge (high red, medium orange, low green), a category tag, the source name, a human "time ago" string, the headline as a link to the original article, and a short body. Populated from the news pipeline.

### 6.8 AI Daily Briefing
A three-bullet executive summary generated by Gemini from the day's news, with a "Read Full Report" link to `/report`. If no briefing exists yet, the panel shows a "Generate Briefing" button that triggers an on-demand Gemini call (cached, so repeated clicks do not burn the API).

### 6.9 Full intelligence report (`/report`)
A standalone, article-styled page rendering a 400 to 600 word Markdown report generated by Gemini, structured into Critical Disruptions, Ocean Freight and Port Operations, Air and Land Logistics, Market and Economic Context, and Forward Outlook. The Markdown is HTML-escaped first and dangerous link protocols (`javascript:`, `data:`) are stripped before rendering, so untrusted model output cannot inject script.

### 6.10 Market ticker
A scrolling marquee of five market indicators (Crude Oil CL=F, Natural Gas NG=F, Copper HG=F, Gold GC=F, VIX) with price, absolute change, and percent change, each colored green or red. Pulled from yfinance and cached for an hour. The content is duplicated so the CSS marquee loops seamlessly.

### 6.11 Disruptions
Auto-generated events. Any category scoring below 70 produces a disruption row (Critical below 40, Stressed otherwise) with an impact score derived from how far below 100 it is. High-severity news alerts also become disruption rows. The disruptions feed the `/api/v1/latest` payload (the on-page table component exists in code but the current layout shows the news panel in that slot).

### 6.12 Newsletter signup
A header button and an auto-appearing toast both open a modal where a visitor enters an email. Validated for an `@`, then stored via `add_subscriber()` into Postgres (prod) or SQLite (dev) with an upsert that reactivates previously unsubscribed addresses. A daily cron job emails subscribers the morning briefing.

### 6.13 Public API and health
`/api/v1/latest` (public, rate-limited), `/api/v1/newsletter-data` (admin, token-protected), `/api/v1/admin/subscribers` (admin, Bearer token), and `/health` plus `/healthz` (monitoring). Covered in detail in sections 19 and 20.

### 6.14 Auto-refresh
The page reloads itself. When data is fresh, every five minutes. When data is provisional (warming up), every 20 seconds, so the page picks up the first real fetch quickly. A separate one-second boot poller on the skeleton screen reloads the moment data lands.

---

## 7. Scoring logic, category by category

This is the heart of the talk. Each category answers a question, pulls a real series, and maps it to 0 to 100. Crucially, the four "deduction" or "percentile" choices are not arbitrary; each is justified below.

### 7.1 Weather Disruptions (weight 0.10)

**Source:** Open-Meteo, free, no API key. **Question:** Are the world's major ports experiencing weather that slows loading, unloading, and vessel movement?

**Method:** For each of the 37 ports, start at 100 and subtract continuous (not threshold) deductions across four factors, then average across all ports.

```
score = 100
score -= WMO-code deduction      (up to 30: thunderstorm/hail; 15 for fog)
score -= wind deduction          (linear 10 to 80 km/h, up to 30)
score -= precipitation deduction (linear 0 to 50 mm, up to 25)
score -= temperature deduction   (extremes both ends, up to 15)
clip to 0..100
```

The deduction budget sums to 30 + 30 + 25 + 15 = 100, matching the scale. The deductions are continuous so the score moves a little every day instead of snapping between thresholds. Wind matters because port cranes stop around 60 km/h; even light rain slows operations; fog is a visibility (vessel arrival) problem; temperature extremes stress equipment and workers.

**Engineering detail worth mentioning:** the Open-Meteo URL is built by hand with literal commas rather than letting `requests` URL-encode them to `%2C`, because some CDN edges between the host and Open-Meteo failed to decode the encoded commas and treated all coordinates as one invalid string. Ports are fetched in parallel chunks of eight, with an in-order reassembly so results stay aligned to port names. Results cache for four hours.

**History:** real historical daily weather scores from Open-Meteo's archive API, averaged across hubs.

### 7.2 Supply Chain Pressure (weight 0.20)

**Source:** NY Fed Global Supply Chain Pressure Index (GSCPI), monthly. **Question:** How stressed is the global supply chain according to the single best purpose-built measure that exists?

**What GSCPI is:** a monthly z-score built by the New York Fed from a PCA over transportation costs (the Baltic Dry Index, Harpex, and BLS air freight series) and the delivery-time / backlog / inventory components of PMI surveys across seven economies. Zero is average pressure, positive is elevated pressure, and it is expressed in standard deviations.

**Method:**
```
score = 50 - GSCPI * 25, clipped 0..100
```
So GSCPI at 0 (average) scores 50, at +2 sigma scores 0, at -2 sigma scores 100. Higher pressure means a lower (worse) health score.

**The publication-lag handling:** GSCPI is monthly and revised, so the provider uses the newest month at or before the previous calendar month-end, which avoids treating an unpublished or heavily revised current month as final.

**Two stories here, both great for a talk:**

1. **The WEI sign error (a methodology bug that was removed).** This category used to blend GSCPI (40%) with the NY Fed's Weekly Economic Index (60%). WEI is a GDP-growth nowcast. The problem: high growth historically coincides with supply chains breaking. In late 2021, WEI ran around +7 (its score pinned at 100) while GSCPI hit its all-time peak around 4.31 (its score clipped to 0). The blend produced 0.6 × 100 + 0.4 × 0 = 60, "Stable," during the worst supply chain crisis in modern history. That one example ends the credibility of the old index. The fix: GSCPI only. WEI is still fetched, but shown as context in the metadata and contributes nothing to the score. The guardrail in the docs reads "do not put WEI back into the supply chain score."

2. **The GSCPI parser bug (a real bug the rigor pass surfaced).** Removing the WEI mask immediately exposed that the NY Fed had changed their CSV export so column headers became Excel serial dates (for example `44562`) instead of `"%b-%y"` strings (`"Jan-22"`). The old parser threw on every fetch, and the failure had been silently masked by the WEI fallback. The fix parses both header formats (strings, and Excel serials via the 1899-12-30 epoch) with sanity bounds that reject mis-parses rather than crashing. After the fix, 54 monthly vintages parse cleanly.

### 7.3 Energy Costs (weight 0.20)

**Source:** live WTI crude futures (CL=F) via yfinance, with FRED `DCOILWTICO` for history and as a fallback. **Question:** How much cost pressure is energy putting on supply chains right now?

**Method:** the score is the **inverse percentile** of the current price within its trailing two-year distribution.
```
score = inverse_percentile_value(price, trailing_2yr_FRED_window)
# cheapest end of the window -> near 100 (low cost pressure)
# most expensive end          -> near 0   (high cost pressure)
```

**The critical framing (say this out loud):** this is explicitly a **cost gauge, not a demand gauge**. A price collapse driven by demand destruction will read as "low cost pressure" (a high score) even though the demand picture is terrible. The classic example: April 2020 WTI at negative 37 dollars would read as the healthiest possible energy reading while supply chains were in free fall. The category does not claim to measure demand health, and the metadata says so.

**Why percentile and not min/max:** an earlier version scored against trailing min/max. Two problems: a single outlier print (like that negative 2020 close) dominates the whole scale, and a score of 0 just means "two-year high," not "crisis." Percentile rank is robust to outliers and reflects where today sits in the distribution.

### 7.4 Trade and Tariffs (weight 0.15)

**Source:** FRED series `EPUTRADE`, the Economic Policy Uncertainty categorical index for trade policy (Baker, Bloom, and Davis), monthly. **Question:** How much trade-policy uncertainty (tariffs, trade wars, import/export policy) is in the news?

**Method:** inverse percentile of the latest value within the trailing two-year window. Higher trade-policy uncertainty means a lower score. The series is monthly, so this category moves slowly by design.

**The story:** this used to be the general EPU index (`USEPUINDXD`), which spikes on debt-ceiling fights, elections, and Fed drama, while the label promised tariffs. The rigor pass swapped it for the trade-specific categorical index, which counts only trade-policy newspaper coverage. The new series was verified live on FRED before shipping.

### 7.5 Inland Freight / Trucking (weight 0.15)

**Source:** DOE weekly retail diesel (FRED `GASDESW`) for the official level and history, plus live Heating Oil futures (HO=F) via yfinance for a same-day nowcast. **Question:** How much fuel cost pressure is on inland freight today?

**The nowcast (a clever, defensible bit):** official retail diesel is only weekly, so today's value is estimated as:
```
estimated_diesel = live_HO_futures_price + retail_spread
```
where the spread (taxes plus distribution margin) is computed dynamically as the gap between the latest weekly DOE print and the HO=F close nearest that print's date, falling back to a typical fixed spread of 1.30 dollars per gallon if it cannot be computed. Heating oil is chemically near-identical to diesel and trades in real time, which is why it is a good high-frequency proxy. The estimate is explicitly labeled an estimate in the UI.

**Method:** inverse percentile of the estimated diesel price within the trailing two-year DOE distribution. Like energy, this is a cost gauge, not a demand gauge.

**The story:** an earlier version fabricated a daily diesel series by adding a constant spread to heating oil futures and presenting it as daily diesel history. The fix: history is now the official weekly DOE series, forward-filled to daily, so the trend shows honest weekly steps instead of a fake smooth daily wiggle. The "wiggle was the bug."

### 7.6 Geopolitical Risk (weight 0.20)

**Source:** roughly 18 specialized supply chain RSS feeds (primary) and NewsAPI (fallback), scored by Google Gemini when available and by VADER sentiment locally otherwise. **Question:** How much negative supply chain news is there, weighted by severity?

**Method (volume-invariant, negative-only):**
```
1. Fetch and classify articles into categories.
2. Score each article's severity: Gemini severity (-10..+10) when available,
   else VADER compound (-1..+1) scaled by 6.
3. Deduplicate by normalized title.
4. Keep the 10 most severe NEGATIVE items.
5. deduction = max(-60, sum of those negatives)   # floor at -60
6. score = 100 + deduction                          # clip 0..100
```

**Why each guard exists (this is a great "I learned something" slide):**

- **Negative only.** Positive news never inflates the score. 100 means "no risk detected," not "great news."
- **Top 10 and floor at -60.** Without these, the score was `100 + sum(all negative severities)`, unbounded. Twenty mildly negative wire stories at compound -0.4 each contributed -48 points and dragged a calm day into "Stressed." Whether the feed returned 20 or 50 items moved the score more than any actual event. The top-N cut plus floor make the score volume-invariant: thirty mild stories cannot outweigh one severe event.
- **Dedup by title.** The same story syndicated across feeds counted multiple times. Now it counts once.

**A candid caveat to raise yourself:** VADER was built for social-media valence, not event severity. "Maersk reroutes around the Cape of Good Hope" is operationally severe and sentimentally neutral, so VADER underweights it. Gemini severity scoring is the better path and is used when available; VADER is the deterministic, no-API fallback. The honest future fix is typed event extraction (section 23, Direction D).

**History:** this is the cleanest "show your work" moment. Geopolitical history comes only from the `daily_category_scores` database table, which means it is real stored measurements and starts as a single point that grows one real point per day. It used to be the VIX (equity volatility) normalized as `120 - 2*VIX` and then level-shifted so the last point matched today's news score, presented as if it were the trend of supply chain news sentiment. A code comment even claimed "the trend looks real (it is)," which was false. That was the worst issue found, and it was deleted entirely.

---

## 8. The two ideas that hold the whole methodology together

### 8.1 Cost gauges versus demand gauges
Energy and trucking measure **cost pressure**, not **demand health**. This distinction is the single most important caveat in the whole index, because a price collapse from demand destruction reads as a healthy (high) score. Owning this explicitly is what separates a credible project from a naive one. The formulas are correct for a cost gauge; the earlier sin was the framing, which has been fixed in the metadata and docs.

### 8.2 Volume invariance
A risk score must not move just because the news feed returned more items. The geopolitical score achieves this with dedup, top-N, and a floor. Mention that this is a general principle: any "sum over a feed" metric secretly measures feed volume unless you cap and normalize it.

### 8.3 Never fabricate history
This is the project's loudest principle, repeated in `CLAUDE.md` as a "things that will break" guardrail. `fetch_history()` must return only real measurements: stored daily scores or the actual source series. No proxy series level-shifted to match the current score, and no backfilling leading NaNs with today's value. Short series render as gaps, and that is correct. The aggregator was changed so that dates before the first real observation stay NaN, and the sparkline and trend chart were made NaN-safe to display those gaps honestly. The reason this matters: a reviewer who opens a file and sees synthesized history presented as measurement stops trusting every other number on the page.

---

## 9. External data sources and services (the stack in depth)

This is your "tools and services" section. Each entry: what it is, why it was chosen, how it is used, and what it costs.

### 9.1 FRED (Federal Reserve Economic Data)
- **What:** the St. Louis Fed's API for economic time series.
- **Used for:** energy history and fallback (`DCOILWTICO`), trade policy uncertainty (`EPUTRADE`), retail diesel (`GASDESW`), and the WEI context series (`WEI`).
- **Why:** authoritative, free, unlimited, and stable. It is the backbone of three of the six scored categories.
- **How:** a shared `fred_client.py` wrapper requests JSON observations, drops FRED's `"."` missing markers, returns a clean pandas Series, and caches per series for one hour. It also provides the two normalization helpers (`normalize_series_inverse` for a whole series and `inverse_percentile_value` for a single current value), both using rolling percentile rank over a trailing two-year window with `min_periods=12` so monthly series still score.
- **Cost:** free with an API key.

### 9.2 NY Fed GSCPI
- **What:** the Global Supply Chain Pressure Index, published as a CSV "vintage matrix" on the New York Fed website (it is not on FRED).
- **Used for:** the entire supply chain category.
- **Why:** it is the professional, purpose-built measure of exactly what this category claims to measure.
- **How:** `gscpi_client.py` downloads the CSV, parses each vintage column header (handling both legacy string and new Excel-serial formats), extracts the latest estimate per month, caches for six hours, and maps the z-score to a 0 to 100 score.
- **Cost:** free, no key.

### 9.3 Open-Meteo
- **What:** a free weather API.
- **Used for:** the weather category and the per-port local weather component of the map.
- **Why:** genuinely free, no key, with both a forecast endpoint (current conditions) and an archive endpoint (historical daily).
- **How:** batched, hand-built URLs, parallel chunks, four-hour cache.
- **Cost:** free, no key.

### 9.4 yfinance (Yahoo Finance)
- **What:** an unofficial Python client for Yahoo Finance market data.
- **Used for:** live WTI crude (CL=F) for energy, live heating oil (HO=F) for the trucking nowcast, and the five market-ticker instruments.
- **Why:** free real-time-ish futures and index quotes with no key.
- **How:** `fast_info` for the latest price with a history fallback when markets are closed; the market panel caches for one hour.
- **Cost:** free, unofficial (so it is treated as best-effort, with FRED as the energy fallback).

### 9.5 NewsAPI
- **What:** a commercial news search API.
- **Used for:** a fallback news source when the RSS feeds return nothing.
- **Why:** breadth, as a safety net behind the curated RSS feeds.
- **How:** queried only when RSS yields zero candidates, with a supply-chain query string.
- **Cost:** free tier is 100 requests per day, which is why RSS is primary and NewsAPI is the backstop.

### 9.6 RSS feeds (the real news backbone)
- **What:** about 18 specialized feeds across four groups: logistics_trade (Supply Chain Dive, FreightWaves, SupplyChainBrain, Logistics Management, SCMR, Logistics Viewpoints), ports_shipping (gCaptain, Splash 247, The Loadstar, Maritime Executive, Logistics Management Ocean Freight), trade_policy (WTO News), and weather_disasters (GDACS, and four NOAA NHC tropical feeds).
- **Why:** curated industry sources are far higher signal than a generic news API, and they are free.
- **How:** fetched in parallel with feedparser, normalized, low-signal items filtered (for example GDACS "Green" alerts and "no tropical cyclones at this time" housekeeping), deduplicated by canonicalized URL and normalized title, sorted newest first.
- **Cost:** free.

### 9.7 VADER (Valence Aware Dictionary and sEntiment Reasoner)
- **What:** a lexicon-and-rule sentiment analyzer that runs locally.
- **Used for:** deterministic article severity scoring when Gemini is unavailable, and for the live-fallback geopolitical score.
- **Why:** no API, no cost, fully deterministic, fast (2 to 3 seconds for a batch).
- **How:** compound score scaled by 6 to fit the project's severity banding.
- **Cost:** free, local. Caveat in section 7.6.

### 9.8 Google Gemini (Generative AI)
- **What:** Google's LLM API (model `gemini-3-flash-preview`).
- **Used for:** four things: per-article relevance + category + severity classification, the three-bullet daily briefing, the long-form `/report`, and the per-port operational summaries on the map. Also the morning newsletter briefing.
- **Why:** event severity and synthesis are exactly where an LLM beats a sentiment lexicon.
- **How:** every Gemini-powered component consults its own file cache and only calls the API when a TTL (default 24 hours) expires, which caps the API bill. JSON mode is used for structured outputs.
- **Cost:** optional; if `GEMINI_API_KEY` is absent, everything degrades to VADER and deterministic fallbacks.

### 9.9 Neon Postgres
- **What:** a serverless PostgreSQL provider.
- **Used for:** newsletter subscribers, the daily composite score history, and the per-category daily score history (the real backbone of the trend charts).
- **Why:** managed, serverless, free tier, and it persists across the host's ephemeral redeploys (Render wipes the disk; the database does not).
- **How:** `database.py` resolves Postgres versus SQLite lazily at connection time, with a 10-second connect timeout and a three-attempt retry to tolerate Neon's serverless cold starts.
- **Cost:** free tier.

### 9.10 SQLite
- **What:** the local, file-based fallback database for development.
- **Used for:** the same three tables when `DATABASE_URL` is not set.
- **Why:** zero-config local development.
- **How:** same schema, `check_same_thread=False` because Dash serves in threads.

### 9.11 Render
- **What:** the primary production host.
- **Used for:** running the Gunicorn web service and the newsletter cron job.
- **Why:** simple deploys from `main`, a health-check integration, and a generous free tier.
- **How:** build `pip install -r requirements.txt`, start `gunicorn app:server -c gunicorn.conf.py`, health check `/health`. The filesystem is ephemeral, which shaped the entire cache and fallback design.
- **Cost:** free tier (which spins the service down after inactivity; section 11 explains how the cache TTLs were tuned around that).

### 9.12 Vercel
- **What:** a serverless platform, configured as an alternate deploy.
- **Used for:** an optional serverless entry at `api/index.py`.
- **Why:** to show the app can run as a WSGI serverless function. Cache is redirected to `/tmp` when the `VERCEL` env var is present.

### 9.13 SMTP (newsletter delivery)
- **What:** a standard SMTP server (for example Gmail) for outbound email.
- **Used for:** the daily subscriber email.
- **How:** `scripts/send_newsletter.py` connects with STARTTLS, logs in, and sends a multipart (text plus HTML) message per subscriber with deliverability headers (Message-ID, List-Unsubscribe, Precedence bulk).

---

## 10. Architecture: how data flows and why it never blocks

### 10.1 The two-thread model
```
Background daemon thread (every 5 minutes)
  -> ThreadPoolExecutor fetches 6 providers + news + market + port summaries in parallel
  -> scoring/engine.py computes the composite
  -> writes to the in-memory cache (under a lock) and to disk (atomically)

Main thread (serves every request)
  -> reads the in-memory cache under the lock; NEVER calls an external API
  -> Dash callbacks render from the cached snapshot
  -> serve_layout() runs on every page load
```

The single most important rule of the whole project: **callbacks read from cache only**. Any external call in a request handler would hang the page. This is why page loads are instant even though the data behind them is live.

### 10.2 The shared global state and the lock
```python
_DATA_CACHE = None          # latest snapshot dict
_LAST_UPDATE = None         # UTC datetime of last fetch
_DATA_IS_FRESH = False      # True only after a real background fetch
_LAST_FETCH_STATUS = "starting"   # starting | running | ok | failed
_LAST_FETCH_ERROR = None
_LAST_FETCH_DURATION_SECONDS = None
_LOCK = threading.Lock()    # guards all of the above
```
Every read and write of those globals happens under `with _LOCK:`. The background thread is a daemon that sleeps 300 seconds between successful cycles and 60 seconds after an error.

### 10.3 The aggregator's parallelism and timeouts
`aggregate_data()` uses a `ThreadPoolExecutor(max_workers=3)` and submits the six providers plus three side tasks (news, market data, port summaries). It collects results with explicit timeouts tuned to each task's real latency:
- providers: 45 seconds (as a group, via `as_completed`)
- news (Gemini analysis): 120 seconds (the old 5-second timeout killed it every cycle)
- market data: 30 seconds
- port summaries (Gemini): 60 seconds

The executor is shut down with `wait=False, cancel_futures=True` in a `finally` block, so a single hung upstream call cannot freeze the update loop. A full live cycle completes in roughly 33 seconds with real keys.

### 10.4 Series alignment (the sparkline correctness fix)
Each provider's history series is reindexed onto a fixed 90-day daily date range with forward fill, and then the last point is overwritten with the live current score:
```python
aligned = hist_series.reindex(dates, method="ffill")
aligned.iloc[-1] = score   # force "today" to the live value, not yesterday's ffill
```
Without that last line, the sparkline and the day-over-day delta would show yesterday's stale close as today. Dates before the first real observation are deliberately left NaN (no backfill), so unmeasured history renders as a gap.

### 10.5 Degradation flags
If a provider fails or returns a non-finite score, the aggregator injects a neutral fallback (50 by default, or the per-category default) and marks the metadata `is_fallback=True`. It then computes `fallback_categories`, sets a `degraded` boolean, and propagates both into the snapshot, the `/api/v1/latest` payload, the `/health` payload, and a card badge. Fallback scores are explicitly excluded from the real daily history that gets persisted, so a temporary failure never pollutes the trend charts. This replaced an earlier pattern of silent fallbacks that injected 50/75/85 into the composite with no signal anywhere.

### 10.6 The geopolitical override
Because the news pipeline is the source of truth for the geopolitical category, the aggregator overwrites the geopolitical provider's snapshot with the fresh news result (score, alerts metadata, and the last history point), keeping the alerts and the score perfectly aligned.

---

## 11. The caching system and the cold-start fallback chain

### 11.1 Why caching is structural, not an optimization
On Render's free tier the filesystem is ephemeral (wiped on every deploy and spin-down) and the service spins down after inactivity. So the cache is not just for speed; it is what makes the app feel instant and what survives a redeploy gracefully.

### 11.2 The file cache
`data/cache.py` writes JSON files to `data/.cache/` (or `/tmp/supply_chain_cache/` on Vercel/Lambda). Writes are **atomic**: write to a temp file, `flush`, `fsync`, then `os.replace`, so a reader never sees a torn file. TTL is enforced by file mtime. There is a helper to read cache age, a clear-all, and dashboard-specific serialize/reconstruct functions that convert pandas Series and DatetimeIndex to JSON-safe lists and back.

### 11.3 TTL table
```
Weather              30 min to 4 h (current/batch cache 4 h)
FRED series          1 hour
News / RSS           4 hours (with hourly RSS re-score between Gemini runs)
Gemini components    ~24 hours (GEMINI_CACHE_TTL_SECONDS)
Market data          1 hour
Dashboard snapshot   24 hours
```
The dashboard snapshot uses a 24-hour TTL on purpose: on a host that spins down, a 1-hour TTL was expiring before any visitor returned, which forced a fallback to the days-old committed snapshot every time. Stale-but-real beats ancient.

### 11.4 Versioned cache keys
Cache keys carry a version suffix (for example `weather_current_v3`, `newsapi_briefing_v16`, `dashboard_snapshot_safe_v2`, `nyfed_gscpi_monthly_v2`). When the cached schema changes, you bump the version so old-shaped payloads are never deserialized into new code. This is a small discipline that prevents a whole class of "old data in new code" bugs.

### 11.5 The cold-start fallback chain
On boot, in order:
1. **In-memory cache** for the current session.
2. **Disk cache** via `get_cached_dashboard()` (24-hour TTL) from a prior successful run in this instance.
3. **The committed `fallback_snapshot_safe.json`** (the only cache file in git), days old but always present, used so cold-start users on Render see something instead of staring at a skeleton for 60 seconds. The narrative parts (alerts, briefing, report, disruptions) are blanked when loading from this snapshot so stale news is never shown.
4. **The loading skeleton** with a one-second boot poller that reloads the moment the background fetch lands, plus a 20-second provisional auto-refresh as a backstop.

The snapshot is also self-refreshing: when the live aggregator writes a fresh snapshot, it rewrites the committed fallback file if that file is more than seven days old, so cold-start users never see weeks-old data.

### 11.6 A documented race condition (intellectual honesty point)
`serve_layout()` has a self-healing path that refreshes worker memory from the newer disk snapshot. The code carries an explicit `TODO` noting a TOCTOU race: between reading `_LAST_UPDATE` under one lock and writing under another, the background thread could have produced fresher data, and the disk-is-newer check compares against the stale read. The fix (re-read under the write lock and abort if memory is newer) is noted in the code. Mentioning a known, documented race shows maturity; pretending the system is perfect does not.

---

## 12. The provider pattern and how to extend it

Every data source implements a small abstract interface in `data/providers/base.py`:
```python
class BaseProvider(ABC):
    category: str = ""   # must match a key in CATEGORY_WEIGHTS

    @abstractmethod
    def fetch_current(self) -> tuple[float, dict]:
        """Return (score 0..100 where 100=healthiest, metadata dict)."""

    @abstractmethod
    def fetch_history(self, days: int) -> pd.Series:
        """Return scores indexed by a DatetimeIndex."""
```

Required metadata keys: `source`, `raw_value`, `raw_label`, `description`, `calculation`, `updated` (and `is_fallback`, set by the aggregator). Those keys are what the detail modal renders, which is why the contract enforces them.

To add a category you: write a provider subclass, set its `category`, implement the two methods, register it in the aggregator's `_PROVIDERS` list, add a weight in `config.py` (rebalancing the others to keep the sum at 1.0), add labels and colors, and add a card and a chart line. The whole system is designed so a new signal is a localized change.

---

## 13. The database layer (Neon Postgres and SQLite)

### 13.1 Lazy dual backend
`_resolve_db_config()` checks `DATABASE_URL` at **connection time**, not import time. This matters because it lets `dotenv` load environment variables first (especially in the cron script), so the same code transparently uses Postgres in production and SQLite locally. A module-level `__getattr__` resolves `DB_TYPE` lazily for the same reason.

### 13.2 The three tables
```
subscribers            (email unique, subscribed_at, is_active)
daily_scores           (date primary key, score)            -- composite per day
daily_category_scores  (date, category, score, PK(date,category))  -- the real trend history
```
`daily_category_scores` is the quiet hero: it is the only honest source of category trend history, which is why geopolitical history reads from it.

### 13.3 Write discipline
`record_daily_scores(composite, category_scores)` upserts the composite and each category, guarded to write **at most once per hour** (the 5-minute cycle would otherwise burn Neon compute), and upserts so the stored row converges to the day's last reading instead of freezing the first post-midnight value. Only measured (non-fallback) scores are passed in.

### 13.4 Read helpers
`get_category_score_history(category, days)` returns a pandas Series over only the days actually measured (so it may be short or empty while history accumulates). `get_previous_daily_score()` returns the most recent score strictly before today, cached in memory for the calendar day so repeated page loads do not each open a Neon connection (and so a Neon cold start cannot block a render). Subscriber CRUD uses upserts that reactivate previously unsubscribed addresses.

---

## 14. The AI layer (Google Gemini) and the cost-control design

### 14.1 What Gemini does
- **`analyze_news_batch`**: one call returns both per-article analysis (relevance, category, severity from -10 to +10, a one-sentence summary, reasoning) and the three-bullet briefing, in a single JSON response, to halve API usage.
- **`generate_full_report`**: a 400 to 600 word Markdown intelligence report with a fixed five-section structure, no emojis.
- **`generate_port_summaries`** (`port_analyst.py`): a unique 1 to 2 sentence operational summary and a 0 to 50 disruption penalty for every one of the 37 ports, grounded in the top 100 recent news headlines so it is not hallucinating from a vacuum.
- **`generate_newsletter_briefing`**: the morning email's four-bullet summary from fresh, deduped, source-diverse articles.
- **`get_on_demand_briefing`**: the button-triggered briefing, cached.

### 14.2 The cost-control design (worth a slide)
Background work runs every few minutes, but each Gemini-powered component reads its own file cache and only calls the API when its TTL (default 24 hours) expires. So the dashboard refreshes constantly while the Gemini bill stays near a handful of calls per day. JSON mode (`response_mime_type`) is used for structured tasks; plain text for prose. Temperature is low (0.2 to 0.3) for analysis and reports, higher (0.7) for port variety.

### 14.3 Graceful degradation
If `GEMINI_API_KEY` is missing or a call fails, everything has a deterministic fallback: VADER scoring, a hand-built three-bullet briefing, a templated five-section report, and empty port summaries. The product never shows a broken panel because the AI was unavailable.

### 14.4 The deleted AI validator (a dead-code story)
There used to be an `ai_validator.py` that computed a score adjustment, clamped it to plus or minus 5, cached it, stored it, and then never applied it and never rendered it. It was pure compute with an API bill and no effect. The rigor pass deleted it entirely. Good example of "removing code is also engineering."

---

## 15. The news pipeline (RSS, NewsAPI, VADER, selection, dedupe)

The flow, end to end:
1. **Fetch** about 18 RSS feeds in parallel (`rss_fetcher.py`), each capped at a per-feed item count.
2. **Filter low signal** (`news_selection.is_low_signal_article`): drop housekeeping items like "no tropical cyclones at this time" and GDACS green alerts.
3. **Deduplicate** by canonicalized URL (tracking params like `utm_*`, `fbclid`, `gclid` stripped) and by normalized title.
4. **Classify and score**: Gemini when available, else VADER, with an irrelevance pre-filter that drops sports, crypto, lifestyle, supplements, 3D printing, apparel, and market-research spam before anything can pollute scores.
5. **Compute the volume-invariant risk score** (dedup, top 10 negatives, floor at -60).
6. **Cache** the whole payload (alerts, briefing, report) under a versioned key with a 24-hour Gemini TTL, and re-score from fresh RSS every hour in between (no API cost) so alerts stay current without re-billing Gemini.
7. **Self-heal**: if a cached payload is missing its briefing or report, rebuild deterministic fallbacks rather than serving broken panels for four hours.

For the newsletter, `select_fresh_articles` adds freshness windows (36-hour fresh, 72-hour fallback) and diversity caps (per-source and per-group limits) so one prolific feed cannot dominate the morning email.

---

## 16. The map: 37 ports, regional risk, and how each dot is colored

### 16.1 The port universe
`ports_data.py` defines 37 major ports across North America, Central and South America, Europe, East Asia, Southeast Asia, South Asia, the Middle East, Africa, and Oceania, each with coordinates and direct keywords for matching news.

### 16.2 The per-port score (four components)
Each marker's score is built from real data only:
```
score = 0.40 * local_weather          (real Open-Meteo at the port's lat/lon)
      + 0.60 * regional_macro          (region-weighted blend of the 5 non-weather categories)
      - structural_vulnerability        (0 to 10 fixed, for chronic-risk zones)
      - news_penalty                    (0 to 50, from matched negative articles)
clip 0..100
```

### 16.3 Region-specific macro weights
Twenty-plus region profiles (`_REGION_PROFILES`) give each region a different macro blend, so a tariff spike hurts Chinese ports more than Rotterdam, and a geopolitical event hammers Red Sea and Taiwan ports harder. Structural vulnerability encodes persistent risk: Red Sea 10 (Houthi attacks), Taiwan 8 (cross-strait tension), East Africa 6 (piracy), Panama 5 (drought capacity), and so on.

### 16.4 The news penalty (diminishing returns)
Matched negative articles (irrelevant ones pre-filtered) produce penalties with diminishing returns: the worst article counts fully, the rest at 20 percent, capped at 50. The AI port analyst can override with a higher penalty when it detects a specific severe disruption. The hover tooltip is transparent about all of this: region, macro score, top risk, AI status, and the headlines driving the color.

### 16.5 The honest caveat
This is the flashiest feature with the least data behind it: 40 percent local weather plus 60 percent regional macro, with no dwell times, no vessel queues, and no throughput. The AI summaries add operational color but are model-generated context, not measured port telemetry. Say this; it is exactly the kind of thing a sharp reviewer probes.

---

## 17. The frontend (Dash, Plotly, callbacks, the dark theme)

### 17.1 Framework
Dash 2.14+ (which wraps Flask) with Dash Bootstrap Components and Plotly for every chart. There are no separate CSS files; styling is inline plus a Bootstrap dark theme, with a custom index template that sets the page background before render to prevent a white flash.

### 17.2 The layout-as-a-function pattern
`app.layout` is a function (`serve_layout`), so it runs on every page load and reads the latest cache. It chooses a provisional 20-second auto-refresh or a fresh 5-minute auto-refresh based on data freshness, and it self-heals worker memory from a newer disk snapshot.

### 17.3 Callbacks (all read-only)
- A clientside callback reloads the page on the refresh interval.
- A boot callback polls every second on the skeleton and triggers a reload when data is ready.
- The category detail modal uses `ctx.triggered_id` to detect which card was clicked and builds the modal body from that category's metadata.
- The API modal and newsletter modal toggle on their buttons.
- The newsletter submit validates the email and calls `add_subscriber`.
- The on-demand briefing button calls Gemini (cached).
Every callback returns `dash.no_update` for outputs that should not change, and none of them ever triggers a fetch.

### 17.4 Theme and chart conventions
Dark palette (background `#0f1117`, cards `#1a1d26`, text `#e1e4ea`, grid `#1e2130`), all defined in `config.py`. Charts use transparent backgrounds, `dragmode=False`, fixed ranges, and unified hover. Fonts are Inter for UI and JetBrains Mono for numbers.

---

## 18. The newsletter system (SMTP, subscribers, cron)

`scripts/send_newsletter.py` is a standalone cron job (intended for Render Cron) that:
1. Fetches the dashboard snapshot from the live `/api/v1/newsletter-data` endpoint (token-protected), because the cron runs as a separate service with its own empty filesystem and cannot read the web service's disk. It falls back to the local disk cache for development.
2. Skips sending if the briefing is still in its placeholder startup state.
3. Builds a fresh morning briefing from public RSS sources via `select_fresh_articles` plus `generate_newsletter_briefing`, cached per calendar day so SMTP retries reuse the same text.
4. Renders a dark-themed HTML email (with a plain-text alternative) showing the score, tier, and the bullets.
5. Loads active subscribers from the database, adds an optional admin recipient, and sends per-subscriber with deliverability headers (unique Message-ID, List-Unsubscribe, Precedence bulk) over STARTTLS.
6. Emails the admin a dispatch summary (attempted, succeeded, failed).
Configuration is all environment variables (RECIPIENT_EMAIL, SMTP_SERVER/PORT/USERNAME/PASSWORD, WEBSITE_URL, ADMIN_TOKEN). A `--dry-run` flag prints instead of sending.

---

## 19. The public API and integrations

```
GET /api/v1/latest            Public. composite_index, categories, degraded,
                              fallback_categories, disruptions, map_markers, meta
GET /api/v1/newsletter-data   Admin (?token=ADMIN_TOKEN). scores, briefing, composite
GET /api/v1/admin/subscribers Admin (Bearer ADMIN_TOKEN). full subscriber list
GET /health, /healthz         Monitoring JSON
```
The public endpoint is rate-limited (Flask-Limiter, 2000/day and 500/hour, in-memory store) and returns a simplified, CC-BY-4.0 snapshot suitable for embedding. The composite is recomputed at request time from the cached category scores. The admin endpoints require either a query token or a Bearer token matching `ADMIN_TOKEN`. Note: there are two `TODO`s in the route code about serializing `pd.Timestamp` safely, an honest "rough edge" to acknowledge.

---

## 20. Deployment and operations (Render, Gunicorn, Vercel)

### 20.1 Render (primary)
- Build: `pip install -r requirements.txt`. Start: `gunicorn app:server -c gunicorn.conf.py`. Python 3.11 (`runtime.txt`).
- Boot sequence: empty disk cache, load the committed fallback snapshot, show the skeleton, background thread fetches fresh data in roughly 50 to 60 seconds, the 20-second provisional reload picks it up.

### 20.2 Gunicorn config (and a critical constraint)
```python
bind = "0.0.0.0:${PORT or 10000}"
workers = 1
threads = 8
worker_class = "gthread"
timeout = 120
```
**Exactly one worker.** The in-memory `_DATA_CACHE` is worker-local; multiple workers would each fetch independently and serve inconsistent numbers. Threaded (`gthread`) workers keep the health endpoint responsive even while `serve_layout()` is doing disk I/O. The 120-second timeout accommodates slow cold-start fetches.

### 20.3 The health endpoint policy
`/health` returns `state` of `healthy`, `warming_up`, or `degraded`, plus `data_age_seconds`, `last_fetch_status`, `last_fetch_error`, fetch duration, and `fallback_categories`. It returns HTTP 200 for healthy and warming_up (so Render does not fail the deploy during warmup) and HTTP 503 only when data is both failing and older than 30 minutes.

### 20.4 Vercel (alternate)
`vercel.json` rewrites all routes to `api/index.py`, which exposes the Flask WSGI app, with a 30-second max duration and `/tmp` cache redirection.

### 20.5 Environment variables
```
FRED_API_KEY    required  energy, tariffs, trucking scoring + WEI context
NEWSAPI_KEY     required  geopolitical fallback source + alerts
GEMINI_API_KEY  optional  briefing, report, news analysis, port summaries
DATABASE_URL    optional  Neon Postgres (omit for SQLite)
ADMIN_TOKEN     optional  protects newsletter-data and admin endpoints
PORT            optional  server port (10000 prod, 8050 dev)
SMTP_* etc.     optional  newsletter delivery
```

---

## 21. The rigor story: the bugs that were found and fixed

This is the most compelling 5 to 10 minutes of any talk, because it is the part that proves judgment. The framing: the author was asked to be skeptical of their own build and to flag anything that "would not survive a sharp interviewer asking why should I trust this number."

What the critique found, ordered by how badly each undermined credibility:
1. **Fabricated geopolitical history** (worst). The 90-day "Geopolitical Risk" trend was the VIX, normalized and level-shifted, presented as news sentiment. A comment falsely claimed it was real. Trucking did a milder version (heating oil plus a constant spread as daily diesel).
2. **The geopolitical score measured feed volume, not risk.** Unbounded sum of negative severities, no cap, no dedup, no normalization.
3. **The WEI sign was backwards** (the 2021 example: blend reported 60 "Stable" during the worst crisis ever).
4. **Cost-side normalization scored demand collapse as healthy** (negative-37-dollar oil reads as max health) and used a moving min/max dominated by outliers.
5. **Weights were arbitrary** and energy plus trucking co-load on petroleum (correlation north of 0.9), so the index was roughly one-third oil price and one-twelfth actual supply chain pressure.
6. **Re-aggregating GSCPI at an 8 percent effective weight** inside noisier signals strictly degraded the best input available.
7. **No backtesting**, and it could not even be backtested because two histories were synthetic.
8. Smaller: general EPU mislabeled as tariffs; the dead AI validator; a thin port map; silent fallbacks.

What was fixed in the correctness pass (without redesigning categories):
- Real stored history replaced both fabricated histories (`daily_category_scores`).
- WEI removed from the score (GSCPI only).
- Geopolitical score made volume-invariant (dedup, top 10, floor).
- Silent fallbacks made visible everywhere (`is_fallback`, `degraded`, badge, API, health).
- The dead AI validator deleted.
- Cost gauges reframed honestly and switched to rolling percentile rank.
- Tariffs switched to the trade-specific `EPUTRADE`.
- Severity labels fixed to the correct scale.
- Documentation drift corrected (the 85-vs-100 docstring, the map blend, the gthreads count).
- A pile of dead code removed.

**The punchline:** fixing the WEI mask surfaced the hidden GSCPI parser bug, and once GSCPI was read correctly the honest composite dropped from the low 60s to 39 ("Critical"). That is not a regression; it is the truth that the masking bug had been hiding. Letting that number stand is the whole point.

Verification that was actually run: clean imports across all modules; synthetic unit checks of the risk score's volume-invariance, dedup, and floor; percentile normalization checks; NaN-safe sparkline checks; a SQLite round trip of the daily-scores write and read; and a full live boot with real keys (about 33 seconds, zero errors, zero fallback categories, `/health` healthy, the API serving the new fields, and the first real daily-history rows confirmed in Neon).

---

## 22. Known limitations to own on stage

Owning these makes you more credible, not less:
- **Weights are not derived.** They are reasonable priors, pending a PCA and a sensitivity analysis.
- **Energy and trucking co-load on petroleum**, so the effective oil weight is larger than 0.20.
- **Energy and trucking are cost gauges, not demand gauges.** Demand-driven price moves are mis-read by design.
- **GSCPI calibration saturates** at plus or minus 2 sigma under `50 - 25z`, so it pins near 0 during sustained pressure.
- **The port map has no operational telemetry** (no dwell times, no queues, no throughput).
- **Tariffs and supply chain are monthly**, so those lines move slowly by design.
- **VADER is a weak severity proxy** on headlines; Gemini is better and is the primary path.
- **A documented TOCTOU race** exists in the worker self-heal path, with the fix noted in code.
- **Backtesting has not been run yet**; real history only began accumulating on 2026-06-10, which is the prerequisite.

---

## 23. Strategic directions (where it could go next)

A strong closer. Four distinct bets, all preserving the core features:
- **Direction A, the validated index ("show your work"):** same scope, but every number earns its place. Justify weights, anchor normalizations, store real history, fix signs, and publish a `/methodology` page with a backtest against the public disruption event library (Suez 2021, Shanghai 2022, Red Sea 2023+, Baltimore 2024, ILA strike 2024, plus tariff windows). Effort 3 to 5 weeks.
- **Direction B, an aerospace and manufacturing monitor:** stop measuring "the global supply chain" (GSCPI already does that better) and measure the industrial base the author wants to work in (LME/COMEX metals, industrial energy and freight, real trade-policy tracking, Census M3 aerospace orders and backlog, ISM supplier deliveries, chokepoints weighted by aerospace exposure). This is the recommendation, built on A's discipline, because the title alone does career work in a screening call. Effort 4 to 6 weeks.
- **Direction C, a daily GSCPI nowcast:** invert the GSCPI relationship and predict the next monthly print, scoring yourself against every release. Falsifiable by construction. Effort 3 to 4 weeks.
- **Direction D, event-driven disruption intelligence:** replace the VADER sum with typed event extraction (event class, chokepoint/region, mode, severity, dates, status, source URLs) using Gemini against a fixed schema and a hand-labeled eval set so precision and recall can be stated. This is the author's stated lean and the heaviest lift. Effort 5 to 8 weeks. The non-negotiable first artifact is a hand-labeled eval set of about 100 articles.

---

## 24. Talking points and likely Q&A

### Soundbites
- "The headline number is a demo of skill, not an operational decision tool, and I built it knowing that."
- "Two of my six histories were fabricated. I found it, I deleted it, and the honest number dropped to Critical. That is the project."
- "Every category score links to its own formula in the UI. If you do not trust a number, you can read exactly how it was made."
- "Energy and trucking measure cost pressure, not demand health. Negative-37-dollar oil would read as healthy, and I say so out loud."
- "The page never calls an external API. A background thread fetches, a lock-guarded cache serves, and an atomic disk write plus a committed fallback survive an ephemeral host."

### Likely questions and answers
- *Why should I trust the geopolitical number?* It is volume-invariant (dedup, top 10, floor), negative-only, and its history is real stored measurements, not a proxy.
- *Why one Gunicorn worker?* The in-memory cache is worker-local; more workers would serve inconsistent numbers.
- *What happens when a source fails?* The category serves a flagged neutral fallback, the failure is visible in the card, the API, and `/health`, and the fallback is excluded from stored history.
- *Why is the trend line for some categories a short stub?* Because that is the real measured history so far. I refuse to backfill synthetic data.
- *Is the LLM making up the report?* The report and port summaries are grounded in real fetched headlines, HTML-escaped before render, and they degrade to deterministic fallbacks if the API is down.

---

## 25. Glossary of every term and series used

- **GSCPI:** NY Fed Global Supply Chain Pressure Index. Monthly z-score from transport costs and PMI components across seven economies. Higher means more pressure.
- **WEI:** NY Fed Weekly Economic Index. A GDP-growth nowcast. Context only here; deliberately not in the score.
- **EPUTRADE:** FRED categorical Economic Policy Uncertainty index for trade policy (Baker, Bloom, Davis). Higher means more trade-policy uncertainty.
- **USEPUINDXD:** the general EPU index (formerly mislabeled as tariffs; replaced by EPUTRADE).
- **DCOILWTICO:** FRED daily WTI crude spot price (energy history and fallback).
- **CL=F:** front-month WTI crude futures (live energy price via yfinance).
- **GASDESW:** FRED weekly DOE US retail diesel price (trucking level and history).
- **HO=F:** heating oil futures (live high-frequency diesel proxy for the trucking nowcast).
- **NG=F, HG=F, GC=F, ^VIX:** natural gas, copper, gold, and the volatility index (market ticker).
- **VADER:** a local lexicon sentiment analyzer; compound score from -1 to +1.
- **WMO code:** World Meteorological Organization weather condition code (drives weather deductions).
- **Composite index:** the weighted 0 to 100 health score.
- **Health tiers:** Healthy 80+, Stable 60 to 79, Stressed 40 to 59, Critical below 40.
- **Cost gauge vs demand gauge:** a price-percentile measure of cost pressure, which is not a measure of demand health.
- **Volume invariance:** a risk score that does not move just because the feed returned more items.
- **Inverse percentile:** scoring where a lower raw value yields a higher health score, using percentile rank in a trailing window.
- **Fallback / degraded:** flags marking an injected neutral score (from a provider failure) rather than a measurement.
- **TOCTOU:** time-of-check to time-of-use, the documented race in the worker self-heal path.
- **Neon:** the serverless Postgres provider used in production.
- **Render:** the primary host. Ephemeral filesystem, spins down on inactivity, which shaped the cache design.
- **Dash / Plotly / Gunicorn / Flask-Limiter / feedparser / yfinance / psycopg2:** the framework, chart library, WSGI server, rate limiter, RSS parser, market client, and Postgres driver respectively.

---

## Appendix A: The full file map (what lives where)

```
app.py                     Entry point, background thread, Dash callbacks, /health
config.py                  Weights, tiers, colors, all tunable constants
gunicorn.conf.py           Production server config (1 worker, 8 gthreads)
Procfile / runtime.txt     Render start command and Python 3.11 pin
vercel.json / api/index.py Serverless alternate deploy

components/
  layout.py                Assembles the whole page
  cards.py                 Category cards + NaN-safe sparkline + fallback badge
  charts.py                90-day trend, health bars, world map
  gauge.py                 Composite semicircle gauge
  feed.py                  Briefing panel, alerts feed, disruptions table
  market_costs.py          Scrolling market ticker
  skeleton.py              Loading skeleton + boot poller

data/
  aggregator.py            Orchestrates providers, news, market, ports; builds the snapshot
  cache.py                 Atomic file TTL cache + dashboard serialize/reconstruct
  database.py              Lazy Postgres/SQLite, 3 tables, hourly score writes
  status.py                File-backed loading status message
  gscpi_client.py          NY Fed GSCPI CSV parser (handles both header formats)
  ai_analyst.py            Gemini: analysis, briefing, report, newsletter briefing
  port_analyst.py          Gemini: per-port summaries + disruption penalties
  rss_fetcher.py           Parallel RSS ingestion
  news_sources.py          ~18 curated feeds in 4 groups
  news_selection.py        Dedupe, low-signal filter, freshness + diversity selection
  ports_data.py            37 ports with coordinates and keywords
  fallback_snapshot_safe.json  Committed cold-start snapshot (only cache file in git)
  providers/
    base.py                Abstract provider interface
    weather.py             Open-Meteo, continuous deductions
    supply_chain.py        GSCPI only (WEI context)
    energy.py              WTI cost-pressure percentile
    tariffs.py             EPUTRADE percentile
    trucking.py            DOE weekly + HO=F nowcast
    geopolitical.py        News severity, volume-invariant, DB history
    fred_client.py         Shared FRED wrapper + percentile normalizers

scoring/
  engine.py                Weighted composite + tier lookup

api/
  routes.py                /api/v1/latest, /newsletter-data
  report.py                /report standalone page
  docs.py                  /docs page
  admin.py                 /api/v1/admin/subscribers
  briefing.py              On-demand briefing endpoint

scripts/
  send_newsletter.py       Daily SMTP cron job

tests/                     RSS, news-sources, news-selection, newsletter-digest, FRED checks
```

## Appendix B-0: A worked end-to-end example of the composite

Use this as a whiteboard moment. Suppose the live category scores on a given day are:

```
weather       82.0   (calm at most ports)
supply_chain   4.4   (GSCPI at +1.82 sigma -> 50 - 1.82*25 = 4.5, rounded)
energy        11.5   (WTI near the top of its 2-year range)
tariffs       40.0   (elevated trade-policy uncertainty)
trucking      13.3   (diesel near the top of its range)
geopolitical  74.0   (a few significant negative items)
```

Apply the weights:
```
0.10*82.0 =  8.20
0.20* 4.4 =  0.88
0.20*11.5 =  2.30
0.15*40.0 =  6.00
0.15*13.3 =  2.00
0.20*74.0 = 14.80
--------------------
composite = 34.18  -> "Critical"
```

This is essentially the real reading at the end of the rigor pass. The story to tell: weather and geopolitical look fine, but the three cost-and-pressure categories (supply chain, energy, trucking) are all near the worst end of their ranges, and because they carry 55 percent of the weight together, they drag the composite into Critical. The number is low because oil and diesel were expensive and GSCPI pressure was high, which is exactly what the index is supposed to register. Before the WEI mask was removed, this same day reported around 64 because a high WEI was drowning out GSCPI.

## Appendix B-1: The exact weather deduction functions

The four deductions are continuous, not threshold, which is what makes the daily score move smoothly.

```
Wind (km/h):    0 at <=10; then linear (speed-10)*30/70; capped at 30 (hurricane force)
Precip (mm):    0 at 0;    then linear mm*25/50;          capped at 25 (flood risk)
Temp (C):       0 in 10..30; else deviation*15/20;        capped at 15 (extremes)
WMO code:       thunderstorm/hail 30; heavy rain/snow/freezing 20; fog 15;
                moderate showers 12; slight 6; drizzle 4; overcast 2; partly cloudy 1; clear 0
```
Total possible deduction is 30 + 25 + 15 + 30 = 100, matching the 0 to 100 scale. The reasoning a reviewer will appreciate: port cranes stop near 60 km/h, so wind is the heaviest weather factor; fog is scored as a visibility/arrival problem rather than a precipitation problem; and temperature penalizes both cold and heat because both stress equipment and labor.

## Appendix B-2: The two normalization helpers (FRED scoring)

```python
def inverse_percentile_value(value, series, lookback_days=None):
    window = trailing_window(series, lookback_days or 730 days)
    if window.empty: return 50.0
    pct = (window <= value).mean()          # share of window at or below value
    return clip((1 - pct) * 100, 0, 100)    # cheaper than most -> high score

def normalize_series_inverse(series, lookback_days=None):
    pct = series.rolling("730D", min_periods=12).rank(pct=True)
    return ((1 - pct) * 100).clip(0, 100)   # whole-series version for history
```
`inverse_percentile_value` scores one current value (today's live price). `normalize_series_inverse` scores a whole series for the trend chart. Both use rolling percentile rank over a trailing two-year window, with `min_periods=12` so a monthly series like EPUTRADE still scores inside the window. The "inverse" is the key: a low raw value (cheap oil, calm policy) produces a high (healthy) score.

## Appendix B-3: How a single page request is served (step by step)

1. The browser requests `/`. Gunicorn (one worker, gthread) hands it to Flask/Dash.
2. `serve_layout()` runs. It reads `_DATA_CACHE`, `_DATA_IS_FRESH`, and `_LAST_UPDATE` under the lock.
3. It also checks the disk snapshot and, if the disk copy is strictly newer (or memory is empty, stale, or holding startup placeholder news), it refreshes worker memory from disk. This self-heals a worker whose background thread stalled.
4. If there is no data at all, it returns the skeleton (with a one-second boot poller).
5. Otherwise it computes the composite from the cached category scores, looks up the day-over-day delta from the database (suppressed if provisional), and builds the gauge, cards, map, trend, briefing, alerts, market ticker, and modals from the cached snapshot.
6. It picks a 20-second auto-refresh if provisional, else 5 minutes.
7. The response goes out. No external API was called during the request. Total time is dominated by Plotly figure construction, not I/O.

Meanwhile, independently, the background `DataUpdater` thread is on its own 5-minute loop fetching everything and rewriting both caches. The two never block each other except for the microsecond lock acquisitions around the shared globals.

## Appendix B-4: Failure modes and how each is handled

- **A provider raises or returns NaN/Inf:** the aggregator substitutes a neutral fallback (50 or the per-category default), tags `is_fallback=True`, surfaces it in the card badge, `degraded`, `/api/v1/latest`, and `/health`, and excludes it from stored history.
- **The whole provider times out (45s):** same fallback path, with `"Provider timed out"` as the error.
- **News/Gemini times out (120s) or returns nothing:** VADER scores the RSS deterministically; if even that is empty, the geopolitical category falls back to a neutral 85 baseline, and the briefing/report use templated fallbacks.
- **yfinance fails for energy:** it falls back to the latest FRED `DCOILWTICO` price.
- **GSCPI CSV format changes:** the parser handles both header formats and rejects mis-parses with sanity bounds rather than crashing.
- **Neon is cold or unreachable:** a 10-second connect timeout and three retries; the previous-score lookup is cached per day so a cold start cannot block a render, and a DB failure simply yields a zero delta.
- **Disk cache torn write:** impossible by construction, because writes go temp file -> fsync -> atomic os.replace.
- **Schema change in cached data:** versioned cache keys mean old payloads are ignored, not mis-deserialized.
- **Host redeploy wipes the disk:** the committed fallback snapshot loads instantly so users see real (if stale) numbers, the narrative fields are blanked, and the background fetch refreshes within a minute.
- **Background thread dies:** `serve_layout()`'s disk self-heal keeps serving the newest disk snapshot, and `/health` reports the stale age so monitoring catches it.

## Appendix B-5: Security and trust posture (talk-ready)

- **Untrusted model output** is HTML-escaped before Markdown rendering on `/report`, and `javascript:`/`data:` link protocols are stripped, so the LLM cannot inject script into the page.
- **Untrusted news input** runs through an irrelevance pre-filter and dedup before it can affect scores or port colors.
- **Admin endpoints** require a query token or a Bearer token equal to `ADMIN_TOKEN`; the public endpoint exposes only a simplified, licensed snapshot.
- **Rate limiting** (2000/day, 500/hour) protects the public API; Dash's hot-reload endpoint is exempted.
- **Secrets** are environment-only on the server (with one caveat: see the maintainer note below).

## Appendix B-6: The dashboard snapshot structure (the contract everything reads)

`aggregate_data()` returns one dict, the single object the entire UI and API consume:

```python
{
  "last_updated_utc": "2026-06-10T15:30:00Z",
  "dates": pd.DatetimeIndex,              # 90 daily dates
  "category_history": dict[str, pd.Series],  # 6 series, one per category (gaps as NaN)
  "current_scores": dict[str, float],    # 6 live scores
  "category_metadata": dict[str, dict],  # 6 metadata dicts (source, raw_value, calculation, is_fallback, ...)
  "map_markers": list[dict],             # 37 ports: name, lat, lon, score, description(HTML)
  "alerts": list[dict],                  # severity, title, body, category, url, source, timestamp, sentiment
  "briefing": str,                       # AI 3-bullet summary
  "full_report": str,                    # AI Markdown report
  "disruptions": list[dict],             # event, region, impact_score, categories, status
  "provider_errors": dict[str, str|None],# None means OK
  "market_data": dict,                   # CL=F, NG=F, HG=F, GC=F, ^VIX: price, prev, change_pct
  "degraded": bool,                      # True if any category is a fallback
  "fallback_categories": list[str],      # which categories are fallbacks
}
```
This is worth a slide because it makes the architecture concrete: producers (providers, news, market, ports) all write into this one shape, and consumers (layout, cards, charts, gauge, API) all read from it. The lock protects the handoff; the disk cache and the committed fallback are just serialized copies of this same shape.

## Appendix B-7: A suggested 30-minute talk flow

1. **Hook (2 min):** show the live site, then say "no one makes a decision from this number, and that is the point." Set up the duality.
2. **Who and why (3 min):** portfolio piece for sourcing/aerospace roles; optimizing for rigor in front of a sharp reviewer.
3. **The product tour (4 min):** gauge, six categories, map, trend, alerts, briefing, API. One sentence each (section 6).
4. **The scoring logic (6 min):** walk two or three categories in depth (GSCPI z-score, energy cost-percentile, geopolitical volume-invariance). Use the worked example in Appendix B-0.
5. **The two big ideas (3 min):** cost-gauge versus demand-gauge, and never fabricate history.
6. **The architecture (4 min):** background thread plus lock-guarded cache plus atomic disk plus committed fallback; "the page never calls an API." Use the request lifecycle in Appendix B-3.
7. **The rigor story (5 min):** the fabricated VIX history, the WEI sign error and the 2021 example, the hidden GSCPI parser bug, the honest drop to 39. This is the climax.
8. **Limitations and what is next (2 min):** own the caveats (section 22), then the four directions (section 23), landing on the aerospace monitor or event-extraction lean.
9. **Close (1 min):** "The interesting part was not building it. It was being willing to find that two of my six histories were fake and let the real number be Critical."

## Appendix B-8: The stack at a glance (one slide)

- **Language/runtime:** Python 3.11.
- **Web:** Dash 2.14+ on Flask, Dash Bootstrap Components, Plotly.
- **Server:** Gunicorn, 1 worker, 8 gthreads.
- **Data libs:** pandas, numpy, requests, feedparser, yfinance.
- **NLP/AI:** VADER (local), Google Gemini (`gemini-3-flash-preview`).
- **Data sources:** FRED, NY Fed GSCPI CSV, Open-Meteo, NewsAPI, ~18 RSS feeds, Yahoo Finance.
- **Database:** Neon Postgres (prod) / SQLite (dev), via psycopg2.
- **Caching:** atomic file-based TTL cache, versioned keys, committed cold-start fallback.
- **API protection:** Flask-Limiter (2000/day, 500/hour), token-gated admin routes.
- **Email:** SMTP with deliverability headers, daily cron.
- **Hosting:** Render (primary), Vercel (serverless alternate).

## Appendix B: Numbers you can quote

- 6 scored categories, weights summing to exactly 1.0.
- 37 ports on the map, 4 score components each, ~20 regional risk profiles.
- ~18 RSS feeds across 4 source groups; up to 25 articles sent to Gemini per cycle, up to 50 for the report, top 100 for port grounding.
- Geopolitical: top 10 negatives, deduction floored at -60.
- Background cycle every 300 seconds (60 on error); Gemini cache ~24 hours; dashboard snapshot TTL 24 hours; FRED 1 hour; weather 4 hours.
- Aggregator timeouts: providers 45s, news 120s, market 30s, ports 60s; full live cycle ~33s.
- 1 Gunicorn worker, 8 gthreads, 120s timeout.
- Health flips to 503 only when failing AND older than 30 minutes.
- The honest composite at the end of the rigor pass: 39 ("Critical").
```
