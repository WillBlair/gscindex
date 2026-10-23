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

The runtime FRED windows in config are trimmed for production, so this script widens them for
the run and restores them afterwards. Nothing is written to a database. The table is also
saved to data/backups/backtest_<date>.txt.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
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
                "FREIGHT_FRED_LOOKBACK_DAYS", "TARIFFS_FRED_LOOKBACK_DAYS")
WIDE_FRED_DAYS = 80 * 365


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


def default_providers() -> dict:
    from scripts.rebuild_category_history import default_providers as providers
    return providers()


def collect(providers: dict, today: date, episodes=EPISODES) -> tuple[list[str], dict[str, dict[str, float | None]]]:
    """Scores per column label per category: episode dates plus today."""
    first = min(d for d, _ in episodes)
    days = (today - first).days + LEAD_IN_DAYS
    labels = [label for _, label in episodes] + [f"today {today.isoformat()}"]
    table: dict[str, dict[str, float | None]] = {label: {} for label in labels}
    for cat in config.CATEGORY_WEIGHTS:
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


def render(labels: list[str], table: dict[str, dict[str, float | None]]) -> str:
    cats = list(config.CATEGORY_WEIGHTS)
    width = max(len(label) for label in labels) + 2
    head = f"{'':<28}" + "".join(f"{label:>{width}}" for label in labels)
    cell = lambda v: "n/a" if v is None else f"{v:.1f}"  # noqa: E731
    lines = [head, "-" * len(head)]
    for cat in cats:
        lines.append(f"{cat + f' ({config.CATEGORY_WEIGHTS[cat]:.0%})':<28}"
                     + "".join(f"{cell(table[l][cat]):>{width}}" for l in labels))
    lines.append("-" * len(head))
    results = {label: composites(table[label]) for label in labels}
    lines.append(f"{'composite (all 8)':<28}" + "".join(f"{cell(results[l][0]):>{width}}" for l in labels))
    lines.append(f"{'categories present':<28}" + "".join(f"{results[l][2]:>{width}}" for l in labels))
    lines.append(f"{'composite (available, renorm.)':<28}"
                 + "".join(f"{cell(results[l][1]):>{width}}" for l in labels))
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

    today = datetime.now(timezone.utc).date()
    with widened_fred_windows():
        labels, table = collect(default_providers(), today)
    text = render(labels, table)
    print(text)
    if not args.no_save:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        out = BACKUP_DIR / f"backtest_{today.isoformat()}.txt"
        out.write_text(text + "\n")
        print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
