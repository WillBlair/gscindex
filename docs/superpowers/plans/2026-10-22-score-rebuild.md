# Score Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rolling-percentile, headline-tone composite with eight categories. Each is scored from published long-history sources and mapped to 0–100 through fixed anchors, so the index reads real events and ranks how severe they are.

**Architecture:** One pure mapping function (`scoring/anchors.py`) and one input-blending helper (`data/providers/readings.py`) are shared by every provider. Raw-source fetchers live in `data/sources/`. One provider per category produces the score plus per-input freshness metadata. Anchors are generated offline by `scripts/compute_anchors.py` into a committed `data/score_anchors.json`. The aggregator gains explicit stale, fallback and exclusion handling and stores the composite in the snapshot.

**Tech Stack:** Python 3.13, pandas 3, Dash 4.4, Flask, requests, yfinance, anthropic, SQLite/PostgreSQL. New dependency: `openpyxl` (for the TPU and Fed survey xlsx files).

**Spec:** `docs/superpowers/specs/2026-10-22-score-rebuild-design.md`. Research numbers: `docs/superpowers/research/2026-10-22-score-inputs-research.md`. Research code and samples: `docs/superpowers/research/2026-10-22-artifacts/`.

## Global Constraints

- Run everything with `DATABASE_URL=` (empty) and `GSC_DISABLE_BACKGROUND=1`. The `.env` `DATABASE_URL` is the PRODUCTION database. Use the interpreter `venv/bin/python`.
- Test command: `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/<file> -v`. Tests must never hit the network: mock `requests.get`, yfinance and `data.cache` the way `tests/portwatch_test.py` does.
- Commit after each task. Never push or deploy. Never write to the production DB.
- All tunables go in `config.py`. Generated anchors go in `data/score_anchors.json`, loaded by `config.py` as `SCORE_ANCHORS`.
- Scores are 0–100, where 100 = healthiest. Anchors: 100 = healthiest 5% of pre-2020 history, **80 = pre-2020 median**, 0 = worst monthly average on record through 2025. Frozen.
- Never invent or backfill history. `fetch_history` returns real recomputed values dated by publication lag. Days before the first real observation stay NaN.
- New provider metadata keys, in addition to the existing required six: `as_of` (ISO date of the oldest input used), `is_stale` (bool), `inputs` (list from `inputs_metadata`).
- A provider whose inputs are all missing raises `RuntimeError`, and the aggregator handles the fallback. Providers never return a neutral constant.
- Pin every new dependency to an exact version in `requirements.txt`.
- Cache keys are versioned. New keys end in `_v1`.
- PortWatch credit text, verbatim: `Sources: UN Global Platform; IMF PortWatch`.

**Canonical input keys** (used in config, anchors JSON, readings and metadata): `gscpi`, `chokepoint_flow`, `brent`, `ulsd`, `ttf`, `ttf_monthly`, `tariff_burden`, `tpu`, `gpr`, `geo_register`, `tsifrght`, `rail_volume`, `prices_paid`, `copper`, `aluminum`, `copper_monthly`, `aluminum_monthly`, `hazards`, `gatun`, `mississippi`.

**Category keys:** `supply_chain`, `chokepoints`, `energy`, `tariffs`, `geopolitical`, `freight`, `inputs`, `physical`.

## Review Focus

1. **A source returns HTTP 200 with an empty or reshaped file** (the GPR .dta columns renamed, the TPU sheet missing, an empty ArcGIS feature list). The input must count as missing and the category must fall back. It must never score 0 or 100. Pinned in Tasks 3, 5, 6, 8 and 10 by an "empty or reshaped payload raises" test per source, and in Task 9 by an "omitted, not raised" test for a failed survey.
2. **Yahoo returns a stale or rescaled quote**: a close dated before the official spot date, or a ratio outside 0.5–2.0, as when TTF changes units. Live scaling must be skipped and the official value used, with the metadata saying so. Pinned in Task 4.
3. **Monthly dates are first-of-month on FRED.** Ages must be measured from period end (Aug 2026 → 2026-08-31), so August data is "live" on Oct 22 and "stale" on Nov 20. Pinned in Task 1.
4. **An input missing from `score_anchors.json`.** The provider raises a clear `RuntimeError("no anchor for <key>")` at fetch time, never a `KeyError` at import. Pinned in Task 1.
5. **A category is excluded from the composite.** `index_summary`, `/api/v1/latest`, `/api/v1/newsletter-data`, the newsletter and the CSV export must not crash on a missing current score. They use the snapshot's `composite`. Pinned in Tasks 13 and 16.

---

### Task 1: Anchored mapping, input readings, freshness config

**Files:**
- Create: `scoring/anchors.py`, `data/providers/readings.py`, `data/score_anchors.json` (placeholder, see below)
- Modify: `config.py` (append a "Score rebuild (methodology v2)" section)
- Test: `tests/anchors_test.py`, `tests/readings_test.py`

**Interfaces:**
- Produces, in `scoring/anchors.py`:
  - `transform_value(raw: float, transform: str, cpi_ratio: float | None = None) -> float`. `transform` is one of `"identity"`, `"log"`, or `"log_real"`. For `log_real` it returns `log(raw * cpi_ratio)`, where `cpi_ratio = CPI_ref / CPI_t`.
  - `anchored_score(x: float, anchor: dict) -> float`. `anchor` has `direction` (`"lower_better"` or `"higher_better"`) and `best`, `normal`, `worst` (in transformed units). It maps piecewise-linearly best→100, normal→80, worst→0 and clips to [0, 100]. It raises `ValueError` if the anchors aren't monotone in the stated direction.
  - `score_raw(raw: float, anchor: dict, cpi_ratio: float | None = None) -> float`, which is `anchored_score(transform_value(raw, anchor["transform"], cpi_ratio), anchor)`.
  - `get_anchor(key: str) -> dict`, which reads `config.SCORE_ANCHORS["inputs"][key]` and raises `RuntimeError(f"no anchor for {key}")` if it's absent.
- Produces, in `data/providers/readings.py`:
  - `@dataclass InputReading`, with fields `name: str`, `score: float | None`, `as_of: date | None`, `source: str`, `raw_value: str = ""`, and `status: str = "live"`.
  - `period_end(obs: date, freq: str) -> date`. `freq` is `"D"`, `"W"` or `"M"`. `"M"` returns the last day of the month. `"D"` and `"W"` return the date unchanged.
  - `freshness_status(as_of: date | None, today: date, key: str) -> str`. It returns `"live"`, `"stale"` or `"missing"`, using `config.FRESHNESS[key] = (stale_after_days, drop_after_days)`.
  - `blend_inputs(readings: list[InputReading], weights: dict[str, float]) -> tuple[float | None, str]`. It drops readings with status `"missing"` or score None and renormalizes the rest. Status is `"stale"` if any used reading is stale and `"missing"` if none remain. The score is rounded to 1 decimal.
  - `inputs_metadata(readings) -> list[dict]`, with keys `name`, `score`, `as_of` (ISO string or None), `status`, `source`, `raw_value`.
  - `oldest_as_of(readings) -> date | None`, over used (non-missing) readings.
