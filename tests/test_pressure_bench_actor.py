"""Deterministic actor tests: no simulator, rig, network, oracle or raw archives."""

from __future__ import annotations

import ast
import asyncio
import copy
import io as stdio
import json
from pathlib import Path

import pytest

from tools import pressure_bench_actor as actor


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeIO:
    def __init__(self, clock):
        self.clock = clock
        self.requests, self.taps, self.polls = [], [], 0
        self.values = {key: 24.0 for key in actor.PRESSURES}
        self.writes, self.geometry_delay = 0, 1
        self.after_statuses = ["accepted_unverified", "verified_applied"]
        self.capture_error = self.touch_error = False
        self.audit_epoch = "native-runtime"
        self.wrong_correlation = self.changed_identity = False
        self.extra_write = self.unexpected_corner = False
        self.card = {
            "mode": "ai_bench",
            "run_id": "opaque-run",
            "prescription_id": "immutable-card",
            "status": "proposed",
            "summary": "956 AI BENCH: LF pressure high",
            "evidence": "Laps 3-4 measured LF 30 psi",
            "reason": "",
            "changes": [{"section": "PRESSURE_LF", "from": 24.0, "to": 23.0, "delta_psi": -1.0}],
        }

    async def request(self, frame, reply, *, budget_s):
        self.clock.now += 1
        self.requests.append(copy.deepcopy(frame))
        result = {"v": 1, "type": reply, "request_id": frame["request_id"], "ok": True}
        if self.wrong_correlation:
            result["request_id"] = "unrelated-reply"
        if frame["type"] == "setup.spinner.list":
            result.update(
                source="csp",
                spinners=[
                    {
                        "section": key,
                        "value": value,
                        "min": 16,
                        "max": 35,
                        "step": 1,
                        "unit": "psi",
                        "range_known": True,
                        "read_only": False,
                        "display_multiplier": 1,
                    }
                    for key, value in self.values.items()
                ],
            )
        elif frame["type"] == "setup.spinner.audit":
            result.update(
                session_id="native-session",
                audit_epoch=self.audit_epoch,
                attempts=self.writes,
                writes=self.writes,
                csp_setter=self.writes,
                ini_write=0,
                setup_load=0,
                counter_semantics="native_mutation_dispatches_including_refusal_or_unknown",
            )
        elif frame["type"] == "setup.bench.get":
            result.update(copy.deepcopy(self.card))
            if frame.get("prescription_id"):
                assert frame["prescription_id"] == self.card["prescription_id"]
                status = self.after_statuses[min(self.polls, len(self.after_statuses) - 1)]
                self.polls += 1
                result.update(status=status, decision="accept", decided_at=1234.5)
                if self.changed_identity:
                    result["prescription_id"] = "another-card"
        else:
            pytest.fail("Actor attempted an unsupported direct RPC")
        return result

    async def capture(self, *, budget_s):
        self.clock.now += 1
        if self.capture_error:
            raise OSError("simulated capture failure")
        return b"\x89PNG\r\n\x1a\nFAKE-IO-FIXTURE", 320, 480

    async def geometry(self, *, budget_s):
        self.clock.now += self.geometry_delay
        return {"accept_x": 70, "accept_y": 340, "prescription_id": "immutable-card"}

    async def touch(self, coordinates, *, budget_s):
        self.clock.now += 1
        self.taps.append(coordinates)
        if self.touch_error:
            raise OSError("unknown touch outcome")
        self.writes += 1 + int(self.extra_write)
        self.values["PRESSURE_LF"] = 23
        if self.unexpected_corner:
            self.values["PRESSURE_RR"] = 25
        return {"v": 1, "type": "screen.touch.ack", "ok": True}

    async def pause(self, *, budget_s):
        self.clock.now += 0.2

    def ready(self, path):
        assert path.name == "ready.json"


def execute(tmp_path, change=None, *, started_at=1000.0):
    clock = Clock()
    io = FakeIO(clock)
    if change:
        change(io)
    config = actor.Config("opaque-run", tmp_path, started_at)
    result = asyncio.run(actor.Actor(config, io, clock=clock).run())
    return result, io


def test_proposed_case_taps_once_polls_immutable_read_and_verifies_all_four(tmp_path):
    result, io = execute(tmp_path)
    assert result["verdict"] == "PASS"
    assert io.taps == [(70, 340)]
    assert io.polls == 2
    assert result["readback"]["PRESSURE_RR"]["value"] == 24
    assert result["audit_delta"]["writes"] == 1
    assert result["llm_inference_calls"] == 0 and result["prompt_hash"] == "not_applicable"
    assert result["duration_s"] < 90
    assert all(frame["type"] in actor.READ_TYPES for frame in io.requests)
    assert all(
        frame["prescription_id"] == "immutable-card"
        for frame in io.requests
        if frame.get("prescription_id")
    )
    assert (tmp_path / "before.png").is_file() and (tmp_path / "after.png").is_file()
    assert json.loads((tmp_path / "ready.json").read_text())["needs_geometry"] is True


def test_explicit_durable_abstention_never_waits_geometry_or_touches(tmp_path):
    def abstain(io):
        io.card.update(
            status="abstained",
            changes=[],
            reason="Cold outlap",
            decision="abstain",
            decided_at=1234.5,
        )
        io.geometry_delay = 1000  # would fail immediately if the branch requested geometry

    result, io = execute(tmp_path, abstain)
    assert result["verdict"] == "PASS" and io.taps == []
    assert result["audit_delta"]["writes"] == 0
    assert all(result["readback"][key]["value"] == 24 for key in actor.PRESSURES)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda io: io.card.update(mode="production"),
        lambda io: io.card.update(run_id="other-run"),
        lambda io: io.card.update(status="verified_applied", decision="accept", decided_at=1234),
        lambda io: io.card["changes"][0].update(to=23.5, delta_psi=-0.5),
        lambda io: io.card["changes"][0].update(delta_psi=-2),
        lambda io: io.card["changes"].append(copy.deepcopy(io.card["changes"][0])),
        lambda io: setattr(io, "wrong_correlation", True),
        lambda io: setattr(io, "capture_error", True),
    ],
)
def test_bad_authority_inputs_grid_or_capture_fail_before_any_touch(tmp_path, mutation):
    result, io = execute(tmp_path, mutation)
    assert result["verdict"] == "FAIL" and io.taps == []


