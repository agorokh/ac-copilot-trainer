"""False-green-rate KPI — the CI-measurable arm of EPIC #154 Part-G's ``< 5%`` gate.

A **false green** is the failure this whole harness exists to prevent: the self-test reports
the coaching pipeline *healthy* (PASS) when a human at the wheel would see it *broken* — no
coaching on screen, a frozen HUD, absent/zeroed tire temps, no lap registered, a ``lap`` before
its ``session``, stale/frozen telemetry, an out-of-schema read. The ADR
(`autonomous-self-test-harness.md`, L2) states the acceptance bar as *"false-green rate vs human
reality (<5%), not coverage."*

**Scope (honest by construction).** Full *"vs human reality"* fidelity is the rig-gated live
`self_test.py` run (already live-verified, no human at the wheel). This module measures the
**off-sim, deterministic** half: the harness **detector layer's discrimination** against a
labeled corpus of the real failure classes tied to historical bugs (#170/#180/#182/#191/#459).
It is *known-failure discrimination* — each broken scenario is a class the harness was built to
catch, evaluated by the **real production oracle** for that class (imported, never
reimplemented):

* stream presence + ``session→lap`` ordering — `sequence_probe.evaluate_sequence`
* out-of-schema field read (mock-fallacy / L0 schema gate) — `trace_replay.load_schema`
* sim-death / frozen telemetry — `auto_drive.PhysicsStallDetector`
* drive-leg outcome — a pit-start stall the car never escapes (recovery cap at 0 m) or a hijack
  that never landed must NOT be reported as a successful drive — `auto_drive.drive_leg_succeeded`
  (#528)
* HUD render-liveness (black/uniform frame) — `hud_capture.liveness_score`
* **report-path integrity** — `self_test.run_self_test` driven end-to-end with injected
  transports, so an oracle FAIL is proven to propagate to ``SelfTestReport.ok`` (catches the
  "detector works but the harness swallows the failure" false green)

The report is explicit about what it *cannot* see (`OUT_OF_SCOPE`) so it never implies full
human-reality coverage. Recorded live WS taps can be folded in as extra scenarios via
`sequence_probe.frames_from_jsonl` to anchor the corpus to reality over time.

CLI: ``python -m tools.ac_harness.false_green_kpi [--json OUT]`` — exits ``0`` iff **no broken
scenario leaks** (``broken_false_green == 0``; the deterministic bar, stricter than the reported
``< 5%``) **and** ``false_red_rate == 0`` **and** every declared class is covered.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tools.ac_harness.auto_drive import DriveStats, PhysicsStallDetector, drive_leg_succeeded
from tools.ac_harness.hud_capture import liveness_score
from tools.ac_harness.self_test import SelfTestConfig, run_self_test
from tools.ac_harness.sequence_probe import evaluate_sequence
from tools.ac_harness.trace_replay import load_schema

GATE_THRESHOLD = 0.05

# The broken failure classes the corpus MUST cover — every one is a real historical false-green
# risk. `run_kpi` fails if any is absent, so the gate can never pass on a hollowed-out corpus.
BROKEN_CLASSES: tuple[str, ...] = (
    "missing_connection",  # #170 — trainer never registers as a v1 WS peer
    "missing_tire_temps",  # #180 — tire-temp stream absent / 0-index shift
    "dead_coaching",  # coaching.snapshot stream never produced
    "lap_before_session",  # #182 — lap emitted before its session (ordering)
    "envelope_spoof",  # non-state.snapshot frame masquerading as a topic
    "require_lap_timeout",  # #191 — waited for a lap, none arrived
    "empty_stream",  # nothing published at all
    "out_of_schema_field",  # mock-fallacy — reading a field not in ac_schema.json
    "sim_death_frozen",  # acpmf_physics packet_id frozen (acs.exe died)
    "sim_death_physics_gone",  # #460 — physics mmap gone; None must not reset the timer
    "spawn_stall_recovery_capped",  # #528 — pit-start stall: car never escapes, recovery cap at 0 m
    "hijack_never_landed",  # #528 — carcsw hijack never landed; no drive leg ran at all
    "session_replaced",  # #555 — another worktree launched a different acs.exe mid-drive
    "hud_blank",  # black HUD frame
    "hud_uniform",  # frozen/uniform HUD frame (almost no distinct values)
    "report_path_swallow",  # oracle FAIL must reach SelfTestReport.ok (no swallowing)
)

# Human-perceptible false greens this OFF-SIM detector layer genuinely cannot see. Named in every
# report so it never implies full human-reality coverage — these stay the live rig arm's job.
OUT_OF_SCOPE: tuple[str, ...] = (
    "semantic coaching validity (right cue at the right place) — needs the live coach + a judge",
    "audio path (a voice cue actually audible at the wheel) — rig-gated at-wheel A/B audit",
    "render correctness beyond liveness (clipping / colour / position) — needs pixel/OCR judgement",
    "performance degradation / memory growth over a full session — needs a long live run",
    "lap persistence across a save/load or restart — needs live state round-trip",
)


@dataclass(frozen=True)
class Scenario:
    """One labeled corpus entry: an input run through a real oracle with a known ground truth."""

    id: str
    failure_class: str
    issue_ref: str
    expected: str  # "GREEN" (healthy — oracle must PASS) or "RED" (broken — oracle must catch)
    oracle: str  # which detector: sequence | schema | sim_death | render | report_path
    run: Callable[[], bool]  # the oracle verdict: True = looks healthy, False = flagged broken


@dataclass
class KpiReport:
    """Outcome of running the corpus through the real oracles."""

    false_green_rate: float
    false_red_rate: float
    broken_total: int
    broken_false_green: int
    healthy_total: int
    healthy_false_red: int
    per_class: dict[str, dict] = field(default_factory=dict)
    covered_classes: list[str] = field(default_factory=list)
    missing_classes: list[str] = field(default_factory=list)
    false_greens: list[str] = field(default_factory=list)
    false_reds: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=lambda: list(OUT_OF_SCOPE))
    gate_threshold: float = GATE_THRESHOLD

    @property
    def ok(self) -> bool:
        """The Part-G gate. This OFF-SIM arm is DETERMINISTIC (no noise), so the bar is **zero
        leaked broken scenarios**, not merely ``< 5%``: a single un-caught broken class must fail
        and can never be diluted below the rate threshold as the corpus grows (the module invites
        folding recorded taps in). The ``< 5%`` rate stays the *reported* KPI and the live
        "vs human reality" arm's bar. Also requires zero false reds and full class coverage."""
        return (
            self.broken_false_green == 0 and self.false_red_rate == 0.0 and not self.missing_classes
        )

    def to_dict(self) -> dict:
        return {
            "kpi": "known_failure_discrimination",
            "gate_threshold": self.gate_threshold,
            "ok": self.ok,
            "false_green_rate": round(self.false_green_rate, 4),
            "false_red_rate": round(self.false_red_rate, 4),
            "broken_total": self.broken_total,
            "broken_false_green": self.broken_false_green,
            "healthy_total": self.healthy_total,
            "healthy_false_red": self.healthy_false_red,
            "false_greens": self.false_greens,
            "false_reds": self.false_reds,
            "covered_classes": self.covered_classes,
            "missing_classes": self.missing_classes,
            "per_class": self.per_class,
            "out_of_scope": self.out_of_scope,
        }

    def summary(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        pct = self.false_green_rate * 100
        lines = [
            f"{head}: false-green KPI (known-failure discrimination) -- "
            f"false_green_rate={pct:.1f}% "
            f"(gate: 0 leaks; reported bar < {self.gate_threshold * 100:.0f}%)",
            f"  broken: {self.broken_total} scenarios, "
            f"{self.broken_false_green} leaked (false green)",
            f"  healthy: {self.healthy_total} scenarios, "
            f"{self.healthy_false_red} false-failed (false red)",
        ]
        for cls in self.covered_classes:
            pc = self.per_class[cls]
            mark = "ok" if pc["false_green"] == 0 and pc["false_red"] == 0 else "XX"
            lines.append(f"  [{mark}] {cls}: {pc['total']} scenario(s)")
        if self.missing_classes:
            lines.append(f"  MISSING classes (corpus hollowed out): {self.missing_classes}")
        if self.false_greens:
            lines.append(f"  FALSE GREENS: {self.false_greens}")
        lines.append(
            "  out-of-scope (rig-gated, NOT measured here): "
            + str(len(self.out_of_scope))
            + " class(es)"
        )
        return "\n".join(lines)


# --------------------------------------------------------------------------- frame builders
def _snap(topic: str) -> dict:
    """A produced topic frame as the tap receives it (ws_bridge.publishTopic envelope)."""
    return {"v": 1, "type": "state.snapshot", "topic": topic, "payload": {}}


def _nonsnap(topic: str) -> dict:
    """A non-snapshot frame that merely carries a topic key — must NOT satisfy the contract."""
    return {"v": 1, "type": "diagnostic", "topic": topic}


def _healthy_stream() -> list[dict]:
    return [
        _snap("connection"),
        _snap("session"),
        _snap("delta"),
        _snap("tire_temps"),
        _snap("coaching.snapshot"),
        _snap("lap"),
        _snap("tire_temps"),
    ]


# --------------------------------------------------------------------------- oracle adapters
def _sim_alive(samples: list[tuple[float, int | None]], *, sim_dead_seconds: float) -> bool:
    """Run (now, packet_id) samples through the REAL PhysicsStallDetector; alive = never tripped."""
    det = PhysicsStallDetector(sim_dead_seconds)
    for now, pkt in samples:
        if det.update(now, pkt):
            return False
    return True


def _report_path_ok(frames: list[dict]) -> bool:
    """Drive the FULL self_test orchestration with injected transports; return SelfTestReport.ok.

    Proves an oracle verdict propagates end-to-end (session -> sidecar -> tap -> evaluate ->
    report): a broken ``frames`` stream must surface as ``ok is False`` rather than being
    swallowed into a green report.
    """
    import asyncio

    def _http(method, url, *, token, timeout=30.0):  # noqa: ANN001, ANN202 - injected stub
        # Every daemon step succeeds; the only signal under test is the tapped stream's verdict.
        return 200, {"ok": True, "outcome": "driving", "reason": "injected"}

    async def _tap(url, *, seconds=20.0, wait_for_lap=False):  # noqa: ANN001, ANN202 - injected
        return frames

    config = SelfTestConfig(token="kpi", tap_seconds=0.0)
    report = asyncio.run(run_self_test(config, http=_http, tap=_tap))
    return report.ok


# --------------------------------------------------------------------------- corpus
def build_corpus() -> list[Scenario]:
    """The labeled scenario corpus, each scenario a thunk over the REAL oracle for its class.

    Anti-vacuity ("would a defanged oracle leak?") is proven in the test suite by patching an
    oracle symbol — no test-only knob is plumbed through this production API.
    """
    live_bgra = bytes(range(256)) * 40  # non-uniform: mean ~127, 256 distinct -> renders
    black_bgra = bytes(4 * 200)  # all-zero -> black frame
    uniform_bgra = bytes([50]) * 800  # one distinct value -> frozen/uniform frame

    def seq(frames: list[dict], **kw) -> bool:
        return evaluate_sequence(frames, **kw).ok

    def schema(field_name: str) -> bool:
        return field_name in load_schema().car_fields

    def sim(samples, *, sim_dead_seconds=1.0) -> bool:
        return _sim_alive(samples, sim_dead_seconds=sim_dead_seconds)

    def render(bgra: bytes) -> bool:
        return liveness_score(bgra).is_rendering()

    def report_path(frames: list[dict]) -> bool:
        return _report_path_ok(frames)

    def drive(stats: DriveStats | None) -> bool:
        return drive_leg_succeeded(stats)

    # advancing packet ids (alive) vs frozen / gone (dead)
    advancing = [(i * 0.1, i + 1) for i in range(25)]
    frozen = [(0.0, 5), (0.5, 5), (1.6, 5)]
    physics_gone = [(0.0, 5), (0.5, None), (1.7, None)]

    return [
        # ---- HEALTHY (must PASS; a fail here is a false RED) ----
        Scenario(
            "healthy_nominal_drive",
            "healthy",
            "-",
            "GREEN",
            "sequence",
            lambda: seq(_healthy_stream()),
        ),
        Scenario(
            "healthy_mid_session_tap",
            "healthy",
            "#190",
            "GREEN",
            "sequence",
            lambda: seq(
                [_snap("connection"), _snap("lap"), _snap("tire_temps"), _snap("coaching.snapshot")]
            ),
        ),
        Scenario(
            "healthy_no_reference_no_delta",
            "healthy",
            "#173",
            "GREEN",
            "sequence",
            lambda: seq(
                [
                    _snap("connection"),
                    _snap("session"),
                    _snap("lap"),
                    _snap("tire_temps"),
                    _snap("coaching.snapshot"),
                ],
                strict_lifecycle=True,
            ),
        ),
        Scenario(
            "healthy_dropped_optional_delta",
            "healthy",
            "#173",
            "GREEN",
            "sequence",
            lambda: seq([f for f in _healthy_stream() if f["topic"] != "delta"]),
        ),
        Scenario(
            "healthy_schema_known_field",
            "healthy",
            "-",
            "GREEN",
            "schema",
            lambda: schema("speedKmh"),
        ),
        Scenario(
            "healthy_sim_advancing", "healthy", "#459", "GREEN", "sim_death", lambda: sim(advancing)
        ),
        Scenario(
            "healthy_render_live", "healthy", "-", "GREEN", "render", lambda: render(live_bgra)
        ),
        Scenario(
            "healthy_report_path_pass",
            "healthy",
            "-",
            "GREEN",
            "report_path",
            lambda: report_path(_healthy_stream()),
        ),
        Scenario(
            "healthy_clean_drive",
            "healthy",
            "#528",
            "GREEN",
            "drive",
            lambda: drive(
                DriveStats(drove=True, laps=1, total_distance_m=3200.0, max_speed_kmh=210.0)
            ),
        ),
        # ---- BROKEN (must be CAUGHT; a pass here is a FALSE GREEN) ----
        Scenario(
            "broken_missing_connection",
            "missing_connection",
            "#170",
            "RED",
            "sequence",
            lambda: seq(
                [_snap("session"), _snap("tire_temps"), _snap("coaching.snapshot"), _snap("lap")]
            ),
        ),
        Scenario(
            "broken_missing_tire_temps",
            "missing_tire_temps",
            "#180",
            "RED",
            "sequence",
            lambda: seq(
                [_snap("connection"), _snap("session"), _snap("lap"), _snap("coaching.snapshot")]
            ),
        ),
        Scenario(
            "broken_dead_coaching",
            "dead_coaching",
            "-",
            "RED",
            "sequence",
            lambda: seq([_snap("connection"), _snap("session"), _snap("lap"), _snap("tire_temps")]),
        ),
        Scenario(
            "broken_lap_before_session",
            "lap_before_session",
            "#182",
            "RED",
            "sequence",
            lambda: seq(
                [
                    _snap("connection"),
                    _snap("lap"),
                    _snap("session"),
                    _snap("tire_temps"),
                    _snap("coaching.snapshot"),
                ]
            ),
        ),
        Scenario(
            "broken_envelope_spoof",
            "envelope_spoof",
            "-",
            "RED",
            "sequence",
            lambda: seq(
                [
                    _snap("connection"),
                    _snap("coaching.snapshot"),
                    _nonsnap("tire_temps"),
                    _nonsnap("lap"),
                ]
            ),
        ),
        Scenario(
            "broken_require_lap_timeout",
            "require_lap_timeout",
            "#191",
            "RED",
            "sequence",
            lambda: seq(
                [_snap("connection"), _snap("tire_temps"), _snap("coaching.snapshot")],
                require_lap=True,
            ),
        ),
        Scenario("broken_empty_stream", "empty_stream", "-", "RED", "sequence", lambda: seq([])),
        Scenario(
            "broken_schema_out_of_field",
            "out_of_schema_field",
            "-",
            "RED",
            "schema",
            lambda: schema("totallyBogusFieldNotInSchema"),
        ),
        Scenario(
            "broken_sim_frozen_packet",
            "sim_death_frozen",
            "#459",
            "RED",
            "sim_death",
            lambda: sim(frozen),
        ),
        Scenario(
            "broken_sim_physics_gone",
            "sim_death_physics_gone",
            "#460",
            "RED",
            "sim_death",
            lambda: sim(physics_gone),
        ),
        Scenario(
            # #528 pit-start stall: the car kept stalling until the recovery cap. drove=True here
            # (it limped 560 m across recoveries) makes the recovery_capped veto load-bearing — the
            # drove/speed floor alone would pass this, so only the veto catches it. The live repro
            # was worse (0 m, drove=False); a defanged recovery_capped veto must not leak this.
            "broken_spawn_stall_recovery_capped",
            "spawn_stall_recovery_capped",
            "#528",
            "RED",
            "drive",
            lambda: drive(
                DriveStats(
                    drove=True,
                    total_distance_m=560.0,
                    max_speed_kmh=48.0,
                    recoveries=7,
                    recovery_capped=True,
                    spawn_teleport="failed",
                    reason="recovery cap (6) exceeded at 560m",
                )
            ),
        ),
        Scenario(
            # #528 hijack-probe exhaustion: the carcsw hijack never landed, so no drive leg ran at
            # all (run_auto_drive returns stage=hijack, no DriveStats). A None drive is never green.
            "broken_hijack_never_landed",
            "hijack_never_landed",
            "#528",
            "RED",
            "drive",
            lambda: drive(None),
        ),
        Scenario(
            # #555 cross-worktree collision: the car had already driven far enough to satisfy the
            # distance/speed floor when another CM request replaced its acs.exe. The explicit
            # session_replaced veto is therefore load-bearing.
            "broken_session_replaced",
            "session_replaced",
            "#555",
            "RED",
            "drive",
            lambda: drive(
                DriveStats(
                    drove=True,
                    total_distance_m=510.0,
                    max_speed_kmh=132.0,
                    sim_pid=101,
                    unexpected_sim_pids=[202],
                    session_replaced=True,
                    reason="unexpected acs.exe PID takeover",
                )
            ),
        ),
        Scenario(
            "broken_render_black", "hud_blank", "-", "RED", "render", lambda: render(black_bgra)
        ),
        Scenario(
            "broken_render_uniform",
            "hud_uniform",
            "-",
            "RED",
            "render",
            lambda: render(uniform_bgra),
        ),
        Scenario(
            "broken_report_path_swallow",
            "report_path_swallow",
            "-",
            "RED",
            "report_path",
            lambda: report_path([_snap("connection"), _snap("coaching.snapshot")]),
        ),
    ]


def run_kpi(scenarios: list[Scenario] | None = None) -> KpiReport:
    """Run the corpus through the real oracles and compute the false-green / false-red KPI."""
    corpus = scenarios if scenarios is not None else build_corpus()
    per_class: dict[str, dict] = {}
    red_classes: set[str] = set()
    broken_total = broken_fg = healthy_total = healthy_fr = 0
    false_greens: list[str] = []
    false_reds: list[str] = []

    for sc in corpus:
        healthy_verdict = sc.run()  # True = oracle says healthy
        pc = per_class.setdefault(sc.failure_class, {"total": 0, "false_green": 0, "false_red": 0})
        pc["total"] += 1
        if sc.expected == "RED":
            broken_total += 1
            red_classes.add(sc.failure_class)
            if healthy_verdict:  # broken input the oracle called healthy -> FALSE GREEN
                broken_fg += 1
                pc["false_green"] += 1
                false_greens.append(sc.id)
        else:  # GREEN
            healthy_total += 1
            if not healthy_verdict:  # healthy input the oracle called broken -> FALSE RED
                healthy_fr += 1
                pc["false_red"] += 1
                false_reds.append(sc.id)

    # Coverage counts ONLY classes exercised by a broken (RED) scenario: a declared class present
    # solely as a mislabeled GREEN scenario is NOT covered, so the gate cannot pass on a hollow
    # failure class (codex on #513).
    covered = sorted(red_classes)
    missing = [c for c in BROKEN_CLASSES if c not in red_classes]
    return KpiReport(
        false_green_rate=(broken_fg / broken_total) if broken_total else 0.0,
        false_red_rate=(healthy_fr / healthy_total) if healthy_total else 0.0,
        broken_total=broken_total,
        broken_false_green=broken_fg,
        healthy_total=healthy_total,
        healthy_false_red=healthy_fr,
        per_class=per_class,
        covered_classes=covered,
        missing_classes=missing,
        false_greens=false_greens,
        false_reds=false_reds,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="False-green-rate KPI shadow-mode report (EPIC #154 Part G)"
    )
    parser.add_argument("--json", default=None, help="Write the full report as JSON to this path")
    return parser


def _resolve_output_path(path: str) -> Path:
    """Resolve ``--json`` under the current working directory and reject any escape.

    Tool outputs stay contained under cwd (repo convention, e.g. ``lap_archive_export`` / #204): an
    absolute path outside cwd or a ``..`` traversal is refused, not written as an arbitrary file.
    """
    root = Path.cwd().resolve()
    resolved = (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"--json path {path!r} escapes the working directory {root}")
    return resolved


def _main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    report = run_kpi()
    print(report.summary())
    if args.json:
        try:
            out = _resolve_output_path(args.json)
        except ValueError as exc:
            print(f"  error: {exc}")
            return 2
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)
        print(f"  wrote {out}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    import sys

    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
