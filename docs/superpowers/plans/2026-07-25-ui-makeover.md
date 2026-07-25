# UI Makeover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Global Supply Chain Index dashboard to a Cursor-inspired refined terminal dark UI (tokens, typography, quiet surfaces) without changing scoring, layout IA, or adding decorative motion.

**Architecture:** Python `config.py` remains the source of truth for Plotly/inline colors; `assets/style.css` gets matching `:root` CSS variables. Components stop hardcoding indigo/Inter/HUD chrome and consume `COLORS` + CSS classes. Skeleton is realigned to production card/panel classes.

**Tech Stack:** Dash + dash-bootstrap-components, Plotly, plain CSS in `assets/style.css`, Google Fonts (IBM Plex Sans + IBM Plex Mono), pytest for palette/contract checks.

**Spec:** [`docs/superpowers/specs/2026-07-25-ui-makeover-design.md`](../specs/2026-07-25-ui-makeover-design.md)

## Global Constraints

- No light mode; no scoring/provider/aggregator changes; preserve layout section order.
- No decorative motion (no pulse, no staggered load, no hover lift). Ticker scroll stays.
- Retire indigo brand accent (`#6366f1`); neutrals + health tiers only for strong color.
- Fonts: IBM Plex Sans + IBM Plex Mono (not Inter / JetBrains Mono).
- Surfaces: canvas `#0a0a0b`, surface `#111113`, raised `#18181b`, border `rgba(255,255,255,0.10)`, text `#ececef` / muted `#8b8b93` / faint `#5c5c66`.
- Radius: panels/cards `10px`, controls `8px`, pills `999px`.
- Semiconductor `card_categories` replace behavior must not regress.
- Frequent commits after each task.

## File map

| File | Responsibility |
|------|----------------|
| `config.py` | New `COLORS`, desaturated `HEALTH_TIERS`, muted `CATEGORY_COLORS` |
| `tests/test_ui_palette.py` | Contract tests that palette keys/values match the makeover |
| `assets/style.css` | `:root` tokens; kill HUD ticks/bezels/pulse; unify panels/cards/modals |
| `app.py` | Font stylesheets; remove `pulsing` live-dot class usage if present |
| `components/layout.py` | Header link colors via `COLORS`; modal chrome tokens; no pulse class |
| `components/cards.py` | Weight/fallback styling via tokens; no indigo |
| `components/charts.py` | Font family strings → Plex; grid/bg from `COLORS` |
| `components/gauge.py` | Font family strings → Plex |
| `components/feed.py` | Drop accent indigo on briefing title/badges; use muted/primary |
| `components/market_costs.py` | Already uses `COLORS` — verify after palette swap |
| `components/skeleton.py` | Match production structure/classes; no `.metric-card` |

---

### Task 1: Palette contract in `config.py` + tests

**Files:**
- Modify: `config.py` (`HEALTH_TIERS`, `CATEGORY_COLORS`, `COLORS`)
- Create: `tests/test_ui_palette.py`

**Interfaces:**
- Produces: `COLORS` keys `bg`, `card`, `card_raised`, `card_border`, `text`, `text_muted`, `text_faint`, `accent` (quiet focus only), `green`, `yellow`, `orange`, `red`, `blue`, `grid`
- Produces: desaturated `HEALTH_TIERS[*].color` and muted `CATEGORY_COLORS` for all baseline + chip keys

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_palette.py`:

```python
"""Palette contract for the 2026-07-25 UI makeover."""
from config import CATEGORY_COLORS, COLORS, HEALTH_TIERS, INDUSTRY_PROFILES


def test_canvas_and_surface_tokens():
    assert COLORS["bg"] == "#0a0a0b"
    assert COLORS["card"] == "#111113"
    assert COLORS["card_raised"] == "#18181b"
    assert COLORS["text"] == "#ececef"
    assert COLORS["text_muted"] == "#8b8b93"
    assert COLORS["text_faint"] == "#5c5c66"
    assert COLORS["accent"] != "#6366f1"