- Produces, in `config.py`:
  - `METHODOLOGY_VERSION = 2`
  - `SCORE_ANCHORS: dict`, loaded from `data/score_anchors.json`; `{}` if the file is missing
  - `FRESHNESS: dict[str, tuple[int, int]]`
  - `PUBLICATION_LAG_DAYS: dict[str, int]`
  - `CATEGORY_DROP_AFTER_DAYS: dict[str, int]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/anchors_test.py
import math, pytest
from scoring.anchors import anchored_score, transform_value, score_raw, get_anchor

LB = {"transform": "identity", "direction": "lower_better", "best": 0, "normal": 10, "worst": 110}
HB = {"transform": "identity", "direction": "higher_better", "best": 10, "normal": 5, "worst": -5}

@pytest.mark.parametrize("x,expected", [(0, 100), (-5, 100), (5, 90), (10, 80), (60, 40), (110, 0), (200, 0)])
def test_lower_better_piecewise(x, expected):
    assert anchored_score(x, LB) == pytest.approx(expected)

@pytest.mark.parametrize("x,expected", [(10, 100), (7.5, 90), (5, 80), (0, 40), (-5, 0)])
def test_higher_better_piecewise(x, expected):
    assert anchored_score(x, HB) == pytest.approx(expected)

def test_log_transform_midpoint():
    a = {"transform": "log", "direction": "lower_better",
         "best": math.log(50), "normal": math.log(100), "worst": math.log(1000)}
    assert score_raw(100, a) == pytest.approx(80)
    assert score_raw(math.sqrt(100 * 1000), a) == pytest.approx(40)

def test_log_real_uses_cpi_ratio():
    assert transform_value(50, "log_real", cpi_ratio=2.0) == pytest.approx(math.log(100))

def test_non_monotone_anchor_raises():
    with pytest.raises(ValueError):
        anchored_score(1, {"direction": "lower_better", "best": 10, "normal": 5, "worst": 20})

def test_missing_anchor_raises_runtime_error(monkeypatch):
    import config
    monkeypatch.setattr(config, "SCORE_ANCHORS", {"inputs": {}})
    with pytest.raises(RuntimeError, match="no anchor for gscpi"):
        get_anchor("gscpi")
```

```python
# tests/readings_test.py
from datetime import date
from data.providers.readings import InputReading, period_end, freshness_status, blend_inputs

def test_period_end_monthly_is_last_day():
    assert period_end(date(2026, 8, 1), "M") == date(2026, 8, 31)

def test_monthly_freshness_counts_from_period_end(monkeypatch):
    import config
    monkeypatch.setitem(config.FRESHNESS, "gscpi", (75, 150))
    as_of = period_end(date(2026, 8, 1), "M")
    assert freshness_status(as_of, date(2026, 10, 22), "gscpi") == "live"
    assert freshness_status(as_of, date(2026, 11, 20), "gscpi") == "stale"
    assert freshness_status(as_of, date(2027, 2, 1), "gscpi") == "missing"
    assert freshness_status(None, date(2026, 10, 22), "gscpi") == "missing"

def test_blend_renormalizes_and_propagates_stale():
    w = {"a": 0.6, "b": 0.4}
    a = InputReading("a", 50.0, date(2026, 10, 1), "x")
    assert blend_inputs([a, InputReading("b", None, None, "y", status="missing")], w) == (50.0, "live")
    b = InputReading("b", 100.0, date(2026, 9, 1), "y", status="stale")
    assert blend_inputs([a, b], w) == (70.0, "stale")
    assert blend_inputs([InputReading("a", None, None, "x", status="missing")], w) == (None, "missing")
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run: `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/anchors_test.py tests/readings_test.py -v`. Expected: ImportError.

- [ ] **Step 3: Implement the two modules and the config section.** Write `data/score_anchors.json` as `{"method_version": 2, "generated": null, "inputs": {}}` (Task 12 fills it). Config values:
  - `FRESHNESS`:
    - `gscpi` (75, 150)
    - `chokepoint_flow` (14, 42)
    - `brent`, `ulsd`, `ttf`, `copper`, `aluminum`: (10, 30) each
    - `ttf_monthly`, `copper_monthly`, `aluminum_monthly`: (75, 150) each
    - `tariff_burden` (60, 150)
    - `tpu` (14, 42)
    - `gpr` (14, 42)
    - `geo_register` (3, 9)
    - `tsifrght` (120, 200)
    - `rail_volume` (14, 45)
    - `prices_paid` (60, 150)
    - `hazards` (3, 9)
    - `gatun` (3, 9)
    - `mississippi` (3, 9)
  - `PUBLICATION_LAG_DAYS`: `gscpi` 5, `tsifrght` 80, `prices_paid` 0, `imf_monthly` 35, `dts` 1, `bopgimp` 35, `gpr` 7, `tpu` 7, `rail_volume` 5, `chokepoint_flow` 4
  - `CATEGORY_DROP_AFTER_DAYS`: `supply_chain` 150, `chokepoints` 42, `energy` 30, `tariffs` 150, `geopolitical` 42, `freight` 200, `inputs` 150, `physical` 9

- [ ] **Step 4: Run the tests and confirm they pass.** Same command. Expected: all PASS.

- [ ] **Step 5: Commit.** `git add scoring/anchors.py data/providers/readings.py data/score_anchors.json config.py tests/anchors_test.py tests/readings_test.py && git commit -m "Anchored 0-100 mapping, input readings and freshness config."`

---

### Task 2: Source fetchers, part 1 (FRED full history, Yahoo helpers, GSCPI)

**Files:**
- Create: `data/sources/__init__.py`, `data/sources/markets.py`
- Modify: `data/providers/fred_client.py` (add `fetch_fred_full`), `data/gscpi_client.py` (expose `fetch_gscpi_full`, if not already equivalent)
- Test: `tests/sources_markets_test.py`

**Interfaces:**
- Produces: `fetch_fred_full(series_id: str, cache_ttl: int = 86400) -> pd.Series`. It reads the full history from `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>` (no key), drops ".", and returns a float series sorted by date. Used by the anchors script and the long-history providers. Cache key `fred_full_<ID>_v1`.
- Produces: `markets.last_quote(symbol: str) -> tuple[date, float]` (the latest daily close, yfinance `history(period="10d")`).
- Produces: `markets.close_on(symbol: str, day: date) -> float | None` (the close on or before `day`, within 5 days).
- Produces: `markets.scale_live(official_value: float, official_date: date, symbol: str, unit_factor: float = 1.0) -> tuple[float, date, str]`. It returns `(value, as_of, mode)`, where `mode` is `"live"` or `"official"`. The live value is `official_value * (last_quote * unit_factor) / (close_on(official_date) * unit_factor)`. The live value is used only when the last quote's date is ≥ `official_date`, both quotes exist, and the ratio is within [0.5, 2.0]. Otherwise it returns `(official_value, official_date, "official")`. It catches every exception from yfinance and treats it as "official".

- [ ] **Step 1: Write the failing tests.** In `tests/sources_markets_test.py`, mock `markets.last_quote` and `markets.close_on`:
  - `test_scale_live_applies_ratio`: official 100.0 on 2026-10-20, close_on → 90.0, last_quote → (2026-10-22, 99.0). Result `(110.0, date(2026,10,22), "live")`.
  - `test_scale_live_rejects_stale_quote`: last_quote dated 2026-10-19. Result is `"official"`.
  - `test_scale_live_rejects_wild_ratio`: close 10.0, last 30.0. Result is `"official"`.
  - `test_scale_live_survives_yfinance_error`: last_quote raises. Result is `"official"`.
  - `test_fetch_fred_full_parses_dots`: mock requests with CSV text `"observation_date,X\n2020-01-01,1.5\n2020-02-01,.\n"`. The result has 1 value.
- [ ] **Step 2: Run the tests and confirm they fail.** Run: `... -m pytest tests/sources_markets_test.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `fetch_fred_full` and `data/sources/markets.py`.
- [ ] **Step 4: Run the tests and confirm they pass.** Expected: PASS.
- [ ] **Step 5: Commit.** "Full-history FRED fetch and guarded Yahoo live scaling."

