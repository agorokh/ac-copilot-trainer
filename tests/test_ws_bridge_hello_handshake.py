"""Regression test for #170 — the trainer's v1 hello handshake with the sidecar.

Found in-sim on AG_PC: the trainer connected at the WS layer but never registered
as a v1 peer, so ``coaching.snapshot`` was rejected and never fanned out (to the
rig screen or a harness tap). Three coupled defects, all asserted here under lupa
with NO Assetto Corsa and NO sidecar:

1. ``publishTopic`` published a ``state.snapshot`` before the hello handshake
   completed (guarded only on ``sock``) -> the sidecar rejected it.
2. The sidecar's ``{v:1,type:"error"}`` rejection is itself a v1 frame, and the
   recv path marked ``sidecarProtocolReady`` true for *any* v1 frame -> the hello
   retry was cancelled and the peer stranded unregistered forever.
3. The hello retry was paced on sim-time, which is frozen in the pre-drive pit
   menu, so it fired only once and never recovered from a first send that lost
   the CSP ``web.socket`` writable race.

These tests exercise the Lua recv/tick path directly so the regression cannot
recur unnoticed (off-sim L0 — the EPIC #154 layer that should have caught it).
"""

from __future__ import annotations

import json
import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"

# Minimal CSP-ish globals ws_bridge touches. `web.socket` captures the recv
# callback and counts sends; the returned socket is a callable table (CSP
# sockets are callables — `sock(json)` sends), matching `M.sendJson`.
_STUB = r"""
ac = { log = function() end, getFolder = function() return "" end, FolderID = { Root = 0 } }
os = os or {}
web = {}
_ws_on_recv = nil
_ws_on_open = nil
_ws_on_opens = {}
_ws_sent = 0
function web.socket(_u, cb, _p)
  _ws_on_recv = cb
  _ws_on_open = _p and _p.onOpen or nil
  _ws_on_opens[#_ws_on_opens + 1] = _ws_on_open
  local s = { close = function() end }
  setmetatable(s, { __call = function(_, _data) _ws_sent = _ws_sent + 1 end })
  return s
end
"""


def _runtime() -> lupa.LuaRuntime:
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(_STUB)
    p = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{p}/?.lua"')
    g = rt.globals()

    def _parse(s):
        if not isinstance(s, str):
            s = str(s)
        return rt.table_from(json.loads(s))

    def _stringify(t, pretty=False):
        # Content is irrelevant to these tests (we assert on state + return
        # values, not wire bytes); just hand sendJson a non-empty string.
        return "{}"

    g["JSON"] = rt.table_from({"parse": _parse, "stringify": _stringify})
    return rt


def _open(rt) -> None:
    rt.execute('local wb = require("ws_bridge"); wb.configure("ws://127.0.0.1:8765"); wb.tick(0)')
    assert rt.eval("_ws_on_recv ~= nil"), "socket should have opened on first tick"


def _inject(rt, frame: dict) -> None:
    rt.globals()["_inject_payload"] = json.dumps(frame)
    rt.execute("_ws_on_recv(_inject_payload)")
    rt.execute('local wb = require("ws_bridge"); wb.tick(0); wb.pollInbound(8)')


def _connected(rt) -> bool:
    return bool(rt.eval('require("ws_bridge").sidecarConnected()'))


def _epoch(rt) -> int:
    return int(rt.eval('require("ws_bridge").openEpoch()'))


def test_publish_is_gated_until_hello_ack():
    rt = _runtime()
    _open(rt)
    # Before hello_ack we are not a registered peer...
    assert _connected(rt) is False
    # ...so publishTopic must NOT emit a state.snapshot (fix #1).
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is False


def test_error_frame_does_not_register_peer():
    rt = _runtime()
    _open(rt)
    _inject(
        rt,
        {
            "v": 1,
            "type": "error",
            "message": "peer must send hello before other frame types",
            "ref_type": "state.snapshot",
        },
    )
    # An error frame is a v1 frame but must NOT flip readiness (fix #2), or the
    # hello retry below would be cancelled and we'd never register.
    assert _connected(rt) is False


def test_hello_retry_is_frame_paced_under_frozen_sim_clock():
    rt = _runtime()
    _open(rt)
    sent_before = int(rt.eval("_ws_sent"))
    # All ticks pass simTime=0 (frozen pit-menu clock). A sim-time gate would
    # fire once; the frame-paced retry (fix #3) fires repeatedly.
    rt.execute('local wb = require("ws_bridge"); for _ = 1, 30 do wb.tick(0) end')
    assert int(rt.eval("_ws_sent")) > sent_before


def test_hello_ack_registers_and_unblocks_publish():
    rt = _runtime()
    _open(rt)
    assert _connected(rt) is False
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    assert _connected(rt) is True
    # With the handshake complete, coaching.snapshot publishing resumes.
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is True


def test_setup_store_registration_failure_is_backed_off():
    rt = _runtime()
    _open(rt)
    rt.execute(
        'require("ws_bridge").setSetupExperimentStorePath('
        '"C:/Assetto Corsa/apps/lua/ac_copilot_trainer/journal/setup_experiments/experiments.jsonl"'
        ")"
    )
    sent_before = int(rt.eval("_ws_sent"))
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    sent_after_registration = int(rt.eval("_ws_sent"))
    assert sent_after_registration == sent_before + 1

    _inject(
        rt,
        {
            "v": 1,
            "type": "setup.experiment.store.ack",
            "ok": False,
            "error": "permission denied",
        },
    )
    sent_after_failed_ack = int(rt.eval("_ws_sent"))
    for _ in range(20):
        _inject(rt, {"v": 1, "type": "state.snapshot", "topic": "session", "payload": {}})

    assert int(rt.eval("_ws_sent")) == sent_after_failed_ack


