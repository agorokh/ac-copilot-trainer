"""CI-safe tests for the #738 CM "Custom Shaders Patch data" dialog skip watcher.

The policy layer (confirm-before-click, per-window cooldown, forensic counters, thread
lifecycle) is exercised with a fake backend and a fake clock; the raw-ctypes UIA backend is
rig-only and covered by the live synthetic-WPF proof plus rig verification (PR #742).
"""

from __future__ import annotations

import threading
import time

import pytest

from tools.ac_harness import cm_dialog_watcher
from tools.ac_harness.auto_drive import (
    AutoDriveConfig,
    _build_arg_parser,
    _config_from_args,
)
from tools.ac_harness.cm_dialog_watcher import (
    _MAX_TITLES_TRACKED,
    CmSkipWatcher,
    DialogCandidate,
    dialog_skip_enabled,
)


class FakeBackend:
    """SkipBackend stand-in: scripted windows, recorded invokes, injectable faults."""

    def __init__(self) -> None:
        self.windows: list[DialogCandidate] = []
        self.invoked: list[int] = []
        self.invoke_result = True
        self.invoke_error: Exception | None = None
        self.find_error: Exception | None = None
        self.closed = False

    def find_candidates(self) -> list[DialogCandidate]:
        if self.find_error is not None:
            raise self.find_error
        return list(self.windows)

    def invoke_skip(self, hwnd: int) -> bool:
        if self.invoke_error is not None:
            raise self.invoke_error
        self.invoked.append(hwnd)
        return self.invoke_result

    def close(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _make(backend: FakeBackend, clock: FakeClock, **kwargs) -> tuple[CmSkipWatcher, list[str]]:
    lines: list[str] = []
    kwargs.setdefault("confirm_polls", 2)
    kwargs.setdefault("click_cooldown", 5.0)
    watcher = CmSkipWatcher(
        log=lines.append,
        backend_factory=lambda: backend,
        clock=clock,
        **kwargs,
    )
    return watcher, lines


DIALOG = DialogCandidate(hwnd=0x1234, title="Loading data for Custom Shaders Patch")


# ---------------------------------------------------------------------------
# Click policy (synchronous ticks — no thread).
# ---------------------------------------------------------------------------
def test_confirm_polls_gate_before_first_click():
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock)
    backend.windows = [DIALOG]

    watcher._tick(backend)  # first sighting: below the confirm threshold
    assert backend.invoked == []
    watcher._tick(backend)  # second consecutive sighting: click
    assert backend.invoked == [DIALOG.hwnd]
    assert watcher.skips == 1
    assert watcher.clicks_failed == 0


def test_cooldown_blocks_immediate_reclick_then_allows():
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock)
    backend.windows = [DIALOG]

    watcher._tick(backend)
    watcher._tick(backend)
    assert watcher.skips == 1
    clock.now += 1.0
    watcher._tick(backend)  # persisting dialog inside the cooldown: no re-click
    assert watcher.skips == 1
    clock.now += 5.0
    watcher._tick(backend)  # past the cooldown: the multi-category fetch needs another Skip
    assert watcher.skips == 2
    assert backend.invoked == [DIALOG.hwnd, DIALOG.hwnd]


def test_vanished_window_resets_confirmation():
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock)

    backend.windows = [DIALOG]
    watcher._tick(backend)
    backend.windows = []  # dialog closed on its own (healthy fast fetch)
    watcher._tick(backend)
    backend.windows = [DIALOG]  # a NEW dialog at a recycled hwnd
    watcher._tick(backend)
    assert backend.invoked == []  # fresh confirm window; one sighting is not enough
    watcher._tick(backend)
    assert backend.invoked == [DIALOG.hwnd]


