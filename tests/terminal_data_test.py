"""Tests for the stored daily history that feeds the Terminal redesign."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import config
import data.database as database
from components import terminal_data as td


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Point the database layer at a throwaway SQLite file (never production)."""
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("sqlite", None))
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "terminal.db"))
    database.init_db()
    return database.SQLITE_PATH


def _insert(path, day, category, score):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO daily_category_scores (date, category, score) VALUES (?, ?, ?)",
        (day.isoformat(), category, score),
    )
    conn.commit()
    conn.close()


def test_daily_scores_align_and_mark_missing_days(sqlite_db):
    today = datetime.now(timezone.utc).date()
    _insert(sqlite_db, today - timedelta(days=2), "energy", 61.5)
    _insert(sqlite_db, today, "energy", 64.0)

    result = database.get_daily_category_scores(91)

    series = result["scores"]["energy"]
    assert len(result["dates"]) == len(series)
    assert result["dates"] == sorted(result["dates"])
    assert result["dates"][-1] == today.isoformat()
    assert series[-3] == 61.5
    assert series[-2] is None
    assert series[-1] == 64.0


def test_daily_scores_empty_without_db(monkeypatch):
    monkeypatch.setattr(database, "_resolve_db_config", lambda: ("none", None))

    assert database.get_daily_category_scores(91) == {"dates": [], "scores": {}}


# --- Terminal view math (no database; snapshots are built by hand) ----------

BASELINE = config.CATEGORY_WEIGHTS
ALL_CATS = set(config.CATEGORY_WEIGHTS) | {c for s in config.SECTORS.values() for c in s["weights"]}


def _snapshot(with_history=True):
    """Two stored days (yesterday and today) for every global and sector category."""
    cats = ALL_CATS
    snap = {
        "last_updated_utc": "2026-10-22T20:04:45Z",
        "current_scores": {c: 70.0 + i for i, c in enumerate(sorted(cats))},
        "category_metadata": {
            c: {
                "source": f"{c} source", "raw_value": 1.5, "raw_label": "raw",
                "updated": "2026-10-22", "description": "desc", "calculation": "calc",
            }
            for c in cats
        },
        "fallback_categories": [],
    }
    if with_history:
        dates = [(date(2026, 10, 22) - timedelta(days=n)).isoformat() for n in range(91, -1, -1)]
        scores = {}
        for i, c in enumerate(sorted(cats)):
            series = [None] * len(dates)
            series[-2] = 60.0 + i  # yesterday
            series[-1] = None      # today is read before the hourly write
            series[-3] = 55.0 + i
            scores[c] = series
        snap["daily_history"] = {"dates": dates, "scores": scores}
    return snap


def test_index_row_equals_weighted_rows():
    snap = _snapshot()
    rows = td.category_rows(snap, "global")
    summary = td.index_summary(snap, "global")

    assert summary["today"] == pytest.approx(sum(r["weight"] * r["today"] for r in rows))
    assert summary["yday"] == pytest.approx(sum(r["weight"] * r["yday"] for r in rows))
    assert summary["change"] == pytest.approx(summary["today"] - summary["yday"])
    assert summary["tier"] == td.tier_for(summary["today"])
    assert [r["weight"] for r in rows] == sorted((r["weight"] for r in rows), reverse=True)
    for r in rows:
        assert r["change"] == pytest.approx(r["today"] - r["yday"])
        assert r["effect"] == pytest.approx(r["change"] * r["weight"])
        assert r["label"] == config.CATEGORY_LABELS[r["cat"]]
        assert r["source"] == f"{r['cat']} source"
        assert r["raw_value"] == 1.5 and r["calculation"] == "calc"


def test_missing_yesterday_blanks_row_and_index_change():
    snap = _snapshot()
    snap["daily_history"]["scores"]["tariffs"][-2] = None

    rows = {r["cat"]: r for r in td.category_rows(snap, "global")}
    assert rows["tariffs"]["yday"] is None
    assert rows["tariffs"]["change"] is None
    assert rows["tariffs"]["effect"] is None
    assert rows["tariffs"]["today"] == snap["current_scores"]["tariffs"]
    for cat, row in rows.items():
        if cat != "tariffs":
            assert isinstance(row["yday"], float)
            assert isinstance(row["change"], float)
            assert isinstance(row["effect"], float)

    summary = td.index_summary(snap, "global")
    assert summary["yday"] is None
    assert summary["change"] is None
    assert isinstance(summary["today"], float)


