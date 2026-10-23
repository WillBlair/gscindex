"""
Compute the frozen 0-100 score anchors (methodology v2) and write data/score_anchors.json.

    DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/compute_anchors.py
    DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/compute_anchors.py --sectors-only

Each input is put on the scale its provider scores (log, CPI-real log, YoY %, z-score) and
averaged by calendar month. Then, on that transformed monthly series:

    100 (best)   = the healthiest 5% of the pre-2020 baseline (5th or 95th percentile)
    80  (normal) = the baseline median
    0   (worst)  = the worst monthly mean on record through 2025, or a cited reference

The script also writes the chokepoint tonnage weights and monthly baselines, the regional Fed
prices-paid stats, port throughput shares and the waterway record lows.

``--sectors-only`` fetches and fits only the Semis and Aero sector inputs (Bank of Japan, FRED)
and merges them into the existing JSON: every other key and value stays byte-identical, so
``git diff`` shows additions only (or, on a re-run, changes to sector keys only).

It downloads public data only (FRED, NY Fed, Caldara-Iacoviello, Treasury, USDA AgTransport,
IMF PortWatch, USGS) through the app's own fetchers, so every anchor is
fitted on exactly the quantity the provider scores. It writes the JSON and nothing else (no
database). Output is deterministic for a given data vintage. Anchors are frozen: re-running it
is a deliberate, versioned change. Review the printed table and commit the JSON.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from scoring.anchors import anchored_score, transform_value  # noqa: E402

OUT = ROOT / "data" / "score_anchors.json"
METHOD_VERSION = 2
WORST_THROUGH = "2025-12-31"
CPI_SERIES = "CPIAUCSL"
CPI_REFERENCE_DATE = "2025-12-01"

# Chokepoints: tonnage weights and monthly baselines come from PortWatch over this window
# (pre-2022 has a coverage break; from Nov 2023 the Red Sea attacks rerouted shipping).
CHOKEPOINT_WINDOW = ("2022-01-01", "2023-10-31")
PORT_SHARE_WINDOW = ("2022-01-01", "2023-12-31")
# ULSD before DDFUELNYH starts (2006) is NY Harbor No. 2 heating oil scaled by this factor
# (research: mean ULSD / heating oil ratio over their overlap). Anchor history only.
ULSD_BACKFILL_FACTOR = 1.0824
# TPU daily and monthly counts are treated as one scale when the overlap's mean ratio of the
# monthly mean of the daily index to the monthly index is within this distance of 1.
TPU_SCALE_TOLERANCE = 0.15
# Rail anchors: BTS monthly carloads and intermodal units on FRED (2000+). The weekly STB data
# the provider scores only starts in 2017, too short for a pre-2020 baseline.
RAIL_CARLOADS, RAIL_INTERMODAL = "RAILFRTCARLOADSD11", "RAILFRTINTERMODALD11"

PORTWATCH_SERVICES = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
# Each dashboard port (data/ports_data.py name) -> its PortWatch portid. The PortWatch port of
# the same name, except: New York = "New York-New Jersey", Los Angeles = "Los Angeles-Long
# Beach", Mumbai = "Mumbai-Jawaharlal Nehru (Nhava Sheva)", Chennai = "Chennai (Madras)",
# Qingdao = "Qingdao Port", and two where the same-name entry is not the cargo port: Dubai =
# Jebel Ali (PortWatch "Dubai" is Port Rashid) and Sydney = Port Botany (PortWatch "Sydney" is
# the harbour, 256 calls in two years).
PORTWATCH_PORT_IDS: dict[str, str] = {
    "Houston": "port481", "New York": "port815", "Los Angeles": "port664", "Savannah": "port1170",
    "Vancouver": "port1350", "Colon": "port1035", "Manzanillo": "port699", "Santos": "port1160",
    "Buenos Aires": "port184", "Rotterdam": "port1114", "Hamburg": "port446", "Antwerp": "port57",
    "Felixstowe": "port343", "Piraeus": "port908", "Algeciras": "port31", "Gdansk": "port380",
    "Shanghai": "port1188", "Hong Kong": "port474", "Busan": "port1065", "Qingdao": "port1069",
    "Tokyo": "port1305", "Kaohsiung": "port541", "Singapore": "port1201",
    "Laem Chabang": "port1197", "Port Klang": "port960", "Mumbai": "port776", "Chennai": "port235",
    "Colombo": "port254", "Dubai": "port744", "Jeddah": "port518", "Durban": "port311",
    "Mombasa": "port757", "Djibouti": "port294", "Lagos": "port626", "Port Said": "port192",
    "Sydney": "port161", "Melbourne": "port729",
}

TARIFF_WORST = 19.8
TARIFF_WORST_BASIS = (
    "Documented historical reference, not in-sample: 19.8% = US duties collected as a share of "
    "total imports for consumption in 1933, the peak under the Tariff Act of 1930 (Smoot-Hawley); "
    "1932 was 19.6%. Source: USITC, 'Value of U.S. Imports for Consumption, Duties Collected, and "
    "Ratio of Duties to Values, 1891-2010' (March 2011), "
    "https://webarchive.library.unt.edu/web/20130213204908mp_/http://dataweb.usitc.gov/scripts/AVE.PDF "
    "(current edition: https://www.usitc.gov/documents/dataweb/ave_table_1891_2018.pdf). Higher "
    "ratios in the 1890s-1900s (29.3% in 1899) predate the income tax, when tariffs were the main "
    "federal revenue, so the 1930s peak is the reference."
)

SOURCES = {
    "gscpi": "NY Fed GSCPI CSV, https://www.newyorkfed.org/research/policy/gscpi",
    "brent": "FRED DCOILBRENTEU, deflated by FRED CPIAUCSL",
    "ulsd": "FRED DDFUELNYH (DHOILNYH x 1.0824 before 2006-06), deflated by FRED CPIAUCSL",
    "ttf": "FRED PNGASEUUSDM (IMF monthly), deflated by FRED CPIAUCSL",
    "copper": "FRED PCOPPUSDM (IMF monthly), deflated by FRED CPIAUCSL",
    "aluminum": "FRED PALUMUSDM (IMF monthly), deflated by FRED CPIAUCSL",
    "tariff_burden": ("Treasury DTS deposits_withdrawals_operating_cash (customs), "
                      "https://fiscaldata.treasury.gov; FRED BOPGIMP"),
    "tpu": "Caldara et al. TPU workbook, https://www.matteoiacoviello.com/tpu.htm",
    "gpr": "Caldara-Iacoviello GPR files, https://www.matteoiacoviello.com/gpr.htm",
    "tsifrght": "FRED TSIFRGHT (BTS Freight Transportation Services Index)",
    "rail_volume": ("anchors: FRED RAILFRTCARLOADSD11 + RAILFRTINTERMODALD11 (BTS); scored: STB EP 724 "
                    "weekly carloads via USDA AgTransport, https://agtransport.usda.gov/resource/tb7q-kn5i.json"),
    "prices_paid": "FRED PPCDFSA066MSFRBPHI, PPCDISA066MSFRBNY, PRMSAMFRBDAL",
    "boj_memory": ("Bank of Japan Time-Series Data Search API, PR01 PRCG20_2500850005 (CGPI import price "
                   "index, MOS memory ICs, contract-currency basis), YoY %"),
    "boj_logic": ("Bank of Japan Time-Series Data Search API, PR01 PRCG20_2500850004 (CGPI import price "
                  "index, MOS logic ICs, contract-currency basis), YoY %"),
    "fab_util_3344": "FRED CAPUTLG3344S (Fed G.17 capacity utilization, NAICS 3344), %",
    "aero_caputl": "FRED CAPUTLG3364T9S (Fed G.17 capacity utilization, NAICS 3364-9), %",
    "aero_inv_ship": ("FRED ANAPTI / 3-month mean of FRED ANAPVS (Census M3 nondefense aircraft and parts "
                      "inventories over shipments), months"),
    "ppi_ti_mill": "FRED WPU102505 (BLS PPI titanium and titanium-base alloy mill shapes), YoY %",
    "ppi_ni_mill": "FRED WPU102504 (BLS PPI nickel and nickel-base alloy mill shapes), YoY %",
    "ppi_ti_forge": "FRED PCU33211233211242 (BLS PPI titanium and titanium alloy forgings), YoY %",
    "ppi_nonferrous_forge": "FRED PCU332112332112 (BLS PPI nonferrous forging), YoY %",
    "ppi_steel_invest_cast": "FRED PCU3315123315120 (BLS PPI steel investment castings), YoY %",
}

# Sector inputs: key -> (transform, direction, pre-2020 baseline). Baselines follow the research
# (docs/superpowers/research/2026-10-23-industry-artifacts: semis/candidate_anchors.json,
# memory-alt, aero/compute_proposed.py): BOJ YoY from 2001 (the series starts 2000-01), and the
# research's pre-2020 windows for the FRED series. Worst = worst month through 2025, no override.
SECTOR_INPUTS: dict[str, tuple[str, str, tuple[str, str]]] = {
    "boj_memory": ("identity", "lower_better", ("2001-01-01", "2019-12-31")),
    "boj_logic": ("identity", "lower_better", ("2001-01-01", "2019-12-31")),
    "fab_util_3344": ("identity", "lower_better", ("1972-01-01", "2019-12-31")),
    "aero_caputl": ("identity", "higher_better", ("1972-01-01", "2019-12-31")),
    "aero_inv_ship": ("log", "lower_better", ("1992-01-01", "2019-12-31")),
    "ppi_ti_mill": ("identity", "lower_better", ("1972-01-01", "2019-12-31")),
    "ppi_ni_mill": ("identity", "lower_better", ("1972-01-01", "2019-12-31")),
    "ppi_ti_forge": ("identity", "lower_better", ("1985-01-01", "2019-12-31")),
    "ppi_nonferrous_forge": ("identity", "lower_better", ("1985-01-01", "2019-12-31")),
    "ppi_steel_invest_cast": ("identity", "lower_better", ("1985-01-01", "2019-12-31")),
}
SECTOR_INPUT_KEYS = tuple(SECTOR_INPUTS)
# Where the record (baseline and worst) starts when the series goes back further. G.17 aerospace
# utilization starts in 1948; the research counts it from 1972, like the semiconductor series,
# so 2020-04 (46.8%) is the worst month rather than 1950-03 (31.8%).
SECTOR_RECORD_START = {"aero_caputl": "1972-01-01"}


# ------------------------------------------------------------------------------ core


def _clean(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(pd.Series(series), errors="coerce").replace([np.inf, -np.inf], np.nan)
    s = s.dropna()
    s.index = pd.DatetimeIndex(s.index)
    s = s.sort_index()
    return s[~s.index.duplicated(keep="last")]


def cpi_reference(cpi: pd.Series) -> float:
    """The CPIAUCSL value for the reference month (2025-12); missing is a ValueError."""
    cpi = _clean(cpi)
    ref = pd.Timestamp(CPI_REFERENCE_DATE)
    if ref not in cpi.index:
        raise ValueError(f"{CPI_SERIES} has no value for {CPI_REFERENCE_DATE}")
    return float(cpi[ref])


def _cpi_ratio(cpi: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """CPI_ref / CPI_t for each date in ``index``: the latest CPI month on or before it, as
    the providers deflate (``data.providers.prices.cpi_ratios`` then a forward fill)."""
    cpi = _clean(cpi)
    ratios = cpi_reference(cpi) / cpi
    return ratios.reindex(ratios.index.union(index)).ffill().reindex(index)


def transform_series(series: pd.Series, transform: str, cpi: pd.Series | None = None) -> pd.Series:
    """The series on its scoring scale: identity, log, or log of the CPI-real (2025-12 $) value."""
    s = _clean(series)
    if transform == "identity":
        return s
    if transform not in ("log", "log_real"):
        raise ValueError(f"unknown transform {transform!r}")
    s = s[s > 0]
    if transform == "log_real":
        if cpi is None:
            raise ValueError("log_real needs the CPI series")
        s = s * _cpi_ratio(cpi, s.index)
    return np.log(s).dropna()


def compute_input_anchor(series: pd.Series, transform: str, direction: str,
                         baseline: tuple[str, str], worst_through: str = WORST_THROUGH,
                         cpi: pd.Series | None = None, worst_override: float | None = None,
                         worst_basis: str = "") -> dict:
    """Anchors for one input from its full history.

    The series is transformed (``log_real`` deflates to 2025-12 dollars with CPIAUCSL) and
    resampled to calendar-month means. ``best`` is the healthy-tail percentile of the baseline
    months (5th for lower_better, 95th for higher_better), ``normal`` the baseline median, and
    ``worst`` the worst monthly mean through ``worst_through``, unless ``worst_override`` (in
    transformed units) is given. Raises ValueError on an empty baseline or non-monotone anchors.
    """
    if direction not in ("lower_better", "higher_better"):
        raise ValueError(f"unknown direction {direction!r}")
    monthly = transform_series(series, transform, cpi).resample("MS").mean().dropna()
    base = monthly[(monthly.index >= pd.Timestamp(baseline[0])) & (monthly.index <= pd.Timestamp(baseline[1]))]
    if base.empty:
        raise ValueError(f"no observations in the baseline {baseline[0]}..{baseline[1]}")
    lower = direction == "lower_better"
    best = float(base.quantile(0.05 if lower else 0.95))
    normal = float(base.median())
    if worst_override is not None:
        worst = float(worst_override)
    else:
        record = monthly[monthly.index <= pd.Timestamp(worst_through)]
        month = record.idxmax() if lower else record.idxmin()
        worst = float(record[month])
        worst_basis = worst_basis or (
            f"worst monthly mean through {worst_through[:7]}: {month:%Y-%m}")
    anchor = {
        "transform": transform,
        "direction": direction,
        "best": round(best, 6),
        "normal": round(normal, 6),
        "worst": round(worst, 6),
        "baseline": f"{base.index[0]:%Y-%m} to {base.index[-1]:%Y-%m} ({len(base)} months)",
        "worst_basis": worst_basis,
        "generated": datetime.now(timezone.utc).date().isoformat(),
    }
    anchored_score(anchor["normal"], anchor)     # raises ValueError unless best < normal < worst
    return anchor


# ------------------------------------------------------------------------------ inputs

# Latest observation of each input, for the printed table: key -> (transformed value, date, raw text)
TODAY: dict[str, tuple[float, date, str]] = {}


def _latest(key: str, series: pd.Series, transform: str, cpi: pd.Series | None, raw_fmt: str) -> None:
    s = _clean(series)
    x = transform_series(s, transform, cpi)
    TODAY[key] = (float(x.iloc[-1]), x.index[-1].date(), raw_fmt.format(float(s.iloc[-1])))


@contextmanager
def _full_fred_window(*names: str):
    """Widen the providers' runtime FRED windows so their own code reads the full history."""
    saved = {name: getattr(config, name) for name in names}
    try:
        for name in names:
            setattr(config, name, 80 * 365)
        yield
    finally:
        for name, value in saved.items():
            setattr(config, name, value)


