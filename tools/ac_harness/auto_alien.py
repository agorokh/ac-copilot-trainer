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

#577 (EPIC #529 P3) adds **flying-lap windows** (``--laps N`` — the drive stage holds its window
open through N timed laps, per-lap times in the report) and **progressive-envelope self-play**
(``--iterations K``): after the base drive, each iteration refines the friction fit from the
previous drive's lap archives only (monotonic merge — measured lateral bins tighten, longitudinal
evidence is never lost), persists it through the canonical plant gates (invalidating the cached
alien line via the fit provenance hash), steps the ggv-scale envelope ladder, and drives the
rebuilt line. Every step is falsifiable: an invalid lap / spin / failed stage reverts the plant to
the last-valid fit (the #244 keep-last-valid pattern) and the report names the falsification —
the ladder never silently retries the same envelope.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.ac_harness.auto_drive import (
    ALIEN_MAX_OVERSPEED_SCALE,
    _archive_matches_combo,
    resolve_ac_user_dir,
    resolve_setup_ini,
    validate_ac_id,
)
from tools.ac_harness.plant_id import (
    load_plant_artifact,
    plant_artifact_path,
    plant_ready_for_full_consumption,
)

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

    True when the plant artifact fails the SAME readiness gate the alien drive stage enforces
    (:func:`~tools.ac_harness.plant_id.plant_ready_for_full_consumption` — absent artifact,
    missing #543 uncertainty-aware friction fit, or incomplete measured steering constants), or
    when forced. Sharing the drive stage's exact gate means this can never skip the handshake
    for a plant the drive stage would then reject (#572 daemon HIGH).
    """
    if force:
        return True, "forced (--force-identify)"
    artifact = load_plant_artifact(user_dir, car_id, track_id, setup, setup_ini, layout=layout)
    reason = plant_ready_for_full_consumption(artifact, require_friction_fit=True)
    if reason is not None:
        return True, reason
    return False, "plant artifact present with uncertainty-aware friction fit"


# ---------------------------------------------------------------------------
# #577 progressive-envelope self-play (pure/injectable — unit-tested off-rig).
# ---------------------------------------------------------------------------


def load_stage_outcome(stage_dir: Path) -> dict | None:
    """The stage's ``report.json`` payload (report + lap_archives extras), or ``None``."""
    try:
        payload = json.loads((Path(stage_dir) / "report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def stage_lap_times_ms(outcome: dict | None) -> list[int]:
    """Per-lap times (ms) the stage's tap observed, from the stage report."""
    report = (outcome or {}).get("report")
    times = report.get("lap_times_ms") if isinstance(report, dict) else None
    if not isinstance(times, list):
        return []
    out: list[int] = []
    for value in times:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            out.append(int(value))
    return out


def stage_lap_archives(outcome: dict | None) -> list[str]:
    """The stage's collected lap-archive paths (already run-scoped + combo-matched)."""
    archives = (outcome or {}).get("lap_archives")
    if not isinstance(archives, list):
        return []
    return [str(p) for p in archives if isinstance(p, str) and p]


def load_archive_payloads(paths: list[str]) -> tuple[list[dict], list[str]]:
    """Load lap-archive JSON payloads; unreadable files are reported, never silently dropped."""
    payloads: list[dict] = []
    errors: list[str] = []
    for path in paths:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: {type(exc).__name__}")
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        else:
            errors.append(f"{path}: archive root is not an object")
    return payloads, errors


def combo_filter_payloads(
    payloads: list[dict], *, car_id: str, track_id: str, layout: str | None
) -> tuple[list[dict], int]:
    """Keep only this combo's archive payloads; returns ``(kept, dropped_count)``.

    The multi-dir archive scan can surface another app/combo's fresh files; those must never
    count as this batch's evidence for the oracle or the refit (#579 Codex P2).
    """
    kept = [
        p
        for p in payloads
        if _archive_matches_combo(p, car_id=car_id, track_id=track_id, layout=layout)
    ]
    return kept, len(payloads) - len(kept)


def evaluate_selfplay_iteration(
    exit_code: int, outcome: dict | None, archive_payloads: list[dict]
) -> tuple[bool, str]:
    """The keep-last-valid falsification oracle for one envelope step (pure; #577/#244).

    An iteration is VALID only when the drive stage passed, the car never needed a recovery,
    at least one TIMED lap completed with its archive present, and no counted lap is AC-invalid.
    Anything else falsifies the step — the caller reverts to the last-valid plant and reports
    the named reason (never a silent retry of the same envelope).
    """
    if outcome is None:
        return False, "stage report missing (drive stage did not produce report.json)"
    report = outcome.get("report") if isinstance(outcome.get("report"), dict) else {}
    if exit_code != 0:
        stage = report.get("stage")
        error = report.get("error")
        return False, f"drive stage failed (exit {exit_code}, stage={stage}, error={error})"
    drive = report.get("drive") if isinstance(report.get("drive"), dict) else {}
    recoveries = drive.get("recoveries")
    if isinstance(recoveries, (int, float)) and recoveries > 0:
        return False, f"{int(recoveries)} recovery(ies) during the envelope step (spin/stall)"
    lap_times = stage_lap_times_ms(outcome)
    if not lap_times:
        return False, "no timed lap completed within the drive budget"
    if not archive_payloads:
        return False, "no lap archives collected (cannot verify lap validity or refine)"
    # Fail closed on verifiability (#579 Qodo): only a payload carrying an explicit lap-validity
    # verdict counts as evidence — a malformed/partial object must not satisfy the batch.
    verifiable = 0
    for payload in archive_payloads:
        lap = payload.get("lap") if isinstance(payload.get("lap"), dict) else {}
        validity = lap.get("is_valid")
        if validity is False:
            lap_n = lap.get("lap_n")
            return False, f"AC-invalid lap in the batch (lap_n={lap_n})"
        if validity is not True:
            return False, (
                "archive payload without a lap-validity verdict "
                "(malformed/partial lap archive — fail closed)"
            )
        verifiable += 1
    if verifiable < len(lap_times):
        # Every counted lap must be verifiable: a partial archive set (writer flake / poll
        # timeout) leaves timed laps whose validity cannot be proven, and refining from it
        # would under-represent the batch (#579 Codex P2).
        return False, (
            f"archive count {verifiable} < {len(lap_times)} timed laps "
            "(cannot verify every counted lap)"
        )
    return True, (f"{len(lap_times)} timed lap(s), all archived laps AC-valid, zero recoveries")


def iteration_scale(base: float, step: float, index: int, cap: float) -> float:
    """The envelope ladder's ggv-scale for iteration ``index`` (1-based), capped."""
    return round(min(base + step * index, cap), 6)


def run_selfplay(
    args: argparse.Namespace,
    *,
    run_stage: StageRunner,
    evidence_root: Path,
    user_dir: Path,
    setup_key: str | None,
    setup_ini: str | Path | None,
    base_outcome: dict | None,
) -> dict:
    """Drive the #577 refine -> rebuild -> drive self-play ladder; returns the selfplay report.

    Iteration ``i`` refines the plant from the PREVIOUS valid drive's lap archives (provenance-
    bound to the pipeline's own stages), persists it through ``save_plant_artifact`` (the fit
    provenance hash change invalidates the cached alien line, so the next drive rebuilds the
    line/QSS against the updated plant), steps the envelope ladder's ggv-scale, and drives again.
    A falsified step (see :func:`evaluate_selfplay_iteration`) reverts the plant to the last
    valid artifact bytes and stops — the report names the falsification. A step that cannot
    change the envelope at all (scale already capped AND the refit failed) stops honestly rather
    than re-driving the identical envelope.
    """
    from tools.ac_harness.auto_drive import generic_gt3_ggv
    from tools.ac_harness.plant_id import save_plant_artifact, selfplay_refine_result

    plant_path = plant_artifact_path(
        user_dir, args.car, args.track, setup_key, setup_ini, layout=args.track_layout
    )
    selfplay: dict = {
        "iterations_requested": args.iterations,
        "laps_per_iteration": args.laps,
        "base_scale": args.ggv_scale,
        "scale_step": args.scale_step,
        "max_scale": args.max_scale,
        "iterations": [],
        "stopped": "completed",
        "lap_trajectory_ms": [],
        "best_lap_ms": None,
    }
    base_laps = stage_lap_times_ms(base_outcome)
    selfplay["lap_trajectory_ms"].append(base_laps)
    # The base drive must pass the SAME oracle before its archives may seed refinement: exit 0
    # does not preclude recoveries or AC-invalid archived laps, and refining from that evidence
    # would promote a plant the falsification oracle would reject (#579 Codex P1). An invalid
    # base still allows the ladder to run — each iteration changes the envelope via scale and is
    # itself falsification-gated — it just refines from nothing until a valid batch exists.
    base_payloads, base_load_errors = load_archive_payloads(stage_lap_archives(base_outcome))
    base_payloads, base_foreign = combo_filter_payloads(
        base_payloads, car_id=args.car, track_id=args.track, layout=args.track_layout
    )
    base_valid, base_reason = evaluate_selfplay_iteration(0, base_outcome, base_payloads)
    selfplay["base"] = {"valid": base_valid, "reason": base_reason, "lap_times_ms": base_laps}
    if base_load_errors:
        # Unreadable/corrupt archives must be DISCLOSED, not hidden behind the generic validity
        # reason (#579 Qodo observability; same class as the repo's no-silent-swallowing pitfall).
        selfplay["base"]["archive_load_errors"] = base_load_errors
    if base_foreign:
        selfplay["base"]["foreign_archives_dropped"] = base_foreign
    # An oracle-invalid base's laps are marked unusable by this very report — they must not seed
    # the performance summary either (#579 Codex P2).
    best: int | None = min(base_laps) if (base_laps and base_valid) else None
    prev_archives = stage_lap_archives(base_outcome) if base_valid else []
    if not base_valid:
        print(
            f"auto-alien: base drive not usable as refinement evidence ({base_reason}) — "
            "the ladder starts without a refit batch"
        )
    prev_scale = args.ggv_scale
    for index in range(1, args.iterations + 1):
        scale = iteration_scale(args.ggv_scale, args.scale_step, index, args.max_scale)
        entry: dict = {"index": index, "ggv_scale": scale}
        selfplay["iterations"].append(entry)

        # 1) Refine the plant from the previous drive's batch (keep-last-valid on any failure).
        #    All artifact I/O is OSError-guarded: a filesystem failure must surface as an honest
        #    stopped reason in the composed report, never crash the pipeline before the report
        #    is written (#579 Qodo reliability).
        refined = False
        last_valid_bytes: bytes | None = None
        candidate_bytes: bytes | None = None
        try:
            if not prev_archives:
                entry["refine"] = {
                    "ok": False,
                    "reason": "no lap archives from the previous drive",
                }
            else:
                # Snapshot the artifact bytes BEFORE loading: the refine-save runs outside the
                # drive stage's machine-global rig lock, so a peer worktree may refresh the same
                # plant between our load and our save — persisting a refinement of stale bytes
                # would silently clobber the peer's newer fit (#579 Codex P2).
                pre_refine_bytes = plant_path.read_bytes() if plant_path.exists() else None
                artifact = load_plant_artifact(
                    user_dir, args.car, args.track, setup_key, setup_ini, layout=args.track_layout
                )
                if artifact is None:
                    entry["refine"] = {
                        "ok": False,
                        "reason": f"plant artifact unloadable ({plant_path})",
                    }
                else:
                    archive_payloads, load_errors = load_archive_payloads(prev_archives)
                    archive_payloads, foreign = combo_filter_payloads(
                        archive_payloads,
                        car_id=args.car,
                        track_id=args.track,
                        layout=args.track_layout,
                    )
                    result, block = selfplay_refine_result(
                        artifact, archive_payloads, generic_gt3_ggv(), prior_name="generic_gt3_ggv"
                    )
                    entry["refine"] = {
                        k: v for k, v in block.items() if k not in ("model", "tyre_states")
                    }
                    if load_errors:
                        entry["refine"]["archive_load_errors"] = load_errors
                    if foreign:
                        entry["refine"]["foreign_archives_dropped"] = foreign
                    merge_stats = block.get("selfplay_merge", {}) if result is not None else {}
                    merge_changed = bool(
                        merge_stats.get("lateral_bins_adopted")
                        or merge_stats.get("lateral_bins_raised")
                        or (
                            merge_stats.get("mu_lat_g_after", 0.0)
                            > merge_stats.get("mu_lat_g_before", 0.0)
                        )
                    )
                    if result is not None and not merge_changed:
                        # A refit that changed nothing (no bin adopted/raised, ceiling unchanged)
                        # is a no-op: persisting it would only churn provenance (a pointless
                        # identical line rebuild) while the PHYSICAL envelope stays the same —
                        # which must not count as "the envelope changed" for the retry guard
                        # (#579 Codex P2).
                        entry["refine"]["no_op"] = True
                        print(
                            f"auto-alien: iteration {index} refit was a no-op (no envelope "
                            "change) — plant left as-is"
                        )
                    elif result is not None:
                        current_bytes = plant_path.read_bytes() if plant_path.exists() else None
                        # Re-key the save with the CALLER-resolved setup identity: a portable/
                        # moved artifact keeps its creator's absolute setup_ini path, and saving
                        # under that stale key would write a DIFFERENT plant filename than the
                        # one this pipeline loads and drives (#579 Codex P2).
                        result["setup_ini"] = str(setup_ini) if setup_ini else None
                        expected_path = plant_artifact_path(
                            user_dir,
                            str(result.get("car_id") or ""),
                            str(result.get("track_id") or ""),
                            result.get("setup"),
                            result.get("setup_ini"),
                            layout=result.get("layout"),
                        )
                        if current_bytes != pre_refine_bytes:
                            entry["refine"]["save_skipped"] = (
                                "plant artifact changed between load and save (peer "
                                "re-identification?) — refinement of stale bytes not persisted"
                            )
                            print(
                                f"auto-alien: iteration {index} refine save SKIPPED — "
                                f"{entry['refine']['save_skipped']}"
                            )
                        elif Path(expected_path) != Path(plant_path):
                            # Refuse a forked plant file OUTRIGHT: writing the refinement under
                            # a different identity key would leave the driven plant untouched
                            # and strand a falsified candidate at a path the revert cannot
                            # reach (#579 daemon HIGH).
                            entry["refine"]["save_skipped"] = (
                                f"refined identity keys to {expected_path}, not the driven "
                                f"plant {plant_path} — refusing a forked plant file"
                            )
                            print(
                                f"auto-alien: iteration {index} refine save SKIPPED — "
                                f"{entry['refine']['save_skipped']}"
                            )
                        else:
                            last_valid_bytes = pre_refine_bytes
                            saved = save_plant_artifact(user_dir, result)
                            candidate_bytes = Path(saved).read_bytes()
                            refined = True
                            print(
                                f"auto-alien: iteration {index} plant refined "
                                f"(lateral bins adopted="
                                f"{merge_stats.get('lateral_bins_adopted')} "
                                f"raised={merge_stats.get('lateral_bins_raised')}) -> {saved}"
                            )
                    else:
                        print(
                            f"auto-alien: iteration {index} refine FAILED — keeping the "
                            f"last-valid plant ({block.get('reason')})"
                        )
        except OSError as exc:
            # Fail loud IN the report: keep-last-valid integrity can no longer be guaranteed
            # once artifact I/O errors, so the ladder stops with the named reason.
            entry.setdefault("refine", {})["ok"] = False
            entry["refine"]["reason"] = f"filesystem error during refine persist: {exc}"
            selfplay["stopped"] = (
                f"filesystem error at iteration {index} ({exc}) — self-play stopped "
                "(keep-last-valid integrity cannot be guaranteed past an I/O failure)"
            )
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break

        # 2) Refuse to re-drive an identical envelope: no refit AND no scale movement means the
        #    step could only repeat the previous iteration verbatim (#577 AC: never silently
        #    retry the same envelope).
        if not refined and scale == prev_scale:
            selfplay["stopped"] = (
                f"envelope unchanged at iteration {index} (scale capped at {scale} and the "
                "refit did not change the plant) — refusing to retry the same envelope"
            )
            entry["skipped"] = True
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break

        # 3) Drive the (possibly rebuilt) line at this iteration's envelope.
        settled = wait_sidecar_port_settled(args.sidecar_url or DEFAULT_SIDECAR_URL)
        entry["sidecar_port_before"] = settled
        stage_dir = Path(evidence_root) / f"iter{index:02d}"
        print(
            f"auto-alien: iteration {index}/{args.iterations} drive "
            f"(ggv_scale={scale}, laps={args.laps or 1})"
        )
        code = run_stage(drive_argv(args, stage_dir, ggv_scale=scale))
        entry["exit_code"] = code
        entry["evidence_dir"] = str(stage_dir)
        outcome = load_stage_outcome(stage_dir)
        archives = stage_lap_archives(outcome)
        archive_payloads, load_errors = load_archive_payloads(archives)
        archive_payloads, foreign = combo_filter_payloads(
            archive_payloads, car_id=args.car, track_id=args.track, layout=args.track_layout
        )
        if load_errors:
            entry["archive_load_errors"] = load_errors
        if foreign:
            entry["foreign_archives_dropped"] = foreign
        lap_times = stage_lap_times_ms(outcome)
        entry["lap_times_ms"] = lap_times
        selfplay["lap_trajectory_ms"].append(lap_times)
        valid, reason = evaluate_selfplay_iteration(code, outcome, archive_payloads)
        entry["valid"] = valid
        entry["reason"] = reason

        if not valid:
            # 4) Keep-last-valid: revert the refined plant so the falsified envelope never
            #    becomes the combo's persisted fit (#244 pattern). Only touch the artifact when
            #    it is still byte-identical to what THIS iteration persisted — a peer worktree
            #    may have re-identified the combo meanwhile.
            entry["falsified"] = reason
            if refined and last_valid_bytes is not None:
                try:
                    current = plant_path.read_bytes() if plant_path.exists() else b""
                    if current == candidate_bytes:
                        tmp = plant_path.with_suffix(".json.tmp")
                        tmp.write_bytes(last_valid_bytes)
                        tmp.replace(plant_path)
                        entry["reverted"] = True
                        print(
                            f"auto-alien: iteration {index} FALSIFIED ({reason}) — plant "
                            "reverted to the last-valid fit"
                        )
                    else:
                        entry["reverted"] = False
                        entry["revert_skipped"] = (
                            "plant artifact changed since this iteration persisted it "
                            "(peer re-identification?) — revert skipped"
                        )
                        print(
                            f"auto-alien: iteration {index} FALSIFIED ({reason}); "
                            f"{entry['revert_skipped']}"
                        )
                except OSError as exc:
                    # The falsified candidate may still be on disk — say so loudly in the
                    # report rather than crash before it is written (#579 Qodo reliability).
                    entry["reverted"] = False
                    entry["revert_error"] = f"filesystem error during revert: {exc}"
                    print(
                        f"auto-alien: iteration {index} FALSIFIED ({reason}); REVERT FAILED — "
                        f"{entry['revert_error']} (the falsified fit may still be persisted; "
                        "re-run --force-identify to rebuild the plant)"
                    )
            else:
                print(
                    f"auto-alien: iteration {index} FALSIFIED ({reason}) — plant unchanged "
                    "this iteration (nothing to revert)"
                )
            selfplay["stopped"] = f"falsified at iteration {index}: {reason}"
            break

        print(
            f"auto-alien: iteration {index} VALID — laps "
            + ", ".join(f"{ms / 1000.0:.3f}s" for ms in lap_times)
        )
        if lap_times:
            it_best = min(lap_times)
            best = it_best if best is None else min(best, it_best)
        prev_archives = archives
        prev_scale = scale

    selfplay["best_lap_ms"] = best
    return selfplay


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


def resolve_drive_seconds(args: argparse.Namespace) -> float:
    """The alien stage's drive budget; scales with the flying-lap window when not explicit.

    ``--drive-seconds`` stays authoritative when passed. The default single-lap budget (300 s)
    cannot fit a multi-lap window (3 Magione laps + standing start already exceed it, Spa far
    more), so a ``--laps N`` run without an explicit budget gets ``180 + 240*N`` — generous per
    lap (Spa ~214 s) because the budget is only a cap: the tap closes the window at the Nth lap.
    """
    if args.drive_seconds is not None:
        return float(args.drive_seconds)
    if args.laps > 0:
        return 180.0 + 240.0 * args.laps
    return 300.0


def drive_argv(
    args: argparse.Namespace,
    evidence_dir: Path,
    *,
    ggv_scale: float | None = None,
    rebuild_line: bool | None = None,
) -> list[str]:
    """The alien drive stage's argv; ``ggv_scale`` overrides per self-play iteration (#577)."""
    scale = args.ggv_scale if ggv_scale is None else ggv_scale
    argv = _passthrough_args(args) + [
        "--driver",
        "alien",
        "--evidence-dir",
        str(evidence_dir),
        "--drive-seconds",
        str(resolve_drive_seconds(args)),
        "--max-speed",
        str(args.max_speed),
        "--ggv-scale",
        str(scale),
        "--wait-lap",
    ]
    if args.laps > 0:
        argv += ["--laps", str(args.laps)]
    if scale > 1.0:
        # Only a self-play iteration override can be > 1 (run_pipeline rejects a bare
        # --ggv-scale > 1, so the one-shot base drive keeps the #572 gate — #579 Codex P1);
        # the drive stage still enforces its hard 1.2 cap and the falsification oracle guards
        # every step (#577).
        argv.append("--alien-allow-overspeed")
    if args.strict:
        argv.append("--strict")
    rebuild = args.rebuild_line if rebuild_line is None else rebuild_line
    if rebuild:
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
        "--drive-seconds",
        type=float,
        default=None,
        help="drive budget for the alien lap stage (default: 300, or 180+240*laps with --laps)",
    )
    p.add_argument("--max-speed", type=float, default=240.0, help="alien drive speed cap (km/h)")
    p.add_argument(
        "--ggv-scale", type=float, default=0.9, help="safety margin on the QSS min-time profile"
    )
    p.add_argument(
        "--laps",
        type=int,
        default=0,
        help="#577 flying-lap window: drive until N TIMED laps complete (or the drive budget); "
        "per-lap times land in the stage report. 0 = legacy single-lap",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="#577 progressive-envelope self-play: after the base drive, run K refine->rebuild->"
        "drive iterations with keep-last-valid falsification (0 = off)",
    )
    p.add_argument(
        "--scale-step",
        type=float,
        default=0.05,
        help="per-iteration ggv-scale increment for the self-play envelope ladder (#244 pattern)",
    )
    p.add_argument(
        "--max-scale",
        type=float,
        default=1.1,
        help="self-play envelope ladder cap (hard limit 1.2; >1 probes above the uncertainty-"
        "safe QSS floor, falsification-gated)",
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
    if args.laps < 0:
        raise ValueError(f"--laps must be >= 0 (got {args.laps})")
    if args.iterations < 0:
        raise ValueError(f"--iterations must be >= 0 (got {args.iterations})")
    # The BASE drive keeps the #572 one-shot gate: above-1 envelopes are reachable only through
    # the falsification-gated self-play ladder (per-iteration scale overrides), never by passing
    # a bare --ggv-scale > 1 (#579 Codex P1).
    if not 0.0 < args.ggv_scale <= 1.0:
        raise ValueError(
            f"--ggv-scale must be in (0, 1] (got {args.ggv_scale}); envelopes above 1 are "
            "reachable only via the --iterations keep-last-valid ladder (--max-scale)"
        )
    if args.iterations > 0:
        import math as _math

        if args.laps < 1:
            raise ValueError(
                "--iterations requires --laps >= 1 (self-play refines from timed-lap batches; "
                "the legacy any-boundary --wait-lap window cannot provide them)"
            )
        if not (_math.isfinite(args.scale_step) and args.scale_step > 0):
            raise ValueError(f"--scale-step must be finite and > 0 (got {args.scale_step})")
        if not (_math.isfinite(args.max_scale) and 0 < args.max_scale <= ALIEN_MAX_OVERSPEED_SCALE):
            raise ValueError(
                f"--max-scale must be in (0, {ALIEN_MAX_OVERSPEED_SCALE}] (got {args.max_scale})"
            )
        if args.max_scale < args.ggv_scale:
            # A cap below the base would make "iteration 1" an EASIER envelope than the base
            # drive — a regression probe, not the progressive ladder (#579 Codex P2).
            raise ValueError(
                f"--max-scale ({args.max_scale}) must be >= --ggv-scale ({args.ggv_scale}); "
                "the ladder only steps upward from the base envelope"
            )
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

    if args.iterations > 0:
        # #577 progressive-envelope self-play. A falsified/stopped ladder is a VALID pipeline
        # outcome — the base drive passed and the report names exactly where and why the ladder
        # ended (keep-last-valid already restored the plant). Only the base stages gate exit.
        base_outcome = load_stage_outcome(stage_dir)
        base_laps = stage_lap_times_ms(base_outcome)
        print(
            "auto-alien: base drive laps "
            + (", ".join(f"{ms / 1000.0:.3f}s" for ms in base_laps) if base_laps else "(none)")
        )
        report["selfplay"] = run_selfplay(
            args,
            run_stage=run_stage,
            evidence_root=evidence_root,
            user_dir=user_dir,
            setup_key=setup_key,
            setup_ini=setup_ini,
            base_outcome=base_outcome,
        )
        best = report["selfplay"].get("best_lap_ms")
        print(
            f"auto-alien: selfplay done — {report['selfplay']['stopped']}"
            + (f"; best lap {best / 1000.0:.3f}s" if isinstance(best, int) else "")
        )

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
