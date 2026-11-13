"""Isolated deterministic #956 touchscreen actor; no label, permit or journal reads.

The parent supplies time.monotonic() BEFORE arming/revealing the case. For a
proposal, this process writes ready.json/before.png and waits for one geometry
line on stdin. The parent inspects the actual frame before supplying coordinates.
Only the real screen touch can decide; this process has no decision RPC.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "956-deterministic-actor-v1"
DEADLINE_S = 90.0
PRESSURES = ("PRESSURE_LF", "PRESSURE_RF", "PRESSURE_LR", "PRESSURE_RR")
READ_TYPES = frozenset({"setup.spinner.list", "setup.spinner.audit", "setup.bench.get"})


class ActorError(RuntimeError):
    """An observed workflow failure, never an instruction to retry a touch."""


def number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def token(value: Any, maximum: int = 64) -> bool:
    return (
        isinstance(value, str) and re.fullmatch(rf"[A-Za-z0-9_-]{{1,{maximum}}}", value) is not None
    )


def native_pressures(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if frame.get("ok") is not True or frame.get("source") != "csp":
        raise ActorError("Fresh native CSP spinner values unavailable")
    rows = {}
    for row in frame.get("spinners", []):
        if not isinstance(row, dict) or row.get("section") not in PRESSURES:
            continue
        section = row["section"]
        if section in rows:
            raise ActorError("Duplicate native pressure corner")
        if (
            row.get("range_known") is not True
            or row.get("read_only") is True
            or not isinstance(row.get("unit"), str)
            or row["unit"].strip().lower() != "psi"
            or not number(row.get("display_multiplier", 1))
            or row.get("display_multiplier", 1) != 1
            or any(not number(row.get(key)) for key in ("value", "min", "max", "step"))
            or row["step"] <= 0
            or not row["min"] <= row["value"] <= row["max"]
            or abs(
                (row["value"] - row["min"]) / row["step"]
                - round((row["value"] - row["min"]) / row["step"])
            )
            > 1e-6
        ):
            raise ActorError("Native pressure units, bounds or supported grid unavailable")
        rows[section] = dict(row)
    if set(rows) != set(PRESSURES):
        raise ActorError("All four native pressure corners are required")
    return rows


def audit_snapshot(frame: dict[str, Any]) -> dict[str, Any]:
    keys = ("attempts", "writes", "csp_setter", "ini_write", "setup_load")
    if (
        frame.get("ok") is not True
        or not isinstance(frame.get("session_id"), str)
        or not frame["session_id"]
        or not isinstance(frame.get("audit_epoch"), str)
        or not frame["audit_epoch"]
        or frame.get("counter_semantics")
        != "native_mutation_dispatches_including_refusal_or_unknown"
        or any(type(frame.get(key)) is not int or frame[key] < 0 for key in keys)
    ):
        raise ActorError("Authoritative mutation audit is unavailable")
    return dict(frame)


def validate_card(card: dict[str, Any], run_id: str, baseline: dict[str, Any]) -> None:
    if (
        card.get("mode") != "ai_bench"
        or card.get("run_id") != run_id
        or not token(card.get("prescription_id"))
    ):
        raise ActorError("Candidate mode, run or immutable prescription identity mismatch")
    changes = card.get("changes")
    if not isinstance(changes, list) or len(changes) > 4:
        raise ActorError("Candidate pressure changes are malformed")
    if card.get("status") == "abstained":
        if changes or not card.get("reason"):
            raise ActorError("Abstention must explicitly explain zero changes")
        return
    if card.get("status") != "proposed" or not changes or card.get("decision") is not None:
        raise ActorError("Case already decided or candidate is not an actionable proposal")
    if not card.get("summary") or "AI BENCH" not in card["summary"] or not card.get("evidence"):
        raise ActorError("Visible bench symptom and measured evidence are required")
    seen = set()
    for change in changes:
        if (
            not isinstance(change, dict)
            or change.get("section") not in baseline
            or change["section"] in seen
        ):
            raise ActorError("Candidate has an unsupported or repeated corner")
        row = baseline[change["section"]]
        if (
            any(not number(change.get(key)) for key in ("from", "to", "delta_psi"))
            or abs(change["from"] - row["value"]) > 0.001
            or not 0.5 <= abs(change["delta_psi"]) <= 1.5
            or abs(change["to"] - change["from"] - change["delta_psi"]) > 0.001
            or not row["min"] <= change["to"] <= row["max"]
            or abs(
                (change["to"] - row["min"]) / row["step"]
                - round((change["to"] - row["min"]) / row["step"])
            )
            > 1e-6
        ):
            raise ActorError("Candidate does not match bounded native psi values and grid")
        seen.add(change["section"])


@dataclass(frozen=True)
class Config:
    run_id: str
    evidence_dir: Path
    started_at: float
    coordinates: tuple[int, int] | None = None


class Evidence:
    """Write-once receipts in only the explicitly provided output directory."""

    def __init__(self, directory: Path, clock):
        self.directory, self.clock, self.sequence = directory, clock, 0
        directory.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, value: Any) -> None:
        raw = (
            value
            if isinstance(value, bytes)
            else (json.dumps(value, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()
        )
        with (self.directory / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def event(self, state: str, **data: Any) -> None:
        self.sequence += 1
        self.write(
            f"{self.sequence:04d}-event.json", {"state": state, "monotonic": self.clock(), **data}
        )


class Actor:
    def __init__(self, config: Config, io, *, clock=time.monotonic):
        self.config, self.io, self.clock = config, io, clock
        self.evidence = Evidence(config.evidence_dir, clock)
        self.code_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.touched, self.card = False, None
        self.before, self.after, self.audit_before, self.audit_after = None, None, None, None

    def remaining(self) -> float:
        elapsed = self.clock() - self.config.started_at
        if elapsed < 0 or elapsed >= DEADLINE_S:
            raise ActorError("External 90-second workflow deadline exhausted or invalid")
        return DEADLINE_S - elapsed

    async def call(self, function, *args):
        left = self.remaining()
        result = await asyncio.wait_for(function(*args, budget_s=left), timeout=left)
        self.remaining()
        return result

    async def rpc(self, kind: str, reply: str, **fields):
        if kind not in READ_TYPES:
            raise ActorError("Actor RPC surface is read-only")
        nonce = uuid.uuid4().hex[:24]
        request = {"v": 1, "type": kind, "request_id": nonce, **fields}
        self.evidence.event("request", frame=request)
        frame = await self.call(self.io.request, request, reply)
        if (
            not isinstance(frame, dict)
            or frame.get("type") != reply
            or frame.get("request_id") != nonce
        ):
            raise ActorError("Fresh correlated response unavailable")
        self.evidence.event("response", frame=frame)
        return frame

    async def pressures(self):
        return native_pressures(await self.rpc("setup.spinner.list", "setup.spinner.list.result"))

    async def audit(self):
        return audit_snapshot(await self.rpc("setup.spinner.audit", "setup.spinner.audit.result"))

    async def get(self, prescription_id: str | None = None):
        fields = {"mode": "ai_bench", "run_id": self.config.run_id}
        if prescription_id is not None:
            fields["prescription_id"] = prescription_id
        return await self.rpc("setup.bench.get", "setup.prescription.card", **fields)

    async def capture(self, name: str):
        png, width, height = await self.call(self.io.capture)
        if (width, height) != (320, 480) or not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ActorError("Actual portrait screen capture unavailable")
        self.evidence.write(name, png)
        digest = hashlib.sha256(png).hexdigest()
        self.evidence.event(
            "framebuffer",
            path=name,
            sha256=digest,
            width=width,
            height=height,
            limitation=(
                "Framebuffer alone does not identify the displayed card "
                "or prove panel/touch behavior"
            ),
        )
        return digest

    async def run(self) -> dict[str, Any]:
        verdict, reason, delta = "FAIL", "Workflow not completed", None
        try:
            if not token(self.config.run_id) or not number(self.config.started_at):
                raise ActorError("Invalid opaque run identity or external start clock")
            self.remaining()
            self.evidence.event(
                "started", run_id=self.config.run_id, started_at=self.config.started_at
            )
            self.audit_before = await self.audit()
            self.before = await self.pressures()
            self.card = await self.get()
            validate_card(self.card, self.config.run_id, self.before)
            frame_hash = await self.capture("before.png")
            self.evidence.write(
                "ready.json",
                {
                    "run_id": self.config.run_id,
                    "card": self.card,
                    "frame_sha256": frame_hash,
                    "started_at": self.config.started_at,
                    "deadline_at": self.config.started_at + DEADLINE_S,
                    "needs_geometry": self.card["status"] == "proposed",
                    "baseline": self.before,
                },
            )
            self.io.ready(self.config.evidence_dir / "ready.json")
            if self.card["status"] == "proposed":
                coordinates = self.config.coordinates
                if coordinates is None:
                    geometry = await self.call(self.io.geometry)
                    if not isinstance(geometry, dict) or set(geometry) - {
                        "accept_x",
                        "accept_y",
                        "frame_sha256",
                        "prescription_id",
                    }:
                        raise ActorError("Only observed Accept geometry is accepted on stdin")
                    if (
                        geometry.get("frame_sha256", frame_hash) != frame_hash
                        or geometry.get("prescription_id", self.card["prescription_id"])
                        != self.card["prescription_id"]
                    ):
                        raise ActorError("Observed geometry belongs to another frame or card")
                    coordinates = geometry.get("accept_x"), geometry.get("accept_y")
                if (
                    type(coordinates[0]) is not int
                    or type(coordinates[1]) is not int
                    or not 0 <= coordinates[0] <= 319
                    or not 0 <= coordinates[1] <= 479
                ):
                    raise ActorError(
                        "Observed Accept coordinates are outside the native portrait screen"
                    )
                self.evidence.event(
                    "touch_once",
                    x=coordinates[0],
                    y=coordinates[1],
                    authority="parent observed current framebuffer geometry",
                )
                self.touched = True  # Set before transport; an uncertain tap is never repeated.
                ack = await self.call(self.io.touch, coordinates)
                if not isinstance(ack, dict) or ack.get("ok") is not True:
                    raise ActorError("Physical touch outcome uncertain; no retry permitted")
                self.evidence.event("touch_ack", frame=ack)
                decision_receipt = None
                while True:
                    current = await self.get(self.card["prescription_id"])
                    if any(
                        current.get(key) != self.card.get(key)
                        for key in ("mode", "run_id", "prescription_id", "changes")
                    ):
                        raise ActorError("Immutable proposal changed during readback")
                    if current.get("decision") is not None:
                        receipt = current.get("decision"), current.get("decided_at")
                        if receipt[0] != "accept" or not number(receipt[1]) or receipt[1] <= 0:
                            raise ActorError("Durable accepted decision receipt unavailable")
                        if decision_receipt is not None and receipt != decision_receipt:
                            raise ActorError("Durable decision receipt changed during readback")
                        decision_receipt = receipt
                    if current.get("status") == "verified_applied":
                        if (
                            current.get("decision") != "accept"
                            or not number(current.get("decided_at"))
                            or current["decided_at"] <= 0
                        ):
                            raise ActorError("Durable accepted decision receipt unavailable")
                        self.card = current
                        break
                    if current.get("status") not in {"proposed", "accepted_unverified"}:
                        raise ActorError("Touch did not reach a truthful verified application")
                    self.card = current
                    await self.call(self.io.pause)
            elif (
                self.card.get("decision") != "abstain"
                or not number(self.card.get("decided_at"))
                or self.card["decided_at"] <= 0
            ):
                raise ActorError("Durable explicit abstention receipt unavailable")
            self.after, self.audit_after = await self.pressures(), await self.audit()
            if any(
                self.audit_before[key] != self.audit_after[key]
                for key in ("session_id", "audit_epoch")
            ):
                raise ActorError("Native audit session or source epoch changed")
            keys = ("attempts", "writes", "csp_setter", "ini_write", "setup_load")
            delta = {key: self.audit_after[key] - self.audit_before[key] for key in keys}
            if min(delta.values()) < 0:
                raise ActorError("Authoritative audit counters regressed")
            expected = {key: self.before[key]["value"] for key in PRESSURES}
            for change in self.card["changes"]:
                expected[change["section"]] = change["to"]
            if any(abs(self.after[key]["value"] - expected[key]) > 0.001 for key in PRESSURES):
                raise ActorError("Complete native four-corner readback disagrees with the decision")
            expected_writes = len(self.card["changes"]) if self.touched else 0
            if (
                delta["writes"] != expected_writes
                or delta["csp_setter"] != expected_writes
                or delta["ini_write"]
                or delta["setup_load"]
            ):
                raise ActorError(
                    "Native dispatch audit shows an unexpected, duplicate or absent write"
                )
            await self.capture("after.png")
            self.remaining()
            self.evidence.event(
                "verified_terminal", card=self.card, readback=self.after, audit_delta=delta
            )
            self.remaining()
            verdict, reason = (
                "PASS",
                "Autonomous workflow verified; accuracy is independently scored",
            )
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, ActorError)
                else f"Workflow stopped: {type(exc).__name__}"
            )
            self.evidence.event("failed", reason=reason, touch_attempted=self.touched)
            # Read-only failure evidence may settle an uncertain application;
            # it never repeats the physical touch or spends past the deadline.
            if self.touched or self.audit_before is not None:
                for attribute, reader in (("after", self.pressures), ("audit_after", self.audit)):
                    if self.clock() - self.config.started_at >= DEADLINE_S:
                        break
                    try:
                        setattr(self, attribute, await reader())
                    except Exception as probe_error:
                        self.evidence.event(
                            "failure_read_unavailable",
                            field=attribute,
                            error_type=type(probe_error).__name__,
                        )
        completed_at = self.clock()
        if verdict == "PASS" and completed_at - self.config.started_at >= DEADLINE_S:
            verdict, reason = "FAIL", "External 90-second workflow deadline exhausted"
        result = {
            "verdict": verdict,
            "reason": reason,
            "scope": "autonomous_workflow_only",
            "run_id": self.config.run_id,
            "version": VERSION,
            "actor_sha256": self.code_sha256,
            "model": "deterministic_fsm",
            "model_version": VERSION,
            "prompt_hash": "not_applicable",
            "llm_inference_calls": 0,
            "human_time_savings": "unmeasured",
            "started_at": self.config.started_at,
            "completed_at": completed_at,
            "duration_s": completed_at - self.config.started_at,
            "deadline_s": DEADLINE_S,
            "touch_attempted": self.touched,
            "uncertain_application": self.touched and verdict != "PASS",
            "card": self.card,
            "baseline": self.before,
            "readback": self.after,
            "audit_before": self.audit_before,
            "audit_after": self.audit_after,
            "audit_delta": delta,
        }
        self.evidence.write("result.json", result)
        return result


class LiveIO:
    def __init__(self, url: str, secret: str | None):
        from tools.ai_sidecar.external_protocol import PRESSURE_BENCH_CLIENT_ID
        from tools.ai_sidecar.harness_client import HarnessClient

        self.url, self.secret = url, secret
        self.client = HarnessClient(url, token=secret, client_id=PRESSURE_BENCH_CLIENT_ID)
        self.connected = False

    async def request(self, frame, reply, *, budget_s):
        if frame.get("type") not in READ_TYPES:
            raise ActorError("Actor transport only permits the three current-case reads")
        if not self.connected:
            await self.client.connect()
            if await self.client.hello(timeout=budget_s) is None:
                raise ActorError("Sidecar did not acknowledge actor connection")
            self.connected = True
        await self.client.send(frame)
        response = await self.client.wait_for(
            lambda item: (
                (item.get("type") == reply and item.get("request_id") == frame["request_id"])
                or (item.get("type") == "error" and item.get("ref_type") == frame["type"])
            ),
            timeout=budget_s,
        )
        if response is None or response.get("type") == "error":
            raise ActorError("Sidecar refused or timed out on a correlated actor read")
        return response

    async def capture(self, *, budget_s):
        from tools.screen_capture import capture, rgb565_to_png

        raw, width, height = await capture(self.url, self.secret, wait_s=budget_s)
        return rgb565_to_png(raw, width, height, big_endian=False), width, height

    async def touch(self, coordinates, *, budget_s):
        from tools.screen_capture import touch

        return await touch(
            self.url, self.secret, x=coordinates[0], y=coordinates[1], wait_s=budget_s
        )

    async def pause(self, *, budget_s):
        await asyncio.sleep(min(0.2, budget_s))

    @staticmethod
    def ready(path):
        print(json.dumps({"state": "ready", "path": str(path)}), flush=True)

    @staticmethod
    async def geometry(*, budget_s):
        # A daemon thread avoids an uninterruptible executor shutdown if the
        # parent never supplies geometry before the workflow deadline.
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def deliver(line):
            if not future.done():
                future.set_result(line)

        def read():
            line = sys.stdin.readline(4097)
            try:
                loop.call_soon_threadsafe(deliver, line)
            except RuntimeError:
                pass

        threading.Thread(target=read, daemon=True).start()
        line = await asyncio.wait_for(future, timeout=budget_s)
        if not line or len(line) > 4096:
            raise ActorError("One bounded geometry line is required")
        try:
            return json.loads(line)
        except ValueError as exc:
            raise ActorError("Observed geometry must be JSON") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--started-at", required=True, type=float)
    parser.add_argument("--accept-x", type=int)
    parser.add_argument("--accept-y", type=int)
    args = parser.parse_args(argv)
    if (args.accept_x is None) != (args.accept_y is None):
        parser.error("--accept-x and --accept-y must be supplied together")
    coordinates = None if args.accept_x is None else (args.accept_x, args.accept_y)
    config = Config(args.run_id, args.evidence_dir, args.started_at, coordinates)

    async def run():
        io = LiveIO(args.url, os.environ.get("AC_COPILOT_SIDECAR_TOKEN") or None)
        try:
            return await Actor(config, io).run()
        finally:
            await io.client.close()

    try:
        result = asyncio.run(run())
    except Exception as exc:
        print(
            json.dumps({"verdict": "FAIL", "reason": f"Actor stopped: {type(exc).__name__}"}),
            flush=True,
        )
        return 1
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "duration_s": result["duration_s"],
                "reason": result["reason"],
            }
        ),
        flush=True,
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