def test_health_tier_colors_desaturated():
    by_label = {t["label"]: t["color"] for t in HEALTH_TIERS}
    assert by_label["Healthy"] == "#3d9b6e"
    assert by_label["Stable"] == "#c4a35a"
    assert by_label["Stressed"] == "#c47a3a"
    assert by_label["Critical"] == "#c44d5f"


def test_category_colors_cover_all_profile_keys():
    keys = set()
    for prof in INDUSTRY_PROFILES.values():
        keys.update(prof["weights"])
    assert keys <= set(CATEGORY_COLORS)
    # No leftover neon purple brand accent as a category default
    assert "#8b5cf6" not in CATEGORY_COLORS.values()
    assert "#6366f1" not in CATEGORY_COLORS.values()


def test_green_red_aliases_match_tiers():
    assert COLORS["green"] == "#3d9b6e"
    assert COLORS["red"] == "#c44d5f"
    assert COLORS["yellow"] == "#c4a35a"
    assert COLORS["orange"] == "#c47a3a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ui_palette.py -v`  
Expected: FAIL (old hex values / missing `card_raised` / `text_faint`)

- [ ] **Step 3: Update `config.py` palette**

Replace `HEALTH_TIERS` colors and `CATEGORY_COLORS` / `COLORS` with:

```python
HEALTH_TIERS: list[dict] = [
    {"min": 80, "max": 100, "label": "Healthy",  "color": "#3d9b6e"},
    {"min": 60, "max": 79,  "label": "Stable",   "color": "#c4a35a"},
    {"min": 40, "max": 59,  "label": "Stressed", "color": "#c47a3a"},
    {"min": 0,  "max": 39,  "label": "Critical", "color": "#c44d5f"},
]

CATEGORY_COLORS: dict[str, str] = {
    "weather":             "#6b8cae",
    "supply_chain":        "#8a7e9c",
    "freight":             "#5f8f7a",
    "energy":              "#b8956a",
    "tariffs":             "#a66d6d",
    "geopolitical":        "#a67c5b",
    "chip_fab_util":       "#5f8f9c",
    "chip_memory_prices":  "#7d7394",
    "chip_lead_times":     "#5a8f86",
    "chip_wafer_prices":   "#9c6b7a",
}

# Keep in sync with :root tokens in assets/style.css (UI makeover 2026-07-25).
COLORS = {
    "bg":           "#0a0a0b",
    "card":         "#111113",
    "card_raised":  "#18181b",
    "card_border":  "rgba(255,255,255,0.10)",
    "text":         "#ececef",
    "text_muted":   "#8b8b93",
    "text_faint":   "#5c5c66",
    "accent":       "#a1a1aa",  # quiet focus / link hover — not indigo
    "green":        "#3d9b6e",
    "yellow":       "#c4a35a",
    "orange":       "#c47a3a",
    "red":          "#c44d5f",
    "blue":         "#6b8cae",
    "grid":         "#1e1e22",
}
```