def test_tabs_use_their_own_weights():
    snap = _snapshot()
    rows = td.category_rows(snap, "semiconductor")
    expected = config.SECTORS["semiconductor"]["weights"]
    assert {r["cat"]: r["weight"] for r in rows} == expected
    assert {r["cat"]: r["weight"] for r in td.category_rows(snap, "global")} == config.CATEGORY_WEIGHTS


def test_snapshot_without_daily_history_renders_dashes():
    snap = _snapshot(with_history=False)
    rows = td.category_rows(snap, "global")
    assert rows
    for r in rows:
        assert r["yday"] is None and r["change"] is None and r["effect"] is None
        assert r["history"] == [None] * 29 + [r["today"]]
    summary = td.index_summary(snap, "global")
    assert summary["yday"] is None and summary["change"] is None
    assert td.index_history(snap, "global", 7) == [None] * 6 + [summary["today"]]


def test_fallback_flag():
    snap = _snapshot()
    snap["fallback_categories"] = ["energy"]
    rows = {r["cat"]: r for r in td.category_rows(snap, "global")}
    assert rows["energy"]["is_fallback"] is True
    assert rows["physical"]["is_fallback"] is False


def test_tier_colors_are_ui_only():
    assert td.tier_for(85)["color"] == "#35D07F"
    assert config.HEALTH_TIERS[0]["color"] == "#3d9b6e"
    assert td.tier_for(85)["label"] == "Healthy"
    assert td.tier_for(79.9)["label"] == "Stable"
    assert td.tier_for(60)["label"] == "Stable"
    assert td.tier_for(59.9)["label"] == "Stressed"
    assert td.tier_for(40)["label"] == "Stressed"
    assert td.tier_for(12)["label"] == "Critical"
    assert td.tier_for(12)["color"] == "#FF4D5E"


def test_today_is_always_live_and_yesterday_is_utc_date_minus_one():
    snap = _snapshot()
    # Stale axis: history ends two days before the snapshot date; yesterday is a gap.
    snap["daily_history"]["dates"] = [
        (date(2026, 10, 20) - timedelta(days=n)).isoformat() for n in range(91, -1, -1)
    ]
    for series in snap["daily_history"]["scores"].values():
        series[-1] = 33.0  # 2026-10-20
    rows = td.category_rows(snap, "global")
    assert all(r["yday"] is None for r in rows)
    assert all(r["history"][-1] == r["today"] for r in rows)


def _march_snapshot(last_updated, stored_days=range(1, 17)):
    """Stored value for every category on 2026-03-DD is DD (far from the real date)."""
    snap = _snapshot(with_history=False)
    snap["last_updated_utc"] = last_updated
    days = list(stored_days)
    snap["daily_history"] = {
        "dates": [f"2026-03-{d:02d}" for d in days],
        "scores": {c: [float(d) for d in days] for c in snap["current_scores"]},
    }
    return snap


@pytest.mark.parametrize(
    "last_updated, expected_yday",
    [
        ("2026-03-14T20:04:45Z", 13.0),            # Z suffix
        ("2026-03-14T23:30:00-07:00", 14.0),       # UTC date is already the 15th
        ("2026-03-14T01:30:00+05:00", 12.0),       # UTC date is still the 13th
        ("2026-03-14T20:04:45", 13.0),             # naive timestamp is treated as UTC
        ("2026-03-14T20:04:45.123456+00:00", 13.0),
    ],
)
def test_utc_date_comes_from_last_updated_utc_not_local_clock(last_updated, expected_yday):
    rows = td.category_rows(_march_snapshot(last_updated), "global")
    assert all(r["yday"] == expected_yday for r in rows)
    # Today's own point is live, and yesterday's stored point sits just before it.
    assert all(r["history"][-1] == r["today"] for r in rows)
    assert all(r["history"][-2] == expected_yday for r in rows)


def test_utc_date_without_stored_predecessor_gives_none():
    # 01:30+05:00 on the 14th is the 13th in UTC; only the 13th is stored, not the 12th.
    snap = _march_snapshot("2026-03-14T01:30:00+05:00", stored_days=[13])
    assert all(r["yday"] is None for r in td.category_rows(snap, "global"))
    assert td.index_summary(snap, "global")["yday"] is None
    # Local-date reading (14th) would have found the 13th; UTC reading must not.
    snap = _march_snapshot("2026-03-14T23:30:00-07:00", stored_days=[13])
    assert all(r["yday"] is None for r in td.category_rows(snap, "global"))