def test_setup_store_registration_retries_after_backoff_without_inbound_frames():
    rt = _runtime()
    _open(rt)
    rt.execute(
        'require("ws_bridge").setSetupExperimentStorePath('
        '"C:/Assetto Corsa/apps/lua/ac_copilot_trainer/journal/setup_experiments/experiments.jsonl"'
        ")"
    )
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    _inject(
        rt,
        {
            "v": 1,
            "type": "setup.experiment.store.ack",
            "ok": False,
            "error": "permission denied",
        },
    )
    sent_after_failed_ack = int(rt.eval("_ws_sent"))

    rt.execute('local wb = require("ws_bridge"); for _ = 1, 300 do wb.tick(0) end')
    assert int(rt.eval("_ws_sent")) == sent_after_failed_ack

    rt.execute('require("ws_bridge").tick(0)')
    assert int(rt.eval("_ws_sent")) == sent_after_failed_ack + 1


def test_setup_path_frames_require_loopback_url():
    rt = _runtime()
    rt.execute('local wb = require("ws_bridge"); wb.configure("ws://192.0.2.10:8765"); wb.tick(0)')
    assert rt.eval("_ws_on_recv ~= nil"), "socket should have opened on first tick"
    rt.execute(
        'require("ws_bridge").setSetupExperimentStorePath('
        '"C:/Assetto Corsa/apps/lua/ac_copilot_trainer/journal/setup_experiments/experiments.jsonl"'
        ")"
    )
    sent_before = int(rt.eval("_ws_sent"))

    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})

    assert int(rt.eval("_ws_sent")) == sent_before
    assert (
        rt.eval(
            'require("ws_bridge").sendSetupExperimentRecord('
            '"C:/Assetto Corsa/apps/lua/ac_copilot_trainer/journal/laps/lap_1.json")'
        )
        is False
    )
    assert int(rt.eval("_ws_sent")) == sent_before


def test_legacy_protocol_frame_does_not_unblock_v1_publish():
    # chatgpt-codex P1 on PR #171: the v1 publish path must require the v1 hello
    # handshake, not just any-protocol readiness. A legacy protocol=1 reply (e.g.
    # corner_advice) sets the legacy `sidecarProtocolReady` but NOT v1 registration
    # — publishTopic must stay blocked until the real v1 hello_ack arrives, else
    # the sidecar (which only fans to v1 _external_peers) rejects the snapshot.
    rt = _runtime()
    _open(rt)
    _inject(
        rt,
        {"protocol": 1, "event": "corner_advice", "corner": "T1", "text": "lift", "lap": 0},
    )
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is False
    # Only a v1 hello_ack opens the v1 publish path.
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is True


def test_reconnect_via_onopen_rearms_handshake():
    # CodeRabbit Major on PR #171: with reconnect=true, CSP auto-reconnects by
    # firing onOpen WITHOUT calling tryOpen. The handshake gating must re-arm on
    # that new transport session, or a stale externalHelloAcked would suppress the
    # hello retry and leave us unregistered with the sidecar's new connection.
    rt = _runtime()
    _open(rt)
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is True

    # Simulate a CSP auto-reconnect: onOpen fires on the new socket, no tryOpen.
    assert rt.eval("_ws_on_open ~= nil"), "ws_bridge must register an onOpen callback"
    sent_before = int(rt.eval("_ws_sent"))
    rt.execute("_ws_on_open()")
    # Re-armed: publishing is gated again until a fresh hello_ack...
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is False
    # ...and a hello was re-announced on the new session.
    assert int(rt.eval("_ws_sent")) > sent_before
    # A fresh hello_ack re-registers us.
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    assert rt.eval('require("ws_bridge").publishTopic("coaching.snapshot", {})') is True


def test_open_epoch_detects_subframe_reconnect_while_connected_boolean_stays_true():
    # Issue #183: the entry script samples sidecarConnected() once per frame.
    # A CSP auto-reconnect can fire onOpen and receive hello_ack between samples,
    # leaving the boolean true before and after. openEpoch must still advance so
    # script.update can re-arm lifecycle `session`.
    rt = _runtime()
    _open(rt)
    assert _epoch(rt) == 0

    assert rt.eval("_ws_on_open ~= nil"), "ws_bridge must register an onOpen callback"
    rt.execute("_ws_on_open()")
    assert _epoch(rt) == 1
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    assert _connected(rt) is True
    connected_before = _connected(rt)
    epoch_before = _epoch(rt)

    # Entire reconnect + hello_ack sequence happens between two app update polls.
    rt.execute("_ws_on_open()")
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})

    assert connected_before is True
    assert _connected(rt) is True
    assert _epoch(rt) == epoch_before + 1


def test_stale_onopen_from_replaced_socket_is_ignored():
    # CodeRabbit on #197: onClose already ignores stale callbacks from replaced
    # handles. onOpen needs the same guard, or a late callback can bump the epoch
    # and reset readiness for the active socket.
    rt = _runtime()
    _open(rt)
    rt.execute("_ws_on_open()")
    _inject(rt, {"v": 1, "type": "hello_ack", "server_version": "1.0.0"})
    assert _connected(rt) is True
    assert _epoch(rt) == 1

    # Reconfigure onto a replacement socket, then invoke the original callback.
    rt.execute('local wb = require("ws_bridge"); wb.configure("ws://127.0.0.1:9876"); wb.tick(0)')
    assert int(rt.eval("#_ws_on_opens")) == 2
    epoch_before = _epoch(rt)
    sent_before = int(rt.eval("_ws_sent"))

    rt.execute("_ws_on_opens[1]()")

    assert _epoch(rt) == epoch_before
    assert int(rt.eval("_ws_sent")) == sent_before
