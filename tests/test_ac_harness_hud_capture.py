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


def test_liveness_score_samples_large_buffer():
    # > 50000 bytes exercises the step>1 sampling path (a full-screen capture is ~20 MB).
    big_content = bytes(range(256)) * 400  # 102_400 bytes -> step = 2
    assert liveness_score(big_content).is_rendering() is True
    assert liveness_score(bytes(102_400)).is_rendering() is False  # all-black, sampled


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


def test_bgra_to_rgb_rejects_short_buffer():
    with pytest.raises(ValueError, match="bgra length"):
        bgra_to_rgb(2, 2, BGRA_2x2[:-4])  # one pixel short


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


def test_periodic_capture_indexes_frames_and_records_errors(tmp_path):
    import json

    calls = []

    def grab(path, region, stride):
        calls.append((path.name, region, stride))
        if len(calls) == 2:
            raise RuntimeError("desktop locked")
        return {"rendering": True, "mean": 55.0, "distinct": 250}

    clock = iter(float(x) for x in range(100, 200))
    cap = hud_capture.PeriodicHudCapture(
        tmp_path / "frames",
        1,
        region="coaching",
        max_frames=2,
        grab=grab,
        clock=lambda: next(clock),
    )
    cap.start()
    cap._thread.join(5)
    summary = cap.stop()
    rows = [json.loads(x) for x in (tmp_path / "frames" / "index.jsonl").read_text().splitlines()]
    assert calls == [("f0001.png", "coaching", 2), ("f0002.png", "coaching", 2)]
    assert rows[0]["rendering"] is True and rows[0]["epoch"] < rows[0]["done_epoch"]
    assert rows[1]["error"] == "RuntimeError: desktop locked"  # recorded, never raised
    assert summary["frames"] == 2 and summary["errors"] == 1


def test_periodic_capture_stop_is_prompt_and_bounded(tmp_path):
    cap = hud_capture.PeriodicHudCapture(
        tmp_path, 30, grab=lambda *_: {"rendering": True, "mean": 1.0, "distinct": 9}
    )
    cap.start()
    assert cap.stop(timeout_s=5)["frames"] == 1  # stop interrupts the 30 s wait
    assert not cap._thread.is_alive()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval_s": 0.5},
        {"interval_s": float("inf")},
        {"interval_s": True},
        {"interval_s": 2, "region": "nope"},
        {"interval_s": 2, "stride": 0},
        {"interval_s": 2, "max_frames": 0},
    ],
)
def test_periodic_capture_rejects_bad_settings(tmp_path, kwargs):
    with pytest.raises(ValueError):
        hud_capture.PeriodicHudCapture(tmp_path, **kwargs)


class _FakeChild:
    """Popen stand-in: finishes with ``out``/``err`` or blocks until terminated/killed."""

    def __init__(self, out="", err="", rc=0, block=False):
        import threading

        self.out, self.err, self.rc, self.block = out, err, rc, block
        self.returncode = None
        self.ended = threading.Event()
        self.killed = self.terminated = False

    def communicate(self, timeout=None):
        import subprocess

        if self.block and not self.ended.wait(timeout):
            raise subprocess.TimeoutExpired("hud_capture", timeout)
        self.returncode = self.rc if not self.block else -15
        return self.out, self.err

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.ended.set()

    def kill(self):
        self.killed = True
        self.ended.set()


def test_grab_frame_subprocess_parses_child_verdict(monkeypatch, tmp_path):
    seen = {}
    out = "hud-capture: BLACK/FROZEN region=full 10x10 -> x.png (5x5) mean=0.4 distinct=1\n"

    def fake_popen(cmd, **kw):
        seen.update(cmd=cmd, cwd=kw.get("cwd"))
        return _FakeChild(out=out, rc=1)

    monkeypatch.setattr(hud_capture.subprocess, "Popen", fake_popen)
    registered = []
    verdict = hud_capture.grab_frame_subprocess(
        tmp_path / "f.png", "full", 2, register=registered.append
    )
    assert verdict == {"rendering": False, "mean": 0.4, "distinct": 1}
    assert seen["cmd"][1:3] == ["-m", "tools.ac_harness.hud_capture"]
    assert seen["cwd"] == hud_capture._REPO_ROOT
    assert isinstance(registered[0], _FakeChild) and registered[-1] is None

    monkeypatch.setattr(
        hud_capture.subprocess, "Popen", lambda *a, **k: _FakeChild(err="no desktop", rc=2)
    )
    with pytest.raises(RuntimeError, match="no desktop"):
        hud_capture.grab_frame_subprocess(tmp_path / "f.png", "full", 2)


def test_grab_frame_subprocess_kills_an_overrunning_child(monkeypatch, tmp_path):
    child = _FakeChild(block=True)
    monkeypatch.setattr(hud_capture.subprocess, "Popen", lambda *a, **k: child)
    with pytest.raises(RuntimeError, match="timed out"):
        hud_capture.grab_frame_subprocess(tmp_path / "f.png", "full", 2, timeout_s=0.05)
    assert child.killed


def test_stop_terminates_an_in_flight_capture_child(monkeypatch, tmp_path):
    import time

    child = _FakeChild(block=True)
    monkeypatch.setattr(hud_capture.subprocess, "Popen", lambda *a, **k: child)
    cap = hud_capture.PeriodicHudCapture(tmp_path, 30)
    cap.start()
    deadline = time.monotonic() + 5
    while cap._child is None and time.monotonic() < deadline:
        time.sleep(0.01)
    t0 = time.monotonic()
    summary = cap.stop(timeout_s=5)
    assert child.terminated and time.monotonic() - t0 < 2  # not the 20 s child timeout
    assert not cap._thread.is_alive()
    assert summary["frames"] == 1 and summary["errors"] == 1