def test_row_history_uses_stored_days_and_live_today():
    snap = _snapshot()
    rows = {r["cat"]: r for r in td.category_rows(snap, "global")}
    hist = rows["physical"]["history"]
    assert len(hist) == 30
    assert hist[-1] == snap["current_scores"]["physical"]
    assert hist[-2] == snap["daily_history"]["scores"]["physical"][-2]
    assert hist[-3] == snap["daily_history"]["scores"]["physical"][-3]
    assert hist[0] is None


def test_index_history_needs_every_category_and_ends_live():
    snap = _snapshot()
    summary = td.index_summary(snap, "global")
    for days in (7, 30, 90):
        hist = td.index_history(snap, "global", days)
        assert len(hist) == days
        assert hist[-1] == pytest.approx(summary["today"])
    hist = td.index_history(snap, "global", 7)
    assert hist[-2] == pytest.approx(summary["yday"])
    assert hist[-3] == pytest.approx(
        sum(w * snap["daily_history"]["scores"][c][-3] for c, w in BASELINE.items())
    )
    assert hist[0] is None

    snap["daily_history"]["scores"]["energy"][-3] = None
    assert td.index_history(snap, "global", 7)[-3] is None
    assert td.index_history(snap, "global", 7)[-2] == pytest.approx(summary["yday"])


# --- methodology v2: excluded categories and per-category freshness ------------

def test_index_today_renormalizes_when_excluded():
    snap = _snapshot()
    del snap["current_scores"]["physical"]
    snap["excluded_categories"] = ["physical"]
    rows = {r["cat"]: r for r in td.category_rows(snap, "global")}
    assert rows["physical"]["today"] is None
    assert rows["physical"]["is_excluded"] is True
    assert rows["energy"]["is_excluded"] is False

    summary = td.index_summary(snap, "global")
    present = {c: w for c, w in BASELINE.items() if c != "physical"}
    total = sum(present.values())
    today = sum(w / total * snap["current_scores"][c] for c, w in present.items())
    assert summary["today"] == pytest.approx(today)
    assert summary["tier"] == td.tier_for(summary["today"])
    # Yesterday uses the same categories and weights, so the change compares like with like.
    yday = sum(w / total * rows[c]["yday"] for c, w in present.items())
    assert summary["yday"] == pytest.approx(yday)
    assert summary["change"] == pytest.approx(today - yday)
    assert td.index_history(snap, "global", 7)[-1] == pytest.approx(today)


def test_index_today_matches_stored_composite_when_excluded():
    from scoring.engine import compute_composite_index, renormalized_weights

    snap = _snapshot()
    del snap["current_scores"]["chokepoints"]
    snap["excluded_categories"] = ["chokepoints"]
    present = {c: snap["current_scores"][c] for c in BASELINE if c != "chokepoints"}
    composite = compute_composite_index(present, renormalized_weights(BASELINE, set(present)))
    assert td.index_summary(snap, "global")["today"] == pytest.approx(composite)


def test_missing_category_that_is_not_excluded_still_blanks_today():
    snap = _snapshot()
    del snap["current_scores"]["physical"]
    assert td.index_summary(snap, "global")["today"] is None


def test_rows_carry_as_of_stale_and_inputs():
    snap = _snapshot()
    inputs = [{"name": "brent", "score": 20.1, "as_of": "2026-10-21", "status": "live",
               "source": "FRED", "raw_value": "$64"}]
    snap["category_metadata"]["energy"].update(as_of="2026-10-21", is_stale=False, inputs=inputs)
    snap["category_metadata"]["freight"].update(as_of="2026-08-31", is_stale=True)
    snap["category_metadata"]["tariffs"].update(as_of=None, stored_on="2026-10-20",
                                                is_stale=True)
    snap["fallback_categories"] = ["tariffs"]
    rows = {r["cat"]: r for r in td.category_rows(snap, "global")}
    assert rows["energy"]["as_of"] == "2026-10-21"
    assert rows["energy"]["inputs"] == inputs
    assert rows["energy"]["is_stale"] is False
    assert rows["freight"]["is_stale"] is True
    assert rows["tariffs"]["as_of"] is None and rows["tariffs"]["stored_on"] == "2026-10-20"
    assert rows["physical"]["inputs"] == []
    snap["stale_categories"] = ["inputs"]
    assert {r["cat"]: r for r in td.category_rows(snap, "global")}["inputs"]["is_stale"] is True