def test_new_dialog_after_skip_needs_its_own_confirmation():
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock)
    backend.windows = [DIALOG]
    watcher._tick(backend)
    watcher._tick(backend)
    assert watcher.skips == 1

    follow_up = DialogCandidate(hwnd=0x9999, title="Loading data for Custom Shaders Patch")
    backend.windows = [follow_up]
    watcher._tick(backend)
    assert backend.invoked == [DIALOG.hwnd]  # not yet
    watcher._tick(backend)
    assert backend.invoked == [DIALOG.hwnd, follow_up.hwnd]
    assert watcher.skips == 2


def test_invoke_exception_is_counted_and_polling_continues():
    backend, clock = FakeBackend(), FakeClock()
    watcher, lines = _make(backend, clock)
    backend.windows = [DIALOG]
    backend.invoke_error = RuntimeError("element vanished mid-invoke")

    watcher._tick(backend)
    watcher._tick(backend)
    assert watcher.skips == 0
    assert watcher.clicks_failed == 1
    assert watcher.last_error is not None
    assert DIALOG.title in watcher.last_error
    assert any("error:" in line for line in lines)

    backend.invoke_error = None
    clock.now += 6.0  # the failed click consumed the cooldown slot
    watcher._tick(backend)
    assert watcher.skips == 1


def test_invoke_returning_false_counts_as_failed_click():
    backend, clock = FakeBackend(), FakeClock()
    watcher, lines = _make(backend, clock)
    backend.windows = [DIALOG]
    backend.invoke_result = False

    watcher._tick(backend)
    watcher._tick(backend)
    assert watcher.skips == 0
    assert watcher.clicks_failed == 1
    assert any("vanished before invoke" in line for line in lines)


def test_scan_failure_recorded_and_logged_once_per_distinct_message():
    backend, clock = FakeBackend(), FakeClock()
    watcher, lines = _make(backend, clock)
    backend.find_error = RuntimeError("COM said no")

    watcher._tick(backend)
    watcher._tick(backend)
    error_lines = [line for line in lines if "error:" in line]
    assert len(error_lines) == 1  # identical message deduplicated
    assert watcher.last_error is not None and "COM said no" in watcher.last_error

    backend.find_error = RuntimeError("different fault")
    watcher._tick(backend)
    error_lines = [line for line in lines if "error:" in line]
    assert len(error_lines) == 2  # a new message is worth a new line


def test_failed_scan_resets_pending_confirmation():
    # Codex #743: a transient scan failure must invalidate a pending confirmation so a window
    # seen once → fault → seen again is NOT clicked on the second sighting (that would bypass the
    # confirm-before-click gate via a UIA glitch).
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock, confirm_polls=2)
    backend.windows = [DIALOG]
    watcher._tick(backend)  # sighting 1
    backend.find_error = RuntimeError("uia glitch")
    watcher._tick(backend)  # scan fails → confirmation reset
    backend.find_error = None
    backend.windows = [DIALOG]
    watcher._tick(backend)  # sighting 1 again (not 2) → must NOT click
    assert backend.invoked == []
    watcher._tick(backend)  # sighting 2 → click
    assert backend.invoked == [DIALOG.hwnd]


def test_start_returns_false_when_thread_cannot_start(monkeypatch):
    # Codex #743: the watcher is best-effort — a failure to spawn its thread must never raise into
    # the launch path; start() records it and returns False.
    class BoomThread:
        def __init__(self, *a, **k) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("cannot allocate thread")

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(cm_dialog_watcher.threading, "Thread", BoomThread)
    lines: list[str] = []
    watcher = CmSkipWatcher(backend_factory=lambda: FakeBackend(), log=lines.append)
    assert watcher.start() is False
    assert not watcher.running
    assert watcher.last_error is not None and "could not start watcher thread" in watcher.last_error


def test_skip_count_accessor_is_lock_guarded_and_current():
    # Codex #743: launch paths must read the skip count through this accessor (lock-guarded),
    # not the raw attribute.
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock)
    assert watcher.skip_count() == 0
    backend.windows = [DIALOG]
    watcher._tick(backend)
    watcher._tick(backend)
    assert watcher.skip_count() == 1