Update `hex_to_rgba` docstring example away from `#6366f1`.  
Note: `card_border` becomes rgba — any code that assumed hex for `hex_to_rgba(COLORS["card_border"])` must be checked; prefer using the string directly as CSS.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ui_palette.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_ui_palette.py
git commit -m "feat(ui): adopt refined-terminal palette in config"
```

---

### Task 2: CSS tokens + kill HUD / pulse chrome

**Files:**
- Modify: `assets/style.css`

**Interfaces:**
- Consumes: palette values from Task 1 (must match exactly)
- Produces: `:root` variables `--bg`, `--surface`, `--surface-raised`, `--border`, `--border-strong`, `--text`, `--text-muted`, `--text-faint`, `--radius-panel`, `--radius-control`, `--font-sans`, `--font-mono`, `--tier-healthy|stable|stressed|critical`

- [ ] **Step 1: Add `:root` block at top of `assets/style.css` (after any reset/body preamble comment)**

```css
:root {
    --bg: #0a0a0b;
    --surface: #111113;
    --surface-raised: #18181b;
    --border: rgba(255, 255, 255, 0.10);
    --border-strong: rgba(255, 255, 255, 0.16);
    --text: #ececef;
    --text-muted: #8b8b93;
    --text-faint: #5c5c66;
    --radius-panel: 10px;
    --radius-control: 8px;
    --radius-pill: 999px;
    --font-sans: "IBM Plex Sans", system-ui, sans-serif;
    --font-mono: "IBM Plex Mono", ui-monospace, monospace;
    --tier-healthy: #3d9b6e;
    --tier-stable: #c4a35a;
    --tier-stressed: #c47a3a;
    --tier-critical: #c44d5f;
}
```

- [ ] **Step 2: Rewire `body`, `.dashboard`, `.dash-header`, `.chart-panel`, `.panel`, `.tech-card`, `.header-meta`, fonts to use variables**

Concrete replacements (search/replace in CSS):

- `background: #0f1117` / `#0f1117` → `var(--bg)`
- card `#1a1d26` / `#11131a` → `var(--surface)`
- text `#e1e4ea` → `var(--text)`; muted `#8a8f9e` → `var(--text-muted)`
- borders `#2a2d3a` / `rgba(255,255,255,0.1)` → `var(--border)`
- `font-family: "Inter"...` → `var(--font-sans)`
- `font-family: "JetBrains Mono"...` → `var(--font-mono)`
- panel/card `border-radius` → `var(--radius-panel)` where those surfaces are

- [ ] **Step 3: Remove HUD / motion debt**

Delete or neutralize:

- `.live-dot.pulsing` rule and `@keyframes livePulse`
- `.tech-card::after` corner-tick blocks (both occurrences ~lines 339 and 1230)
- `.tech-card-bezel` styles (hide with `display: none` or remove class usage in Task 4)
- `@keyframes shimmer` and any shine/glow on health bars
- Indigo `#6366f1` rules (profile focus may use `var(--border-strong)` + `var(--text)`)

Hover for `.tech-card`:

```css
.tech-card:hover {
    border-color: var(--border-strong);
    /* no transform, box-shadow, or filter */
}
```

Keep `@keyframes ticker-scroll` (allowed functional motion).

- [ ] **Step 4: Modal + Bootstrap overrides**

Add:

```css
.modal-content {
    background: var(--surface) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-panel) !important;
}
.modal-header, .modal-footer {
    border-color: var(--border) !important;
}
.modal-title { color: var(--text) !important; }
```

- [ ] **Step 5: Orphan cleanup**

Either delete unused `.metric-card` blocks or leave a one-line comment that skeleton no longer uses them (Task 6 removes usage). Prefer deleting dead `.metric-card` rules once skeleton is updated — if doing CSS first, comment `/* legacy: removed in skeleton task */` and delete in Task 6.

- [ ] **Step 6: Visual smoke (no server assert)**

Run: `rg -n "livePulse|6366f1|tech-card-bezel|JetBrains|Inter" assets/style.css`  
Expected: no matches for `livePulse`, `6366f1`, `JetBrains`, `Inter` (bezel may remain only if Task 4 still emits the class — then hide via CSS).

- [ ] **Step 7: Commit**

```bash
git add assets/style.css
git commit -m "feat(ui): add CSS tokens and remove HUD/pulse chrome"
```

---

### Task 3: Fonts in `app.py` + kill pulse class

**Files:**
- Modify: `app.py` (external_stylesheets ~248–251; any `pulsing` references)
- Modify: `components/layout.py` (live-dot className)

**Interfaces:**
- Consumes: Google Fonts URLs for IBM Plex Sans + Mono
- Produces: layout live indicator without `pulsing` class