---

### Task 3: Chokepoints category

**Files:**
- Modify: `data/portwatch.py` (add the history query and pure scoring; keep `fetch_chokepoint_traffic` for the panel)
- Create: `data/providers/chokepoints.py`
- Test: `tests/chokepoints_test.py`

**Interfaces:**
- Consumes: `get_anchor` is NOT used here. Chokepoints read `config.SCORE_ANCHORS["chokepoint_weights"]` (corridor → weight) and `config.SCORE_ANCHORS["chokepoint_baseline"]` (corridor → {month "1"–"12": mean daily transits}). If either is missing, the provider raises `RuntimeError("no anchor for chokepoint_flow")`.
- Produces: `portwatch.CORRIDORS = ["Malacca", "Taiwan", "Gibraltar", "Hormuz", "Dover", "RedSea", "Bosporus", "Panama"]`. Also `portwatch.PORTIDS`, mapping the short names Hormuz, BabM, Suez, Panama, Malacca, Taiwan, Gibraltar, Dover, Bosporus and Cape to their PortWatch portids. Look up the Dover and Bosporus ids from `PortWatch_chokepoints_database` (see `docs/.../artifacts/scripts/pw_fetch.py`).
- Produces: `portwatch.fetch_chokepoint_daily(start: date) -> pd.DataFrame`. It returns columns date, portid, n_total and capacity, paging the ArcGIS `Daily_Chokepoints_Data` layer 1,000 rows at a time. Cache key `portwatch_daily_v1`, TTL 6 h.
- Produces: `portwatch.corridor_ratios(daily: pd.DataFrame, baseline: dict) -> pd.DataFrame`. Index is date; columns are `CORRIDORS` plus `BabM`, `Suez` and `Cape`. Each ratio is the 7-day mean of n_total ÷ the baseline for the same calendar month. `RedSea` = min(BabM, Suez).
- Produces: `portwatch.chokepoint_score(ratios_row: pd.Series, weights: dict) -> float`. It computes s = clip(ratio / 0.90, 0, 1) and score = clip(100 − 300 × Σ w·(1 − s), 0, 100). Any corridor NaN → NaN.
- Produces: `ChokepointsProvider(BaseProvider)` with `category = "chokepoints"`.
  - `fetch_current` computes the score on the latest date. Metadata `raw_value` looks like "Hormuz 4% · Red Sea 35% · …" (the three worst corridors). `as_of` = the latest PortWatch date. `inputs` = one reading, `chokepoint_flow`. The description includes the Cape of Good Hope ratio as context and the credit line.
  - `fetch_history(days)` returns daily scores, each dated latest data date + `PUBLICATION_LAG_DAYS["chokepoint_flow"]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_score_all_normal_is_100`: every ratio = 1.0. Score 100.0.
  - `test_score_deadband`: every ratio = 0.9. Score 100.0.
  - `test_score_hormuz_closed`: weights from `docs/.../artifacts/outputs/out_weights.csv` (`ton` column). Hormuz ratio 0.04, the rest 1.0. Expected `100 - 300*0.13038920936378975*(1 - 0.04/0.9)` = 62.6 (approx, ±0.1).
  - `test_red_sea_takes_worse_of_bab_and_suez`: build a tiny daily frame with BabM at 50% and Suez at 80%. `corridor_ratios(...)["RedSea"]` ≈ 0.5.
  - `test_empty_feature_list_raises`: mock `_query` to return []. `ChokepointsProvider().fetch_current()` raises `RuntimeError`.
  - `test_research_backtest_today`: feed the ratios row for 2026-10-18 from `docs/.../artifacts/outputs/out_recommended_daily.csv` (copy that one row into the test as a dict). The result is ≈ 36.1 (±0.5).
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.** Keep the `ratio_*` columns in the CSV fixture as plain floats in the test file; don't commit the CSV to tests.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Chokepoints category from IMF PortWatch transits."

---

### Task 4: Energy category rewrite

**Files:**
- Modify (rewrite): `data/providers/energy.py`
- Test: `tests/energy_test.py`

**Interfaces:**
- Consumes: `fetch_fred_series` / `fetch_fred_full`, `markets.scale_live`, `get_anchor`, `score_raw` and the `readings` helpers.
- Produces: `ENERGY_LEG_WEIGHTS = {"brent": 0.35, "ulsd": 0.40, "ttf": 0.25}` and `ENERGY_SPIKE = {"start": 0.20, "full": 0.82, "max_points": 15.0}` (put both in `config.py`).
- Produces: `spike_penalty(change_3m: float) -> float`. Input is the real 91-day change as a fraction. It returns 0 at ≤ 0.20 and 15 at ≥ 0.82, linear in between.
- Produces: `EnergyProvider` with `category = "energy"`. The legs:
  - Brent: FRED `DCOILBRENTEU`, live `BZ=F`.
  - ULSD: FRED `DDFUELNYH`, live `HO=F`. Keep it in $/gal everywhere: anchors, live value and display.
  - TTF: FRED `PNGASEUUSDM` (monthly), live `TTF=F` converted from EUR/MWh to $/MMBtu with `EURUSD=X` ÷ 3.412. If live fails, the leg uses the monthly value under the freshness key `ttf_monthly`.
  - CPI ratio = `SCORE_ANCHORS["cpi_reference"]["value"]` ÷ the latest `CPIAUCSL`.
  - Leg score = `score_raw(price, get_anchor(leg), cpi_ratio)` − the weighted spike penalty. The penalty is computed per leg from the real price 91 days earlier and subtracted after the weighted blend: `score = blend − Σ w_leg·spike_penalty(change_leg)`, clipped 0–100.
  - The metadata hover lists WTI, the Brent–WTI spread and the ULSD crack as context lines.
  - `fetch_history(days)` recomputes daily from the FRED histories (ffill weekly/monthly to daily, dated by publication lag: FRED daily = same day; IMF monthly = `imf_monthly`).

