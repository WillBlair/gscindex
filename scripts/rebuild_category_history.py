"""
Rebuild the stored daily category scores with the new methodology (v2).

    DATABASE_URL= GSC_DISABLE_BACKGROUND=1 venv/bin/python scripts/rebuild_category_history.py
    ... scripts/rebuild_category_history.py --days 92 --write
    ... scripts/rebuild_category_history.py --sectors-only --days 92 --write   (the sector backfill)

For each weighted category, and for each sector category (the three Semis and four Aero
categories in ``config.SECTORS``), the provider's own ``fetch_history`` supplies the real
source-series scores, dated by publication lag (NaN where nothing was measured). The rebuild
covers the ``--days`` dates ending yesterday (UTC); today's row belongs to the live
aggregator. The composite for a date is the weighted composite of the eight global categories
and is written only when every one has a value that day, otherwise that date keeps a gap.
Sector categories feed no composite: ``daily_scores`` is the global index only, and a sector
index is computed from its category rows when it is shown. The register (``geo_register``)
and the retired industry categories (``chip_*``, ``aero_metals`` and the like) are not touched.

``--sectors-only`` covers the seven sector categories alone: no global category is fetched or
written and no ``daily_scores`` composite row is written, so the live-recorded global history
stays exactly as it is. The backup, the COUNT check and the partial-write refusal then cover the
sector rows only. The sector backfill uses this flag.

Default is a dry run: it reads the current rows, writes
``data/backups/rebuild_dryrun_<date>.csv`` (``rebuild_dryrun_sectors_<date>.csv`` with
``--sectors-only``; columns date, category, old, new) and prints a summary.
Nothing is written to the database.

``--write`` first exports the existing rows it will overwrite to
``data/backups/category_scores_pre_v2_<date>_<HHMMSS>.csv`` (a new file each run, never
overwritten), checks the export against a COUNT of the rows in the database, then upserts.
It aborts if the export fails or does not match. It never deletes and never writes NaN.
It refuses when any rebuilt category (global or sector; sector only with ``--sectors-only``) failed
to fetch, or has no value in the window, unless ``--allow-partial`` is passed, and when
the resolved database is Postgres unless the environment variable ``CONFIRM_PROD_REBUILD=yes``
is set.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from data import database  # noqa: E402
from scoring.engine import compute_composite_index  # noqa: E402

logger = logging.getLogger("rebuild_category_history")

BACKUP_DIR = ROOT / "data" / "backups"
DEFAULT_DAYS = 92
EXTRA_FETCH_DAYS = 30           # asked of each provider beyond the kept window
CONFIRM_ENV = "CONFIRM_PROD_REBUILD"
COMPOSITE = "composite"


class WriteRefused(RuntimeError):
    """``--write`` refused: Postgres without the confirmation variable, or a failed category."""


class BackupError(RuntimeError):
    """The pre-rebuild export could not be made or verified, so nothing was written."""


def rebuild_categories(sectors_only: bool = False) -> tuple[str, ...]:
    """Every category the rebuild covers: the global weighted ones, then each sector's.
    With ``sectors_only``, the sector categories alone."""
    sector = tuple(cat for spec in config.SECTORS.values() for cat in spec["weights"])
    return sector if sectors_only else (*config.CATEGORY_WEIGHTS, *sector)


def default_providers() -> dict:
    """One instance of each rebuilt category's provider (global and sector), keyed by category."""
    from data.providers.chokepoints import ChokepointsProvider
    from data.providers.energy import EnergyProvider
    from data.providers.freight import FreightProvider
    from data.providers.geopolitical import GeopoliticalProvider
    from data.providers.inputs import InputsProvider
    from data.providers.physical import PhysicalProvider
    from data.providers.aero import FlowProvider, ForgeCastProvider, MillPricesProvider, ThroughputProvider
    from data.providers.semis import FabUtilizationProvider, LogicPricesProvider, MemoryPricesProvider
    from data.providers.supply_chain import SupplyChainProvider
    from data.providers.tariffs import TariffsProvider

    providers = {p.category: p for p in (
        SupplyChainProvider(), ChokepointsProvider(), EnergyProvider(), TariffsProvider(),
        GeopoliticalProvider(), FreightProvider(), InputsProvider(), PhysicalProvider(),
        MemoryPricesProvider(), LogicPricesProvider(), FabUtilizationProvider(),
        ThroughputProvider(), FlowProvider(), MillPricesProvider(), ForgeCastProvider())}
    missing = set(rebuild_categories()) - set(providers)
    if missing:
        raise RuntimeError(f"no provider for rebuilt categories: {sorted(missing)}")
    return providers