def build_gscpi() -> dict:
    from data.gscpi_client import fetch_gscpi_series
    s = fetch_gscpi_series()
    _latest("gscpi", s, "identity", None, "{:+.2f}")
    return compute_input_anchor(s, "identity", "lower_better", ("1998-01-01", "2019-12-31"))


def build_prices(cpi: pd.Series) -> dict[str, dict]:
    from data.providers.fred_client import fetch_fred_full
    out = {}
    ulsd = _clean(fetch_fred_full("DDFUELNYH"))
    heating = _clean(fetch_fred_full("DHOILNYH"))
    ulsd_hist = pd.concat([heating[heating.index < ulsd.index[0]] * ULSD_BACKFILL_FACTOR, ulsd])
    legs = {
        "brent": (_clean(fetch_fred_full("DCOILBRENTEU")), "${:.2f}/bbl"),
        "ulsd": (ulsd_hist, "${:.3f}/gal"),
        "ttf": (_clean(fetch_fred_full("PNGASEUUSDM")), "${:.2f}/MMBtu"),
        "copper": (_clean(fetch_fred_full("PCOPPUSDM")), "${:,.0f}/mt"),
        "aluminum": (_clean(fetch_fred_full("PALUMUSDM")), "${:,.0f}/mt"),
    }
    for key, (series, fmt) in legs.items():
        _latest(key, series, "log_real", cpi, fmt)
        out[key] = compute_input_anchor(series, "log_real", "lower_better",
                                        ("1990-01-01", "2019-12-31"), cpi=cpi)
    out["ulsd"]["baseline"] += f"; DHOILNYH x {ULSD_BACKFILL_FACTOR} before {ulsd.index[0]:%Y-%m-%d}"
    for alias, base in (("ttf_monthly", "ttf"), ("copper_monthly", "copper"), ("aluminum_monthly", "aluminum")):
        out[alias] = dict(out[base])
        TODAY[alias] = TODAY[base]
    return out


