"""One-command autonomous self-test (EPIC #154 Part G).

Drives the in-session harness daemon (#228/#229) **hands-off from the agent's own shell** and
asserts the trainer's live coaching pipeline — no human at the wheel:

    POST /session/start (cm)  -> wait for the shared-memory detector to report "driving"
    POST /sidecar/start       -> sidecar up on the external bind
    tap the sidecar WS        -> assert the L1.5 producer contract (sequence_probe)
    POST /session/stop        -> cleanup (unless --keep)

It catches the class of bugs that only surface in-game and that a human currently finds by
driving — e.g. the trainer never registering as a v1 WS peer (#170), tire-temp 0-index shift
(#180) — by asserting the live ``connection`` / ``tire_temps`` / ``coaching.snapshot`` streams
and the ``session``->``lap`` ordering. The carcsw lap (``lap_driver``) is an optional follow-up
step, not required: the pipeline ticks whenever car 0 is on track.

Run on the rig (loopback to the daemon + sidecar):

    python -m tools.ac_harness.self_test --token <DAEMON_TOKEN>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from tools.ac_harness.sequence_probe import evaluate_sequence, tap_frames

HttpCall = Callable[..., tuple[int, dict[str, Any]]]
TapCall = Callable[..., Awaitable[list[dict]]]


@dataclass
class SelfTestConfig:
    """Inputs for one self-test run (the daemon is the persistent rig service)."""

    token: str
    daemon_url: str = "http://127.0.0.1:9876"
    sidecar_url: str = "ws://127.0.0.1:8765"
    tap_seconds: float = 20.0
    wait_lap: bool = False
    strict: bool = False
    keep: bool = False
    session_timeout: float = 150.0


@dataclass
class SelfTestReport:
    """Structured result of a self-test run."""

    ok: bool
    stage: str
    session_outcome: str = ""
    session_reason: str = ""
    sidecar_ok: bool = False
    sequence_ok: bool | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        lines = [f"self-test: {'PASS' if self.ok else 'FAIL'} (stage={self.stage})"]
        if self.session_outcome:
            lines.append(f"  session: outcome={self.session_outcome} reason={self.session_reason}")
        lines.append(f"  sidecar: {'up' if self.sidecar_ok else 'not started'}")
        if self.sequence_ok is not None:
            lines.append(f"  pipeline: {'ok' if self.sequence_ok else 'FAILED'}")
            if self.counts:
                lines.append(
                    "  frames: " + ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
                )
            for note in self.notes:
                lines.append(f"  note: {note}")
        if self.error:
            lines.append(f"  error: {self.error}")
        return "\n".join(lines)


def _http(
    method: str, url: str, *, token: str, timeout: float = 30.0
) -> tuple[int, dict[str, Any]]:
    """Token-authenticated JSON request to the daemon (stdlib only)."""
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback daemon
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, (json.loads(body) if body else {})


async def run_self_test(
    config: SelfTestConfig,
    *,
    http: HttpCall = _http,
    tap: TapCall = tap_frames,
) -> SelfTestReport:
    """Drive the daemon → sidecar → pipeline assertion and return a structured report.

    ``http`` and ``tap`` are injectable so the orchestration is unit-testable without a game.
    """

    # 1) Launch AC on track (cm mode) via the daemon.
    _, body = http(
        "POST",
        f"{config.daemon_url}/session/start",
        token=config.token,
        timeout=config.session_timeout,
    )
    outcome = str(body.get("outcome", ""))
    reason = str(body.get("reason", ""))
    if not body.get("ok"):
        return SelfTestReport(
            ok=False,
            stage="session_start",
            session_outcome=outcome,
            session_reason=reason,
            error="session did not reach driving",
        )

    # 2) Start the sidecar (external bind + token).
    _, sb = http("POST", f"{config.daemon_url}/sidecar/start", token=config.token, timeout=30.0)
    if not sb.get("ok"):
        _stop(config, http)
        return SelfTestReport(
            ok=False,
            stage="sidecar_start",
            session_outcome=outcome,
            session_reason=reason,
            error=str(sb.get("error", "sidecar failed to start")),
        )

    # 3) Tap the live pipeline and evaluate the L1.5 contract.
    try:
        frames = await tap(
            config.sidecar_url, seconds=config.tap_seconds, wait_for_lap=config.wait_lap
        )
        result = evaluate_sequence(
            frames, strict_lifecycle=config.strict, require_lap=config.wait_lap
        )
    except Exception as exc:  # noqa: BLE001 - surface any tap/eval failure as a FAIL report
        if not config.keep:
            _stop(config, http)
        return SelfTestReport(
            ok=False,
            stage="pipeline_tap",
            session_outcome=outcome,
            session_reason=reason,
            sidecar_ok=True,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if not config.keep:
            _stop(config, http)

    return SelfTestReport(
        ok=result.ok,
        stage="pipeline",
        session_outcome=outcome,
        session_reason=reason,
        sidecar_ok=True,
        sequence_ok=result.ok,
        counts=dict(result.counts),
        notes=list(result.notes),
    )


def _stop(config: SelfTestConfig, http: HttpCall) -> None:
    try:
        http("POST", f"{config.daemon_url}/session/stop", token=config.token, timeout=30.0)
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Autonomous self-test runner (EPIC #154 Part G) — drive the harness daemon"
    )
    parser.add_argument("--token", required=True, help="Daemon bearer token")
    parser.add_argument("--daemon-url", default="http://127.0.0.1:9876", help="Harness daemon URL")
    parser.add_argument("--sidecar-url", default="ws://127.0.0.1:8765", help="Sidecar WS URL")
    parser.add_argument(
        "--seconds", type=float, default=20.0, help="Fixed tap window (window mode)"
    )
    parser.add_argument(
        "--wait-lap", action="store_true", help="Wait for on-track + a lap boundary, then assert"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Require session + lap and enforce session→lap order"
    )
    parser.add_argument("--keep", action="store_true", help="Do not /session/stop on exit")
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = SelfTestConfig(
        token=args.token,
        daemon_url=args.daemon_url,
        sidecar_url=args.sidecar_url,
        tap_seconds=args.seconds,
        wait_lap=args.wait_lap,
        strict=args.strict,
        keep=args.keep,
    )
    report = asyncio.run(run_self_test(config))
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    raise SystemExit(_main())
