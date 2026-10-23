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