def build_tariff_burden() -> dict:
    from data.providers.fred_client import fetch_fred_full
    from data.sources import treasury
    burden = treasury.tariff_burden_series(treasury.fetch_customs_monthly(), fetch_fred_full("BOPGIMP"))
    _latest("tariff_burden", burden, "identity", None, "{:.2f}%")
    anchor = compute_input_anchor(burden, "identity", "lower_better", ("2005-01-01", "2017-12-31"),
                                  worst_override=TARIFF_WORST, worst_basis=TARIFF_WORST_BASIS)
    record = burden[burden.index <= pd.Timestamp(WORST_THROUGH)]
    anchor["in_sample_worst"] = round(float(record.max()), 6)
    anchor["in_sample_worst_month"] = f"{record.idxmax():%Y-%m}"
    return anchor


def build_tpu() -> tuple[dict, str]:
    from data.providers.tariffs import _tpu_mean_series
    from data.sources import tpu
    daily, monthly = tpu.fetch_tpu()
    mean30 = _tpu_mean_series()
    _latest("tpu", mean30, "log", None, "{:.1f}")
    # Scale check: calendar-month mean of the daily index against the monthly index.
    daily_by_month = daily.resample("MS").mean()
    both = pd.concat([daily_by_month.rename("daily"), _clean(monthly).resample("MS").mean().rename("monthly")],
                     axis=1, sort=True).dropna()
    ratio = float((both["daily"] / both["monthly"]).mean())
    corr = float(both["daily"].corr(both["monthly"]))
    check = (f"Scale check over {both.index[0]:%Y-%m}..{both.index[-1]:%Y-%m} ({len(both)} months): "
             f"monthly mean of daily TPU / monthly TPU = {ratio:.3f} on average, correlation {corr:.3f}")
    peak = mean30[mean30.index <= pd.Timestamp(WORST_THROUGH)]
    peak_day = peak.idxmax()
    if abs(ratio - 1.0) <= TPU_SCALE_TOLERANCE:
        basis = (f"max 30-day mean of the daily TPU through {WORST_THROUGH[:7]}: {peak.max():.1f} on "
                 f"{peak_day:%Y-%m-%d}. {check}: comparable, so best and normal come from the monthly "
                 "TPU 1985-2019.")
        anchor = compute_input_anchor(monthly, "log", "lower_better", ("1985-01-01", "2019-12-31"),
                                      worst_override=math.log(float(peak.max())), worst_basis=basis)
    else:
        basis = (f"max 30-day mean of the daily TPU through {WORST_THROUGH[:7]}: {peak.max():.1f} on "
                 f"{peak_day:%Y-%m-%d}. {check}: not comparable, so all three anchors come from the "
                 "daily 30-day mean, best and normal over its pre-2020 months.")
        anchor = compute_input_anchor(mean30, "log", "lower_better", ("1985-01-01", "2019-12-31"),
                                      worst_override=math.log(float(peak.max())), worst_basis=basis)
    return anchor, check