def test_summary_and_as_dict_report_forensics():
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock)
    assert watcher.summary() is None

    backend.windows = [DIALOG]
    watcher._tick(backend)
    watcher._tick(backend)
    summary = watcher.summary()
    assert summary is not None and "csp_dialog_skips=1" in summary

    snapshot = watcher.as_dict()
    assert snapshot["skips"] == 1
    assert snapshot["clicks_failed"] == 0
    assert snapshot["titles_seen"] == {DIALOG.title: 2}


def test_titles_seen_is_bounded():
    backend, clock = FakeBackend(), FakeClock()
    watcher, _lines = _make(backend, clock, confirm_polls=99)  # observe only, never click
    for index in range(_MAX_TITLES_TRACKED + 8):
        backend.windows = [DialogCandidate(hwnd=0x1000 + index, title=f"window {index}")]
        watcher._tick(backend)
    assert len(watcher.titles_seen) == _MAX_TITLES_TRACKED


# ---------------------------------------------------------------------------
# Thread lifecycle.
# ---------------------------------------------------------------------------
def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_thread_lifecycle_clicks_then_stops_and_closes_backend():
    backend = FakeBackend()
    backend.windows = [DIALOG]
    watcher = CmSkipWatcher(
        backend_factory=lambda: backend,
        poll_interval=0.01,
        confirm_polls=1,
        click_cooldown=0.0,
    )
    assert watcher.start() is True
    assert watcher.start() is True  # idempotent
    assert _wait_until(lambda: watcher.skips >= 1)
    watcher.stop()
    watcher.stop()  # safe to repeat
    assert not watcher.running
    assert backend.closed


def test_context_manager_arms_and_disarms():
    backend = FakeBackend()
    backend.windows = [DIALOG]
    with CmSkipWatcher(
        backend_factory=lambda: backend,
        poll_interval=0.01,
        confirm_polls=1,
    ) as watcher:
        assert _wait_until(lambda: watcher.skips >= 1)
    assert not watcher.running
    assert backend.closed


def test_backend_factory_failure_is_recorded_not_raised():
    def exploding_factory():
        raise RuntimeError("no COM today")

    watcher = CmSkipWatcher(backend_factory=exploding_factory, poll_interval=0.01)
    assert watcher.start() is True
    assert _wait_until(lambda: watcher.last_error is not None)
    watcher.stop()
    assert watcher.last_error is not None and "backend init failed" in watcher.last_error
    assert watcher.skips == 0