# --- sector tabs (project 3) ------------------------------------------------------

SEMIS = list(config.SECTORS["semiconductor"]["weights"])
AERO = list(config.SECTORS["aerospace"]["weights"])


def _sector_block(index, **lists):
    block = {"index": index, "tier": None, "coverage": 0, "degraded": False,
             "stale_categories": [], "excluded_categories": [], "fallback_categories": []}
    block.update(lists)
    return block


def _sector_snapshot():
    snap = _snapshot()
    snap["sectors"] = {"semiconductor": _sector_block(64.2), "aerospace": _sector_block(71.3)}
    return snap


def test_semis_tab_rows_only_semis():
    rows = td.category_rows(_sector_snapshot(), "semiconductor")
    assert [r["cat"] for r in rows] == SEMIS
    assert all(r["weight"] == pytest.approx(1 / 3) for r in rows)
    assert not {r["cat"] for r in rows} & set(config.CATEGORY_WEIGHTS)
    for r in rows:
        assert r["effect"] == pytest.approx(r["change"] / 3)


def test_aero_tab_index_from_snapshot_sectors():
    snap = _sector_snapshot()
    summary = td.index_summary(snap, "aerospace")
    # Today is the aggregator's sector index, not a weighting of current_scores.
    assert summary["today"] == 71.3
    assert summary["tier"] == td.tier_for(71.3)
    stored = [snap["daily_history"]["scores"][c][-2] for c in AERO]
    assert summary["yday"] == pytest.approx(sum(stored) / 4)
    assert summary["change"] == pytest.approx(71.3 - sum(stored) / 4)
    hist = td.index_history(snap, "aerospace", 7)
    assert hist[-1] == 71.3
    assert hist[-2] == pytest.approx(summary["yday"])


def test_sector_yesterday_needs_coverage():
    snap = _sector_snapshot()
    scores = snap["daily_history"]["scores"]
    # Aero needs 3 of 4: one missing category still gives the mean of the other three.
    scores["aero_flow"][-2] = None
    expected = sum(scores[c][-2] for c in AERO if c != "aero_flow") / 3
    assert td.index_summary(snap, "aerospace")["yday"] == pytest.approx(expected)
    # Two of four is below coverage: no 2-category "index" for that day.
    scores["aero_mill_prices"][-2] = None
    assert td.index_summary(snap, "aerospace")["yday"] is None
    assert td.index_summary(snap, "aerospace")["change"] is None
    assert td.index_history(snap, "aerospace", 7)[-2] is None
    # Semis needs 2 of 3.
    scores["semis_logic_prices"][-3] = None
    assert td.index_history(snap, "semiconductor", 7)[-3] == pytest.approx(
        (scores["semis_memory_prices"][-3] + scores["semis_fab_utilization"][-3]) / 2)
    scores["semis_memory_prices"][-3] = None
    assert td.index_history(snap, "semiconductor", 7)[-3] is None


def test_sector_change_needs_the_same_categories_on_both_days():
    snap = _sector_snapshot()
    scores = snap["daily_history"]["scores"]
    # 4 categories today and 4 stored yesterday: the change is shown.
    summary = td.index_summary(snap, "aerospace")
    assert summary["change"] == pytest.approx(71.3 - summary["yday"])
    # 4 today, 3 yesterday: yesterday's index still shows, the change does not.
    scores["aero_flow"][-2] = None
    summary = td.index_summary(snap, "aerospace")
    assert summary["yday"] is not None
    assert summary["change"] is None
    # 3 today (aero_flow excluded) and the same 3 yesterday: comparable again.
    del snap["current_scores"]["aero_flow"]
    summary = td.index_summary(snap, "aerospace")
    assert summary["change"] == pytest.approx(71.3 - summary["yday"])


def test_sector_below_coverage_today_has_no_index_or_tier():
    snap = _sector_snapshot()
    snap["sectors"]["semiconductor"] = _sector_block(None, excluded_categories=SEMIS[:2])
    for cat in SEMIS[:2]:
        del snap["current_scores"][cat]
    summary = td.index_summary(snap, "semiconductor")
    assert summary["today"] is None and summary["tier"] is None and summary["change"] is None
    rows = {r["cat"]: r for r in td.category_rows(snap, "semiconductor")}
    assert rows[SEMIS[0]]["is_excluded"] is True
    assert rows[SEMIS[2]]["is_excluded"] is False