def build_gpr() -> tuple[dict, str]:
    from data.providers.geopolitical import _gpr_mean
    from data.sources import gpr
    monthly = gpr.fetch_gpr_monthly()
    daily = gpr.fetch_gpr_daily()
    mean30, _ = _gpr_mean()
    _latest("gpr", mean30.dropna(), "log", None, "{:.0f}")
    both = pd.concat([daily.resample("MS").mean().rename("daily"),
                      _clean(monthly).resample("MS").mean().rename("monthly")], axis=1, sort=True).dropna()
    ratio = float((both["daily"] / both["monthly"]).mean())
    corr = float(both["daily"].corr(both["monthly"]))
    check = (f"Scale check over {both.index[0]:%Y-%m}..{both.index[-1]:%Y-%m} ({len(both)} months): "
             f"monthly mean of daily GPRD / monthly GPR = {ratio:.3f} on average, correlation {corr:.3f} "
             "(both are normalized to 100 = the 1985-2019 average)")
    anchor = compute_input_anchor(monthly, "log", "lower_better", ("1985-01-01", "2019-12-31"))
    anchor["worst_basis"] = f"record monthly GPR, {anchor['worst_basis'].split(': ')[-1]}. {check}"
    return anchor, check


def build_tsifrght() -> dict:
    from data.providers import freight
    with _full_fred_window("FREIGHT_FRED_LOOKBACK_DAYS"):
        yoy = freight._tsifrght_yoy()
    _latest("tsifrght", yoy, "identity", None, "{:+.1f}% YoY")
    return compute_input_anchor(yoy, "identity", "higher_better", ("2001-01-01", "2019-12-31"))