- [ ] **Step 1: Write the failing tests.**
  - `test_spike_penalty_bounds`: 0.10 → 0, 0.20 → 0, 0.51 → 7.5, 0.82 → 15, 1.5 → 15.
  - `test_energy_uses_official_when_yahoo_stale`: mock `scale_live` to return `"official"`. Metadata `inputs[0]["source"]` contains "official", and the score is computed from the FRED value.
  - `test_energy_ttf_falls_back_to_monthly`: mock live TTF to fail. The ttf reading's name is `ttf_monthly`.
  - `test_energy_all_legs_missing_raises`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.** Delete the old WTI/GASDESW scoring. Keep `CL=F` out of the score.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Energy: Brent, ULSD and TTF on anchored real prices with a spike penalty."

---

### Task 5: Tariffs category rewrite

**Files:**
- Create: `data/sources/treasury.py`, `data/sources/tpu.py`
- Modify (rewrite): `data/providers/tariffs.py`
- Delete: `data/providers/tariff_news_nowcast.py`
- Modify: `requirements.txt` (add `openpyxl==3.1.5`; install it in the venv)
- Test: `tests/tariffs_test.py`

**Interfaces:**
- Produces: `treasury.monthly_customs_from_rows(rows: list[dict]) -> pd.Series`. It sums `transaction_today_amt` ($M) by month for `transaction_type == "Deposits"` and `transaction_catg` in the three names listed in `docs/.../artifacts/scripts/fetch_dts.py`.
- Produces: `treasury.fetch_customs_monthly() -> pd.Series`. Endpoint `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/deposits_withdrawals_operating_cash`, paged. Cache key `dts_customs_v1`, 12 h.
- Produces: `tariff_burden_series(customs_m: pd.Series, imports_m: pd.Series) -> pd.Series`, equal to 100 × (trailing 3-month customs sum) ÷ (trailing 3-month BOPGIMP sum), in %. Check the BOPGIMP units in FRED (millions of $) and make them match.
- Produces: `tpu.parse_tpu_xlsx(path_or_bytes) -> tuple[pd.Series, pd.Series]` (daily `TPUD_index` from sheet `TPU_DAILY`, monthly `TPU` from sheet `TPU_MONTHLY`). It raises `ValueError` if a sheet or column is missing.
- Produces: `tpu.fetch_tpu() -> tuple[pd.Series, pd.Series]`, from `https://www.matteoiacoviello.com/tpu_files/tpu_web_latest.xlsx`. Verify the URL. If it has moved, find the current link on `https://www.matteoiacoviello.com/tpu.htm`. Cache 12 h.
- Produces: `TARIFF_WEIGHTS = {"tariff_burden": 0.6, "tpu": 0.4}` in config.
- Produces: `TariffsProvider` with `category = "tariffs"`.
  - Burden reading: dated period end + max(`dts`, `bopgimp`) lag.
  - TPU reading: the 30-day mean of the daily index, log anchor.
  - Score via `blend_inputs`.
  - The hover shows the latest EPUTRADE value as context and says deposits are gross of IEEPA refunds.

- [ ] **Step 1: Write the failing tests.**
  - `test_monthly_customs_sums_deposits_only`, using rows shaped like `docs/.../artifacts/samples/dts_customs_head.csv`.
  - `test_tariff_burden_ratio`: customs [10, 10, 10] and imports [1000, 1000, 1000] → 1.0.
  - `test_tpu_missing_sheet_raises`: an xlsx built in-memory with openpyxl that has only `TPU_MONTHLY`.
  - `test_tariffs_blend_weights`: burden score 40 and TPU score 70 → 52.0.
  - `test_nowcast_module_removed`: `importlib.util.find_spec("data.providers.tariff_news_nowcast") is None`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Tariffs: customs burden and daily trade policy uncertainty; drop the VADER nowcast."

---

### Task 6: Geopolitical category (GPR) and register weight hook

**Files:**
- Create: `data/sources/gpr.py`
- Modify: `data/providers/geopolitical.py`. Replace only the `GeopoliticalProvider` class. The news helpers and `blend_port_disruption` stay until Tasks 13 and 14 remove them, so the aggregator keeps importing.
- Modify: `data/database.py` (add `get_last_category_score`)
- Modify: `config.py` (add `GEO_REGISTER_WEIGHT = 0.0`)
- Test: `tests/geopolitical_test.py`