def test_start_is_disabled_without_uia_and_without_injected_backend(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(cm_dialog_watcher, "available", lambda: False)
    watcher = CmSkipWatcher(log=lines.append)
    assert watcher.start() is False
    assert not watcher.running
    assert any("disabled" in line for line in lines)


class SlowBackend(FakeBackend):
    """find_candidates blocks until released — models a UIA scan outlasting stop()'s join."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def find_candidates(self):
        self.entered.set()
        self.release.wait(timeout=5.0)
        return super().find_candidates()


def test_stop_keeps_thread_reference_when_join_times_out():
    # Codex #743: if the scan outlasts stop()'s join, the live thread must NOT be dropped —
    # otherwise `running` reads False and a second start() spawns a coexisting watcher.
    backend = SlowBackend()
    backend.windows = [DIALOG]
    watcher = CmSkipWatcher(
        backend_factory=lambda: backend,
        poll_interval=0.01,
        confirm_polls=1,
        join_timeout=0.05,
    )
    watcher.start()
    assert backend.entered.wait(timeout=5.0)  # thread is blocked inside the scan
    watcher.stop()  # join times out — thread still alive
    assert watcher.running  # reference retained, not dropped
    backend.release.set()  # let the blocked scan finish
    assert _wait_until(lambda: not watcher.running)


class HangingInvokeBackend(FakeBackend):
    """invoke_skip blocks until released — models a hung cross-process UIA invoke."""

    def __init__(self) -> None:
        super().__init__()
        self.invoke_entered = threading.Event()
        self.release = threading.Event()

    def invoke_skip(self, hwnd: int) -> bool:
        self.invoke_entered.set()
        self.release.wait(timeout=10.0)
        return super().invoke_skip(hwnd)


def test_stop_is_bounded_even_while_an_invoke_hangs():
    # Codex #743 P1: stop() must NOT block on _invoke_lock while a cross-process invoke_skip is
    # hung, or every launch path's stop() would freeze. It sets the event first (no lock) and the
    # bounded join returns; the thread ref is retained (join timed out on the stuck invoke).
    backend = HangingInvokeBackend()
    backend.windows = [DIALOG]
    watcher = CmSkipWatcher(
        backend_factory=lambda: backend,
        poll_interval=0.01,
        confirm_polls=1,
        click_cooldown=0.0,
        join_timeout=0.1,
    )
    watcher.start()
    assert backend.invoke_entered.wait(timeout=5.0)  # a click is in-flight, holding _invoke_lock
    start = time.monotonic()
    watcher.stop()  # must return promptly, not deadlock on the lock
    assert (time.monotonic() - start) < 3.0
    assert watcher._stop_event.is_set()
    backend.release.set()  # let the hung invoke finish
    assert _wait_until(lambda: not watcher.running)


def test_in_flight_tick_does_not_click_after_stop_requested():
    # Codex #743: a stop requested while blocked in the scan must suppress the click.
    backend = SlowBackend()
    backend.windows = [DIALOG]
    watcher = CmSkipWatcher(
        backend_factory=lambda: backend,
        poll_interval=0.01,
        confirm_polls=1,
        join_timeout=0.05,
    )
    watcher.start()
    assert backend.entered.wait(timeout=5.0)
    watcher._stop_event.set()  # request stop while the scan is blocked
    backend.release.set()  # scan returns a candidate, but the post-scan guard must skip it
    assert _wait_until(lambda: not watcher.running)
    assert backend.invoked == []
    assert watcher.skips == 0


# ---------------------------------------------------------------------------
# Env / CLI opt-out resolution (#738 / Codex #743).
# ---------------------------------------------------------------------------
def test_dialog_skip_enabled_default_on_and_cli_opt_out():
    assert dialog_skip_enabled(False, env={}) is True
    assert dialog_skip_enabled(True, env={}) is False


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "disable", "DISABLED", " No "])
def test_env_kill_switch_disables(value):
    assert dialog_skip_enabled(False, env={"AC_COPILOT_CM_DIALOG_SKIP": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "", "on", "please"])
def test_env_non_disable_values_keep_it_on(value):
    assert dialog_skip_enabled(False, env={"AC_COPILOT_CM_DIALOG_SKIP": value}) is True


# ---------------------------------------------------------------------------
# auto_drive seam: config default + CLI opt-out (#738).
# ---------------------------------------------------------------------------
def test_cm_dialog_skip_defaults_on_and_cli_flag_disables():
    assert AutoDriveConfig.cm_dialog_skip is True
    base = ["--car", "ks_porsche_911_gt3_r_2016", "--track", "spa"]
    assert _config_from_args(_build_arg_parser().parse_args(base)).cm_dialog_skip is True
    assert (
        _config_from_args(
            _build_arg_parser().parse_args(base + ["--no-cm-dialog-skip"])
        ).cm_dialog_skip
        is False
    )


def test_resilient_launch_cli_accepts_no_cm_dialog_skip():
    # The resilient_launch parser is built inside its rig-only main(); the flag's presence is
    # asserted at the source level so a rename cannot silently orphan the supervisor path.
    import inspect

    from tools.ac_harness import resilient_launch

    source = inspect.getsource(resilient_launch.main)
    assert '"--no-cm-dialog-skip"' in source
    assert "CmSkipWatcher" in source
    # The env kill-switch resolution must be wired (Codex #743: Game Point's frozen child
    # cannot receive the CLI arg, so the env override is its only opt-out).
    assert "dialog_skip_enabled" in source


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