def combined_yoy(carloads: pd.Series, intermodal: pd.Series) -> pd.Series:
    """YoY % of monthly carloads plus intermodal units, each month against the same month a year
    earlier by date (a missing month is a gap, never a shifted comparison)."""
    total = (_clean(carloads) + _clean(intermodal)).dropna()
    base = total.reindex(total.index - pd.DateOffset(months=12))
    yoy = (total / base.to_numpy() - 1.0) * 100.0
    return yoy.replace([np.inf, -np.inf], np.nan).dropna()


def build_rail() -> tuple[dict, str]:
    """Anchors from the long BTS monthly rail series; the provider scores the weekly STB 4-week
    YoY against them (the same quantity: carloads plus intermodal units, year over year)."""
    from data.providers.fred_client import fetch_fred_full
    from data.sources import rail
    yoy = combined_yoy(fetch_fred_full(RAIL_CARLOADS), fetch_fred_full(RAIL_INTERMODAL))
    anchor = compute_input_anchor(yoy, "identity", "higher_better", ("2001-01-01", "2019-12-31"))
    anchor["baseline"] += (f"; YoY % of FRED {RAIL_CARLOADS} + {RAIL_INTERMODAL} (BTS monthly rail "
                           "carloads plus intermodal containers and trailers, both unit counts built "
                           "the same way from AAR weekly data, seasonally adjusted), summed then "
                           "compared with the same month a year earlier. The provider scores the "
                           "weekly STB EP 724 4-week-mean YoY of the same total against these anchors")
    anchor["worst_basis"] = (f"lowest monthly combined YoY through {WORST_THROUGH[:7]}: "
                             f"{anchor['worst_basis'].split(': ')[-1]}")
    weekly = rail.fetch_rail_weekly()
    stb = rail.rail_yoy(weekly).dropna()
    _latest("rail_volume", stb, "identity", None, "{:+.1f}% YoY")
    both = pd.concat([stb.resample("MS").mean().rename("stb"), yoy.rename("bts")], axis=1, sort=True).dropna()
    latest, prior = float(weekly.iloc[-1]), weekly.iloc[-5:-1]
    note = (f"BTS vs STB YoY overlap {both.index[0]:%Y-%m}..{both.index[-1]:%Y-%m} ({len(both)} months): "
            f"correlation {both['stb'].corr(both['bts']):.3f}, mean STB - BTS "
            f"{(both['stb'] - both['bts']).mean():+.2f} pts. Latest STB week {weekly.index[-1]:%Y-%m-%d}: "
            f"{latest:,.0f} units vs prior 4-week mean {prior.mean():,.0f} ({latest / prior.mean() - 1:+.1%})")
    return anchor, note


def common_months(surveys: dict[str, pd.Series]) -> pd.DatetimeIndex:
    """Months in which every survey has a value."""
    months = None
    for series in surveys.values():
        idx = _clean(series).index
        months = idx if months is None else months.intersection(idx)
    return months.sort_values()


def build_prices_paid() -> tuple[dict, dict]:
    from data.sources import fed_surveys
    with _full_fred_window("INPUTS_FRED_LOOKBACK_DAYS"):
        surveys = fed_surveys.fetch_prices_paid()
    missing = set(fed_surveys.PRICES_PAID_SERIES) - set(surveys)
    if missing:
        raise RuntimeError(f"prices-paid surveys unavailable: {sorted(missing)}")
    stats = {}
    for name, series in surveys.items():
        base = _clean(series)["2004-01-01":"2019-12-31"]
        stats[name] = [round(float(base.mean()), 6), round(float(base.std(ddof=1)), 6)]
    composite = fed_surveys.prices_paid_composite(surveys, stats)
    _latest("prices_paid", composite, "identity", None, "z {:+.2f}")
    # Worst only where all three surveys report, so a single-survey month (Philadelphia alone
    # before 2001) cannot set it.
    full = composite[composite.index.isin(common_months(surveys))]
    full = full[full.index <= pd.Timestamp(WORST_THROUGH)]
    month = full.idxmax()
    anchor = compute_input_anchor(
        composite, "identity", "lower_better", ("2004-01-01", "2019-12-31"),
        worst_override=float(full[month]),
        worst_basis=(f"worst monthly composite z through {WORST_THROUGH[:7]} among months where all "
                     f"three surveys report ({full.index[0]:%Y-%m} on): {month:%Y-%m}"))
    anchor["baseline"] += ("; z per survey against its own 2004-01..2019-12 mean and sample sd "
                           "(Dallas starts " + f"{_clean(surveys['dallas']).index[0]:%Y-%m})")
    return anchor, stats


