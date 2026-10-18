"""Frame-hitch watchdog: attributes a main-thread freeze to the trainer's own sections or not."""

from __future__ import annotations

from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules/frame_hitch.lua"


def watchdog(threshold=0.25, max_logs=40):
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(SOURCE.read_text())
    now = [0.0]
    lines = []
    hitch = module.new(
        lua.table_from(
            {
                "clock": lambda: now[0],
                "log": lines.append,
                "threshold": threshold,
                "maxLogs": max_logs,
            }
        )
    )
    return lua, hitch, now, lines


def run_update(hitch, now, body_seconds, marks=()):
    """One wrapped `script.update`: frame() first, marks inside, the whole call charged after."""
    start = now[0]
    hitch.frame(hitch, "ctx")
    for name, seconds in marks:
        now[0] += seconds
        hitch.mark(hitch, name)
    now[0] = start + body_seconds
    hitch.add(hitch, "update", body_seconds)


def test_quiet_frames_log_nothing():
    _, hitch, now, lines = watchdog()
    for _ in range(5):
        run_update(hitch, now, 0.002)
        now[0] += 0.014
    assert lines == []


def test_hitch_in_our_section_is_attributed_to_it():
    _, hitch, now, lines = watchdog()
    run_update(hitch, now, 0.002)
    run_update(hitch, now, 2.1, marks=[("u:wsTick", 0.001), ("u:archiveJobs", 2.09)])
    now[0] += 0.01
    hitch.frame(hitch, "ctx")
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("[COPILOT][HITCH] gap=2.11s ours=2100ms ")
    # The biggest section leads; sub-sections are listed but not double-counted in `ours`.
    assert line.split()[3] == "update=2100ms"
    assert "u:archiveJobs=2090ms" in line
    assert line.endswith(" ctx")


def test_hitch_outside_the_trainer_reports_near_zero_ours():
    _, hitch, now, lines = watchdog()
    run_update(hitch, now, 0.002)
    now[0] += 3.0  # main thread busy elsewhere (CSP, a Python app, AC itself)
    hitch.frame(hitch, None)
    assert lines == ["[COPILOT][HITCH] gap=3.00s ours=2ms update=2ms"]


def test_context_function_is_called_only_when_logging():
    lua, hitch, now, lines = watchdog()
    calls = []

    def py_context():
        calls.append(1)
        return "speed=120"

    # A real Lua function, as the trainer passes; the module type-checks for "function".
    context = lua.eval("function(f) return function() return f() end end")(py_context)

    hitch.frame(hitch, context)
    now[0] += 0.016
    hitch.frame(hitch, context)
    assert calls == []
    now[0] += 1.0
    hitch.frame(hitch, context)
    assert calls == [1]
    assert lines[-1].endswith(" speed=120")


def test_log_count_is_bounded():
    _, hitch, now, lines = watchdog(max_logs=2)
    for _ in range(5):
        hitch.frame(hitch, None)
        now[0] += 1.0
    assert len(lines) == 2


def test_wrap_charges_the_callback_and_propagates_errors():
    lua, hitch, now, _ = watchdog()

    def slow(_dt):
        now[0] += 0.5

    wrapped = hitch.wrap(hitch, "windowMain", slow)
    wrapped(0.016)
    assert hitch.sections["windowMain"] == pytest.approx(0.5)

    failing = hitch.wrap(hitch, "Draw3D", lua.eval("function() error('boom') end"))
    with pytest.raises(Exception, match="boom"):
        failing()
