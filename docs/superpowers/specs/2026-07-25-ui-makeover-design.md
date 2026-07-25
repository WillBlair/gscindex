# UI Makeover Design — Global Supply Chain Index

**Date:** 2026-07-25  
**Status:** Approved direction (pending implementation plan)  
**Goals:** Portfolio first impression + daily ops usability  
**Aesthetic:** Cursor-inspired refined terminal (dark, quiet, expensive)

---

## 1. Intent

Refresh the dashboard so it no longer reads as a 2023 “tech HUD / indigo SaaS” mashup. Keep the existing information architecture and scoring behavior. Upgrade surface language, typography, tokens, and component consistency so the product feels modern, calm, and institutional.

Success looks like:

- First viewport feels intentional within ~2 seconds (brand, gauge, map, profile control).
- Dark UI uses hairline borders and muted hierarchy instead of glow, bezels, or rainbow chrome.
- Category cards *replace* cleanly on industry profile switch (already shipped); makeover must not regress that.
- Cold-start skeleton matches production chrome (no flash of legacy card styles).

---

## 2. Non-goals

- Light mode
- New data features, providers, or scoring changes
- Cursor IDE-style sidebar / multi-panel app shell
- Rebuilding Plotly charts from scratch (restyle to tokens only)
- Decorative motion, staggered page-load choreography, or hover “lift” animations

---

## 3. Visual system

### 3.1 Surfaces

| Token role | Target | Notes |
|------------|--------|-------|
| Canvas | `#0a0a0b` | Near-black page background |
| Surface | `#111113` | Cards, panels, modals |
| Surface raised | `#18181b` | Subtle secondary (ticker track, inputs) |
| Border | `rgba(255,255,255,0.10)` | Default hairline |
| Border strong | `rgba(255,255,255,0.16)` | Focus / hover |
| Text primary | `#ececef` | Titles, scores when not tier-colored |
| Text muted | `#8b8b93` | Labels, meta, timestamps |
| Text faint | `#5c5c66` | Tertiary chrome |

Depth comes from **border + one-step surface lift**, not drop shadows or colored glows.

### 3.2 Radius

One family only:

- Panels / cards / modals: `10px`
- Controls (select, buttons): `8px`
- Pills (status, small chips): `999px`

Remove tech-HUD corner ticks, bezels, and shine overlays.

### 3.3 Typography

- **UI sans:** IBM Plex Sans (Google Fonts; replaces Inter).
- **Data mono:** IBM Plex Mono for scores, ticker prices, weight badges, timestamps (replaces JetBrains Mono for a matched family).
- Hierarchy via size/weight/muted color — not accent color on every label.

### 3.4 Color discipline

- **Retire indigo (`#6366f1`) as brand accent.** Neutrals carry chrome; links use primary text + underline/opacity, or a single quiet accent if needed for focus rings only.
- **Health tiers remain the only strong semantic color** (Healthy / Stable / Stressed / Critical). Slightly desaturate current greens/oranges/reds so they sit on the zinc canvas without neon.
- **Category chart colors:** replace the Tailwind rainbow with a short, muted palette (6–8 distinguishable but calm hues) including semiconductor categories.
- Map marker coloring continues to respect existing rank + absolute Critical/Healthy guardrails; only hex values change to match the new tier palette.

### 3.5 Design tokens

Introduce `:root` CSS variables in `assets/style.css` for surfaces, text, borders, radii, fonts, and health tiers.

Keep `config.py` `COLORS` / `HEALTH_TIERS` / `CATEGORY_COLORS` as the Python source of truth for Plotly and server-rendered inline styles. Values must match the CSS tokens (document the mapping in a short comment block in both places). Long-term goal of this makeover: **eliminate ad-hoc hex in component Python** wherever a token already exists; remaining inline styles should reference `COLORS[...]`.

---

## 4. Layout (preserve)

Keep the live section order and grid shell (max-width ~1400px, existing breakpoints):

1. Header (brand + profile select + meta/nav)
2. Hero: gauge + world map
3. Market ticker
4. Category cards row (profile-driven `card_categories`)
5. Briefing + news
6. Health bars + 90-day trend
7. Footer

No structural redesign into a marketing landing page. Spacing may increase slightly for breathability, but density stays appropriate for an ops dashboard.

