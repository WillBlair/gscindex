"""Palette contract: config tokens (email and stored metadata) and the Terminal stylesheet."""
from config import (
    CATEGORY_COLORS,
    COLORS,
    HEALTH_TIERS,
    INDUSTRY_PROFILES,
)


def test_canvas_and_surface_tokens():
    assert COLORS["bg"] == "#0a0a0b"
    assert COLORS["card"] == "#111113"
    assert COLORS["card_raised"] == "#18181b"
    assert COLORS["text"] == "#ececef"
    assert COLORS["text_muted"] == "#8b8b93"
    assert COLORS["text_faint"] == "#5c5c66"
    assert COLORS["accent"] != "#6366f1"


def test_health_tier_colors_desaturated():
    by_label = {t["label"]: t["color"] for t in HEALTH_TIERS}
    assert by_label["Healthy"] == "#3d9b6e"
    assert by_label["Stable"] == "#c4a35a"
    assert by_label["Stressed"] == "#c47a3a"
    assert by_label["Critical"] == "#c44d5f"


def test_category_colors_cover_all_profile_keys():
    keys = set()
    for prof in INDUSTRY_PROFILES.values():
        keys.update(prof["weights"])
    assert keys <= set(CATEGORY_COLORS)
    # No leftover neon purple brand accent as a category default
    assert "#8b5cf6" not in CATEGORY_COLORS.values()
    assert "#6366f1" not in CATEGORY_COLORS.values()


def test_green_red_aliases_match_tiers():
    # Green was deliberately brightened for live indicators and the
    # newsletter (e2c7259); the other aliases still match their tiers.
    assert COLORS["green"] == "#4ade80"
    assert COLORS["red"] == "#c44d5f"
    assert COLORS["yellow"] == "#c4a35a"
    assert COLORS["orange"] == "#c47a3a"


# --- Terminal stylesheet (2026-10-22 redesign) ---------------------------------
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def test_terminal_stylesheet_carries_the_draft_palette():
    css = (ASSETS / "terminal.css").read_text()
    for token in ("#000000", "#07090C", "#1D232B", "#F2F4F7", "#8A94A3", "#FFB020",
                  "#35D07F", "#F5C542", "#FF8A3D", "#FF4D5E"):
        assert token in css, token
    assert "JetBrains Mono" in css and "Inter" in css


def test_old_stylesheet_is_gone():
    assert not (ASSETS / "style.css").exists()


def test_page_loads_terminal_fonts_and_no_tile_map_assets(monkeypatch):
    monkeypatch.setenv("GSC_DISABLE_BACKGROUND", "1")
    import app as application
    sheets = " ".join(str(s) for s in application.app.config.external_stylesheets)
    assert "JetBrains+Mono" in sheets and "Inter" in sheets
    assert "satoshi" not in sheets.lower() and "IBM+Plex" not in sheets
    assert "cartocdn" not in application.app.index_string
