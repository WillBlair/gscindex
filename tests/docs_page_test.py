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


def test_docs_has_limitations_section(body):
    assert "<h2>Limitations</h2>" in body
    text = _text(body)
    assert text.index("Limitations") < text.index("Data sources and credits")
    section = text[text.index("Limitations"):text.index("Data sources and credits")]
    assert "April 2020" in section and "demand collapse" in section
    assert "about 70" in section and "has not been tuned away" in section
    assert "\u2014" not in section


def _sector_section(text: str) -> str:
    return text[text.index("Sector indexes"):text.index("What Claude does")]


def test_docs_sector_section_and_no_silicon_analysts(body):
    assert "<h2>Sector indexes</h2>" in body
    text = _text(body)
    assert "silicon analysts" not in text.lower()
    for old in ("Aircraft Orders", "Aero Metals", "Aircraft PPI", "Wafer Prices", "Lead Times"):
        assert old not in text, old
    section = _sector_section(text)
    assert "—" not in section

    for key, spec in config.SECTORS.items():
        assert spec["title"] in section, key
        for cat in spec["weights"]:
            assert config.CATEGORY_LABELS[cat] in section.replace("&amp;", "&"), cat
    # Equal weights and the coverage rule, from config.
    assert "33%" in section and "25%" in section
    assert "at least 2 of its 3 categories" in section
    assert "at least 3 of its 4 categories" in section
    assert "Not enough data" in section

    # Every series used, and anchors and freshness read from the anchors file and config.
    for code in ("PRCG20_2500850005", "PRCG20_2500850004", "CAPUTLG3344S", "CAPUTLG3364T9S", "ANAPTI",
                 "ANAPVS", "WPU102505", "WPU102504", "PCU33211233211242", "PCU332112332112",
                 "PCU3315123315120"):
        assert code in section, code
    memory = config.SCORE_ANCHORS["inputs"]["boj_memory"]
    assert f"0 at {memory['worst']:+.1f}% (Dec 2025)" in section
    fab = config.SCORE_ANCHORS["inputs"]["fab_util_3344"]
    assert f"80 at {fab['normal']:.1f}%" in section
    flow = config.SCORE_ANCHORS["inputs"]["aero_inv_ship"]
    assert f"{math.exp(flow['worst']):.2f} months" in section
    stale, drop = config.FRESHNESS["boj_memory"]
    assert f"stale after {stale} days, dropped after {drop}" in section
    assert f"{config.SECTOR_DROP_AFTER_DAYS} days" in section


def test_docs_sector_limitations_and_credits(body):
    text = _text(body)
    section = _sector_section(text)
    memory = config.SCORE_ANCHORS["inputs"]["boj_memory"]
    # Disclosed limitations (spec settled item 1 and the anchor rulings).
    assert "glut" in section and "demand collapse" in section
    assert f"above {memory['worst']:+.1f}%" in section and "316%" in section
    assert "does not separate" in section
    assert "1972" in section and "1948" in section
    # Credits: the BOJ line verbatim, and the US government sources.
    assert ("This service uses the API provided by the 'Bank of Japan Time-Series Data Search.' "
            "The Bank of Japan does not guarantee the content of the service.") in text
    assert "requires the Bank of Japan's permission" in section
    for credit in ("Federal Reserve Board", "G.17", "Census Bureau", "M3", "Bureau of Labor Statistics",
                   "Producer Price Index"):
        assert credit in text, credit
    # The API and /health sector fields are described.
    assert "sectors" in text and "terms" in text


def test_docs_sector_worst_months_agree_with_the_anchors_file():
    from api import docs

    for key in ("boj_memory", "boj_logic", "fab_util_3344", "aero_caputl", "aero_inv_ship", "ppi_ti_mill",
                "ppi_ni_mill", "ppi_ti_forge", "ppi_nonferrous_forge", "ppi_steel_invest_cast"):
        assert key in docs.WORST_MONTHS, key
