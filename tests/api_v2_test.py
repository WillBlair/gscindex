"""Public API and /health for methodology v2: category objects, stored composite, freshness.

Snapshots are built by hand; nothing touches the network or a database.
"""
from __future__ import annotations

import pytest
from flask import Flask

from api.routes import api_bp
from config import CATEGORY_WEIGHTS
from data import cache
from scoring.engine import snapshot_composite

_SCORES = {
    "supply_chain": 52.5, "chokepoints": 36.1, "energy": 23.3, "tariffs": 46.2,
    "geopolitical": 49.3, "freight": 77.2, "inputs": 41.9, "physical": 82.8,
}
_BRENT = {"name": "brent", "score": 20.1, "as_of": "2026-10-21", "status": "live",
          "source": "FRED DCOILBRENTEU", "raw_value": "$64.20/bbl"}


def _meta(cat, **extra):
    meta = {
        "source": f"{cat} source", "raw_value": "1", "raw_label": "x", "description": "d",
        "calculation": "c", "updated": "2026-10-22", "as_of": "2026-10-21",
        "is_stale": False, "is_fallback": False, "inputs": [],
    }
    meta.update(extra)
    return meta


def _snapshot():
    metadata = {c: _meta(c) for c in CATEGORY_WEIGHTS}
    metadata["energy"] = _meta("energy", inputs=[_BRENT])
    metadata["freight"] = _meta("freight", as_of="2026-08-31", is_stale=True)
    return {
        "last_updated_utc": "2026-10-22T20:04:45Z",
        "current_scores": dict(_SCORES),
        "composite": 47.31,
        "category_metadata": metadata,
        "degraded": False,
        "fallback_categories": [],
        "excluded_categories": [],
        "stale_categories": ["freight"],
        "disruptions": [], "map_markers": [],
    }


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    return app.test_client()


def test_latest_api_category_objects_and_version(client, monkeypatch):
    monkeypatch.setattr(cache, "get_cached_dashboard", _snapshot)
    body = client.get("/api/v1/latest").get_json()

    assert body["methodology_version"] == 2
    assert body["composite_index"] == 47.3
    assert body["stale_categories"] == ["freight"]
    assert body["excluded_categories"] == []
    assert set(body["categories"]) == set(CATEGORY_WEIGHTS)
    energy = body["categories"]["energy"]
    for key in ("score", "weight", "as_of", "source", "is_stale", "is_fallback", "inputs"):
        assert key in energy, key
    assert energy["score"] == 23.3
    assert energy["weight"] == CATEGORY_WEIGHTS["energy"]
    assert energy["as_of"] == "2026-10-21"
    assert energy["source"] == "energy source"
    assert energy["inputs"] == [_BRENT]
    assert body["categories"]["freight"]["is_stale"] is True
    # Existing keys stay.
    for key in ("timestamp", "degraded", "fallback_categories", "disruptions", "map_markers", "meta"):
        assert key in body, key


def test_latest_api_uses_stored_composite_when_category_missing(client, monkeypatch):
    snap = _snapshot()
    del snap["current_scores"]["physical"]
    snap["excluded_categories"] = ["physical"]
    snap["composite"] = 45.04
    snap["category_metadata"]["physical"] = _meta(
        "physical", source="Unavailable (provider failed)", as_of=None)
    monkeypatch.setattr(cache, "get_cached_dashboard", lambda: snap)

    response = client.get("/api/v1/latest")
    assert response.status_code == 200
    body = response.get_json()
    assert body["composite_index"] == 45.0
    assert body["excluded_categories"] == ["physical"]
    physical = body["categories"]["physical"]
    assert physical["score"] is None and physical["as_of"] is None


def test_latest_api_reports_stored_fallback_date_not_as_of(client, monkeypatch):
    snap = _snapshot()
    snap["category_metadata"]["energy"] = _meta(
        "energy", as_of=None, stored_on="2026-10-20", is_stale=True, is_fallback=True)
    snap["fallback_categories"] = ["energy"]
    monkeypatch.setattr(cache, "get_cached_dashboard", lambda: snap)

    energy = client.get("/api/v1/latest").get_json()["categories"]["energy"]
    assert energy["as_of"] is None
    assert energy["stored_on"] == "2026-10-20"
    assert energy["is_fallback"] is True


def test_latest_api_old_snapshot_without_metadata(client, monkeypatch):
    """A pre-v2 snapshot (no composite, no metadata) still answers, composite None."""
    monkeypatch.setattr(cache, "get_cached_dashboard",
                        lambda: {"current_scores": {"weather": 80.0, "energy": 50.0}})
    body = client.get("/api/v1/latest").get_json()
    assert body["composite_index"] is None
    assert body["categories"]["energy"]["score"] == 50.0
    assert body["categories"]["supply_chain"]["score"] is None


def test_newsletter_data_uses_stored_composite(client, monkeypatch):
    snap = _snapshot()
    del snap["current_scores"]["physical"]
    snap["composite"] = 45.04
    monkeypatch.setattr(cache, "get_cached_dashboard", lambda: snap)
    monkeypatch.setattr("api.admin.verify_admin", lambda: True)
    body = client.get("/api/v1/newsletter-data").get_json()
    assert body["composite_index"] == 45.0


