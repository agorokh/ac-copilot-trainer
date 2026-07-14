"""One-button alien pipeline (#572, EPIC #529 P2): plant-ID -> optimized line -> QSS -> drive.

``python -m tools.ac_harness.auto_alien --car <car> --track <track> [--setup <name>]`` takes any
car/track combo from nothing to an autonomously driven lap on its own optimized racing line:

1. **Ensure plant** — load the combo's identified plant artifact; when it is missing, lacks the
   uncertainty-aware friction fit (#543), or ``--force-identify`` is set, run the #532 handshake +
   identification session first (a full ``auto_drive --driver handshake`` cycle).
2. **Line + profile + drive** — run ``auto_drive --driver alien``, which builds or reuses the
   identity/provenance-gated alien-line artifact (min-curvature QP within the corridor + QSS
   min-time profile against the identified plant) and drives it with the full measured plant
   controller.
3. **Report** — write a composed machine-readable ``alien_report.json`` naming each stage's
   verdict and evidence bundle.

Stage failures abort the pipeline honestly (the failed stage named, its exit code propagated) —
there is no silent degrade to the stock line or the generic plant anywhere in this path.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.ac_harness.auto_drive import resolve_ac_user_dir, resolve_setup_ini, validate_ac_id
from tools.ac_harness.plant_id import load_plant_artifact, plant_ggv_model

StageRunner = Callable[[list[str]], int]

DEFAULT_SIDECAR_URL = "ws://127.0.0.1:8765"


def _utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _probe_tcp(url: str) -> bool:
    """Whether something is listening on the sidecar URL's host:port right now."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def wait_sidecar_port_settled(
    url: str,
    *,
    probe: Callable[[str], bool] | None = None,
    timeout_s: float = 12.0,
    stable_s: float = 4.0,
    poll_s: float = 0.5,
    sleep=time.sleep,
    now=time.monotonic,
) -> str:
    """Let the previous stage's auto-started sidecar finish dying before the next stage starts.

    The identify stage may auto-start a loopback sidecar that ``auto_drive`` terminates on stage
    exit; starting the drive stage immediately can observe the dying process's port as listening
    and adopt it, only for it to exit under the tap (#572 Codex review). Two settled states:

    * port stops answering within ``timeout_s`` → released (the next stage auto-starts its own);
    * port answers continuously for ``stable_s`` → a stable pre-existing sidecar (one the stage
      did not terminate) → safe to adopt.
    """
    check = probe or _probe_tcp
    deadline = now() + timeout_s
    stable_since: float | None = None
    while now() < deadline:
        if check(url):
            t = now()
            if stable_since is None:
                stable_since = t
            elif t - stable_since >= stable_s:
                return "stable"
        else:
            return "released"
        sleep(poll_s)
    return "timeout"


def needs_identification(
    user_dir: Path,
    car_id: str,
    track_id: str,
    setup: str | None,
    setup_ini: str | Path | None,
    *,
    layout: str | None,
    force: bool = False,
) -> tuple[bool, str]:
    """Whether the identification stage must run, with the human-readable reason.

    True when the plant artifact is absent, when it carries no uncertainty-aware friction fit
    (#543 — a v1/v2 or degraded fit must be re-identified, not extrapolated), or when forced.
    """
    if force:
        return True, "forced (--force-identify)"
    artifact = load_plant_artifact(user_dir, car_id, track_id, setup, setup_ini, layout=layout)
    if artifact is None:
        return True, "no plant artifact for this combo"
    if plant_ggv_model(artifact) is None:
        return True, "plant artifact has no uncertainty-aware friction fit (#543)"
    return False, "plant artifact present with uncertainty-aware friction fit"