# ------------------------------------------------------------------------------ sectors


def _sector_measures() -> dict[str, pd.Series]:
    """Each sector input's monthly measure from its provider's own code (BOJ YoY, G.17 level,
    M3 inventories over the 3-month shipment mean, PPI YoY), over the full history."""
    from data.providers import aero, semis
    with _full_fred_window("SEMIS_FRED_LOOKBACK_DAYS", "AERO_FRED_LOOKBACK_DAYS"):
        measures = {cls.input_key: cls()._monthly() for cls in (
            semis.MemoryPricesProvider, semis.LogicPricesProvider, semis.FabUtilizationProvider)}
        for cls in (aero.ThroughputProvider, aero.FlowProvider, aero.MillPricesProvider, aero.ForgeCastProvider):
            measures.update({spec.key: spec.monthly() for spec in cls.inputs})
    missing = set(SECTOR_INPUT_KEYS) - set(measures)
    if missing:
        raise RuntimeError(f"no provider measure for {sorted(missing)}")
    return measures


def build_sectors() -> dict[str, dict]:
    out = {}
    for key, series in _sector_measures().items():
        transform, direction, baseline = SECTOR_INPUTS[key]
        # Latest month as the provider reads it (an unmeasurable latest month stays NaN).
        value = float(series.iloc[-1])
        measurable = math.isfinite(value) and (transform == "identity" or value > 0)
        x = transform_value(value, transform) if measurable else float("nan")
        fmt = {"aero_inv_ship": "{:.2f} months", "fab_util_3344": "{:.1f}%", "aero_caputl": "{:.1f}%"}
        TODAY[key] = (x, series.index[-1].date(), fmt.get(key, "{:+.1f}% YoY").format(value))
        start = SECTOR_RECORD_START.get(key)
        record = series[series.index >= pd.Timestamp(start)] if start else series
        out[key] = compute_input_anchor(record, transform, direction, baseline)
        if start:
            out[key]["worst_basis"] += f"; record counted from {start[:7]}, as in the research"
        out[key]["source"] = SOURCES[key]
    return out


def _dump(anchors: dict) -> str:
    return json.dumps(anchors, indent=2) + "\n"


def merge_sector_anchors(path: Path, sector_inputs: dict[str, dict]) -> None:
    """Write the sector anchors into the anchors JSON at ``path`` and change nothing else.

    New sector keys go at the top of ``inputs`` so every existing line, including the last
    entry's closing brace, is untouched; a sector key already present is replaced in place.
    Raises ValueError for a key that is not a sector input, or a file that would not be
    rewritten byte for byte.
    """
    unknown = set(sector_inputs) - set(SECTOR_INPUT_KEYS)
    if unknown:
        raise ValueError(f"not sector inputs: {sorted(unknown)}")
    text = path.read_text(encoding="utf-8")
    anchors = json.loads(text)
    if _dump(anchors) != text:
        raise ValueError(f"{path} is not in this script's JSON format; refusing to rewrite it")
    current = anchors["inputs"]
    inputs = {key: sector_inputs[key] for key in SECTOR_INPUT_KEYS if key in sector_inputs and key not in current}
    for key, value in current.items():
        inputs[key] = sector_inputs.get(key, value)
    anchors["inputs"] = inputs
    path.write_text(_dump(anchors), encoding="utf-8")


# ------------------------------------------------------------------------------ PortWatch


def build_chokepoints() -> tuple[dict, dict]:
    from data import portwatch
    start, end = (pd.Timestamp(d) for d in CHOKEPOINT_WINDOW)
    daily = portwatch.fetch_chokepoint_daily(start.date())
    names = {pid: name for name, pid in portwatch.PORTIDS.items()}
    d = daily.assign(name=daily["portid"].map(names))
    d = d[(d["date"] >= start) & (d["date"] <= end)].dropna(subset=["name"])
    capacity = d.groupby("name")["capacity"].mean()
    missing = set(portwatch.PORTIDS) - set(capacity.dropna().index)
    if missing:
        raise RuntimeError(f"PortWatch window has no capacity for {sorted(missing)}")
    capacity["RedSea"] = capacity[["BabM", "Suez"]].mean()
    corridor = capacity[portwatch.CORRIDORS]
    weights = {name: round(float(v), 8) for name, v in (corridor / corridor.sum()).items()}
    by_month = d.groupby(["name", d["date"].dt.month])["n_total"].mean()
    baseline = {}
    for name in portwatch.PORTIDS:
        months = by_month[name]
        if len(months) != 12:
            raise RuntimeError(f"PortWatch window misses months for {name}")
        baseline[name] = {str(int(m)): round(float(v), 4) for m, v in months.items()}
    return weights, baseline