def check_write_allowed(write: bool = True) -> None:
    """Raise WriteRefused for a write against Postgres unless CONFIRM_PROD_REBUILD=yes."""
    if write and database.get_db_type() == "postgres" and os.environ.get(CONFIRM_ENV) != "yes":
        raise WriteRefused(
            f"Refusing --write: the database is Postgres. Set {CONFIRM_ENV}=yes to confirm a "
            "production rebuild (only after the dry-run CSV has been reviewed).")


@dataclass
class RebuildResult:
    dates: list[date]
    old: dict[tuple[date, str], float]
    new: dict[str, pd.Series]                 # category -> scores indexed by date (NaN = not measured)
    composite: dict[date, float]
    dates_without_composite: list[date]
    csv_path: Path | None = None
    backup_path: Path | None = None
    written: int = 0
    failed_categories: dict[str, str] = field(default_factory=dict)
    sectors_only: bool = False

    @property
    def categories(self) -> tuple[str, ...]:
        return rebuild_categories(self.sectors_only)

    @property
    def keys(self) -> tuple[str, ...]:
        """The stored keys this run covers: its categories, plus the composite unless sectors only."""
        return self.categories if self.sectors_only else (*self.categories, COMPOSITE)

    def category_rows(self) -> list[tuple[date, str, float]]:
        return [(d, cat, float(v)) for cat, s in self.new.items() for d, v in s.items() if math.isfinite(v)]

    def composite_rows(self) -> list[tuple[date, float]]:
        return sorted(self.composite.items())


def _window(days: int, today: date) -> list[date]:
    """The ``days`` dates ending yesterday, ascending."""
    return [today - timedelta(days=n) for n in range(days, 0, -1)]


def _history_on(series: pd.Series, dates: list[date]) -> pd.Series:
    """A provider history as floats on exactly ``dates`` (NaN where it has no value)."""
    s = pd.to_numeric(pd.Series(series), errors="coerce").replace([np.inf, -np.inf], np.nan)
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")]
    out = s.reindex(pd.DatetimeIndex(dates))
    out.index = list(dates)
    return out.astype(float)


def build_new_scores(providers: dict, days: int, today: date,
                     sectors_only: bool = False) -> tuple[dict[str, pd.Series], dict[str, str]]:
    """Each rebuilt category's (global and sector, or sector only) scores on the window, and why
    any category failed.

    A history with no finite value inside the window counts as failed, the same as a raise:
    writing the other categories alone would leave mixed-method rows.
    """
    dates = _window(days, today)
    new: dict[str, pd.Series] = {}
    failed: dict[str, str] = {}
    for cat in rebuild_categories(sectors_only):
        try:
            history = providers[cat].fetch_history(days + EXTRA_FETCH_DAYS)
            new[cat] = _history_on(history, dates)
            if not new[cat].notna().any():
                failed[cat] = f"no finite values in the rebuild window ({dates[0]} to {dates[-1]})"
        except Exception as exc:
            logger.warning("%s history unavailable: %s", cat, exc)
            failed[cat] = f"{type(exc).__name__}: {exc}"
            new[cat] = pd.Series(np.nan, index=list(dates), dtype=float)
        logger.info("%s: %d of %d dates have a value", cat, int(new[cat].notna().sum()), len(dates))
    return new, failed


