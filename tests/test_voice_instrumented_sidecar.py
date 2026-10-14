"""Offline diagnostic-wrapper parity; never touch hardware."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.ai_sidecar import server
from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.voice import instrumented_sidecar as instrument
from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.dispatch import DispatchTapPlayback
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler
from tools.ai_sidecar.voice.shadow_replay import _manifest


class Rows:
    run_id = "synthetic-test"

    def __init__(self):
        self.rows = []

    def emit(self, kind, **data):
        self.rows.append(dict(kind=kind, **data))


def pipeline():
    records = []
    playback = DispatchTapPlayback(
        RecordingPlayback(),
        lambda d: records.append(d.to_payload()),
        wall_clock=lambda: 100,
        mono_clock=lambda: 100,
    )
    scheduler = Scheduler(Resolver(_manifest()), playback, VoiceConfig(), clock=lambda: 100)
    low = Advisory("late_brake", 2, 0.3, "prepare", "Prepare", register="calm")
    high = Advisory("late_brake", 2, 0.3, "act", "Brake", register="critical")
    scheduler.submit(low)
    scheduler.process_pending(100)
    scheduler.submit(high)
    scheduler.process_pending(100)
    return records


def test_diagnostics_preserve_actual_resolver_scheduler_playback_decisions():
    expected = pipeline()
    tap = Rows()
    undo = instrument.install(tap)
    try:
        actual = pipeline()
    finally:
        undo()
    assert actual == expected
    assert len(actual) == 2
    dispatched = [row for row in tap.rows if row["kind"] == "voice_dispatch"]
    assert all(row["exact_object_identity"] for row in dispatched)
    assert dispatched[-1]["dispatch"]["corner"] is None
    assert dispatched[-1]["correlation"]["advisory"]["corner"] == 2
    assert [row for row in tap.rows if row["kind"] == "playback_cancel"]
    assert any(row.get("reason") == "barge_in" for row in tap.rows)


def test_async_producer_context_cannot_be_overwritten_by_another_tick(monkeypatch):
    scheduler = Scheduler(
        Resolver(_manifest()), RecordingPlayback(), VoiceConfig(), clock=lambda: 100
    )

    async def source(frame, *, exclude):
        await asyncio.sleep(0)
        scheduler.submit(
            Advisory("late_brake", frame["seq"], 0.3, "act", "Brake", register="critical")
        )

    monkeypatch.setattr(server, "_publish_coaching_cues", source)
    tap = Rows()
    undo = instrument.install(tap)

    async def run():
        await asyncio.gather(
            server._publish_coaching_cues({"seq": 1}, exclude=None),
            server._publish_coaching_cues({"seq": 2}, exclude=None),
        )

    try:
        asyncio.run(run())
    finally:
        undo()
    submitted = [row for row in tap.rows if row["kind"] == "advisory_submitted"]
    assert [
        (row["advisory"]["corner"], row["producer_tick"]["frame"]["seq"]) for row in submitted
    ] == [(1, 1), (2, 2)]


def test_tap_is_exclusive_and_stamped_with_wrapper_hash(tmp_path):
    path = tmp_path / "tap.jsonl"
    tap = instrument.Tap(path)
    tap.emit("producer_tick_ingress", wall_ms=1234, mono_ms=5678, frame={"seq": 1})
    tap.close()
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        instrument.Tap(path)
    assert path.read_bytes() == original
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["instrumented"] is True
    assert len(rows[0]["wrapper_sha256"]) == 64
    assert rows[1]["wall_ms"] == 1234
    assert rows[-1]["dropped"] == 0


def test_tap_reports_changed_instrumented_source(tmp_path):
    source = tmp_path / "owned-source.py"
    source.write_text("initial")
    tap = instrument.Tap(tmp_path / "tap.jsonl")
    tap.source_hashes[str(source)] = instrument.hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("changed")
    tap.close()
    rows = [json.loads(line) for line in (tmp_path / "tap.jsonl").read_text().splitlines()]
    assert rows[-1]["source_hashes_unchanged"] is False


def test_no_stop_file_preserves_arguments_and_normal_return(monkeypatch, tmp_path):
    path = tmp_path / "normal.jsonl"
    seen = []
    monkeypatch.setattr(sys, "argv", ["wrapper", "--tap", str(path), "--", "--port", "9876"])
    monkeypatch.setattr(instrument, "install", lambda tap: lambda: seen.append("undo"))
    monkeypatch.setattr(
        instrument.runpy,
        "run_module",
        lambda module, **kw: seen.append((module, kw, list(sys.argv))),
    )
    instrument.main()
    assert seen == [
        ("tools.ai_sidecar", {"run_name": "__main__"}, ["tools.ai_sidecar", "--port", "9876"]),
        "undo",
    ]
    assert [json.loads(line)["kind"] for line in path.read_text().splitlines()] == [
        "tap_start",
        "tap_end",
    ]


@pytest.mark.parametrize("existing", [False, True])
def test_stop_file_rejects_stale_signal_or_missing_parent_before_creating_tap(
    monkeypatch, tmp_path, existing
):
    stop = tmp_path / "stop" if existing else tmp_path / "absent" / "stop"
    if existing:
        stop.write_text("old owner")
    tap = tmp_path / "tap.jsonl"
    monkeypatch.setattr(sys, "argv", ["wrapper", "--tap", str(tap), "--stop-file", str(stop)])
    with pytest.raises(ValueError, match="startup|parent"):
        instrument.main()
    assert not tap.exists()
    if existing:
        assert stop.read_text() == "old owner"


def test_closed_watcher_cannot_deliver_delayed_interrupt(monkeypatch, tmp_path):
    tap = Rows()
    watcher = instrument.StopFileWatcher(tmp_path / "stop", tap)
    interrupts = []
    monkeypatch.setattr(instrument._thread, "interrupt_main", lambda: interrupts.append(True))
    watcher.start()
    watcher.close()
    watcher._interrupt()
    assert interrupts == []
    assert not watcher.thread.is_alive()
    assert not watcher.path.exists()


def test_real_sigint_wakes_asyncio_and_flushes_tap_after_normal_cleanup(tmp_path):
    # Child process uses the real watcher and asyncio SIGINT handling, but replaces
    # only the sidecar entrypoint: no sockets, rig, playback or audio are opened.
    code = r"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools.ai_sidecar.voice import instrumented_sidecar as instrument
from tools.ai_sidecar import server
root = Path(sys.argv[2])
stop = root / "owned.stop"
tap_path = root / "tap.jsonl"
holder = {}
def install(tap):
    holder["tap"] = tap
    return lambda: tap.emit("instrumentation_undone")
def sidecar(module, *, run_name):
    assert module == "tools.ai_sidecar" and run_name == "__main__"
    assert sys.argv == ["tools.ai_sidecar", "--port", "9876"]
    async def run():
        server._event_loop = asyncio.get_running_loop()
        server._event_loop.call_later(0.1, lambda: stop.write_text("owner requests shutdown"))
        try:
            await asyncio.Future()
        finally:
            server._event_loop = None
            holder["tap"].emit("sidecar_finally")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        holder["tap"].emit("sidecar_keyboard_interrupt_handled")
instrument.install = install
instrument.runpy.run_module = sidecar
sys.argv = ["wrapper", "--tap", str(tap_path), "--stop-file", str(stop), "--", "--port", "9876"]
instrument.main()
assert stop.read_text() == "owner requests shutdown"
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, str(Path(__file__).resolve().parents[1]), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    rows = [json.loads(line) for line in (tmp_path / "tap.jsonl").read_text().splitlines()]
    assert [row["kind"] for row in rows] == [
        "tap_start",
        "stop_file_armed",
        "stop_requested",
        "stop_signal_delivered",
        "sidecar_finally",
        "sidecar_keyboard_interrupt_handled",
        "instrumentation_undone",
        "tap_end",
    ]
    assert rows[-1]["dropped"] == 0
    assert rows[-1]["writer_error"] is None
    assert rows[-1]["source_hashes_unchanged"] is True