- [ ] **Step 1: Replace font stylesheets in `create_app()`**

```python
external_stylesheets=[
    dbc.themes.DARKLY,
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap",
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap",
],
```

Also update `app.index_string` boot background if it hardcodes `#0f1117` → `#0a0a0b`.

- [ ] **Step 2: Remove pulse from live dot in `components/layout.py`**

Change:

```python
className="live-dot" if is_provisional else "live-dot pulsing",
```

to:

```python
className="live-dot",
```

Keep color: green when live, amber when provisional (`COLORS["green"]` / `COLORS["yellow"]` preferred over raw hex).

- [ ] **Step 3: Header link colors**

Replace hardcoded `#6366f1` / `#10b981` on Docs/API/Newsletter with muted/primary:

```python
style={"color": COLORS["text_muted"], "fontWeight": "600", "fontSize": "14px", "textDecoration": "none"}
```

Import `COLORS` if not already (layout already imports from config — add `COLORS` to the import). Newsletter may stay slightly emphasized with `COLORS["green"]` or stay muted for stricter Cursor look — **use muted for all three** per spec neutrals.

- [ ] **Step 4: Commit**

```bash
git add app.py components/layout.py
git commit -m "feat(ui): switch to IBM Plex and remove live-dot pulse"
```

---

### Task 4: Cards, gauge, charts, feed, market — consume new palette/fonts

**Files:**
- Modify: `components/cards.py`
- Modify: `components/gauge.py`
- Modify: `components/charts.py`
- Modify: `components/feed.py`
- Modify: `components/market_costs.py` (verify only)
- Modify: `components/layout.py` (modal inline styles)

**Interfaces:**
- Consumes: Task 1 `COLORS` / `CATEGORY_COLORS` / `HEALTH_TIERS`
- Produces: no `"Inter"` / `"JetBrains Mono"` / `#6366f1` string literals in `components/`

- [ ] **Step 1: cards.py**

- Remove bezel child if present: delete `html.Div(className="tech-card-bezel")` from card children.
- Fallback badge already uses `COLORS["orange"]` — OK after palette swap.
- Ensure weight badge has no indigo (CSS handles `.tech-weight`).

- [ ] **Step 2: gauge.py — font families**

Replace every `"Inter"` with `"IBM Plex Sans"` and `"JetBrains Mono, monospace"` with `"IBM Plex Mono, monospace"`.

- [ ] **Step 3: charts.py — fonts + fallback color**

```python
# title/legend/map fonts
"family": "IBM Plex Sans"
# health bar label style
"fontFamily": "IBM Plex Sans, sans-serif"
# fallback when category missing
CATEGORY_COLORS.get(cat, COLORS["text_muted"])  # was COLORS["accent"]
```

If map/geo uses `COLORS["card_border"]` as a Plotly color and rgba breaks Plotly, set a solid hex for plot-only borders in COLORS e.g. keep `"card_border_solid": "#2a2a2e"` **or** use `#2a2a2e` only in charts geo lines while CSS uses rgba. Prefer adding:

```python
"card_border_hex": "#2a2a2e",  # Plotly cannot take rgba for some geo attrs
```

and use `COLORS["card_border_hex"]` in `charts.py` geo line colors. Update test to allow the extra key.

- [ ] **Step 4: feed.py — retire accent indigo on briefing**

- Briefing title: `style={"color": COLORS["text"]}` (not accent)
- Any accent border/badge for briefing → `COLORS["card_border"]` / `COLORS["text_muted"]`
- Severity badges: keep tier colors; reduce visual weight via CSS class if needed

- [ ] **Step 5: layout.py modals**

Replace newsletter/API modal inline `#0f1117`, `#1a1d26`, `#6366f1` with `COLORS["bg"]`, `COLORS["card"]`, `COLORS["text"]` / `COLORS["text_muted"]`. Primary button: solid `COLORS["text"]` on `COLORS["bg"]` or inverted white-on-dark pill (`backgroundColor: COLORS["text"]`, `color: COLORS["bg"]`) — Cursor-like CTA.

