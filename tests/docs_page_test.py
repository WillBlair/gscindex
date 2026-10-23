"""The /docs methodology page matches methodology v2: eight categories, anchors, credits, API."""
from __future__ import annotations

import math
import re

import flask
import pytest

import config


@pytest.fixture
def body():
    from api import docs

    app = flask.Flask(__name__)
    app.register_blueprint(docs.docs_bp)
    return app.test_client().get("/docs").get_data(as_text=True)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_docs_lists_eight_categories_and_credit(body):
    text = _text(body)
    assert len(config.CATEGORY_WEIGHTS) == 8
    for cat, weight in config.CATEGORY_WEIGHTS.items():
        label = config.CATEGORY_LABELS[cat].replace("&", "&amp;")
        assert label in body, cat
        assert f"{round(weight * 100)}%" in text, cat
    assert "Sources: UN Global Platform; IMF PortWatch" in text
    for credit in ("Federal Reserve Bank of New York", "IMF PortWatch", "FRED", "EIA", "Yahoo Finance",
                   "Daily Treasury Statement", "BOPGIMP", "Caldara", "Iacoviello", "Trade Policy Uncertainty",
                   "Bureau of Transportation Statistics", "Surface Transportation Board", "AgTransport",
                   "Federal Reserve Bank of Philadelphia", "Federal Reserve Bank of Dallas",
                   "IMF Primary Commodity Prices", "GDACS", "Panama Canal Authority", "USGS", "USITC"):
        assert credit in text, credit


def test_docs_has_no_stale_claims(body):
    text = _text(body)
    assert "25 newest" not in text
    assert not re.search(r"hover[^.]*explanation", text, re.IGNORECASE)
    for stale in ("VADER", "BDRY", "IYT", "12.5", "72 +", "EPUTRADE", "2-year", "Port Weather",
                  "port-disruption", "Kansas City"):
        assert stale not in text, stale


def test_docs_anchor_values_come_from_the_anchors_file(body):
    text = _text(body)
    gscpi = config.SCORE_ANCHORS["inputs"]["gscpi"]
    assert f"{gscpi['worst']:+.2f}" in text
    brent = config.SCORE_ANCHORS["inputs"]["brent"]
    assert f"${math.exp(brent['normal']):.0f}" in text
    assert "19.8%" in text            # tariff burden zero point (USITC, 1933)


def test_docs_worst_months_agree_with_the_anchors_file():
    from api import docs

    for key, month in docs.WORST_MONTHS.items():
        basis = config.SCORE_ANCHORS["inputs"][key]["worst_basis"]
        assert month.strftime("%Y-%m") in basis, key


def test_docs_freshness_limits_come_from_config(body):
    text = _text(body)
    stale, drop = config.FRESHNESS["chokepoint_flow"]
    assert f"stale after {stale} days, dropped after {drop}" in text


def test_docs_describe_the_api_shape(body):
    text = _text(body)
    for field in ("methodology_version", "composite_index", "excluded_categories", "stale_categories",
                  "is_stale", "is_fallback", "stored_on", "as_of", "inputs", "last_fetch_status"):
        assert field in text, field
    assert "renormalized" in text


def test_docs_render_without_anchors(monkeypatch):
    """A missing anchors file must not break the page."""
    from api import docs

    monkeypatch.setattr(config, "SCORE_ANCHORS", {})
    app = flask.Flask(__name__)
    app.register_blueprint(docs.docs_bp)
    response = app.test_client().get("/docs")
    assert response.status_code == 200
    assert "Chokepoints" in response.get_data(as_text=True)