def compute_composites(new: dict[str, pd.Series], dates: list[date]) -> dict[date, float]:
    """The composite on each date where every weighted category has a finite value."""
    out: dict[date, float] = {}
    for d in dates:
        scores = {cat: new[cat].get(d, float("nan")) for cat in config.CATEGORY_WEIGHTS}
        if all(math.isfinite(v) for v in scores.values()):
            out[d] = compute_composite_index(scores)
    return out


def _fmt(value) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.4f}".rstrip("0").rstrip(".")


def write_dryrun_csv(result: RebuildResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "category", "old", "new"])
        for d in result.dates:
            for cat in result.keys:
                old = result.old.get((d, cat))
                new = result.composite.get(d) if cat == COMPOSITE else result.new[cat].get(d)
                if old is None and (new is None or not math.isfinite(new)):
                    continue
                writer.writerow([d.isoformat(), cat, _fmt(old), _fmt(new)])


def write_backup_csv(rows: list[tuple], path: Path) -> None:
    """Write the pre-rebuild rows. Mode "x": an existing backup is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "category", "score"])
        for d, cat, score in rows:
            writer.writerow([d.isoformat(), cat, repr(float(score))])


def run(days: int = DEFAULT_DAYS, write: bool = False, providers: dict | None = None,
        today: date | None = None, backup_dir: Path | None = None,
        allow_partial: bool = False, now: datetime | None = None,
        sectors_only: bool = False) -> RebuildResult:
    check_write_allowed(write)
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    backup_dir = Path(backup_dir) if backup_dir is not None else BACKUP_DIR
    providers = providers if providers is not None else default_providers()

    dates = _window(days, today)
    new, failed = build_new_scores(providers, days, today, sectors_only)
    if write and failed and not allow_partial:
        raise WriteRefused(
            f"Refusing --write: {', '.join(sorted(failed))} failed to fetch or returned no values in "
            "the window, so the rebuild would be partial and leave mixed-method rows. Fix the source, "
            "or pass --allow-partial to write the categories that did load.")
    composite = {} if sectors_only else compute_composites(new, dates)

    if write and database.get_db_type() == "sqlite":
        database.init_db()              # a fresh dev database has no tables yet
    keys = rebuild_categories(sectors_only) if sectors_only else (*rebuild_categories(), COMPOSITE)
    # On the write path the read is strict: a query error must abort, never yield an empty backup.
    try:
        stored = database.export_category_rows(dates[0], list(keys), strict=write)
    except Exception as exc:
        if not write:
            raise
        raise BackupError(f"Could not read the existing rows for the backup ({exc}). Nothing was written.") from exc
    in_window = set(dates)
    old = {(d, cat): score for d, cat, score in stored if d in in_window}

    result = RebuildResult(
        dates=dates, old=old, new=new, composite=composite,
        dates_without_composite=[] if sectors_only else [d for d in dates if d not in composite],
        failed_categories=failed, sectors_only=sectors_only)
    scope = "sectors_" if sectors_only else ""
    result.csv_path = backup_dir / f"rebuild_dryrun_{scope}{today.isoformat()}.csv"
    write_dryrun_csv(result, result.csv_path)

    if write:
        cat_rows, comp_rows = result.category_rows(), result.composite_rows()
        touched = {(d, cat) for d, cat, _ in cat_rows} | {(d, COMPOSITE) for d, _ in comp_rows}
        existing = [r for r in stored if (r[0], r[1]) in touched]
        in_db = database.count_existing_rows(sorted(touched))
        if in_db != len(existing):
            raise BackupError(
                f"Backup check failed: {len(existing)} rows exported but the database holds {in_db} "
                "for the rows about to be overwritten. Nothing was written.")
        result.backup_path = backup_dir / f"category_scores_pre_v2_{now:%Y-%m-%d_%H%M%S}.csv"
        try:
            write_backup_csv(existing, result.backup_path)
        except OSError as exc:
            raise BackupError(f"Could not write the backup {result.backup_path} ({exc}). Nothing was written.") from exc
        logger.info("Exported %d existing rows to %s", len(existing), result.backup_path)
        n_cat = database.upsert_scores_for_dates(cat_rows)
        n_comp = 0 if sectors_only else database.upsert_composite_for_dates(comp_rows)
        if n_cat < 0 or n_comp < 0:
            raise RuntimeError("database upsert failed; see the log (the backup CSV was written first)")
        result.written = n_cat + n_comp
    return result


def summarize(result: RebuildResult) -> str:
    lines = [f"Window: {result.dates[0]} to {result.dates[-1]} ({len(result.dates)} dates, today excluded)"]
    lines.append(f"{'category':<24}{'new rows':>9}{'no old':>8}{'changed':>9}{'mean |delta|':>14}")
    total_new = total_changed = 0
    for cat in result.keys:
        series = (pd.Series(result.composite).reindex(result.dates) if cat == COMPOSITE
                  else result.new[cat])
        new_rows = no_old = changed = 0
        deltas = []
        for d in result.dates:
            v = series.get(d, float("nan"))
            if not math.isfinite(v):
                continue
            new_rows += 1
            old = result.old.get((d, cat))
            if old is None:
                no_old += 1
            else:
                deltas.append(abs(v - old))
                if abs(v - old) >= 0.05:
                    changed += 1
        total_new += new_rows
        total_changed += changed + no_old
        mean = f"{sum(deltas) / len(deltas):.2f}" if deltas else "n/a"
        lines.append(f"{cat:<24}{new_rows:>9}{no_old:>8}{changed:>9}{mean:>14}")
    if result.sectors_only:
        lines.append("(--sectors-only: the global category rows and daily_scores are not touched)")
    else:
        lines.append("(composite is the global index only; the sector indexes have no stored rows of their own)")
    lines.append(f"Rows that would be written: {total_new}; of those, new or changed by 0.05+ points: {total_changed}")
    for cat, why in result.failed_categories.items():
        lines.append(f"FAILED {cat}: {why}")
    if not result.sectors_only:
        gaps = result.dates_without_composite
        lines.append(f"Dates without a composite: {len(gaps)} of {len(result.dates)}"
                     + (f" ({gaps[0]} to {gaps[-1]})" if gaps else ""))
    unmatched = sum(1 for (d, cat) in result.old
                    if cat != COMPOSITE and not math.isfinite(result.new[cat].get(d, float("nan"))))
    unmatched += sum(1 for (d, cat) in result.old if cat == COMPOSITE and d not in result.composite)
    lines.append(f"Stored rows left as they are (no new value for that date, never deleted): {unmatched}")
    return "\n".join(lines)


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=_positive_int, default=DEFAULT_DAYS,
                        help="dates to rebuild, ending yesterday (default 92, at least 1)")
    parser.add_argument("--write", action="store_true", help="upsert the rebuilt rows (default is a dry run)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="with --write, proceed even if some category failed to fetch")
    parser.add_argument("--sectors-only", action="store_true",
                        help="rebuild the sector categories only; global category and composite rows "
                             "are not touched (use this for the sector backfill)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        result = run(days=args.days, write=args.write, allow_partial=args.allow_partial,
                     sectors_only=args.sectors_only)
    except (WriteRefused, BackupError) as exc:
        logger.error("%s", exc)
        return 2
    print(summarize(result))
    print(f"CSV: {result.csv_path}")
    if args.write:
        print(f"Backup of overwritten rows: {result.backup_path}")
        print(f"Rows upserted: {result.written}")
    else:
        print("Dry run: nothing was written. Re-run with --write after reviewing the CSV.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