- [ ] **Step 6: Grep gate**

Run: `rg -n "Inter|JetBrains|#6366f1|#0f1117|#1a1d26" components/ app.py`  
Expected: no matches (except possibly comments).

- [ ] **Step 7: Commit**

```bash
git add components/cards.py components/gauge.py components/charts.py components/feed.py components/layout.py config.py tests/test_ui_palette.py
git commit -m "feat(ui): restyle components to refined-terminal tokens"
```

---

### Task 5: Skeleton parity

**Files:**
- Modify: `components/skeleton.py`

**Interfaces:**
- Consumes: production section order from `components/layout.py`
- Produces: skeleton using `.header-brand`, `.chart-panel`, `.tech-card` (not `.metric-card`), ticker placeholder, section order matching live layout

- [ ] **Step 1: Rewrite skeleton structure**

Match live order:

1. Header with `.header-brand` + `.header-meta` placeholders  
2. `.hero-row` gauge + map panels  
3. Ticker placeholder: `html.Div(className="market-section-ticker", children=[html.Div(className="skeleton-pulse", style={...})])`  
4. `.cards-row` with six `.tech-card` skeletons (not `.metric-card`)  
5. `.bottom-row` briefing/news panels  
6. `.charts-row` health + trend  

Remove JetBrains inline font; rely on CSS `var(--font-mono)` / sans.

Replace `skeleton-pulse` animation: if it shimmers, either remove animation from `.skeleton-pulse` in CSS (static muted blocks) per motion policy, or keep a single low-contrast static fill without `@keyframes`. **Prefer static** — update CSS:

```css
.skeleton-pulse {
    background: var(--surface-raised);
    /* no animation */
}
```

- [ ] **Step 2: Commit**

```bash
git add components/skeleton.py assets/style.css
git commit -m "feat(ui): align skeleton with production chrome"
```

---

### Task 6: Acceptance pass

**Files:**
- Verify only (fix gaps if grep/tests fail)

- [ ] **Step 1: Run palette tests**

Run: `python3 -m pytest tests/test_ui_palette.py -v`  
Expected: PASS

- [ ] **Step 2: Grep acceptance**

```bash
rg -n "Inter|JetBrains|#6366f1|livePulse|metric-card|tech-card-bezel" \
  assets/style.css components/ app.py config.py
```

Expected: no hits (or only historical comments in docs/).

- [ ] **Step 3: Manual dashboard check**

Run: `python3 app.py` → open `http://127.0.0.1:8050`

Checklist:

- Fonts are Plex; no Inter
- Cards/panels share hairline border + 10px radius; no corner ticks
- Live dot does not pulse
- Profile → Semiconductor replaces six cards (fab/memory/lead/wafer/supply/geo)
- Modals on-theme
- Gauge/map/ticker/trend use muted palette

- [ ] **Step 4: Final commit if any fixups**

```bash
git add -A
git commit -m "fix(ui): makeover acceptance fixups"
```

Only create this commit if Step 3 found issues that required code changes.

---

## Spec coverage (self-review)

| Spec section | Task |
|--------------|------|
| 3.1 Surfaces | 1, 2 |
| 3.2 Radius | 2 |
| 3.3 Typography | 2, 3, 4 |
| 3.4 Color discipline | 1, 4 |
| 3.5 Tokens | 1, 2 |
| 4 Layout preserve | 5 (skeleton only; live layout unchanged) |
| 5.1–5.7 Components | 2, 3, 4 |
| 5.8 Skeleton | 5 |
| 6 Motion policy | 2, 3, 5 |
| 8 Acceptance | 6 |
| card_categories regression | 6 manual + existing callback untouched |

## Placeholder scan

None intentional. Plotly rgba edge case handled via optional `card_border_hex` in Task 4 Step 3.