def test_parent_observation_delay_stays_inside_original_external_timer(tmp_path):
    result, io = execute(tmp_path, lambda io: setattr(io, "geometry_delay", 90))
    assert result["verdict"] == "FAIL" and io.taps == []
    assert result["duration_s"] >= 90


@pytest.mark.parametrize("started_at", [909.0, 1001.0])
def test_expired_or_future_parent_clock_performs_no_service_requests(tmp_path, started_at):
    result, io = execute(tmp_path, started_at=started_at)
    assert result["verdict"] == "FAIL" and not io.requests and not io.taps


@pytest.mark.parametrize(
    "flag", ["touch_error", "extra_write", "unexpected_corner", "changed_identity"]
)
def test_uncertain_or_inconsistent_application_is_retained_never_retapped(tmp_path, flag):
    result, io = execute(tmp_path, lambda io: setattr(io, flag, True))
    assert result["verdict"] == "FAIL" and len(io.taps) == 1
    assert result["uncertain_application"] is True
    assert result["readback"] is not None and result["audit_after"] is not None
    assert (tmp_path / "result.json").is_file()


def test_accepted_unverified_never_becomes_pass_on_a_deadline(tmp_path):
    result, io = execute(
        tmp_path, lambda io: setattr(io, "after_statuses", ["accepted_unverified"])
    )
    assert result["verdict"] == "FAIL" and len(io.taps) == 1
    assert result["card"]["status"] == "accepted_unverified"
    assert result["duration_s"] >= 90


def test_output_evidence_is_write_once(tmp_path):
    result, _ = execute(tmp_path)
    saved = (tmp_path / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        execute(tmp_path)
    assert (tmp_path / "result.json").read_bytes() == saved
    assert result["verdict"] == "PASS"


def test_actor_reads_no_external_files_or_hidden_decision_sources():
    tree = ast.parse(Path(actor.__file__).read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name and ("oracle" in name or "pressure_bench" in name or "setup_prescription" in name)
        for name in imports
    )
    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_bytes", "read_text"}
    ]
    assert len(reads) == 1 and ast.unparse(reads[0].func.value) == "Path(__file__)"
    opens = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "open"
    ]
    assert len(opens) == 1 and opens[0].args[0].value == "xb"
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"open", "exec", "eval", "__import__"}
        for node in ast.walk(tree)
    )


def test_terminal_evidence_latency_counts_in_external_deadline(tmp_path):
    clock = Clock()
    io = FakeIO(clock)
    machine = actor.Actor(actor.Config("opaque-run", tmp_path, 1000.0), io, clock=clock)
    original = machine.evidence.event

    def slow_terminal(state, **data):
        original(state, **data)
        if state == "verified_terminal":
            clock.now += 90

    machine.evidence.event = slow_terminal
    result = asyncio.run(machine.run())
    assert result["verdict"] == "FAIL" and result["duration_s"] >= 90
    assert len(io.taps) == 1


def test_actor_transport_does_not_have_a_direct_decision_escape(tmp_path):
    clock, io = Clock(), FakeIO(Clock())
    machine = actor.Actor(actor.Config("opaque-run", tmp_path, 1000.0), io, clock=clock)
    with pytest.raises(actor.ActorError, match="read-only"):
        asyncio.run(machine.rpc("setup.bench.decide", "setup.prescription.card"))
    assert not io.requests


def test_live_adapter_uses_correlated_reads_and_existing_capture_touch(monkeypatch):
    from tools import screen_capture

    class Client:
        async def connect(self):
            pass

        async def hello(self, **kwargs):
            return {"type": "hello_ack"}

        async def send(self, frame):
            self.frame = frame

        async def wait_for(self, predicate, **kwargs):
            result = {"type": "setup.spinner.audit.result", "request_id": self.frame["request_id"]}
            assert predicate(result)
            return result

    async def capture(url, token, *, wait_s):
        assert wait_s == 0.75
        return bytes(320 * 480 * 2), 320, 480

    async def touch(url, token, *, x, y, wait_s):
        assert (x, y, wait_s) == (70, 340, 0.75)
        return {"ok": True}

    monkeypatch.setattr(screen_capture, "capture", capture)
    monkeypatch.setattr(screen_capture, "touch", touch)
    transport = actor.LiveIO("ws://127.0.0.1:8765", None)
    transport.client = Client()

    async def run():
        result = await transport.request(
            {"type": "setup.spinner.audit", "request_id": "nonce"},
            "setup.spinner.audit.result",
            budget_s=0.75,
        )
        assert result["request_id"] == "nonce"
        png, width, height = await transport.capture(budget_s=0.75)
        assert png.startswith(b"\x89PNG") and (width, height) == (320, 480)
        assert (await transport.touch((70, 340), budget_s=0.75))["ok"]

    asyncio.run(run())


def test_geometry_reads_one_bounded_parent_line_without_network(monkeypatch):
    monkeypatch.setattr(actor.sys, "stdin", stdio.StringIO('{"accept_x":70,"accept_y":340}\n'))
    assert asyncio.run(actor.LiveIO.geometry(budget_s=0.5)) == {"accept_x": 70, "accept_y": 340}