**Interfaces:**
- Produces: `gpr.parse_gpr_daily(df: pd.DataFrame) -> pd.Series`, using columns `date` and `GPRD`. It raises `ValueError` if they're missing.
- Produces: `gpr.parse_gpr_monthly(df) -> pd.Series`, using columns `month` and `GPR`.
- Produces: `gpr.fetch_gpr_daily() -> pd.Series`, via `pd.read_stata` on `https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.dta`. Also `fetch_gpr_monthly()` via `.../gpr_files/data_gpr_export.dta`. Verify the URLs on `https://www.matteoiacoviello.com/gpr.htm`. Cache 12 h.
- Produces: `get_last_category_score(category: str) -> tuple[date, float] | None`, the newest row in `daily_category_scores` for the category, or None with no DB or no rows. Task 13 also uses it.
- Produces: `GeopoliticalProvider` with `category = "geopolitical"`.
  - GPR reading = the 30-day mean of GPRD, through `get_anchor("gpr")` (a log transform).
  - Register reading = the stored `geo_register` score from the DB, read with `get_last_category_score("geo_register")`, and used only when `GEO_REGISTER_WEIGHT > 0`.
  - Weights `{"gpr": 1 - GEO_REGISTER_WEIGHT, "geo_register": GEO_REGISTER_WEIGHT}`, combined with `blend_inputs`.
  - `fetch_history` returns daily GPR scores dated + `PUBLICATION_LAG_DAYS["gpr"]` (or the file's actual last date, whichever is later).

- [ ] **Step 1: Write the failing tests.**
  - `test_gpr_reshaped_file_raises`: a DataFrame without `GPRD` → `ValueError`.
  - `test_geo_ignores_register_at_zero_weight`: `GEO_REGISTER_WEIGHT=0`, GPR score 60 → 60.0 with only one input in the metadata.
  - `test_geo_blends_register_when_enabled`: weight 0.5, GPR 60, register 40 → 50.0.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Geopolitical: Caldara-Iacoviello GPR replaces headline tone."

---

### Task 7: Claude disruption register (shadow)

**Files:**
- Create: `data/register.py`
- Modify: `data/database.py` (the `disruption_events` table and its functions), `data/aggregator.py` (submit the register job; record the `geo_register` score)
- Test: `tests/register_test.py`

**Interfaces:**
- Produces, DB:
  - `disruption_events(id TEXT PRIMARY KEY, title TEXT, region TEXT, corridors TEXT, severity REAL, trade_share_pct REAL, trade_share_basis TEXT, opened DATE, updated DATE, closed DATE NULL, evidence TEXT, rationale TEXT)`. Lists are stored as JSON text.
  - `load_open_disruption_events() -> list[dict]`
  - `upsert_disruption_events(events: list[dict]) -> None`
- Produces: `register.register_score(events: list[dict]) -> float`, equal to `100 - min(100, 0.3 * Σ severity × trade_share_pct)` over events with `closed` None. Severity is clamped to 0–10 and share to 0–100.
- Produces: `register.update_register(open_events: list[dict], articles: list[dict]) -> list[dict]`. One `llm.research_json` call with web search. A JSON schema lists events with the fields above plus `action` ∈ {open, update, close, keep}. The result is clamped and validated, and an id may only be closed if it was open. On failure or no key it returns `open_events` unchanged.
- Produces: `register.run_register_cycle() -> float | None`. Runs at most once per `AI_CACHE_TTL_SECONDS` (cache key `disruption_register_v1`) and caches failures for `AI_FAILURE_RETRY_SECONDS`. It loads, updates, upserts and returns the score.
- The aggregator puts the returned score in the measured scores under `geo_register`. It is not in any weights.

- [ ] **Step 1: Write the failing tests.**
  - `test_register_score_formula`: events [{severity 10, share 13}, {severity 8, share 10}] → 100 − min(100, 0.3×(130+80)) = 37.0.
  - `test_closed_events_ignored`.
  - `test_update_register_keeps_events_on_llm_error`: patch `llm.research_json` to raise. The result equals the input.
  - `test_cannot_close_unknown_id`: the model returns close for id "x", which wasn't open. It's ignored.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.** Put the prompt in `data/register.py` as a module constant, and wrap the articles as untrusted data the same way `data/ai_analyst.py` does.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Claude disruption register in shadow mode."

---

### Task 8: Freight category rewrite

**Files:**
- Create: `data/sources/rail.py`
- Modify (rewrite): `data/providers/freight.py`
- Delete: `data/providers/transport_equity_proxy.py`
- Test: `tests/freight_test.py`

**Interfaces:**
- Produces: `rail.fetch_rail_weekly() -> pd.Series`, the weekly originated carloads plus intermodal units (total) from USDA AgTransport Socrata dataset `tb7q-kn5i`. Use `$where type='Originated'`, grouped by date. Confirm the commodity value that represents intermodal units; see `docs/.../artifacts/scripts/ams_fetch.py`. Cache 12 h.
- Produces: `rail_yoy(weekly: pd.Series) -> pd.Series`, the 4-week mean ÷ the 4-week mean 52 weeks earlier − 1, in %.
- Produces: `FREIGHT_WEIGHTS = {"tsifrght": 0.5, "rail_volume": 0.5}` in config.
- Produces: `FreightProvider` with `category = "freight"` and label "Freight Volume".
  - The TSIFRGHT YoY reading uses `get_anchor("tsifrght")` (higher better) and is dated + 80 days.
  - The rail reading uses `get_anchor("rail_volume")`.
  - The description says it measures goods moving (demand); a contraction is bad.
  - IYT is not used anywhere in scoring.

- [ ] **Step 1: Write the failing tests.**
  - `test_rail_yoy`: 60 weeks of constant 100, then 4 weeks of 110 → last YoY = 10.0.
  - `test_freight_uses_rail_when_tsifrght_too_old`: TSIFRGHT as_of 250 days ago → missing, so the score equals the rail score and status is "live".
  - `test_rail_empty_payload_raises`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Freight: TSIFRGHT and weekly STB rail volume; drop IYT."

---

### Task 9: Input costs category (new)

**Files:**
- Create: `data/sources/fed_surveys.py`, `data/providers/inputs.py`
- Test: `tests/inputs_test.py`

**Interfaces:**
- Produces: `fed_surveys.fetch_prices_paid() -> dict[str, pd.Series]` (monthly, keys `philly`, `empire`, `dallas`, `kc`):
  - Philly: FRED `PPCDFSA066MSFRBPHI`
  - Empire: FRED `PPCDISA066MSFRBNY`
  - Dallas: the TMOS raw-materials prices index, from FRED if a series exists, otherwise the Dallas Fed download
  - KC: the KC Fed manufacturing survey xlsx
  Verify each source. A failed survey is omitted, not raised.
- Produces: `prices_paid_composite(surveys: dict[str, pd.Series], stats: dict[str, tuple[float, float]]) -> pd.Series`. It z-scores each survey against its 2004–2019 (mean, sd), taken from `SCORE_ANCHORS["prices_paid_stats"]`, then averages the available z values per month.
- Produces: `INPUT_WEIGHTS = {"prices_paid": 0.5, "copper": 0.25, "aluminum": 0.25}` in config.
- Produces: `InputsProvider` with `category = "inputs"` and label "Input Costs".
  - Copper: `PCOPPUSDM` monthly, live `HG=F` × 2204.62 → $/mt via `scale_live`. The freshness key is `copper_monthly` when not live.
  - Aluminum: `PALUMUSDM`, live `ALI=F` (check the unit against IMF $/mt).
  - Both are log_real, anchored.
  - The hover adds supplier delivery times (`DTCDFSA066MSFRBPHI`, `DTCDISA066MSFRBNY`) as context only.

- [ ] **Step 1: Write the failing tests.**
  - `test_prices_paid_composite_averages_available`: two surveys, z-values 1.0 and 3.0 → 2.0. One survey missing that month → that survey's z alone.
  - `test_inputs_blend`: prices paid 20, copper 40, aluminum 60 → 35.0.
  - `test_failed_survey_is_omitted_not_raised`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Input Costs category: Fed prices paid, copper, aluminum."

---

### Task 10: Physical disruption category (replaces weather in the composite)

**Files:**
- Create: `data/sources/gdacs.py`, `data/sources/waterways.py`, `data/providers/physical.py`
- Modify: `data/database.py` (the `gauge_readings` table), `data/providers/weather.py` (precipitation unit and gust fixes; still used for the map)
- Test: `tests/physical_test.py`, plus update `tests/test_weather_scoring.py`

**Interfaces:**
- Produces: `gdacs.fetch_events(start: date, end: date) -> list[dict]`, from `https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH` with `alertlevel=Orange;Red` and `eventlist=TC;FL;EQ;VO`. Verify the parameters against `docs/.../artifacts/samples/gdacs.json`. Each item has `type`, `alert` (Orange/Red), `lat`, `lon`, `name`, `from`, `to`. Query in chunks of 6 months or less.
- Produces: `gdacs.hazard_score(events, ports: list[dict], shares: dict[str, float], radius_km: dict[str, float]) -> float`. An event affects a port within `radius_km[type]` of the event centre. Penalty = Σ over affected ports of `share × level_points`. Clip to 0–100.
  - Penalty = `HAZARD_SCALE × Σ share × HAZARD_LEVEL_POINTS[alert]`, with `HAZARD_LEVEL_POINTS = {"Orange": 0.5, "Red": 1.0}` and `HAZARD_SCALE = 1000.0`, so one Red typhoon over a port with share 0.05 costs 50 points.
  - Check that calibration against the real `port_throughput_share` values once Task 12 has generated them, and adjust `HAZARD_SCALE` so a Red event over a top-10 port reads ≈ 50. Record this in a config comment.
  - `config.HAZARD_RADIUS_KM`: TC 300, FL 100, EQ 150, VO 50 (my defaults; cite or adjust in the comment).
- Produces: `waterways.fetch_gatun() -> pd.Series` (daily ft, ACP CSV with columns `DATE_LOG,GATUN_LAKE_LEVEL(FEET)`; find the CSV URL on pancanal.com, sample in artifacts). Also `fetch_mississippi_stl() -> pd.Series` (USGS daily values for site 07010000, the St. Louis gauge height; sample in artifacts) and `fetch_kaub_latest() -> tuple[date, float]` (PEGELONLINE KAUB W, cm).
- Produces: `gatun_score(level_ft: float, record_low: float) -> float`: 100 at ≥ 85.0 ft, 0 at `record_low`, linear in between. Also `river_score(stage: float, threshold: float, record_low: float) -> float`, the same shape. Put the thresholds in config with a cited source comment.
- Produces: `PHYSICAL_WEIGHTS = {"hazards": 0.5, "gatun": 0.25, "mississippi": 0.25}` in config.
- Produces: `PhysicalProvider` with `category = "physical"` and label "Physical Disruption". It upserts the Kaub reading into `gauge_readings(date, gauge, value)` each cycle (not scored).
- Weather fixes: `_precip_deduction` takes daily mm. Request `daily=precipitation_sum` (or the hourly sum) from Open-Meteo instead of the 15-minute `current` value. Wind uses `wind_gusts_10m`.

- [ ] **Step 1: Write the failing tests.**
  - `test_hazard_red_typhoon_over_big_port`: one Red TC at a port's coordinates with share 0.05 → ≈ 50 (±2).
  - `test_hazard_far_event_ignored`: event 2,000 km away → 100.
  - `test_gatun_score`: 86 → 100; record_low 78, level 81.5 → 50.0.
  - `test_physical_missing_gauges_uses_hazards_only`.
  - `test_weather_precip_uses_daily_total` in `tests/test_weather_scoring.py`: 30 mm daily → deduction 15.0, matching the existing ramp of 25 × 30/50.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Physical Disruption category: GDACS hazards and waterways; weather fixes for the map."

---

### Task 11: Supply chain on anchored GSCPI

**Files:**
- Modify (rewrite): `data/providers/supply_chain.py`
- Delete: `data/providers/freight_rate_proxy.py`, moving the BDRY fetch into the supply chain hover context only, via `markets.last_quote("BDRY")`
- Test: `tests/supply_chain_test.py`

**Interfaces:**
- Produces: `SupplyChainProvider` with `category = "supply_chain"`.
  - Score = `score_raw(gscpi, get_anchor("gscpi"))`.
  - The reading is dated period end + 5 days, freshness key `gscpi`.
  - The hover shows GSCPI, WEI (context) and BDRY (context, "not scored").
  - `fetch_history` returns GSCPI scores, each month's value starting on its publication date and ffilled.
  - Remove `gscpi_to_score` from `data/gscpi_client.py` if nothing else uses it.

- [ ] **Step 1: Write the failing tests.**
  - `test_supply_chain_anchor`: an anchor with best −1.0, normal −0.36, worst 4.43 (lower_better). GSCPI −0.36 → 80.0; 4.43 → 0.0.
  - `test_supply_chain_stale_flag`: GSCPI as_of 100 days ago → `is_stale` True.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Supply chain: anchored GSCPI; BDRY becomes context."

---

### Task 12: Anchors script and generated anchors

**Files:**
- Create: `scripts/compute_anchors.py`
- Modify: `data/score_anchors.json` (generated)
- Test: `tests/compute_anchors_test.py`

**Interfaces:**
- Consumes: every source fetcher above, plus `fetch_fred_full`.
- Produces: `compute_input_anchor(series: pd.Series, transform: str, direction: str, baseline: tuple[str, str], worst_through: str = "2025-12-31", cpi: pd.Series | None = None, worst_override: float | None = None, worst_basis: str = "") -> dict`.
  - It transforms the series (deflating with CPI for `log_real`, CPI_ref = the 2025-12 CPIAUCSL value), then resamples to monthly mean.
  - best = the 5th or 95th percentile of the baseline (the healthy tail for the direction), normal = the baseline median, worst = the worst monthly mean through `worst_through`, unless `worst_override` is given.
  - It returns `{transform, direction, best, normal, worst, baseline, worst_basis, generated}`.
- Writes `data/score_anchors.json` with:
  - `method_version: 2`
  - `generated` date
  - `cpi_reference {series, date, value}`
  - `inputs` (one entry per anchored input):
    - `gscpi`: identity, lower_better, 1998–2019
    - `brent`, `ulsd`, `ttf` (and `ttf_monthly` = the same anchor), `copper`, `aluminum` (and their `_monthly` aliases): log_real, lower_better, 1990–2019 (ttf: the monthly IMF series)
    - `tariff_burden`: identity, lower_better, 2005–2017, `worst_override` = a cited historical US average duty rate. Put the citation in `worst_basis`.
    - `tpu`: log, lower_better. Baseline = the monthly TPU 1985–2019; worst = the max 30-day mean of the daily series. Record the scale check in `worst_basis`.
    - `gpr`: log, lower_better. Monthly 1985–2019; worst = the record monthly value.
    - `tsifrght`: identity on YoY %, higher_better, 2001–2019
    - `rail_volume`: identity on YoY %, higher_better, the full pre-2020 history the dataset has (document the years)
    - `prices_paid`: identity on composite z, lower_better, 2004–2019
  - `prices_paid_stats {survey: [mean, sd]}`
  - `chokepoint_weights`: the tonnage shares over 2022-01-01..2023-10-31, RedSea = the mean of BabM and Suez capacity
  - `chokepoint_baseline`: corridor → month → mean daily n_total over 2022-01-01..2023-10-31
  - `port_throughput_share`: the 37 ports in `data/ports_data.py` → each one's share of total PortWatch port calls over 2022–2023 (`Daily_Ports_Data`; see `pw_ports.py`)
  - Gatun and Mississippi `record_low`
- The script prints a table: each input's anchors and today's score.

- [ ] **Step 1: Write the failing tests.**
  - `test_compute_input_anchor_lower_better`: a monthly series 1..100 over a 2000–2019 baseline. Normal = median and best = the 5th percentile; worst = the max value through 2025.
  - `test_compute_input_anchor_higher_better_flips_tails`.
  - `test_worst_override_used`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Generate the anchors.** Run: `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/compute_anchors.py`. Expected: the JSON is written and today's printed scores are near the research figures: supply chain ≈ 50, chokepoints ≈ 36, energy 20–35, tariffs ≈ 30–55, freight ≈ 55–60, inputs ≈ 30. Investigate any category more than 15 points off before continuing.
- [ ] **Step 6: Commit.** "Generate frozen score anchors (methodology v2)."

---

### Task 13: Weights, profiles, aggregator wiring, fallback and exclusion

**Files:**
- Modify: `config.py`:
  - `CATEGORY_WEIGHTS`, the `INDUSTRY_PROFILES` weights and the baseline `card_categories`
  - `CATEGORY_LABELS` and `CATEGORY_COLORS` for `chokepoints` "Chokepoints", `inputs` "Input Costs", `physical` "Physical Disruption" and `freight` "Freight Volume"
  - remove `DEFAULT_FALLBACK_SCORES`, the old proxy weights, `GSCPI_SCORE_SCALE`, the `FREIGHT_YOY_*` constants and `PORT_DISRUPTION_WEIGHT`
- Modify: `scoring/engine.py` (add `renormalized_weights`), `data/database.py` (`get_last_category_score`; `record_daily_scores` accepts `composite: float | None`), `data/aggregator.py`
- Test: `tests/aggregator_v2_test.py`, plus updates to `tests/industry_profiles_test.py` and `tests/score_integrity_test.py`

**Interfaces:**
- Produces: `CATEGORY_WEIGHTS = {"supply_chain": .20, "chokepoints": .15, "energy": .15, "tariffs": .15, "geopolitical": .10, "freight": .10, "inputs": .10, "physical": .05}`. The semiconductor and aerospace profiles use these × 0.60 plus their unchanged industry weights.
- Produces: `renormalized_weights(weights: dict, present: set[str]) -> dict`.
- Consumes: `get_last_category_score` (Task 6).
- Aggregator behaviour:
  - `_PROVIDERS` = the 8 category providers plus `ChipFabUtilProvider` and `AeroMetalsProvider`. `WeatherProvider` is a separate module-level instance used only for the map.
  - On provider failure: if `get_last_category_score(cat)` is younger than `CATEGORY_DROP_AFTER_DAYS[cat]`, use it with `is_fallback=True` and `is_stale=True`. The metadata says "Last stored reading from <date>". It is not written to history. Otherwise the category is left out of `current_scores` and added to `excluded_categories`.
  - `composite = compute_composite_index(current_scores restricted to present, renormalized_weights(...))`. Store `result["composite"]` and `result["excluded_categories"]`. `degraded = bool(fallback_categories or excluded_categories)`. Add `stale_categories` (metadata `is_stale`).
  - Delete the geopolitical news override block, `blend_port_disruption` (in `geopolitical.py`, along with its tests in `tests/score_integrity_test.py`), `PORT_DISRUPTION_WEIGHT`, and the whole score-explanation block. Delete `generate_score_explanation` from `data/ai_analyst.py` and `scoring/explanation.py` if nothing else imports them (check `api/` and the tests).
  - `record_daily_scores(composite if not excluded_categories else None, measured_scores)`. Measured scores include `geo_register` when present. The DB snapshot is saved only when nothing is excluded and no weighted category is a fallback.
  - Disruptions use one 0–100 impact scale: category `100 - score`; news `abs(severity) * 10`.
  - Remove `_make_fallback_series` for failed providers; history stays NaN.

- [ ] **Step 1: Write the failing tests.**
  - `test_weights_sum_and_profiles`: every profile sums to 1.0 ± 1e-9. The semiconductor `supply_chain` weight is 0.12.
  - `test_renormalized_weights`: drop `physical` → the rest sum to 1.0 and `supply_chain` = 0.20/0.95.
  - `test_failed_provider_uses_recent_stored_score`: patch a provider to raise and `get_last_category_score` → (today − 2 d, 61.0). The current score is 61.0 and the category is in both `fallback_categories` and `stale_categories`.
  - `test_failed_provider_excluded_when_too_old`: stored score 400 days old → the category is in `excluded_categories`, the composite still computes, and `record_daily_scores` gets composite None.
  - `test_no_score_explanation_key`: the snapshot has no `score_explanation`.
  
  Mock every provider, the news job, the market job, the port summaries, the register and `record_daily_scores`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Run `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/ -q`. Expected: all pass; update the old tests that asserted removed behaviour.
- [ ] **Step 5: Commit.** "Aggregator v2: eight categories, explicit stale/fallback/exclusion, stored composite."

---

### Task 14: News alerts on Claude only

**Files:**
- Create: `data/news_alerts.py`. Move into it `fetch_supply_chain_news` and the helpers from `data/providers/geopolitical.py` that serve alerts, briefing and report. Update the imports in `data/aggregator.py`, `api/briefing.py`, `api/report.py` and the tests.
- Modify: `requirements.txt` (remove `vaderSentiment`), `config.py` (`NEWS_AI_REFRESH_SECONDS = 21600`; remove `NEWS_RSS_REFRESH_SECONDS`), `data/news_sources.py` if needed
- Test: `tests/news_alerts_test.py`, plus updates to the existing news tests

**Interfaces:**
- Produces: `fetch_supply_chain_news() -> tuple[list[dict], str, str]` (alerts, briefing, report). No score.
- Behaviour:
  - Every `NEWS_AI_REFRESH_SECONDS`, fetch RSS (plus web search on the daily full run). Send only articles whose normalized title isn't already in the cached alerts to `analyze_news_batch`, and merge them with the cached alerts. Keep the newest 60.
  - The full report and briefing regenerate on the existing `AI_CACHE_TTL_SECONDS`.
  - If Claude fails, keep the cached alerts and set `"stale": True` in the payload. The UI label reads "Claude (stale)".
  - With no key, alerts get `severity=None` and `severity_label="unscored"`.
  - Remove every VADER import, plus `_build_vader_alerts`, `_refresh_cached_news_from_rss` and `_risk_score_from_alerts` (and their tests).
- Produces: `classify_topic(text: str) -> str`, using word-boundary regexes built from `_CATEGORY_KEYWORDS` (`re.compile(r"\b(?:" + "|".join(map(re.escape, kws)) + r")\b")`). Bump `NEWS_BRIEFING_CACHE_KEY` to `newsapi_briefing_v19`.

- [ ] **Step 1: Write the failing tests.**
  - `test_topic_word_boundaries`: "Annual report shows record sales" isn't supply_chain; "Warehouse automation" isn't geopolitical; "Heavy-duty trucks" isn't tariffs; "Port of Oakland congestion" is supply_chain.
  - `test_incremental_scoring_only_sends_new_titles`: two cached alerts plus three RSS items, one already cached → `analyze_news_batch` gets two.
  - `test_claude_failure_keeps_cached_alerts_flagged_stale`.
  - `test_no_vader_dependency`: `importlib.util.find_spec("vaderSentiment") is None` OR there is no import in `data/` (grep in the test via `pathlib`).
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.** Uninstall `vaderSentiment` from the venv after the code no longer imports it.
- [ ] **Step 4: Run the tests and confirm they pass,** then run the full suite.
- [ ] **Step 5: Commit.** "News alerts scored by Claude only, incrementally; word-boundary topic tags; VADER removed."

---

### Task 15: Map fixes

**Files:**
- Modify: `data/aggregator.py` (`_derive_map_markers`; delete `_REGION_PROFILES`, the vulnerability penalty and the trucking fold), `data/ports_data.py`
- Test: `tests/map_markers_test.py`

**Interfaces:**
- `_derive_map_markers(composite: float, alerts, weather_provider, port_summaries) -> list[dict]` (takes the composite instead of `current_scores`).
  - Port score = `0.6*composite + 0.4*local_weather` (or the composite alone) − max(news_penalty, ai_penalty). The penalty caps don't change.
  - The hover drops "regional macro" and lists the composite, the weather and the penalties.
- `ports_data` keyword matching uses word boundaries. Fix the Casablanca mapping at `ports_data.py:93`. Delete the documented-but-missing regional half-penalty text at `ports_data.py:10`.

- [ ] **Step 1: Write the failing tests.**
  - `test_oman_does_not_match_woman`.
  - `test_casablanca_maps_to_casablanca` (or no port, if Casablanca isn't one of the 37).
  - `test_port_score_formula`: composite 50, weather 100, AI penalty 10 → 0.6·50 + 0.4·100 − 10 = 60.0.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "Map: drop region profiles and vulnerability double count; fix port keywords."

---

### Task 16: UI, API and health

**Files:**
- Modify:
  - `components/terminal_data.py`: today's index renormalizes over present categories when `excluded_categories` is non-empty; each row gets `is_stale`, `as_of` and `inputs`
  - `components/terminal.py`: a "stale" suffix like "fallback"; the hover lists each input with its as-of date and status; 8 rows fit
  - `components/workspace.py`: the CSV adds `as_of` and `status`
  - `api/routes.py`: `/api/v1/latest` and `/api/v1/newsletter-data` use `data["composite"]`; categories become objects
  - `app.py`: `/health` adds `stale_categories` and `excluded_categories`
  - `assets/terminal.css` (only if needed)
  - the chokepoint panel credit
- Test: `tests/terminal_data_test.py`, `tests/terminal_ui_test.py`, `tests/api_v2_test.py`

**Interfaces:**
- `/api/v1/latest` returns:
  - `methodology_version: 2`
  - `composite_index`, from `data["composite"]`; fall back to `compute_composite_index` only if that key is absent
  - `categories: {cat: {"score", "weight", "as_of", "source", "is_stale", "is_fallback", "inputs"}}`
  - `excluded_categories`, `stale_categories`, plus the existing keys
- `index_summary(data, profile)["today"]` is not None when a category is excluded.

- [ ] **Step 1: Write the failing tests.**
  - `test_index_today_renormalizes_when_excluded`.
  - `test_latest_api_category_objects_and_version`.
  - `test_latest_api_uses_stored_composite_when_category_missing` (the old code raised ValueError).
  - `test_table_shows_stale_suffix`.
  - `test_chokepoint_panel_has_credit`: the layout HTML contains "Sources: UN Global Platform; IMF PortWatch".
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass,** plus the full suite.
- [ ] **Step 5: Commit.** "UI/API/health: as-of dates, stale flags, stored composite, PortWatch credit."

---

### Task 17: Docs page, newsletter, report, CLAUDE.md

**Files:**
- Modify:
  - `api/docs.py`: rewrite the methodology for the 8 categories, covering sources, anchors (100/80/0), weights, lags, the shadow register and credits. Remove the "25 newest" and hover-explanation claims.
  - `scripts/send_newsletter.py`: use `data["composite"]` and the new labels
  - `api/report.py`: imports only
  - `CLAUDE.md`
- Test: update `tests/newsletter_digest_test.py` and `tests/security_newsletter_test.py`; add `tests/docs_page_test.py`

**Interfaces:** none new.
- Credits on `/docs`: NY Fed GSCPI; IMF PortWatch (verbatim credit line); FRED/EIA; ICE/Yahoo for live futures; U.S. Treasury DTS; Census via FRED; Caldara–Iacoviello GPR and TPU; BTS; STB via USDA AgTransport; the Philadelphia, New York, Dallas and Kansas City Feds; IMF commodity prices; GDACS; Panama Canal Authority; USGS.
- In `CLAUDE.md`, rewrite the sections Scoring System, Provider Contract, Provider-Specific Patterns, Caching TTLs, Aggregator, Snapshot Structure, API and AI, plus the "Things That Will Break" bullets, to match. Remove the stale Known Inconsistencies entries this work resolves.

- [ ] **Step 1: Write the failing tests.**
  - `test_docs_lists_eight_categories_and_credit`.
  - `test_docs_has_no_stale_claims` (no "25 newest" and no "hover over the index for an explanation").
  - The newsletter test uses a snapshot with `composite` and one excluded category, and doesn't crash.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass,** plus the full suite.
- [ ] **Step 5: Commit.** "Docs, newsletter and CLAUDE.md for methodology v2."

---

### Task 18: History rebuild and backtest scripts

**Files:**
- Create: `scripts/rebuild_category_history.py`, `scripts/backtest_composite.py`
- Modify: `data/database.py` (`upsert_scores_for_dates(rows: list[tuple[date, str, float]])`, `upsert_composite_for_dates(rows: list[tuple[date, float]])`, `export_category_rows(start: date, categories: list[str]) -> list[tuple]`)
- Test: `tests/rebuild_history_test.py`

**Interfaces:**
- `rebuild_category_history.py [--days 92] [--write]`:
  - Calls each weighted provider's `fetch_history(days + 30)`, keeping the last `days` dates.
  - Computes the composite only on dates where every weighted category has a value.
  - Writes `data/backups/rebuild_dryrun_<date>.csv` (date, category, old, new).
  - With `--write`: exports the existing rows to `data/backups/category_scores_pre_v2_<date>.csv`, then upserts. It never deletes.
  - Refuses `--write` unless the environment variable `CONFIRM_PROD_REBUILD=yes` is set when `DATABASE_URL` points at Postgres.
- `backtest_composite.py`:
  - Prints each category and the composite at 2008-07, 2020-04, 2021-03-29, 2021-12, 2024-02, 2025-04, 2026-03-20 and today, using `fetch_history` over long windows wherever the history exists ("n/a" otherwise).
  - Also prints today's composite.

- [ ] **Step 1: Write the failing tests.**
  - `test_rebuild_dry_run_writes_csv_and_no_db_writes` (SQLite temp DB, mocked providers).
  - `test_rebuild_write_refuses_postgres_without_confirm`.
  - `test_composite_only_on_complete_dates`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit.** "History rebuild (dry-run by default) and composite backtest scripts."

---

### Task 19: Final verification

- [ ] **Step 1: Full suite.** `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python -m pytest tests/ -q`. Expected: 0 failures.
- [ ] **Step 2: Backtest.** `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/backtest_composite.py`. Save the output for the final report. Checks: the 2026-03 Hormuz and today composites are clearly lower than 2023 calm; chokepoints today < 45; tariffs today < 60.
- [ ] **Step 3: Live fetch smoke test** (SQLite). Run `DATABASE_URL= venv/bin/python -c "from data.aggregator import aggregate_data; d=aggregate_data(); print(d['composite'], d['current_scores'], d['stale_categories'], d['excluded_categories'])"`. Expected: 8 weighted categories plus the industry categories, and nothing excluded.
- [ ] **Step 4: Preview.** Start `DATABASE_URL= GSC_DISABLE_BACKGROUND=1 gunicorn app:server -c gunicorn.conf.py` via the launch config. Open it in the browser pane and check:
  - all 8 rows render with sources and as-of dates
  - stale suffixes appear where expected
  - `/docs` and `/api/v1/latest` look right
  - the phone width (375 px) still works
- [ ] **Step 5: Dry-run rebuild against SQLite** to prove the script runs. The production dry run waits for Will's "push it" and his approval.
- [ ] **Step 6: Final commit** of any fixes. Report local, pushed and live states separately.