def _portwatch_calls(where: str) -> list[dict]:
    import requests
    stats = json.dumps([{"statisticType": "sum", "onStatisticField": "portcalls",
                         "outStatisticFieldName": "calls"}])
    params = {"where": where, "outStatistics": stats, "f": "json"}
    if "portid IN" in where:
        params["groupByFieldsForStatistics"] = "portid"
    resp = requests.get(f"{PORTWATCH_SERVICES}/Daily_Ports_Data/FeatureServer/0/query",
                        params=params, timeout=180)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"PortWatch error: {body['error']}")
    return [f["attributes"] for f in body.get("features", [])]


def build_port_shares() -> tuple[dict, list[str]]:
    """Each dashboard port's share of all PortWatch port calls over 2022-2023."""
    from data.ports_data import MAJOR_PORTS
    window = f"date >= DATE '{PORT_SHARE_WINDOW[0]}' AND date <= DATE '{PORT_SHARE_WINDOW[1]}'"
    total = float(_portwatch_calls(window)[0]["calls"])
    ids = ",".join(f"'{pid}'" for pid in PORTWATCH_PORT_IDS.values())
    calls = {row["portid"]: float(row["calls"] or 0) for row in _portwatch_calls(f"portid IN ({ids}) AND {window}")}
    shares, not_found = {}, []
    for name, *_ in MAJOR_PORTS:
        pid = PORTWATCH_PORT_IDS.get(name)
        if pid is None or not calls.get(pid):
            not_found.append(name)
            shares[name] = 0.0
        else:
            shares[name] = round(calls[pid] / total, 8)
    return shares, not_found


def build_waterways() -> dict:
    from data.sources import waterways
    stl = waterways.fetch_mississippi_stl(None)
    TODAY["mississippi"] = (float(stl.iloc[-1]), stl.index[-1].date(), f"{stl.iloc[-1]:.2f} ft")
    return {
        "mississippi_record_low": round(float(stl.min()), 4),
        "mississippi_record_low_date": f"{stl.idxmin():%Y-%m-%d}",
        "mississippi_threshold": round(float(stl.quantile(0.10)), 4),
        "mississippi_history": f"{stl.index[0]:%Y-%m-%d} to {stl.index[-1]:%Y-%m-%d} (10th percentile of daily values)",
        "source": "USGS 07010000 daily gauge height (00065)",
    }


# ------------------------------------------------------------------------------ report


def _raw_anchor(value: float, transform: str) -> str:
    return f"{math.exp(value):,.2f}" if transform in ("log", "log_real") else f"{value:,.3f}"


def print_inputs(anchors: dict) -> None:
    print(f"\n{'input':<23}{'transform':<10}{'best':>12}{'normal':>12}{'worst':>12}  "
          f"{'latest':<26}{'as of':<12}{'score':>6}")
    for key, a in anchors["inputs"].items():
        raw = " ".join(_raw_anchor(a[k], a["transform"]) for k in ("best", "normal", "worst"))
        cells = "".join(f"{a[k]:>12.4f}" for k in ("best", "normal", "worst"))
        x, day, text = TODAY.get(key, (float("nan"), None, "-"))
        score = anchored_score(x, a) if math.isfinite(x) else float("nan")
        print(f"{key:<23}{a['transform']:<10}{cells}  {text:<26}{str(day):<12}{score:>6.1f}")
        if a["transform"] != "identity":
            unit = " (2025-12 $)" if a["transform"] == "log_real" else ""
            print(f"{'':<33}raw: {raw}{unit}")


EXPECTED = {"supply_chain": "~50", "chokepoints": "~36", "energy": "20-35", "tariffs": "30-55",
            "geopolitical": "50s", "freight": "55-60", "inputs": "~30", "physical": "high 90s if quiet"}


def print_categories(anchors: dict) -> None:
    from data.providers.chokepoints import ChokepointsProvider
    from data.providers.energy import EnergyProvider
    from data.providers.freight import FreightProvider
    from data.providers.geopolitical import GeopoliticalProvider
    from data.providers.inputs import InputsProvider
    from data.providers.physical import PhysicalProvider
    from data.providers.supply_chain import SupplyChainProvider
    from data.providers.tariffs import TariffsProvider

    config.SCORE_ANCHORS = anchors
    PhysicalProvider._store_kaub = staticmethod(lambda: None)   # this script writes no database rows
    providers = [SupplyChainProvider, ChokepointsProvider, EnergyProvider, TariffsProvider,
                 GeopoliticalProvider, FreightProvider, InputsProvider, PhysicalProvider]
    print(f"\n{'category':<14}{'score':>7}  {'expected':<18}{'as of':<12}raw")
    for cls in providers:
        try:
            score, meta = cls().fetch_current()
            print(f"{cls.category:<14}{score:>7.1f}  {EXPECTED[cls.category]:<18}{meta['as_of']:<12}"
                  f"{meta['raw_value']}")
        except Exception as exc:
            print(f"{cls.category:<14}{'ERROR':>7}  {EXPECTED[cls.category]:<18}{type(exc).__name__}: {exc}")


SECTOR_EXPECTED = {"semis_memory_prices": "~0", "semis_logic_prices": "63-66", "semis_fab_utilization": "~85",
                   "aero_throughput": "~80", "aero_flow": "~76", "aero_mill_prices": "~74",
                   "aero_forge_cast": "~37", "semiconductor": "~50", "aerospace": "~64"}