def test_snapshot_composite_rejects_bool():
    assert snapshot_composite({"composite": True}) is None
    assert snapshot_composite({"composite": False}) is None
    assert snapshot_composite({"composite": float("nan")}) is None
    assert snapshot_composite({"composite": 47}) == 47.0


def test_health_lists_stale_and_excluded_categories(monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    snap = _snapshot()
    snap["excluded_categories"] = ["physical"]
    monkeypatch.setattr(application, "_DATA_CACHE", snap)
    # Dash builds the layout on the first request, which would reload the disk cache.
    monkeypatch.setattr("data.cache.get_cached_dashboard", lambda: None)
    body = application.server.test_client().get("/health").get_json()
    assert body["stale_categories"] == ["freight"]
    assert body["excluded_categories"] == ["physical"]
    assert body["fallback_categories"] == []
    assert "state" in body and "data_age_seconds" in body


def test_startup_keeps_a_snapshot_with_an_excluded_category(monkeypatch):
    """An excluded category is absent from current_scores but the snapshot is current
    (methodology v2), so the startup schema check must not throw it away."""
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    snap = _snapshot()
    assert application._has_current_categories(snap) is True
    del snap["current_scores"]["physical"]
    assert application._has_current_categories(snap) is False
    snap["excluded_categories"] = ["physical"]
    assert application._has_current_categories(snap) is True
    # An old-format snapshot (pre-v2 categories) is still rejected.
    assert application._has_current_categories({"current_scores": {"weather": 80.0}}) is False


def test_latest_api_meta_credits_portwatch_verbatim(client, monkeypatch):
    monkeypatch.setattr(cache, "get_cached_dashboard", _snapshot)
    meta = client.get("/api/v1/latest").get_json()["meta"]
    assert "Sources: UN Global Platform; IMF PortWatch" in meta["credits"]
    assert meta["documentation"] == "https://gscindex.com/docs"


# ---------------------------------------------------------------- sector indexes

from datetime import datetime, timezone  # noqa: E402

from config import SECTORS  # noqa: E402

_BOJ_CREDIT_VERBATIM = (
    "This service uses the API provided by the 'Bank of Japan Time-Series Data Search.' "
    "The Bank of Japan does not guarantee the content of the service.")
_SECTOR_SCORES = {
    "semis_memory_prices": 0.0, "semis_logic_prices": 65.94, "semis_fab_utilization": 84.6,
    "aero_throughput": 80.0, "aero_flow": 76.2, "aero_mill_prices": 74.1, "aero_forge_cast": 37.3,
}


def _sector_block(index, tier, coverage, degraded=False, **lists):
    block = {"index": index, "tier": tier, "coverage": coverage, "degraded": degraded,
             "stale_categories": [], "excluded_categories": [], "fallback_categories": []}
    block.update(lists)
    return block


def _sector_snapshot():
    snap = _snapshot()
    snap["current_scores"].update(_SECTOR_SCORES)
    for cat in _SECTOR_SCORES:
        snap["category_metadata"][cat] = _meta(cat, as_of="2026-09-30")
    snap["sectors"] = {
        "semiconductor": _sector_block(50.18, "Stressed", 3),
        "aerospace": _sector_block(66.9, "Stable", 4),
    }
    return snap


def test_latest_has_sectors_and_global_categories_unchanged(client, monkeypatch):
    monkeypatch.setattr(cache, "get_cached_dashboard", _sector_snapshot)
    body = client.get("/api/v1/latest").get_json()

    # Global output is exactly what it was: sector categories never appear at the top level.
    assert set(body["categories"]) == set(CATEGORY_WEIGHTS)
    assert body["composite_index"] == 47.3
    assert body["degraded"] is False
    assert body["meta"]["license"] == "CC-BY-4.0"

    assert set(body["sectors"]) == set(SECTORS)
    semis = body["sectors"]["semiconductor"]
    assert semis["index"] == 50.2
    assert semis["tier"] == "Stressed"
    assert semis["coverage"] == 3
    assert semis["degraded"] is False
    assert set(semis["categories"]) == set(SECTORS["semiconductor"]["weights"])
    logic = semis["categories"]["semis_logic_prices"]
    for key in ("score", "weight", "as_of", "stored_on", "source", "is_stale", "is_fallback", "inputs"):
        assert key in logic, key
    assert logic["score"] == 65.9
    assert logic["weight"] == pytest.approx(1 / 3)
    assert logic["as_of"] == "2026-09-30"

    aero = body["sectors"]["aerospace"]
    assert aero["index"] == 66.9
    assert set(aero["categories"]) == set(SECTORS["aerospace"]["weights"])
    assert aero["categories"]["aero_forge_cast"]["weight"] == pytest.approx(0.25)
    assert "CC-BY-4.0" in aero["terms"]
    for credit in ("Federal Reserve", "Census", "Bureau of Labor Statistics"):
        assert credit in aero["terms"], credit
    assert "Bank of Japan" not in aero["terms"]


def test_latest_sector_block_reports_its_own_degradation(client, monkeypatch):
    snap = _sector_snapshot()
    for cat in ("semis_memory_prices", "semis_logic_prices"):
        del snap["current_scores"][cat]
    snap["sectors"]["semiconductor"] = _sector_block(
        None, None, 1, degraded=True, excluded_categories=["semis_logic_prices", "semis_memory_prices"])
    monkeypatch.setattr(cache, "get_cached_dashboard", lambda: snap)
    body = client.get("/api/v1/latest").get_json()

    semis = body["sectors"]["semiconductor"]
    assert semis["index"] is None and semis["tier"] is None
    assert semis["coverage"] == 1 and semis["degraded"] is True
    assert semis["excluded_categories"] == ["semis_logic_prices", "semis_memory_prices"]
    assert semis["categories"]["semis_memory_prices"]["score"] is None
    # The global flags are untouched by the sector outage.
    assert body["degraded"] is False
    assert body["excluded_categories"] == []


def test_latest_sectors_from_a_snapshot_saved_before_sectors(client, monkeypatch):
    monkeypatch.setattr(cache, "get_cached_dashboard", _snapshot)
    sectors = client.get("/api/v1/latest").get_json()["sectors"]
    assert set(sectors) == set(SECTORS)
    for block in sectors.values():
        assert block["index"] is None and block["coverage"] == 0 and block["degraded"] is True
        assert all(c["score"] is None for c in block["categories"].values())


def test_semis_terms_boj_verbatim(client, monkeypatch):
    monkeypatch.setattr(cache, "get_cached_dashboard", _sector_snapshot)
    terms = client.get("/api/v1/latest").get_json()["sectors"]["semiconductor"]["terms"]
    assert _BOJ_CREDIT_VERBATIM in terms
    assert "Commercial reuse of the memory and logic" in terms
    assert "requires the Bank of Japan's permission" in terms
    import config
    assert config.BOJ_COMMERCIAL_NOTE in terms
    # Fab utilization is Federal Reserve data, not BOJ data.
    assert "Federal Reserve" in terms and "CC-BY-4.0" in terms
    assert "—" not in terms


def test_health_sectors_block_and_status_unaffected(monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    monkeypatch.setattr("data.cache.get_cached_dashboard", lambda: None)
    monkeypatch.setattr(application, "_LAST_UPDATE", datetime.now(timezone.utc))
    monkeypatch.setattr(application, "_HAS_FETCHED_OK", True)
    monkeypatch.setattr(application, "_FETCH_STARTED_AT", None)
    client = application.server.test_client()

    monkeypatch.setattr(application, "_DATA_CACHE", _sector_snapshot())
    healthy = client.get("/health")
    assert healthy.get_json()["sectors"] == {
        "semiconductor": {"degraded": False, "coverage": 3},
        "aerospace": {"degraded": False, "coverage": 4},
    }

    # Every sector category out: the sector blocks say so, the global status does not change.
    snap = _sector_snapshot()
    for cat in _SECTOR_SCORES:
        del snap["current_scores"][cat]
    snap["sectors"] = {
        "semiconductor": _sector_block(None, None, 0, degraded=True,
                                       excluded_categories=sorted(SECTORS["semiconductor"]["weights"])),
        "aerospace": _sector_block(None, None, 0, degraded=True,
                                   excluded_categories=sorted(SECTORS["aerospace"]["weights"])),
    }
    monkeypatch.setattr(application, "_DATA_CACHE", snap)
    outage = client.get("/health")
    body = outage.get_json()
    assert outage.status_code == healthy.status_code == 200
    assert body["state"] == healthy.get_json()["state"] == "healthy"
    assert body["sectors"] == {
        "semiconductor": {"degraded": True, "coverage": 0},
        "aerospace": {"degraded": True, "coverage": 0},
    }
    assert body["fallback_categories"] == [] and body["excluded_categories"] == []


def test_boj_commercial_note_is_identical_in_api_csv_and_docs(client, monkeypatch):
    """One wording everywhere: the API terms, the Semis CSV rows and /docs all render the
    config constant verbatim."""
    import csv
    import io

    import config
    from api import docs
    from components.workspace import snapshot_csv

    note = config.BOJ_COMMERCIAL_NOTE
    assert note.startswith("Commercial reuse") and "Bank of Japan's permission" in note
    monkeypatch.setattr(cache, "get_cached_dashboard", _sector_snapshot)
    terms = client.get("/api/v1/latest").get_json()["sectors"]["semiconductor"]["terms"]
    assert terms.startswith(config.BOJ_CREDIT + " " + note)

    rows = list(csv.DictReader(io.StringIO(snapshot_csv(_sector_snapshot(), "semiconductor"))))
    boj_rows = [r for r in rows if r["category"] in ("Memory Prices", "Logic Chip Prices")]
    assert len(boj_rows) == 2 and all(r["credit"] == config.BOJ_CREDIT + " " + note for r in boj_rows)

    app = Flask(__name__)
    app.register_blueprint(docs.docs_bp)
    page = app.test_client().get("/docs").get_data(as_text=True)
    assert note in page