def _passthrough_args(args: argparse.Namespace) -> list[str]:
    """CLI flags shared verbatim by both stages (combo identity + rig plumbing)."""
    out = ["--car", args.car, "--track", args.track]
    if args.track_layout:
        out += ["--track-layout", args.track_layout]
    if args.setup:
        out += ["--setup", args.setup]
    if args.ac_root:
        out += ["--ac-root", str(args.ac_root)]
    if args.ac_user_dir:
        out += ["--ac-user-dir", str(args.ac_user_dir)]
    if args.cm_exe:
        out += ["--cm-exe", str(args.cm_exe)]
    if args.sidecar_url:
        out += ["--sidecar-url", args.sidecar_url]
    if args.rig_lock_timeout is not None:
        out += ["--rig-lock-timeout", str(args.rig_lock_timeout)]
    return out


def identify_argv(args: argparse.Namespace, evidence_dir: Path) -> list[str]:
    argv = _passthrough_args(args) + [
        "--driver",
        "handshake",
        "--evidence-dir",
        str(evidence_dir),
    ]
    if args.identify_seconds is not None:
        argv += ["--drive-seconds", str(args.identify_seconds)]
    return argv


def drive_argv(args: argparse.Namespace, evidence_dir: Path) -> list[str]:
    argv = _passthrough_args(args) + [
        "--driver",
        "alien",
        "--evidence-dir",
        str(evidence_dir),
        "--drive-seconds",
        str(args.drive_seconds),
        "--max-speed",
        str(args.max_speed),
        "--ggv-scale",
        str(args.ggv_scale),
        "--wait-lap",
    ]
    if args.strict:
        argv.append("--strict")
    if args.rebuild_line:
        argv.append("--alien-rebuild-line")
    return argv


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "One-button alien pipeline (#572): ensure the combo's identified plant "
            "(runs the #532/#543 handshake+ID session when needed), then drive the "
            "optimized min-curvature line + identified-plant QSS profile."
        )
    )
    p.add_argument("--car", required=True, help="AC car id (e.g. ks_porsche_911_gt3_r_2016)")
    p.add_argument("--track", required=True, help="AC track id (e.g. magione)")
    p.add_argument("--track-layout", default=None, help="layout subdir for multi-layout tracks")
    p.add_argument("--setup", default=None, help="car setup name (plant identity includes it)")
    p.add_argument("--ac-root", type=Path, default=None, help="AC content root (Steam install)")
    p.add_argument("--ac-user-dir", type=Path, default=None, help="AC user data root")
    p.add_argument("--cm-exe", type=Path, default=None, help="Content Manager.exe path")
    p.add_argument("--sidecar-url", default=None)
    p.add_argument(
        "--force-identify",
        action="store_true",
        help="re-run the handshake+identification session even when a usable plant exists",
    )
    p.add_argument(
        "--rebuild-line",
        action="store_true",
        help="ignore the cached alien-line artifact and rebuild it from the current plant",
    )
    p.add_argument(
        "--identify-seconds",
        type=float,
        default=None,
        help="drive budget for the identification stage (default: auto_drive's default)",
    )
    p.add_argument(
        "--drive-seconds", type=float, default=300.0, help="drive budget for the alien lap stage"
    )
    p.add_argument("--max-speed", type=float, default=240.0, help="alien drive speed cap (km/h)")
    p.add_argument(
        "--ggv-scale", type=float, default=0.9, help="safety margin on the QSS min-time profile"
    )
    p.add_argument(
        "--strict", action="store_true", help="alien stage: require session+lap, enforce ordering"
    )
    p.add_argument(
        "--rig-lock-timeout",
        type=float,
        default=None,
        help="seconds to wait for another auto-drive process to release the single-rig lock",
    )
    p.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="pipeline evidence root (default: .scratch/harness-evidence/<ts>_alien_...)",
    )
    return p


