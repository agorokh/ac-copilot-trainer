from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIRMWARE = REPO / "firmware" / "screen"


def test_racing_atelier_tokens_are_wired_to_firmware() -> None:
    tokens = (FIRMWARE / "include" / "ui" / "tokens.h").read_text(encoding="utf-8")

    for color in (
        "0x0B0C0D",
        "0x141618",
        "0xC8983E",
        "0xF23B2C",
        "0xF4A52C",
        "0x2FBE6E",
        "0x49B6C9",
    ):
        assert color in tokens

    assert "#define UI_RADIUS_TILE      0" in tokens
    assert "#define UI_ACCENT_GOLD      UI_BRASS" in tokens
    assert "LV_FONT_DECLARE(font_saira_sc_black_54);" in tokens
    assert "#define UI_FONT_COMMAND_HERO  (&font_saira_sc_black_54)" in tokens
    assert "#define UI_FONT_MONO_XS       (&font_spline_mono_10)" in tokens


def test_racing_atelier_font_bundle_is_committed_and_documented() -> None:
    font_dir = FIRMWARE / "src" / "ui" / "fonts"
    expected_generated = {
        "font_saira_sc_black_54.c",
        "font_saira_sc_bold_34.c",
        "font_saira_sc_bold_28.c",
        "font_saira_sc_semibold_12.c",
        "font_saira_sc_semibold_11.c",
        "font_saira_sc_semibold_9.c",
        "font_saira_bold_46.c",
        "font_saira_bold_34.c",
        "font_saira_bold_26.c",
        "font_spline_mono_12.c",
        "font_spline_mono_11.c",
        "font_spline_mono_10.c",
    }
    expected_sources = {
        "Saira-wdth-wght.ttf",
        "Saira-Bold.ttf",
        "SairaSemiCondensed-Black.ttf",
        "SairaSemiCondensed-Bold.ttf",
        "SairaSemiCondensed-SemiBold.ttf",
        "SplineSansMono-wght.ttf",
        "SplineSansMono-Medium.ttf",
    }

    for filename in expected_generated:
        path = font_dir / filename
        assert path.exists(), filename
        assert path.stat().st_size > 1000
        generated = path.read_text(encoding="utf-8")
        assert '#include "lvgl.h"' in generated
        assert "lvgl/lvgl.h" not in generated

    for filename in expected_sources:
        path = font_dir / "src" / filename
        assert path.exists(), filename
        assert path.stat().st_size > 1000

    assert not (font_dir / "src" / "Michroma-Regular.ttf").exists()
    assert not (font_dir / "src" / "Montserrat-Regular.ttf").exists()
    assert not (font_dir / "src" / "Syncopate-Bold.ttf").exists()

    readme = (font_dir / "README.md").read_text(encoding="utf-8")
    assert "Racing Atelier" in readme
    assert "--no-compress" in readme
    assert "--lv-include lvgl.h" in readme
    assert "SairaSemiCondensed-Black.ttf" in readme
    assert "SplineSansMono-Medium.ttf" in readme

    ignore = (font_dir / ".gitignore").read_text(encoding="utf-8")
    assert "!font_saira_*.c" in ignore
    assert "!font_spline_*.c" in ignore


def test_ac_copilot_screen_uses_racing_atelier_instrument_elements() -> None:
    screen = (FIRMWARE / "src" / "ui" / "screen_ac_copilot.cpp").read_text(encoding="utf-8")

    assert "lv_bar_create" not in screen
    assert "constexpr int SEGMENT_COUNT = 12;" in screen
    assert "delta_fill" in screen
    assert "SNAPSHOT_STALE_MS" in screen
    assert '"STALE"' in screen
    assert '"BRAKE ZONE"' in screen
    assert "UI_FONT_COMMAND_HERO" in screen
    assert "UI_FONT_READ_XL" in screen
