"""Tests for the EPIC #154 Part G HUD framebuffer capture (#238) — pure helpers + guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ac_harness import hud_capture
from tools.ac_harness.hud_capture import (
    LivenessScore,
    _main,
    bgra_to_rgb,
    capture_bgra,
    encode_png,
    liveness_score,
    region_rect,
    save_png,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# 2x2 top-down BGRA: per pixel (B, G, R, A).
BGRA_2x2 = bytes([1, 2, 3, 255, 4, 5, 6, 255, 7, 8, 9, 255, 10, 11, 12, 255])


def test_region_rect_named_regions():
    assert region_rect("full", 3000, 1500) == (0, 0, 3000, 1500)
    assert region_rect("left", 3000, 1500) == (0, 0, 1000, 1500)
    x, y, w, h = region_rect("coaching", 3000, 1500)
    assert (x, y) == (0, 0)
    assert w == 1050 and h == 750  # 0.35 * 3000, 0.5 * 1500


def test_region_rect_unknown_raises():
    with pytest.raises(ValueError, match="unknown region"):
        region_rect("nope", 100, 100)


def test_liveness_score_detects_black_vs_content():
    black = liveness_score(bytes(2000))
    assert black.is_rendering() is False
    content = liveness_score(bytes(range(256)) * 8)
    assert content.is_rendering() is True
    assert liveness_score(b"").is_rendering() is False


def test_liveness_thresholds_configurable():
    score = LivenessScore(mean=5.0, distinct=10)
    assert score.is_rendering(min_mean=2.0, min_distinct=8) is True
    assert score.is_rendering(min_mean=6.0) is False
    assert score.is_rendering(min_distinct=20) is False


def test_bgra_to_rgb_swaps_channels():
    out_w, out_h, rgb = bgra_to_rgb(2, 2, BGRA_2x2)
    assert (out_w, out_h) == (2, 2)
    # BGR -> RGB per pixel.
    assert rgb == bytes([3, 2, 1, 6, 5, 4, 9, 8, 7, 12, 11, 10])


def test_bgra_to_rgb_downsamples_by_stride():
    out_w, out_h, rgb = bgra_to_rgb(2, 2, BGRA_2x2, stride=2)
    assert (out_w, out_h) == (1, 1)
    assert rgb == bytes([3, 2, 1])  # only the top-left pixel


def test_bgra_to_rgb_rejects_bad_stride():
    with pytest.raises(ValueError, match="stride"):
        bgra_to_rgb(2, 2, BGRA_2x2, stride=0)


def test_encode_png_is_valid_and_carries_dims():
    _, _, rgb = bgra_to_rgb(2, 2, BGRA_2x2)
    png = encode_png(2, 2, rgb)
    assert png.startswith(PNG_SIGNATURE)
    # IHDR width/height live right after the 8-byte sig + 4-byte len + 4-byte "IHDR".
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (width, height) == (2, 2)
    assert png.endswith(b"IEND" + (0xAE426082).to_bytes(4, "big"))  # IEND CRC


def test_encode_png_rejects_length_mismatch():
    with pytest.raises(ValueError, match="rgb length"):
        encode_png(2, 2, b"\x00\x00\x00")


def test_save_png_writes_file(tmp_path: Path):
    out = tmp_path / "hud.png"
    w, h = save_png(str(out), 2, 2, BGRA_2x2)
    assert (w, h) == (2, 2)
    assert out.read_bytes().startswith(PNG_SIGNATURE)


def test_capture_bgra_requires_windows(monkeypatch):
    monkeypatch.setattr(hud_capture.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        capture_bgra()


@pytest.mark.parametrize(
    ("bgra", "code"),
    [
        (bytes(range(256)) * 4, 0),  # content -> rendering -> exit 0
        (bytes(4 * 16), 1),  # all-black -> exit 1
    ],
)
def test_main_exit_code_from_liveness(monkeypatch, tmp_path: Path, bgra: bytes, code: int):
    monkeypatch.setattr(
        hud_capture, "capture_region", lambda name="full": (4, len(bgra) // 16, bgra)
    )
    out = tmp_path / "hud.png"
    assert _main(["--out", str(out), "--region", "full"]) == code
    assert out.read_bytes().startswith(PNG_SIGNATURE)
