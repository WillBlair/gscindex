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
                   "IMF Primary Commodity Prices", "GDACS", "USGS", "USITC"):
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


def test_docs_describe_live_ttf_conversion(body):
    """TTF is not scaled from an official print: it is TTF=F x EURUSD=X / 3.412, checked against
    the latest IMF monthly value (energy.py _live_ttf)."""
    text = _text(body)
    assert "EURUSD=X" in text
    assert f"{config.MWH_PER_MMBTU:g}" in text
    assert f"{config.TTF_LIVE_MAX_AGE_DAYS} days" in text
    assert "Brent and diesel" in text


def test_docs_say_kaub_is_not_scored(body):
    text = _text(body)
    assert "Kaub is recorded, not scored" in text
    assert "until it has a year" not in text


def test_docs_failed_category_step_separates_fetch_failure_from_expired_inputs(body):
    text = _text(body)
    assert "If every input fails to load, the category shows its last stored daily score" in text
    assert ("If the inputs load but are all past their drop limits, the category is excluded "
            "right away") in text
    assert "If every input is missing, the category shows" not in text


def test_docs_tariff_burden_freshness_reads_config(body):
    stale, drop = config.FRESHNESS["tariff_burden"]
    assert f"The burden is stale after {stale} days, dropped after {drop}" in _text(body)


def test_docs_headlines_mention_the_hourly_unscored_refresh(body):
    minutes = f"{config.NEWS_RSS_REFRESH_SECONDS / 60:g}"
    assert (f"The feeds are re-read every {minutes} minutes, and new headlines appear with no "
            "severity until Claude's next run.") in _text(body)


def test_docs_drops_gatun_and_panama_canal_authority(body):
    text = _text(body)
    assert "gatun" not in text.lower()
    assert "Panama Canal Authority" not in text
    assert "PortWatch transits in Chokepoints" in text
    assert f"{round(config.PHYSICAL_WEIGHTS['hazards'] * 100)}% hazards, " \
           f"{round(config.PHYSICAL_WEIGHTS['mississippi'] * 100)}% Mississippi" in text