def test_sector_rows_read_sector_flags_not_global_lists():
    snap = _sector_snapshot()
    snap["category_metadata"]["aero_flow"].update(is_fallback=True, is_stale=True, stored_on="2026-10-20")
    snap["category_metadata"]["aero_throughput"].update(is_stale=True)
    snap["sectors"]["aerospace"] = _sector_block(
        71.3, fallback_categories=["aero_flow"], stale_categories=["aero_flow", "aero_throughput"])
    assert snap["fallback_categories"] == []  # the global list never carries sector keys
    rows = {r["cat"]: r for r in td.category_rows(snap, "aerospace")}
    assert rows["aero_flow"]["is_fallback"] is True
    assert rows["aero_throughput"]["is_stale"] is True and rows["aero_throughput"]["is_fallback"] is False
    assert rows["aero_mill_prices"]["is_stale"] is False


def test_old_snapshot_without_sectors_does_not_crash():
    snap = _snapshot()  # no "sectors" block, as in a snapshot saved before project 3
    for key in ("semiconductor", "aerospace"):
        assert td.index_summary(snap, key)["today"] is None
        assert len(td.index_history(snap, key, 30)) == 30


def test_unknown_or_old_tab_key_maps_to_global():
    assert td.tab_key("baseline") == "global"
    assert td.tab_key(None) == "global"
    assert td.tab_key("semiconductor") == "semiconductor"
    snap = _snapshot()
    assert td.category_rows(snap, "baseline") == td.category_rows(snap, "global")


# --- Global tab is unchanged (golden output captured before the tab rewrite) ----------

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "global_tab_golden.json"


def golden_snapshot():
    """Stored history with gaps, one excluded, one stored fallback, one stale category."""
    cats = sorted(ALL_CATS)
    dates = [(date(2026, 10, 22) - timedelta(days=n)).isoformat() for n in range(91, -1, -1)]
    scores = {}
    for i, c in enumerate(cats):
        series = [round(40 + ((d * 7 + i * 13) % 50) * 0.9, 1) for d in range(len(dates))]
        for d in range(len(dates)):
            if (d + i) % 9 == 0:
                series[d] = None
        series[-1] = None
        scores[c] = series
    current = {c: round(45 + i * 3.7, 1) for i, c in enumerate(cats)}
    del current["physical"]
    meta = {c: {"source": f"{c} source", "raw_value": "1.5", "raw_label": "raw", "updated": "2026-10-22",
                "description": f"{c} desc", "calculation": f"{c} calc", "as_of": "2026-10-21",
                "is_stale": False} for c in cats}
    meta["freight"].update(is_stale=True, as_of="2026-08-31")
    meta["tariffs"].update(is_stale=True, is_fallback=True, as_of=None, stored_on="2026-10-20")
    meta["energy"]["inputs"] = [{"name": "brent", "score": 20.1, "as_of": "2026-10-21", "status": "live",
                                 "source": "FRED", "raw_value": "$64"}]
    return {
        "last_updated_utc": "2026-10-22T20:04:45Z",
        "current_scores": current,
        "category_metadata": meta,
        "fallback_categories": ["tariffs"],
        "stale_categories": ["freight", "tariffs"],
        "excluded_categories": ["physical"],
        "daily_history": {"dates": dates, "scores": scores},
        "sectors": {"semiconductor": _sector_block(64.2), "aerospace": _sector_block(71.3)},
        "alerts": [], "map_markers": [], "market_data": {}, "briefing": "",
    }


def _text(node):
    if node is None:
        return ""
    if isinstance(node, (str, int, float)):
        return str(node)
    if isinstance(node, (list, tuple)):
        return " ".join(_text(n) for n in node)
    return _text(getattr(node, "children", None))


def global_tab_output(key):
    from components import terminal as term
    from components.workspace import snapshot_csv

    snap = golden_snapshot()
    table = term.build_category_table(snap, key)
    return json.loads(json.dumps({
        "rows": td.category_rows(snap, key),
        "summary": td.index_summary(snap, key),
        "history": {str(n): td.index_history(snap, key, n) for n in (7, 30, 90)},
        "readout_text": _text(term.build_readout(snap, key, 30)),
        "table_text": _text(table),
        "csv": snapshot_csv(snap, key),
    }))


def test_global_tab_unchanged():
    assert global_tab_output("global") == json.loads(GOLDEN.read_text())
