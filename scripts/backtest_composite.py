"""
Backtest the methodology v2 composite at past episodes.

    DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/backtest_composite.py

Each category's ``fetch_history`` is read over a window long enough to reach the first
episode, then looked up on each episode date (dated by publication lag, so the value is what
the site could have shown that day). "n/a" means the source had no measurement that day
(chokepoints start in 2022, physical about 2024, TPU daily 2015+, and so on). The last column
is today, from each provider's ``fetch_current``.

Two composites are printed:
  composite             all eight weighted categories present, the real index definition
  composite (available) the categories that exist that day with their weights renormalized
                        to sum to 1. NOT the index; shown only to see how a partial set reads.

A second section prints each sector index (Semis, Aero) at its own episodes. A sector index is
the equal-weight mean of the sector categories present that day, and "n/a" when fewer than the
sector's ``min_categories`` are present. Sector history is dated by publication lag too, so an
episode month is looked up on the first day all of that month's inputs were public (month end
plus the slowest input's lag), which is the value the research targets describe.

The runtime FRED windows in config are trimmed for production, so this script widens them for
the run and restores them afterwards. Both tables are also
saved to data/backups/backtest_<date>.txt. BOJ series come from the 24 h cache in
``data/sources/boj.py``, so the run asks BOJ at most once per series.

No score or history rows are written, but ``PhysicalProvider.fetch_current`` records a Kaub
gauge reading in the database. So the script refuses to run unless the resolved database is
SQLite (the local dev file): run it with ``DATABASE_URL=`` set empty.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from data import database  # noqa: E402
from scoring.engine import compute_composite_index, renormalized_weights  # noqa: E402

logger = logging.getLogger("backtest_composite")

BACKUP_DIR = ROOT / "data" / "backups"
EPISODES: list[tuple[date, str]] = [
    (date(2008, 7, 15), "2008-07-15"),
    (date(2020, 4, 15), "2020-04-15"),
    (date(2021, 3, 29), "2021-03-29"),
    (date(2021, 12, 15), "2021-12-15"),
    (date(2024, 2, 15), "2024-02-15"),
    (date(2025, 4, 15), "2025-04-15"),
    (date(2026, 3, 20), "2026-03-20"),
]
# Lead-in before the first episode so lagged monthly series and year-over-year bases exist.
LEAD_IN_DAYS = 60
# Config lookbacks that trim the runtime FRED reads; widened so fetch_history reaches 2008.
FRED_WINDOWS = ("ENERGY_FRED_LOOKBACK_DAYS", "INPUTS_FRED_LOOKBACK_DAYS",
                "FREIGHT_FRED_LOOKBACK_DAYS", "TARIFFS_FRED_LOOKBACK_DAYS",
                "SEMIS_FRED_LOOKBACK_DAYS", "AERO_FRED_LOOKBACK_DAYS")
WIDE_FRED_DAYS = 80 * 365

# Sector episodes: (year, month) of the reading. The lookup date is the first day every input
# for that month was public: month end plus the slowest publication lag among the lag keys the
# sector's own providers declare (so a provider change moves the dates with it).
SECTOR_EPISODE_MONTHS: dict[str, list[tuple[int, int]]] = {
    "semiconductor": [(2021, 6), (2021, 12), (2022, 6), (2023, 3), (2024, 6)],
    "aerospace": [(2019, 6), (2020, 6), (2022, 6), (2023, 9), (2024, 10)],
}


def provider_lag_keys(provider) -> set[str]:
    """The PUBLICATION_LAG_DAYS keys a sector provider reads: its own ``lag_key`` (Semis) or one
    per input (Aero)."""
    if getattr(provider, "inputs", ()):
        return {spec.lag_key for spec in provider.inputs}
    return {provider.lag_key}


def sector_episodes(sector: str, providers: dict | None = None) -> list[tuple[date, str]]:
    """(lookup date, label) per episode month: month end plus the sector's slowest publication lag."""
    providers = providers if providers is not None else default_providers()
    keys = set().union(*(provider_lag_keys(providers[cat]) for cat in config.SECTORS[sector]["weights"]))
    lag = max(config.PUBLICATION_LAG_DAYS[k] for k in keys)
    out = []
    for year, month in SECTOR_EPISODE_MONTHS[sector]:
        month_end = (date(year + month // 12, month % 12 + 1, 1)) - timedelta(days=1)
        out.append((month_end + timedelta(days=lag), f"{year}-{month:02d}"))
    return out


@contextmanager
def widened_fred_windows(names=FRED_WINDOWS, days: int = WIDE_FRED_DAYS):
    """Raise the runtime FRED lookbacks inside the block and always restore them."""
    saved = {name: getattr(config, name) for name in names}
    try:
        for name in names:
            setattr(config, name, days)
        yield
    finally:
        for name, value in saved.items():
            setattr(config, name, value)


def _finite(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def lookup(series: pd.Series | None, day: date) -> float | None:
    """The series value on ``day`` or None when it has no measurement then."""
    if series is None or series.empty:
        return None
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    s = pd.Series(pd.to_numeric(series, errors="coerce").to_numpy(), index=idx.normalize())
    s = s[~s.index.duplicated(keep="last")]
    stamp = pd.Timestamp(day)
    return _finite(s.get(stamp)) if stamp in s.index else None


def composites(scores: dict[str, float | None]) -> tuple[float | None, float | None, int]:
    """(full composite or None, renormalized composite over what exists or None, categories present)."""
    present = {cat: v for cat, v in scores.items() if v is not None and cat in config.CATEGORY_WEIGHTS}
    if not present:
        return None, None, 0
    full = compute_composite_index(present) if len(present) == len(config.CATEGORY_WEIGHTS) else None
    weights = renormalized_weights(config.CATEGORY_WEIGHTS, set(present))
    return full, compute_composite_index(present, weights), len(present)


def sector_index(scores: dict[str, float | None], sector: str) -> tuple[float | None, int]:
    """(sector index or None below the coverage minimum, categories present).

    The index is the mean of the present sector categories with the sector weights renormalized
    over them, the same rule the aggregator applies.
    """
    spec = config.SECTORS[sector]
    present = {cat: v for cat, v in scores.items() if v is not None and cat in spec["weights"]}
    if not present or len(present) < spec["min_categories"]:
        return None, len(present)
    weights = renormalized_weights(spec["weights"], set(present))
    return float(sum(weights[cat] * v for cat, v in present.items())), len(present)


def default_providers() -> dict:
    from scripts.rebuild_category_history import default_providers as providers
    return providers()


def collect(providers: dict, today: date, episodes=EPISODES,
            categories=None) -> tuple[list[str], dict[str, dict[str, float | None]]]:
    """Scores per column label per category: episode dates plus today.

    ``categories`` defaults to the global weighted categories; pass a sector's categories with
    that sector's episodes for a sector table.
    """
    categories = list(config.CATEGORY_WEIGHTS if categories is None else categories)
    first = min(d for d, _ in episodes)
    days = (today - first).days + LEAD_IN_DAYS
    labels = [label for _, label in episodes] + [f"today {today.isoformat()}"]
    table: dict[str, dict[str, float | None]] = {label: {} for label in labels}
    for cat in categories:
        provider = providers[cat]
        started = time.monotonic()
        try:
            history = provider.fetch_history(days)
        except Exception as exc:
            logger.warning("%s: history unavailable: %s", cat, exc)
            history = None
        for d, label in episodes:
            table[label][cat] = lookup(history, d)
        try:
            score, _ = provider.fetch_current()
            table[labels[-1]][cat] = _finite(score)
        except Exception as exc:
            logger.warning("%s: fetch_current failed: %s", cat, exc)
            table[labels[-1]][cat] = None
        logger.info("%s done in %.1fs", cat, time.monotonic() - started)
    return labels, table


def render(labels: list[str], table: dict[str, dict[str, float | None]],
           sector: str | None = None, episodes=None) -> str:
    """The global table, or with ``sector`` that sector's table (``episodes`` are its lookup dates)."""
    spec = config.SECTORS[sector] if sector else None
    weights = spec["weights"] if spec else config.CATEGORY_WEIGHTS
    width = max(len(label) for label in labels) + 2
    head = f"{'':<28}" + "".join(f"{label:>{width}}" for label in labels)
    cell = lambda v: "n/a" if v is None else f"{v:.1f}"  # noqa: E731
    row = lambda name, values: f"{name:<28}" + "".join(f"{v:>{width}}" for v in values)  # noqa: E731
    lines = ([f"{spec['title']} index"] if spec else []) + [head, "-" * len(head)]
    for cat, weight in weights.items():
        lines.append(row(f"{cat} ({weight:.0%})", [cell(table[label][cat]) for label in labels]))
    lines.append("-" * len(head))
    if spec:
        results = {label: sector_index(table[label], sector) for label in labels}
        lines.append(row(f"{spec['label']} index", [cell(results[label][0]) for label in labels]))
        lines.append(row("categories present", [results[label][1] for label in labels]))
        lines.append(f"{spec['label']} index: mean of the categories present; n/a below {spec['min_categories']} of "
                     f"{len(weights)}. Episode months are read on the first day all their inputs were public: "
                     + ", ".join(f"{label} on {d.isoformat()}" for d, label in episodes or []) + ".")
        return "\n".join(lines)
    results = {label: composites(table[label]) for label in labels}
    lines.append(row("composite (all 8)", [cell(results[label][0]) for label in labels]))
    lines.append(row("categories present", [results[label][2] for label in labels]))
    lines.append(row("composite (available, renorm.)", [cell(results[label][1]) for label in labels]))
    lines.append("")
    lines.append("composite (all 8): the index as defined; n/a when any category has no measurement that day.")
    lines.append("composite (available, renorm.): NOT the index. Categories that exist that day, weights "
                 "rescaled to sum to 1, so columns with fewer categories are not comparable with each other.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-save", action="store_true", help="print only; do not write data/backups/backtest_<date>.txt")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if database.get_db_type() != "sqlite":
        logger.error("Refusing to run: the resolved database is %s and fetch_current records a "
                     "gauge reading in it. Run with DATABASE_URL= (empty) to use the local SQLite file.",
                     database.get_db_type())
        return 2

    today = datetime.now(timezone.utc).date()
    providers = default_providers()
    with widened_fred_windows():
        labels, table = collect(providers, today)
        sector_tables = {}
        for sector in config.SECTORS:
            episodes = sector_episodes(sector, providers)
            sector_tables[sector] = (episodes, *collect(
                providers, today, episodes, config.SECTORS[sector]["weights"]))
    text = "\n\n".join([render(labels, table)]
                        + [render(sector_labels, sector_table, sector, episodes)
                           for sector, (episodes, sector_labels, sector_table) in sector_tables.items()])
    print(text)
    if not args.no_save:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        out = BACKUP_DIR / f"backtest_{today.isoformat()}.txt"
        out.write_text(text + "\n")
        print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