---

## 5. Component treatments

### 5.1 Header

- Brand block left; profile `dbc.Select` as a quiet pill under/near title (current structure OK).
- Meta + Docs / API / Newsletter / Live packed right; muted mono for timestamps.
- Live indicator: **static green/amber dot + label** (no pulse animation).

### 5.2 Gauge + map panels

- Shared panel class: surface fill, 1px border, 10px radius, consistent padding.
- Plotly paper/plot backgrounds transparent or token surface; gridlines use faint border color.
- Score tooltip restyled to token surfaces; keep behavior.

### 5.3 Market ticker

- Raised surface track, hairline border, mono prices.
- Green/red only on change direction; labels muted.
- Keep pause-on-hover scrolling behavior (functional, not decorative entrance motion).

### 5.4 Category cards

- **Single card system:** `.tech-card` becomes the only live card language (rename conceptually to “metric card” in CSS if useful). Delete unused `.metric-card` / orphan sparkline rules or repoint skeleton to the live classes.
- Content preserved: label, weight (muted text, not indigo pill), score (tier color), 24h Δ, LO/HI, sparkline, fallback badge.
- Hover: border color to `border-strong` only — **no translate/scale/shadow animation**.
- Profile switch continues to replace `cards-container` children via `card_categories`.

### 5.5 Briefing + news

- Same panel shell as hero charts.
- Severity badges: small, low-contrast pills; severity still readable (color + text).
- Reduce inline hex; use tokens / `COLORS`.

### 5.6 Health bars + trend chart

- Restyle bars to token surfaces; remove shine/glow if present.
- Trend lines use the new muted `CATEGORY_COLORS`.
- Chart titles/legends use UI sans + muted secondary text.

### 5.7 Modals (API, newsletter, details)

- Restyle to surface + hairline border matching the app.
- Neutralise Bootstrap DARKLY clashes (`--bs-modal-*` overrides or custom modal chrome).
- In scope for v1 so the makeover doesn’t break when users open Docs-adjacent flows.

### 5.8 Skeleton / provisional

- Align skeleton markup/classes with production (ticker present or intentionally omitted with matching gap; cards use live card classes; section order matches `layout.py`).
- Provisional “Updating…” state uses amber text/dot without pulse animation.

---

## 6. Motion policy

**Default: no motion.**

Allowed:

- Instant state changes (profile switch content replace, modal open/close without flourish).
- Existing ticker horizontal scroll (data conveyor, not UI chrome animation).
- Browser/OS focus outlines for accessibility.

Disallowed:

- Staggered page-load fades/slides
- Pulsing live dots
- Hover lift / scale / glow transitions beyond an instant or ≤100ms border-color change
- Shimmer/shine loops on bars or cards

If a CSS transition remains for border-color, keep it ≤100ms or remove entirely.

---

## 7. Implementation boundaries

Primary files:

- `assets/style.css` — tokens, surface language, delete HUD debt
- `config.py` — `COLORS`, `HEALTH_TIERS`, `CATEGORY_COLORS`
- `app.py` — font stylesheets; reduce DARKLY conflict; drop pulse classes if unused
- `components/layout.py`, `cards.py`, `charts.py`, `gauge.py`, `feed.py`, `market_costs.py`, `skeleton.py` — class/style alignment to tokens

Do not change aggregator/scoring/provider logic.

---

## 8. Acceptance checklist

- [ ] No Inter; UI + mono fonts load and apply sitewide
- [ ] No corner ticks / bezels / indigo weight pills / pulse animations
- [ ] All major surfaces share one border + radius language
- [ ] CSS `:root` tokens exist and match `config.py` palette
- [ ] Semiconductor profile still replaces (not appends) the six cards
- [ ] Skeleton matches production card/panel language
- [ ] Modals readable and on-theme
- [ ] Gauge, map, ticker, cards, briefing, trend all use the new palette
- [ ] No decorative entrance or hover motion

---

## 9. Decisions log

| Decision | Choice |
|----------|--------|
| Audience | Both portfolio + daily use |
| Aesthetic | Cursor-like refined terminal |
| Motion | Minimal / none (user preference) |
| Accent | Neutrals + health tiers; drop indigo brand |
| Layout | Preserve current IA |
| Modals | In scope for v1 |
