"""
Energy Provider
===============
Fuel cost pressure on supply chains from three prices, each scored as an anchored log
real price, minus a penalty for a fast run-up.

Legs (weights in ``config.ENERGY_LEG_WEIGHTS``, renormalized over the legs available):

    1. Brent crude     - FRED ``DCOILBRENTEU`` ($/bbl), live ``BZ=F``.
    2. NY Harbor ULSD  - FRED ``DDFUELNYH`` ($/gal), live ``HO=F``.
    3. European gas    - live ``TTF=F`` (EUR/MWh) x ``EURUSD=X`` / 3.412 -> $/MMBtu, else the
                         latest IMF monthly average, FRED ``PNGASEUUSDM``.

Score Logic
-----------
Each price is deflated to the CPI reference month (``CPIAUCSL``), logged and mapped through
its anchors (healthiest 5% of pre-2020 history = 100, pre-2020 median = 80, worst monthly
average on record = 0). The legs are blended, then each leg's spike penalty is subtracted
at that leg's renormalized weight:

    score = blend - sum(w_leg * spike_penalty(real price now / real price 91 days ago - 1))

The penalty is 0 up to a 20% rise and 15 points at an 82% rise or more. WTI, the Brent-WTI
spread and the ULSD crack spread are shown for context and never scored.

This is a COST gauge, not a demand gauge: a price collapse from falling demand reads as low
cost pressure even though the demand picture may be bad.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
from data.providers.base import BaseProvider
from data.providers.fred_client import fetch_fred_full
from data.providers.readings import (
    InputReading, blend_inputs, freshness_status, inputs_metadata, oldest_as_of, period_end)
from data.sources import markets
from scoring.anchors import get_anchor, score_raw

logger = logging.getLogger(__name__)

_FRED_CACHE_TTL = 3600
_CPI_SERIES = "CPIAUCSL"
_LEGS = {
    # leg: (label, FRED series, live symbol, unit label)
    "brent": ("Brent", "DCOILBRENTEU", "BZ=F", "/bbl"),
    "ulsd": ("ULSD", "DDFUELNYH", "HO=F", "/gal"),
}
_TTF_SERIES = "PNGASEUUSDM"
_TTF_QUOTE = "TTF=F"
_FX_QUOTE = "EURUSD=X"
_LEG_LABELS = {"brent": "Brent", "ulsd": "ULSD", "ttf": "TTF", "ttf_monthly": "TTF"}
_UNITS = {"brent": "/bbl", "ulsd": "/gal", "ttf": "/MMBtu", "ttf_monthly": "/MMBtu"}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _fred(series_id: str) -> pd.Series:
    return fetch_fred_full(series_id, cache_ttl=_FRED_CACHE_TTL)


def spike_penalty(change_3m: float) -> float:
    """Points off for a real price rise over 91 days (fraction): 0 at <= start, max at >= full."""
    spike = config.ENERGY_SPIKE
    if change_3m is None or not math.isfinite(change_3m):
        return 0.0
    frac = (change_3m - spike["start"]) / (spike["full"] - spike["start"])
    return spike["max_points"] * min(max(frac, 0.0), 1.0)


def _clean(series: pd.Series) -> pd.Series:
    """Finite, positive prices only, sorted, one value per date."""
    series = pd.to_numeric(series, errors="coerce").dropna()
    series = series[(series > 0) & series.map(math.isfinite)].sort_index()
    return series[~series.index.duplicated(keep="last")]


def _asof(series: pd.Series, day: date) -> float | None:
    """Last value dated on or before ``day``."""
    earlier = series[series.index <= pd.Timestamp(day)]
    return float(earlier.iloc[-1]) if len(earlier) else None


def _anchors() -> tuple[dict, float]:
    """The energy anchors and the CPI reference value; a missing one is a RuntimeError."""
    anchors = {key: get_anchor(key) for key in ("brent", "ulsd", "ttf", "ttf_monthly")}
    try:
        cpi_ref = float(config.SCORE_ANCHORS["cpi_reference"]["value"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("no anchor for cpi_reference") from None
    return anchors, cpi_ref


def _cpi_ratios(cpi_ref: float) -> pd.Series:
    """CPI_ref / CPI_t, dated by CPI observation month."""
    try:
        cpi = _clean(_fred(_CPI_SERIES))
    except Exception as exc:
        raise RuntimeError(f"{_CPI_SERIES} unavailable: {exc}") from exc
    if cpi.empty:
        raise RuntimeError(f"{_CPI_SERIES} unavailable: no observations")
    return cpi_ref / cpi


def _missing(name: str, source: str) -> InputReading:
    return InputReading(name, None, None, source, status="missing")


def _real_change(price: float, ratio_now: float, history: pd.Series, ratios: pd.Series,
                 ref_day: date) -> float | None:
    """Real price now over the real price in ``history`` on/before ``ref_day``, minus 1."""
    then, ratio_then = _asof(history, ref_day), _asof(ratios, ref_day)
    if then is None or ratio_then is None:
        return None
    return price * ratio_now / (then * ratio_then) - 1.0


def _raw_text(name: str, price: float, change: float | None, penalty: float) -> str:
    text = f"${price:.2f}{_UNITS[name]}"
    if change is None:
        return f"{text}; no price 3 months back, no spike penalty"
    return f"{text}; real price {change:+.0%} in 3 months, spike penalty {penalty:.1f} pts"


class EnergyProvider(BaseProvider):
    """Energy & Fuel - Brent, ULSD and TTF as anchored real prices minus a spike penalty."""

    category = "energy"

    # ------------------------------------------------------------------ current

    def _daily_leg(self, leg: str, today: date, anchor: dict, ratios: pd.Series,
                   ratio_now: float) -> tuple[InputReading, float | None, float]:
        label, series_id, symbol, _ = _LEGS[leg]
        try:
            history = _clean(_fred(series_id))
            if history.empty:
                raise ValueError("no observations")
            official_date, official = history.index[-1].date(), float(history.iloc[-1])
            value, as_of, mode = markets.scale_live(official, official_date, symbol)
            return self._reading(leg, value, as_of, mode, symbol, series_id, anchor, ratio_now,
                                 history, ratios, today, official_date)
        except Exception as exc:
            logger.warning("Energy %s leg unavailable: %s", label, exc)
            return _missing(leg, f"{label}: FRED {series_id} unavailable"), None, 0.0

    def _reading(self, name: str, value: float, as_of: date, mode: str, symbol: str,
                 series_id: str, anchor: dict, ratio_now: float, history: pd.Series,
                 ratios: pd.Series, today: date, official_date: date | None = None) -> tuple[InputReading, float | None, float]:
        """Score one price. Returns (reading, price, spike penalty in points)."""
        label = _LEG_LABELS[name]
        score = score_raw(value, anchor, ratio_now)
        change = _real_change(value, ratio_now, history, ratios,
                              as_of - timedelta(days=config.ENERGY_SPIKE_LOOKBACK_DAYS))
        penalty = spike_penalty(change)
        if mode == "live" and name == "ttf":
            source = f"{label} ({symbol}: live, converted to $/MMBtu; {series_id} monthly average is the fallback)"
        elif mode == "live":
            source = f"{label} ({series_id}, {symbol}: live, scaled from the {official_date} print)"
        else:
            source = f"{label} ({series_id}, {symbol}: official, {as_of})"
        reading = InputReading(name, score, as_of, source, _raw_text(name, value, change, penalty),
                               freshness_status(as_of, today, name))
        return reading, value, penalty

    def _live_ttf(self, monthly_value: float | None, today: date) -> tuple[float, date]:
        """TTF=F x EURUSD=X in $/MMBtu, or ValueError if any check fails."""
        if monthly_value is None:
            raise ValueError("no monthly TTF value to check the live quote against")
        ttf_date, ttf = markets.last_quote(_TTF_QUOTE)
        fx_date, fx = markets.last_quote(_FX_QUOTE)
        oldest = min(ttf_date, fx_date)
        if (today - oldest).days > config.TTF_LIVE_MAX_AGE_DAYS:
            raise ValueError(f"quote dated {oldest} is stale")
        value = ttf * fx / config.MWH_PER_MMBTU
        if not (math.isfinite(value) and value > 0):
            raise ValueError("converted TTF is not a positive number")
        low, high = config.LIVE_SCALE_RATIO_BOUNDS
        if not low <= value / monthly_value <= high:
            raise ValueError(f"converted TTF ${value:.2f} is outside {low}-{high}x of the monthly ${monthly_value:.2f}")
        return value, oldest

    def _ttf_leg(self, today: date, anchors: dict, ratios: pd.Series,
                 ratio_now: float) -> tuple[InputReading, float | None, float]:
        try:
            monthly = _clean(_fred(_TTF_SERIES))
        except Exception as exc:
            logger.warning("Energy TTF monthly unavailable: %s", exc)
            monthly = pd.Series(dtype=float)
        monthly_value = float(monthly.iloc[-1]) if len(monthly) else None
        try:
            value, as_of = self._live_ttf(monthly_value, today)
            return self._reading("ttf", value, as_of, "live", f"{_TTF_QUOTE} x {_FX_QUOTE}", _TTF_SERIES,
                                 anchors["ttf"], ratio_now, monthly, ratios, today)
        except Exception as exc:
            logger.warning("Energy live TTF skipped, using the monthly value: %s", exc)
        if monthly_value is None:
            return _missing("ttf_monthly", f"TTF: FRED {_TTF_SERIES} unavailable"), None, 0.0
        as_of = period_end(monthly.index[-1].date(), "M")
        return self._reading("ttf_monthly", monthly_value, as_of, "official", "monthly average",
                             _TTF_SERIES, anchors["ttf_monthly"], ratio_now, monthly, ratios, today)

    def _context(self, prices: dict[str, float]) -> str:
        """WTI, Brent-WTI spread and ULSD crack lines; never raises."""
        lines = []
        try:
            wti = _clean(_fred("DCOILWTICO"))
            wti_date, wti_price = wti.index[-1].date(), float(wti.iloc[-1])
            lines.append(f"WTI crude is ${wti_price:.2f}/bbl ({wti_date}, not scored).")
            brent_then = _asof(_clean(_fred("DCOILBRENTEU")), wti_date)
            if brent_then is not None:
                lines.append(f"Brent minus WTI is ${brent_then - wti_price:.2f}/bbl.")
        except Exception as exc:
            logger.info("Energy WTI context unavailable: %s", exc)
        if "brent" in prices and "ulsd" in prices:
            crack = prices["ulsd"] * 42 - prices["brent"]
            lines.append(f"The ULSD crack spread (ULSD x 42 minus Brent) is ${crack:.2f}/bbl.")
        return " ".join(lines)

    def fetch_current(self) -> tuple[float, dict]:
        today = _today()
        anchors, cpi_ref = _anchors()
        ratios = _cpi_ratios(cpi_ref)
        ratio_now = float(ratios.iloc[-1])

        legs = [self._daily_leg("brent", today, anchors["brent"], ratios, ratio_now),
                self._daily_leg("ulsd", today, anchors["ulsd"], ratios, ratio_now),
                self._ttf_leg(today, anchors, ratios, ratio_now)]
        readings = [leg[0] for leg in legs]
        prices = {leg[0].name: leg[1] for leg in legs}
        penalties = {leg[0].name: leg[2] for leg in legs}

        weights = {**config.ENERGY_LEG_WEIGHTS, "ttf_monthly": config.ENERGY_LEG_WEIGHTS["ttf"]}
        blend, status = blend_inputs(readings, weights)
        if blend is None:
            raise RuntimeError("no energy input available: " + "; ".join(r.source for r in readings))

        used = [r for r in readings if r.status != "missing" and r.score is not None]
        total = sum(weights[r.name] for r in used)
        spike = sum(weights[r.name] / total * penalties[r.name] for r in used)
        score = round(min(max(blend - spike, 0.0), 100.0), 1)

        used_prices = {r.name.replace("_monthly", ""): prices[r.name] for r in used}
        raw_parts = [f"{_LEG_LABELS[r.name]} ${prices[r.name]:.2f}{_UNITS[r.name]}" for r in used]
        context = self._context(used_prices)
        spike_note = (f" Spike penalty this cycle: {spike:.1f} pts." if spike else "")
        metadata = {
            "source": "; ".join(r.source for r in readings),
            "raw_value": " / ".join(raw_parts),
            "raw_label": "Brent $/bbl, ULSD $/gal, TTF $/MMBtu",
            "description": (
                "Cost pressure on supply chains from Brent crude, New York Harbor ultra-low-sulfur "
                "diesel and European natural gas (TTF), each as a price adjusted for inflation. It "
                "measures energy cost pressure, not demand-side health, and a fast run-up in any "
                f"price costs extra points.{spike_note} {context}"
            ).strip(),
            "calculation": (
                f"Per leg: price x CPI ratio (to {config.SCORE_ANCHORS['cpi_reference']['date']} dollars), log, "
                "then mapped through anchors (healthiest 5% of pre-2020 = 100, pre-2020 median = 80, worst "
                "monthly average = 0). Weights " + ", ".join(
                    f"{_LEG_LABELS[k]} {w:.0%}" for k, w in config.ENERGY_LEG_WEIGHTS.items())
                + f", renormalized over available legs. Minus the weighted spike penalty: 0 up to a {config.ENERGY_SPIKE['start']:.0%} real "
                f"rise over {config.ENERGY_SPIKE_LOOKBACK_DAYS} days, {config.ENERGY_SPIKE['max_points']:.0f} "
                f"points at {config.ENERGY_SPIKE['full']:.0%} or more. Clipped to 0-100."
            ),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": oldest_as_of(readings).isoformat(),
            "is_stale": status == "stale",
            "inputs": inputs_metadata(readings),
        }
        return score, metadata

    # ------------------------------------------------------------------ history

    @staticmethod
    def _daily_series(prices: pd.Series, today: date, limit: int, lag_days: int,
                      monthly: bool) -> pd.Series:
        """Official prices on a daily index, dated by publication and carried forward ``limit`` days."""
        dated = prices.copy()
        if monthly:
            dated.index = pd.DatetimeIndex([pd.Timestamp(period_end(d.date(), "M")) + pd.Timedelta(days=lag_days)
                                            for d in dated.index])
        dated = dated[~dated.index.duplicated(keep="last")]
        full = pd.date_range(dated.index.min().normalize(), pd.Timestamp(today), freq="D")
        return dated.reindex(full).ffill(limit=limit)

    def fetch_history(self, days: int) -> pd.Series:
        today = _today()
        anchors, cpi_ref = _anchors()
        ratios = _cpi_ratios(cpi_ref)
        lookback = config.ENERGY_SPIKE_LOOKBACK_DAYS
        cut = pd.Timestamp(today - timedelta(days=days + 2 * lookback + 400))
        lag = config.PUBLICATION_LAG_DAYS["imf_monthly"]

        sources = {
            "brent": ("DCOILBRENTEU", anchors["brent"], False),
            "ulsd": ("DDFUELNYH", anchors["ulsd"], False),
            "ttf": (_TTF_SERIES, anchors["ttf_monthly"], True),
        }
        scores, penalties = {}, {}
        for leg, (series_id, anchor, monthly) in sources.items():
            try:
                prices = _clean(_fred(series_id))
                prices = prices[prices.index >= cut - pd.Timedelta(days=120 if monthly else 0)]
                if prices.empty:
                    raise ValueError("no observations")
                drop_after = config.FRESHNESS["ttf_monthly" if monthly else leg][1]
                limit = max(drop_after - (lag if monthly else 0), 0)
                daily = self._daily_series(prices, today, limit, lag, monthly)
                ratio = ratios.reindex(ratios.index.union(daily.index)).ffill().reindex(daily.index)
                real = daily * ratio
                scores[leg] = pd.Series(
                    [self._safe_score(p, anchor, r) for p, r in zip(daily, ratio)], index=daily.index)
                penalties[leg] = (real / real.shift(lookback) - 1.0).map(spike_penalty)
            except Exception as exc:
                logger.warning("Energy %s history unavailable: %s", leg, exc)
        if not scores:
            raise RuntimeError("no energy history available")

        window = pd.date_range(pd.Timestamp(today - timedelta(days=days)) + pd.Timedelta(days=1),
                               pd.Timestamp(today), freq="D")
        frame = pd.DataFrame({k: v.reindex(window) for k, v in scores.items()})
        pen = pd.DataFrame({k: v.reindex(window) for k, v in penalties.items()}).fillna(0.0)
        w = pd.Series({k: config.ENERGY_LEG_WEIGHTS[k] for k in frame.columns})
        weight_sum = frame.notna().mul(w, axis=1).sum(axis=1)
        blend = frame.mul(w, axis=1).sum(axis=1, skipna=True) / weight_sum
        spike = (frame.notna() * pen).mul(w, axis=1).sum(axis=1) / weight_sum
        out = (blend - spike).where(weight_sum > 0).clip(0.0, 100.0).round(1)
        if out.isna().all():
            raise RuntimeError("no energy history available")
        return out.rename("energy")

    @staticmethod
    def _safe_score(price: float, anchor: dict, ratio: float) -> float:
        if not (math.isfinite(price) and math.isfinite(ratio)):
            return float("nan")
        return score_raw(price, anchor, ratio)
