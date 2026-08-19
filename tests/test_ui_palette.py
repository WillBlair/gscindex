"""Palette contract for the 2026-07-25 UI makeover."""
from config import (
    CATEGORY_COLORS,
    COLORS,
    FONT_NUMBERS,
    FONT_SANS,
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


def test_meter_numbers_share_the_ui_sans_face():
    assert FONT_NUMBERS == FONT_SANS
    assert FONT_NUMBERS.startswith("Satoshi")


def test_green_red_aliases_match_tiers():
    assert COLORS["green"] == "#3d9b6e"
    assert COLORS["red"] == "#c44d5f"
    assert COLORS["yellow"] == "#c4a35a"
    assert COLORS["orange"] == "#c47a3a"