def print_sectors(anchors: dict) -> None:
    """Today's score per sector category and each sector index (equal-weight mean)."""
    from data.providers import aero, semis
    providers = {cls.category: cls for cls in (
        semis.MemoryPricesProvider, semis.LogicPricesProvider, semis.FabUtilizationProvider,
        aero.ThroughputProvider, aero.FlowProvider, aero.MillPricesProvider, aero.ForgeCastProvider)}
    config.SCORE_ANCHORS = anchors
    print(f"\n{'sector category':<24}{'score':>7}  {'expected':<10}{'as of':<12}raw")
    for sector, spec in config.SECTORS.items():
        scores = []
        for category in spec["weights"]:
            try:
                score, meta = providers[category]().fetch_current()
                scores.append(score)
                print(f"{category:<24}{score:>7.1f}  {SECTOR_EXPECTED[category]:<10}{meta['as_of']:<12}"
                      f"{meta['raw_value']}")
            except Exception as exc:
                print(f"{category:<24}{'ERROR':>7}  {SECTOR_EXPECTED[category]:<10}{type(exc).__name__}: {exc}")
        index = sum(scores) / len(scores) if scores else float("nan")
        print(f"{spec['label'] + ' index':<24}{index:>7.1f}  {SECTOR_EXPECTED[sector]:<10}"
              f"({len(scores)} of {len(spec['weights'])} categories, equal weight)\n")


def sectors_main() -> int:
    sector = build_sectors()
    merge_sector_anchors(OUT, sector)
    print(f"Merged {len(sector)} sector inputs into {OUT.relative_to(ROOT)}")
    anchors = json.loads(OUT.read_text(encoding="utf-8"))
    print_inputs({"inputs": sector})
    print_sectors(anchors)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute the frozen score anchors.")
    parser.add_argument("--sectors-only", action="store_true",
                        help="fit only the sector inputs and merge them into the existing JSON")
    if parser.parse_args(argv).sectors_only:
        return sectors_main()
    from data.providers.fred_client import fetch_fred_full
    cpi = fetch_fred_full(CPI_SERIES)
    inputs: dict[str, dict] = {"gscpi": build_gscpi()}
    inputs.update(build_prices(cpi))
    inputs["tariff_burden"] = build_tariff_burden()
    inputs["tpu"], tpu_check = build_tpu()
    inputs["gpr"], gpr_check = build_gpr()
    inputs["tsifrght"] = build_tsifrght()
    inputs["rail_volume"], rail_note = build_rail()
    inputs["prices_paid"], pp_stats = build_prices_paid()
    for key, anchor in inputs.items():
        anchor["source"] = SOURCES[key.replace("_monthly", "")]
    # Sector keys first, in SECTOR_INPUT_KEYS order, as --sectors-only merged them into the
    # committed file, so a full regeneration never reorders the JSON.
    sector = build_sectors()
    inputs = {**{key: sector[key] for key in SECTOR_INPUT_KEYS}, **inputs}
    weights, baseline = build_chokepoints()
    shares, not_found = build_port_shares()

    anchors = {
        "method_version": METHOD_VERSION,
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "cpi_reference": {"series": CPI_SERIES, "date": CPI_REFERENCE_DATE, "value": cpi_reference(cpi)},
        "inputs": inputs,
        "chokepoint_weights": weights,
        "chokepoint_baseline": baseline,
        "chokepoint_basis": (f"PortWatch Daily_Chokepoints_Data {CHOKEPOINT_WINDOW[0]}..{CHOKEPOINT_WINDOW[1]}: "
                             "weights = mean daily capacity (tonnage) share of the 8 corridors, RedSea = "
                             "mean of BabM and Suez; baseline = mean daily n_total by calendar month"),
        "prices_paid_stats": pp_stats,
        "port_throughput_share": shares,
        "port_throughput_basis": (f"share of all PortWatch Daily_Ports_Data port calls, "
                                  f"{PORT_SHARE_WINDOW[0]}..{PORT_SHARE_WINDOW[1]}"),
        "waterways": build_waterways(),
    }
    OUT.write_text(_dump(anchors), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")

    print_inputs(anchors)
    print(f"\nTPU: {tpu_check}")
    print(f"GPR: {gpr_check}")
    print(f"Rail: {rail_note}")
    print("Chokepoint weights: " + ", ".join(f"{k} {v:.3f}" for k, v in weights.items()))
    top = sorted(shares.items(), key=lambda kv: -kv[1])
    print("Port shares (top 10): " + ", ".join(f"{k} {v:.2%}" for k, v in top[:10]))
    top10 = [v for _, v in top[:10]]
    print(f"Ports not found: {not_found or 'none'}; HAZARD_SCALE {config.HAZARD_SCALE:g}: a Red "
          f"event over the median top-10 port ({float(np.median(top10)):.2%}) costs "
          f"{config.HAZARD_SCALE * float(np.median(top10)):.0f} points "
          f"(range {config.HAZARD_SCALE * top10[-1]:.0f}-{config.HAZARD_SCALE * top10[0]:.0f})")
    w = anchors["waterways"]
    print(f"Waterways: Mississippi record low {w['mississippi_record_low']} ft ({w['mississippi_record_low_date']}), "
          f"threshold (p10) {w['mississippi_threshold']} ft")
    print_categories(anchors)
    print_sectors(anchors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
