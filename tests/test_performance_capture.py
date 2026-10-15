"""CSP interval identity/pause/bounds and measured distribution provenance (#854)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ac_harness.performance_capture import summarize_capture
from tools.ai_sidecar.external_protocol import validate_inbound


def recorder():
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    source = (
        Path(__file__).resolve().parents[1]
        / "src/ac_copilot_trainer/modules/performance_capture.lua"
    )
    module = lua.execute(source.read_text())
    capture = module.new()
    chunks = []

    def publish(topic, payload):
        assert topic == "performance.frames"
        chunk = {key: value for key, value in payload.items() if key != "rows"}
        chunk["rows"] = [dict(payload.rows[i].items()) for i in range(1, len(payload.rows) + 1)]
        chunks.append(chunk)

    assert capture.start(capture, lua.table_from({"capture_id": "test-1", "seconds": 1}), 0)[0]
    return capture, chunks, publish


def test_render_interval_dedup_pause_and_complete_round_trip():
    capture, chunks, publish = recorder()
    capture.tick(capture, 100, 0.016, False, 0.01, publish)
    capture.tick(capture, 100, 0.016, False, 0.015, publish)  # same render frame
    capture.tick(capture, 101, 0.020, True, 0.03, publish)  # UI still advances while paused
    capture.tick(capture, 102, 0.030, False, 0.06, publish)
    capture.tick(capture, 103, 0.020, False, 1.01, publish)
    assert capture.active is False
    result = summarize_capture(chunks)
    assert result["sample_count"] == 3 and result["active_samples"] == 2
    assert result["paused_samples"] == 1 and result["duplicates_ignored"] == 1
    assert result["p50_ms"] == 16 and result["p99_ms"] == 30
    assert result["elapsed_s"] == 1.01


@pytest.mark.parametrize(
    "frame,dt,reason",
    [(0, 0.02, "frame_reset"), (3, 0.02, "duration"), (2, float("nan"), "duration")],
)
def test_gaps_resets_and_invalid_dt_cannot_certify_frame_distribution(frame, dt, reason):
    capture, chunks, publish = recorder()
    capture.tick(capture, 1, 0.016, False, 0.01, publish)
    capture.tick(capture, frame, dt, False, 0.02, publish)
    capture.tick(capture, frame, dt, False, 1.01, publish)
    assert chunks[-1]["reason"] == reason
    with pytest.raises(ValueError):
        summarize_capture(chunks)


def test_capture_does_not_record_when_off_or_grow_beyond_bounds():
    capture, chunks, publish = recorder()
    for frame in range(1, 20001):
        capture.tick(capture, frame, 0.001, False, frame / 100000, publish)
    assert capture.active is False and chunks[-1]["reason"] == "sample_limit"
    assert all(len(chunk["rows"]) <= 128 for chunk in chunks)
    capture.tick(capture, 20001, 0.016, False, 0.5, publish)
    assert chunks[-1]["sample_count"] == 20000
    assert summarize_capture(chunks)["sample_count"] == 20000


def test_reordered_or_missing_chunks_are_not_accepted():
    capture, chunks, publish = recorder()
    for frame in range(1, 131):
        capture.tick(capture, frame, 0.005, False, frame / 1000, publish)
    capture.tick(capture, 131, 0.005, False, 1.1, publish)
    assert len(chunks) == 2
    with pytest.raises(ValueError, match="missing/reordered"):
        summarize_capture(chunks[1:])
    with pytest.raises(ValueError, match="missing/reordered"):
        summarize_capture(list(reversed(chunks)))


def test_existing_protocol_accepts_diagnostic_action_and_topic():
    assert (
        validate_inbound(
            {
                "v": 1,
                "type": "action",
                "name": "capturePerformance",
                "args": {"capture_id": "rules-1", "seconds": 60},
            }
        )
        is None
    )
    assert (
        validate_inbound({"v": 1, "type": "state.subscribe", "topics": ["performance.frames"]})
        is None
    )


def test_luajit_ffi_integer_frame_identity_is_exactly_bounded():
    luajit = pytest.importorskip("lupa.luajit21")
    lua = luajit.LuaRuntime(unpack_returned_tuples=True)
    source = (
        Path(__file__).resolve().parents[1]
        / "src/ac_copilot_trainer/modules/performance_capture.lua"
    )
    lua.globals().capture_module = lua.execute(source.read_text())
    lua.execute("""
      local ffi = require('ffi')
      local cap = capture_module.new()
      chunks = {}
      local publish = function(_, p) chunks[#chunks + 1] = p end
      assert(cap:start({capture_id='ffi-proof', seconds=1}, 0))
      cap:tick(ffi.new('uint64_t', 100), 0.016, false, 0.01, publish)
      cap:tick(ffi.new('uint64_t', 100), 0.016, false, 0.02, publish)
      cap:tick(ffi.new('uint64_t', 101), 0.020, false, 0.03, publish)
      cap:tick(ffi.new('uint64_t', 102), 0.020, false, 1.01, publish)
      assert(chunks[1].sample_count == 2 and chunks[1].duplicates == 1)
      assert(chunks[1].raw_frame_type == 'cdata' and chunks[1].rows[1].frame == 100)
      assert(cap:start({capture_id='unsafe-int', seconds=1}, 2))
      cap:tick(ffi.new('uint64_t', 9007199254740992), 0.02, false, 2.01, publish)
      assert(chunks[2].reason == 'invalid_frame' and chunks[2].sample_count == 0)
    """)
