"""
Aerospace & Manufacturing Data Provider
=======================================
Sector scores for the Aerospace industry profile. All series come from
FRED (existing ``FRED_API_KEY``) plus an optional daily aluminum-futures
nowcast via yfinance (no key).

Returns four category scores from one fetch:
  - aero_metals       Aluminum + nickel cost pressure (inverse percentile)
  - aero_orders       Census M3 nondefense aircraft new orders (direct)
  - aero_production   Fed industrial production, NAICS 3364 (direct)
  - aero_ppi          Aircraft manufacturing PPI (inverse / cost pressure)

This is NOT a 1:1 BaseProvider. ``AeroMetalsProvider`` is the aggregator
adapter: it returns metals as the primary score and packs the other three
under ``additional_scores`` / ``additional_history``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from config import FRED_SCORE_LOOKBACK_DAYS, HISTORY_DAYS, INDUSTRY_PROVIDER_CACHE_TTL
from data.cache import get_cached, set_cached
from data.providers.fred_client import (
    direct_percentile_value,
    fetch_fred_series,
    inverse_percentile_value,
    normalize_series_direct,
    normalize_series_inverse,
)

logger = logging.getLogger(__name__)

# Daily aluminum futures (COMEX) scored against their own 2-year window,
# then blended as a minority nowcast so metals move between monthly IMF prints.
_ALUMINUM_FUTURES = "ALI=F"
_METALS_PROXY_WEIGHT = 0.30
_ALUMINUM_CACHE_KEY = "ali_futures_daily_v1"
_ALUMINUM_CACHE_TTL = 3600

# Aircraft new orders are lumpy (a single widebody order can 3x a month).
# Smooth before percentile ranking so one print does not pin the score.
_ORDERS_SMOOTH_MONTHS = 3

_PPI_SERIES_CANDIDATES = (
    "PCU336411336411",  # PPI: Aircraft manufacturing
    "PCU3364133641",    # PPI: Aerospace product and parts manufacturing
)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _fallback_meta(label: str, reason: str) -> dict:
    return {
        "source": "FRED",
        "raw_value": "—",
        "raw_label": label,
        "description": reason,
        "calculation": "Neutral default — source unavailable",
        "updated": _now_stamp(),
        "is_fallback": True,
    }


def _fetch_aluminum_futures() -> pd.Series:
    """Daily COMEX aluminum close via yfinance. Own 2-year window, own units."""
    cached = get_cached(_ALUMINUM_CACHE_KEY, ttl=_ALUMINUM_CACHE_TTL)
    if cached is not None:
        s = pd.Series(cached["values"], name=_ALUMINUM_FUTURES)
        s.index = pd.DatetimeIndex(cached["dates"])
        return s

    import yfinance as yf

    hist = yf.Ticker(_ALUMINUM_FUTURES).history(period="2y")
    if hist.empty:
        raise ValueError(f"yfinance returned no data for {_ALUMINUM_FUTURES}")

    closes = hist["Close"].astype(float)
    closes.index = pd.DatetimeIndex(closes.index.date)
    closes = closes.sort_index()
    set_cached(
        _ALUMINUM_CACHE_KEY,
        {
            "dates": [d.strftime("%Y-%m-%d") for d in closes.index],
            "values": closes.tolist(),
        },
    )
    return closes.rename(_ALUMINUM_FUTURES)


def _smooth_monthly(series: pd.Series, months: int) -> pd.Series:
    """Trailing mean on a monthly series; falls back to the raw series if short."""
    series = series.sort_index()
    if len(series) < months:
        return series
    return series.rolling(months, min_periods=months).mean().dropna()


def _score_metals() -> tuple[float, dict, pd.Series]:
    """Inverse-percentile blend of IMF aluminum and nickel prices."""
    alum = fetch_fred_series("PALUMUSDM")
    nickel = fetch_fred_series("PNICKUSDM")
    alum_score = inverse_percentile_value(float(alum.iloc[-1]), alum)
    nickel_score = inverse_percentile_value(float(nickel.iloc[-1]), nickel)
    fred_score = (alum_score + nickel_score) / 2.0

    alum_hist = normalize_series_inverse(alum)
    nickel_hist = normalize_series_inverse(nickel)
    idx = alum_hist.index.union(nickel_hist.index)
    fred_hist = pd.concat(
        [alum_hist.reindex(idx).ffill(), nickel_hist.reindex(idx).ffill()],
        axis=1,
    ).mean(axis=1)

    proxy_note = ""
    blend_weight = 0.0
    score = fred_score
    try:
        futures = _fetch_aluminum_futures()
        proxy_score = inverse_percentile_value(float(futures.iloc[-1]), futures)
        blend_weight = _METALS_PROXY_WEIGHT
        score = (1 - blend_weight) * fred_score + blend_weight * proxy_score
        proxy_hist = normalize_series_inverse(futures)
        aligned = fred_hist.index.union(proxy_hist.index)
        fred_hist = (
            (1 - blend_weight) * fred_hist.reindex(aligned).ffill()
            + blend_weight * proxy_hist.reindex(aligned).ffill()
        )
        proxy_note = (
            f" Blended with COMEX aluminum futures ({_ALUMINUM_FUTURES} "
            f"${float(futures.iloc[-1]):.0f}) at {blend_weight:.0%} weight "
            "so this category moves between monthly IMF prints."
        )
    except Exception as exc:
        logger.warning("Aluminum futures nowcast failed (using 100%% FRED metals): %s", exc)

    alum_val = float(alum.iloc[-1])
    nickel_val = float(nickel.iloc[-1])
    meta = {
        "source": (
            "FRED PALUMUSDM + PNICKUSDM + ALI=F"
            if blend_weight
            else "FRED PALUMUSDM + PNICKUSDM"
        ),
        "raw_value": f"${alum_val:,.0f} Al / ${nickel_val:,.0f} Ni",
        "raw_label": "Al & Ni (USD/mt)",
        "description": (
            f"IMF global aluminum is ${alum_val:,.0f}/metric ton and nickel is "
            f"${nickel_val:,.0f}/mt. Aerospace airframes and superalloys are "
            "aluminum- and nickel-intensive; this is a cost-pressure gauge, "
            f"not a demand gauge.{proxy_note}"
        ),
        "calculation": (
            "Score = average of two inverse percentiles (aluminum, nickel) "
            f"within the trailing {FRED_SCORE_LOOKBACK_DAYS}-day window"
            + (
                f", blended {blend_weight:.0%} with COMEX aluminum futures "
                "scored the same way against their own 2-year range"
                if blend_weight
                else ""
            )
            + ". Cheaper than most of the window = high score."
        ),
        "updated": _now_stamp(),
        "is_fallback": False,
    }
    return round(float(score), 1), meta, fred_hist.round(1).rename("aero_metals")


def _score_orders() -> tuple[float, dict, pd.Series]:
    """Direct percentile of 3-month-smoothed Census aircraft new orders."""
    raw = fetch_fred_series("ANAPNO")
    smoothed = _smooth_monthly(raw, _ORDERS_SMOOTH_MONTHS)
    latest = float(smoothed.iloc[-1])
    score = direct_percentile_value(latest, smoothed)
    history = normalize_series_direct(smoothed).rename("aero_orders")
    raw_latest = float(raw.iloc[-1])
    meta = {
        "source": "FRED ANAPNO (Census M3)",
        "raw_value": f"${raw_latest:,.0f}M",
        "raw_label": "Aircraft new orders",
        "description": (
            f"Census manufacturers' new orders for nondefense aircraft and parts "
            f"are ${raw_latest:,.0f} million this month "
            f"(${latest:,.0f}M as a {_ORDERS_SMOOTH_MONTHS}-month average). "
            "Higher order books read healthier. The average exists because a "
            "single widebody order can dominate one monthly print."
        ),
        "calculation": (
            f"Score = direct percentile of the {_ORDERS_SMOOTH_MONTHS}-month "
            f"average of ANAPNO within the trailing {FRED_SCORE_LOOKBACK_DAYS}-day "
            "window. Higher orders = higher score."
        ),
        "updated": _now_stamp(),
        "is_fallback": False,
    }
    return score, meta, history


def _score_production() -> tuple[float, dict, pd.Series]:
    """Direct percentile of Fed industrial production for NAICS 3364."""
    raw = fetch_fred_series("IPG3364S")
    latest = float(raw.iloc[-1])
    score = direct_percentile_value(latest, raw)
    history = normalize_series_direct(raw).rename("aero_production")
    meta = {
        "source": "FRED IPG3364S (Fed G.17)",
        "raw_value": f"{latest:.1f}",
        "raw_label": "Aero IP (2017=100)",
        "description": (
            f"Federal Reserve industrial production for aerospace product and "
            f"parts (NAICS 3364) is {latest:.1f} (index 2017=100). This measures "
            "real output at US aerospace plants, not orders or prices. Higher "
            "production reads healthier."
        ),
        "calculation": (
            f"Score = direct percentile of IPG3364S within the trailing "
            f"{FRED_SCORE_LOOKBACK_DAYS}-day window. Higher output = higher score."
        ),
        "updated": _now_stamp(),
        "is_fallback": False,
    }
    return score, meta, history


def _score_ppi() -> tuple[float, dict, pd.Series]:
    """Inverse percentile of aircraft manufacturing producer prices."""
    last_error: Exception | None = None
    raw = None
    series_id = _PPI_SERIES_CANDIDATES[0]
    for series_id in _PPI_SERIES_CANDIDATES:
        try:
            raw = fetch_fred_series(series_id)
            if raw is not None and not raw.empty:
                break
        except Exception as exc:
            last_error = exc
            logger.warning("Aerospace PPI series %s failed: %s", series_id, exc)
            raw = None
    if raw is None or raw.empty:
        raise last_error or ValueError("No aerospace PPI series available")

    latest = float(raw.iloc[-1])
    score = inverse_percentile_value(latest, raw)
    history = normalize_series_inverse(raw).rename("aero_ppi")
    meta = {
        "source": f"FRED {series_id} (BLS PPI)",
        "raw_value": f"{latest:.1f}",
        "raw_label": "Aircraft PPI",
        "description": (
            f"Producer Price Index for aircraft manufacturing ({series_id}) is "
            f"{latest:.1f}. This is a cost-pressure gauge: elevated producer "
            "prices squeeze airframe and engine supply chains. Cheaper than "
            "the trailing window reads healthier."
        ),
        "calculation": (
            f"Score = inverse percentile of {series_id} within the trailing "
            f"{FRED_SCORE_LOOKBACK_DAYS}-day window. Lower PPI = higher score."
        ),
        "updated": _now_stamp(),
        "is_fallback": False,
    }
    return score, meta, history


class AerospaceProvider:
    """Fetch all four aerospace category scores from FRED (+ optional yfinance)."""

    category: str = "aero_metals"

    def __init__(self) -> None:
        self._scores: dict[str, tuple[float, dict]] | None = None
        self._histories: dict[str, pd.Series] | None = None
        self._cache_time: datetime | None = None

    def _expired(self) -> bool:
        if self._scores is None or self._cache_time is None:
            return True
        age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
        return age >= INDUSTRY_PROVIDER_CACHE_TTL

    def _compute(self) -> None:
        if not self._expired():
            return

        scores: dict[str, tuple[float, dict]] = {}
        histories: dict[str, pd.Series] = {}
        fetchers = {
            "aero_metals": (_score_metals, "Metals cost pressure"),
            "aero_orders": (_score_orders, "Aircraft new orders"),
            "aero_production": (_score_production, "Aerospace production"),
            "aero_ppi": (_score_ppi, "Aircraft PPI"),
        }
        for key, (fn, label) in fetchers.items():
            try:
                score, meta, hist = fn()
                scores[key] = (float(score), meta)
                histories[key] = hist.tail(HISTORY_DAYS) if hist is not None else pd.Series(dtype=float)
            except Exception as exc:
                logger.error("Aerospace %s failed: %s", key, exc)
                scores[key] = (50.0, _fallback_meta(label, f"{label} unavailable: {exc}"))
                histories[key] = pd.Series(dtype=float, name=key)

        self._scores = scores
        self._histories = histories
        self._cache_time = datetime.now(timezone.utc)

    def fetch_all_current(self) -> dict[str, tuple[float, dict]]:
        self._compute()
        assert self._scores is not None
        return self._scores

    def fetch_all_history(self, days: int = HISTORY_DAYS) -> dict[str, pd.Series]:
        self._compute()
        assert self._histories is not None
        return {key: series.tail(days) for key, series in self._histories.items()}


_aero_instance: AerospaceProvider | None = None


def get_aerospace_provider() -> AerospaceProvider:
    """Singleton — one FRED/yfinance cache per process."""
    global _aero_instance
    if _aero_instance is None:
        _aero_instance = AerospaceProvider()
    return _aero_instance


class AeroMetalsProvider:
    """Adapter: metals is the primary category; other three ride in metadata."""

    category: str = "aero_metals"

    def fetch_current(self) -> tuple[float, dict]:
        provider = get_aerospace_provider()
        all_scores = provider.fetch_all_current()
        primary_score, primary_meta = all_scores["aero_metals"]
        additional = {
            key: all_scores[key]
            for key in ("aero_orders", "aero_production", "aero_ppi")
            if key in all_scores
        }
        primary_meta = dict(primary_meta)
        primary_meta["additional_scores"] = additional
        additional_history = {
            key: hist
            for key, hist in provider.fetch_all_history().items()
            if key != "aero_metals"
        }
        primary_meta["additional_history"] = additional_history
        return primary_score, primary_meta

    def fetch_history(self, days: int) -> pd.Series:
        histories = get_aerospace_provider().fetch_all_history(days)
        hist = histories.get("aero_metals")
        if hist is None or hist.empty:
            today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
            score, _ = get_aerospace_provider().fetch_all_current().get(
                "aero_metals", (50.0, {})
            )
            return pd.Series([float(score)], index=[today], name="aero_metals")
        return hist