def run_pipeline(
    args: argparse.Namespace, *, run_stage: StageRunner | None = None
) -> tuple[int, dict]:
    """Execute the staged pipeline; returns ``(exit_code, report_dict)``.

    ``run_stage`` is injectable (defaults to :func:`tools.ac_harness.auto_drive._main`) so the
    orchestration — stage planning, abort-on-failure, re-verification after identification — is
    unit-testable without a rig.
    """
    if run_stage is None:
        from tools.ac_harness.auto_drive import _main as run_stage  # pragma: no cover - rig glue

    validate_ac_id("car", args.car)
    validate_ac_id("track", args.track)
    if args.track_layout:
        validate_ac_id("layout", args.track_layout)
    user_dir = resolve_ac_user_dir(args.ac_user_dir)
    setup_key = Path(args.setup).stem if args.setup else None
    setup_ini = None
    if args.setup:
        try:
            setup_ini = resolve_setup_ini(
                user_dir, args.car, args.track, args.setup, layout=args.track_layout
            )
        except (FileNotFoundError, ValueError):
            setup_ini = None  # unresolved -> basename-only identity key (matches auto_drive)

    evidence_root = args.evidence_dir or (
        Path(".scratch") / "harness-evidence" / f"{_utc_stamp()}_alien_{args.car}_{args.track}"
    )
    evidence_root.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "pipeline": "alien",
        "issue": 572,
        "evidence_root": str(evidence_root),
        "car": args.car,
        "track": args.track,
        "layout": args.track_layout,
        "setup": setup_key,
        "started_utc": _utc_stamp(),
        "stages": {},
        "ok": False,
    }

    identify, why = needs_identification(
        user_dir,
        args.car,
        args.track,
        setup_key,
        setup_ini,
        layout=args.track_layout,
        force=args.force_identify,
    )
    report["identification_needed"] = identify
    report["identification_reason"] = why
    print(f"auto-alien: identification {'REQUIRED' if identify else 'skipped'} — {why}")

    if identify:
        stage_dir = evidence_root / "identify"
        code = run_stage(identify_argv(args, stage_dir))
        report["stages"]["identify"] = {"exit_code": code, "evidence_dir": str(stage_dir)}
        if code != 0:
            report["error"] = f"identification stage failed (exit {code})"
            print(f"auto-alien: FAIL — {report['error']}")
            return code or 1, report
        # Re-verify the artifact the stage claims to have persisted — the drive stage must never
        # start on a plant that is still missing or fit-degraded (fail loud, never degrade).
        still_needed, why_after = needs_identification(
            user_dir,
            args.car,
            args.track,
            setup_key,
            setup_ini,
            layout=args.track_layout,
        )
        if still_needed:
            report["error"] = (
                f"identification stage exited 0 but the plant is still unusable: {why_after}"
            )
            print(f"auto-alien: FAIL — {report['error']}")
            return 1, report
        print("auto-alien: plant artifact verified after identification")
        # The identify stage may have auto-started (and then terminated) a loopback sidecar;
        # let its port settle so the drive stage never adopts a dying process (#572 review).
        settled = wait_sidecar_port_settled(args.sidecar_url or DEFAULT_SIDECAR_URL)
        report["sidecar_port_between_stages"] = settled
        print(f"auto-alien: sidecar port between stages: {settled}")

    stage_dir = evidence_root / "drive"
    code = run_stage(drive_argv(args, stage_dir))
    report["stages"]["drive"] = {"exit_code": code, "evidence_dir": str(stage_dir)}
    if code != 0:
        report["error"] = f"alien drive stage failed (exit {code})"
        print(f"auto-alien: FAIL — {report['error']}")
        return code or 1, report

    report["ok"] = True
    return 0, report


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only CLI wiring
    args = _build_arg_parser().parse_args(argv)
    try:
        code, report = run_pipeline(args)
    except ValueError as exc:
        print(f"auto-alien: {exc}")
        return 2
    report_path = Path(report["evidence_root"]) / "alien_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    verdict = "OK" if report.get("ok") else f"FAIL ({report.get('error')})"
    print(f"auto-alien: {verdict}")
    print(f"  report: {report_path}")
    return code


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    import sys
    from pathlib import Path as _Path

    _repo_root = str(_Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main(sys.argv[1:]))
