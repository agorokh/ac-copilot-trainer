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
(``--iterations K``): after the base drive, the ladder alternates two kinds of iteration, each
moving exactly ONE knob so a falsification is attributable (#703):

* a **plant** step refines the friction fit from the previous drive's lap archives only (monotonic
  merge — measured lateral bins tighten, longitudinal evidence is never lost), persists it through
  the canonical plant gates (invalidating the cached alien line via the fit provenance hash), and
  drives the rebuilt line at the last VALIDATED ggv-scale;
* an **envelope** step leaves the plant untouched and drives the next ggv-scale ladder rung.

Every step is falsifiable: an invalid lap / spin / failed stage stops the ladder and the report
names both the reason and the falsified component. A falsified **plant** step reverts the plant to
the last-valid fit (the #244 keep-last-valid pattern); a falsified **envelope** rung has nothing to
revert, so a refit that was independently validated survives it. The ladder never silently retries
the same envelope.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.ac_harness.auto_drive import (
    ALIEN_MAX_OVERSPEED_SCALE,
    archive_matches_combo,
    resolve_ac_user_dir,
    resolve_lap_window_drive_seconds,
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


def stage_l3_summary(outcome: dict | None) -> dict | None:
    """Condensed #582 L3 refinement summary from a drive stage's report, or ``None`` when absent.

    Keeps the composed pipeline report honest about what each stage actually drove: how many
    corners ran the refined interior, how many reverted to safe-QSS, and the planner's predicted
    gain — the full per-corner report stays in the stage's own artifact/report.

    ``write_evidence`` stores the alien-line detail under the TOP-LEVEL ``run`` extras of
    ``report.json`` (``run.alien_line``), not inside the ``report`` block (#583 Codex P2).
    """
    run = (outcome or {}).get("run")
    if not isinstance(run, dict):
        return None
    alien = run.get("alien_line")
    if not isinstance(alien, dict):
        return None
    l3 = alien.get("l3")
    if not isinstance(l3, dict):
        return None
    summary = {
        "refined_corners": l3.get("refined_corners"),
        "reverted_corners": l3.get("reverted_corners"),
        "predicted_gain_ms": l3.get("predicted_gain_ms"),
    }
    if l3.get("reverted_all"):
        summary["reverted_all"] = l3.get("reverted_all")
    return summary


def compose_stint_layers(
    *,
    plant_artifact: dict | None,
    archive_payloads: Sequence[dict],
    laps_remaining: int,
    fuel_start_l: float,
    fuel_burn_l_per_lap: float,
    tyre_temp_target_c: float,
    tyre_temp_tolerance_c: float,
    wear_budget_fraction: float,
    v_top_kmh: float,
    environment_prior: dict | None = None,
) -> dict:
    """Build Layer-0 environment + Layer-4 stint plan blocks for the composed report (#674).

    Failures stay named in the returned dict (never swallowed): a bad archive or unusable plant
    surfaces as ``ok=False`` with a reason so the pipeline can keep driving with baseline knobs.
    """
    from tools.ac_harness.env_observer import (
        EnvironmentObserverError,
        EnvironmentState,
        environment_for_plan,
        environment_from_archives,
    )
    from tools.ac_harness.stint_optimizer import StintInputs, StintOptimizerError, plan_stint

    block: dict = {"ok": False, "environment": None, "stint": None}
    try:
        prior = EnvironmentState.from_dict(environment_prior)
        environment = (
            environment_from_archives(archive_payloads, prior=prior) if archive_payloads else prior
        )
        if environment is not None:
            block["environment"] = environment_for_plan(environment)
            block["environment_state"] = environment.to_dict()
        if plant_artifact is None:
            raise StintOptimizerError("stint_plant_missing")
        plan = plan_stint(
            StintInputs(
                plant_artifact=plant_artifact,
                environment=environment,
                laps_remaining=max(1, int(laps_remaining)),
                fuel_start_l=fuel_start_l,
                fuel_burn_l_per_lap=fuel_burn_l_per_lap,
                tyre_temp_target_c=tyre_temp_target_c,
                tyre_temp_tolerance_c=tyre_temp_tolerance_c,
                wear_budget_fraction=wear_budget_fraction,
                v_top_kmh=v_top_kmh,
            )
        )
        block["stint"] = plan.to_dict()
        block["inner_loop"] = {
            "ggv_scale": plan.pace_scale,
            "l3_params": plan.l3_params,
            "degraded": plan.degraded,
            "reasons": list(plan.reasons),
        }
        block["ok"] = True
    except (EnvironmentObserverError, StintOptimizerError, ValueError, TypeError) as exc:
        block["error"] = str(exc)
    return block


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
        if archive_matches_combo(p, car_id=car_id, track_id=track_id, layout=layout)
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
    """The envelope ladder's ggv-scale for rung ``index`` (1-based), capped.

    Since #703 the rung index advances only on *envelope* steps, so it is no longer the same
    counter as the self-play iteration index (plant steps hold the last validated scale).
    """
    return round(min(base + step * index, cap), 6)


def _read_plant_bytes(plant_path: Path) -> bytes | None:
    """The plant artifact's current bytes, or ``None`` when absent/unreadable (best-effort)."""
    try:
        return plant_path.read_bytes() if plant_path.exists() else None
    except OSError:
        return None


def next_envelope_rung(
    base: float, step: float, cap: float, prev_scale: float, rung: int
) -> int | None:
    """Smallest rung index >= ``rung`` whose ladder scale strictly EXCEEDS ``prev_scale``.

    ``None`` means there is no envelope rung left at all — which is NOT the same as "the rung is
    capped at the current scale": with ``--stint`` the validated base can sit **above**
    ``--max-scale``, because the cap is validated only against ``--ggv-scale``. A saturated
    candidate that does not exceed ``prev_scale`` is therefore no rung, not a rung to drive; a
    "ladder rung" that lowered the envelope would be the second knob moving the wrong way.

    Computed algebraically rather than by scanning, because :func:`iteration_scale` rounds to six
    decimals: a legal cap with more decimals (``--max-scale 0.9000004``) saturates every candidate
    to the same rounded value, and a scan comparing against the UNROUNDED cap would never
    terminate (#703 Codex P2). The cap comparison here uses the same rounding as the ladder.
    """
    capped = round(cap, 6)
    if capped <= prev_scale:
        return None
    if iteration_scale(base, step, rung, cap) > prev_scale:
        return rung
    # The smallest rung whose UNSATURATED value rounds strictly above prev_scale. The +5e-7 is the
    # six-decimal rounding threshold: a small `--scale-step` (1e-7) leaves several consecutive
    # rungs on the same rounded plateau, and a closed form that ignores it lands *inside* the
    # plateau and wrongly concludes no rung remains (#703 Codex P2).
    needed = math.ceil((prev_scale + 5e-7 - base) / step)
    # Saturation is a guaranteed hit because `capped > prev_scale` was established above, so this
    # search is bounded and always finds a rung when one exists — no unbounded scan.
    saturating = math.ceil((cap - base) / step)
    probes = sorted({max(rung, 1), max(rung, needed), max(rung, needed) + 1, max(rung, saturating)})
    for probe in probes:
        if iteration_scale(base, step, probe, cap) > prev_scale:
            return probe
    return None


def _inherited_selfplay_merges(
    user_dir: Path,
    args: argparse.Namespace,
    setup_key: str | None,
    setup_ini: str | Path | None,
) -> int:
    """How many self-play merges the combo's plant already carried before this ladder ran.

    Read-only and best-effort: an unreadable/absent artifact yields 0 rather than failing the
    ladder, because this figure is reporting fidelity (#703), never a gate.
    """
    try:
        artifact = load_plant_artifact(
            user_dir, args.car, args.track, setup_key, setup_ini, layout=args.track_layout
        )
    except OSError:
        return 0
    if not isinstance(artifact, dict):
        return 0
    ggv = artifact.get("ggv") if isinstance(artifact.get("ggv"), dict) else {}
    model = ggv.get("model") if isinstance(ggv.get("model"), dict) else {}
    provenance = model.get("provenance") if isinstance(model.get("provenance"), dict) else {}
    merges = provenance.get("selfplay_merges")
    return len(merges) if isinstance(merges, list) else 0


def run_selfplay(
    args: argparse.Namespace,
    *,
    run_stage: StageRunner,
    evidence_root: Path,
    user_dir: Path,
    setup_key: str | None,
    setup_ini: str | Path | None,
    base_outcome: dict | None,
    base_scale: float | None = None,
) -> dict:
    """Drive the #577 refine -> rebuild -> drive self-play ladder; returns the selfplay report.

    **Decoupled ladder (#703).** Every iteration changes exactly ONE knob, so a falsification
    identifies which knob it falsified:

    * a **plant** step refines the plant from the PREVIOUS valid drive's lap archives (provenance-
      bound to the pipeline's own stages), persists it through ``save_plant_artifact`` (the fit
      provenance hash change invalidates the cached alien line, so the drive rebuilds the line/QSS
      against the updated plant) and drives at the LAST VALIDATED ``ggv_scale``;
    * an **envelope** step leaves the plant untouched and drives the next rung of the ggv-scale
      ladder.

    The steps alternate, starting with a plant step. A plant step whose refit is unavailable or a
    no-op falls through to an envelope step rather than re-driving an identical line, and an
    envelope step at the scale cap falls back to a plant step — the ladder only stops when neither
    knob can move.

    Why not one iteration per (refit + scale step)? Because the oracle judges the iteration as a
    whole, so a falsified scale rung reverted a refit built from independently valid evidence, and
    the top rung is by construction the one most likely to falsify — the ladder destroyed its own
    best lever (issue #703; ~3.5 s at identical scale on the #529 Magione ladders). Attributing the
    verdict by re-driving would cost an extra launch cycle (expensive under #627), and simply
    keeping every refit is unsafe: :func:`~tools.ac_harness.ggv_profile.merge_selfplay_model` is
    strictly monotone (it only ever RAISES bins), so the keep-last-valid revert is the only
    downward path the plant has. Decoupling keeps that safety valve and makes it precise: a
    falsified plant step still reverts, a falsified envelope step has nothing to revert.

    A falsified step (see :func:`evaluate_selfplay_iteration`) stops the ladder and the report
    names both the reason and the falsified component (``plant`` vs ``envelope``).
    """
    from tools.ac_harness.auto_drive import generic_gt3_ggv
    from tools.ac_harness.plant_id import (
        persist_selfplay_refinement,
        revert_plant_artifact,
        selfplay_refine_result,
    )
    from tools.ac_harness.rig_lock import RigSessionBusy

    plant_path = plant_artifact_path(
        user_dir, args.car, args.track, setup_key, setup_ini, layout=args.track_layout
    )
    lock_timeout = args.rig_lock_timeout if args.rig_lock_timeout is not None else 0.0
    # The scale the BASE drive actually ran. ``--stint`` can override it with the Layer-4 pace
    # scale, and a plant step "holds the last validated scale" — so seeding this from
    # ``args.ggv_scale`` when the base drove at the override would silently move the envelope
    # during a supposedly plant-only iteration and misattribute its verdict (#703, Codex P1).
    resolved_base_scale = args.ggv_scale if base_scale is None else float(base_scale)
    selfplay: dict = {
        "iterations_requested": args.iterations,
        "laps_per_iteration": args.laps,
        "base_scale": resolved_base_scale,
        "ladder_base_scale": args.ggv_scale,
        "scale_step": args.scale_step,
        "max_scale": args.max_scale,
        "iterations": [],
        "ok": True,
        "stopped": "completed",
        "lap_trajectory_ms": [],
        "best_lap_ms": None,
        # #703: each iteration moves exactly one knob, so a verdict is attributable.
        "ladder_mode": "decoupled",
        "refit_iterations": [],
        # Self-play merges the plant already carried when this invocation started. The refit
        # compounds ACROSS runs, so a run whose own plant step is a no-op can still be protecting
        # an inherited fit — reporting "nothing was retained" from `refit_iterations` alone would
        # be false in exactly the cross-invocation case this change exists to expose (#703).
        "inherited_selfplay_merges": _inherited_selfplay_merges(
            user_dir, args, setup_key, setup_ini
        ),
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
    base_l3 = stage_l3_summary(base_outcome)
    if base_l3 is not None:
        selfplay["base"]["l3"] = base_l3
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
    prev_scale = resolved_base_scale
    rung = 1  # next envelope rung to attempt (advances only on envelope steps, #703)
    # The plant bytes as of the last VALIDATED state. An envelope step must drive exactly this
    # plant; if a peer re-identified the combo meanwhile, the step would move two knobs and its
    # verdict would not be the envelope's (#703 Codex P1).
    validated_plant_bytes = _read_plant_bytes(plant_path)
    next_step_kind = "plant"
    for index in range(1, args.iterations + 1):
        # 0) Pick this iteration's single knob (#703). When no envelope rung can exceed the
        #    validated scale, the refit is the only remaining lever; if it is also a no-op the
        #    fall-through below reaches the unchanged-envelope stop.
        step_kind = next_step_kind
        usable_rung = next_envelope_rung(
            args.ggv_scale, args.scale_step, args.max_scale, prev_scale, rung
        )
        if usable_rung is not None:
            rung = usable_rung
        envelope_scale = (
            iteration_scale(args.ggv_scale, args.scale_step, rung, args.max_scale)
            if usable_rung is not None
            else None
        )
        if step_kind == "envelope" and envelope_scale is None:
            step_kind = "plant"
        scale = prev_scale if step_kind == "plant" else envelope_scale
        entry: dict = {"index": index, "step_kind": step_kind, "ggv_scale": scale}
        selfplay["iterations"].append(entry)

        # 1) Refine the plant from the previous drive's batch (keep-last-valid on any failure).
        #    All artifact I/O is OSError-guarded: a filesystem failure must surface as an honest
        #    stopped reason in the composed report, never crash the pipeline before the report
        #    is written (#579 Qodo reliability).
        refined = False
        peer_skipped: str | None = None
        last_valid_bytes: bytes | None = None
        candidate_bytes: bytes | None = None
        try:
            if step_kind == "envelope":
                # #703: an envelope step moves only ggv_scale. The plant is deliberately left
                # alone, so a falsification here cannot implicate — or discard — a refit whose
                # evidence was independently valid.
                entry["refine_skipped"] = "envelope step (plant deliberately untouched)"
            elif not prev_archives:
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
                        artifact,
                        archive_payloads,
                        generic_gt3_ggv(),
                        prior_name="generic_gt3_ggv",
                        setup_ini=setup_ini,
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
                        saved, persisted_bytes, save_skipped = persist_selfplay_refinement(
                            user_dir,
                            result,
                            expected_path=plant_path,
                            expected_current_bytes=pre_refine_bytes,
                            lock_timeout=lock_timeout,
                        )
                        if save_skipped:
                            entry["refine"]["save_skipped"] = save_skipped
                            peer_skipped = save_skipped
                            print(
                                f"auto-alien: iteration {index} refine save SKIPPED — "
                                f"{entry['refine']['save_skipped']}"
                            )
                        else:
                            last_valid_bytes = pre_refine_bytes
                            candidate_bytes = persisted_bytes
                            refined = True
                            # This plant step's own change becomes the state a later envelope
                            # step must find untouched (#703).
                            validated_plant_bytes = persisted_bytes
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
        except (OSError, RigSessionBusy) as exc:
            # Fail loud IN the report: keep-last-valid integrity can no longer be guaranteed
            # once artifact I/O errors, so the ladder stops with the named reason.
            entry.setdefault("refine", {})["ok"] = False
            entry["refine"]["reason"] = f"filesystem error during refine persist: {exc}"
            selfplay["ok"] = False
            selfplay["stopped"] = (
                f"filesystem error at iteration {index} ({exc}) — self-play stopped "
                "(keep-last-valid integrity cannot be guaranteed past an I/O failure)"
            )
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break

        # 2) A peer re-identified the combo between our snapshot and our save, so the plant on
        #    disk is no longer the one the previous drive validated AND is not ours to attribute.
        #    Falling through to the rung would change BOTH knobs (peer plant + new scale) and the
        #    report would blame the envelope for a drive the peer's plant may have caused — the
        #    exact attribution this decoupling exists to guarantee. Stop instead; a fresh run
        #    rebases on the peer's plant honestly (#703, Codex P1).
        if peer_skipped:
            selfplay["stopped"] = (
                f"plant changed by a peer at iteration {index} ({peer_skipped}) — self-play "
                "stopped rather than driving an unattributable step (re-run to rebase on the "
                "peer's plant)"
            )
            entry["skipped"] = True
            selfplay["requires_rebase"] = True
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break

        # 3) A plant step whose refit did not land has nothing of its own to test: spend the
        #    drive on the envelope rung instead of re-driving the identical line (#703).
        if step_kind == "plant" and not refined:
            step_kind = "envelope"
            scale = envelope_scale
            entry["step_kind"] = step_kind
            entry["ggv_scale"] = scale
            entry["fell_back_to_envelope"] = "refit did not change the plant"

        # 3b) An envelope step must drive the plant the previous step validated. `auto_drive`
        #     loads the latest on-disk plant after it takes the rig lock, so a peer that
        #     re-identified the combo meanwhile would silently change the second knob and the
        #     verdict would not be the envelope's. Stop rather than attribute it (#703 Codex P1).
        if step_kind == "envelope":
            current_plant_bytes = _read_plant_bytes(plant_path)
            if current_plant_bytes != validated_plant_bytes:
                selfplay["stopped"] = (
                    f"plant changed on disk before iteration {index}'s envelope step (peer "
                    "re-identification?) — self-play stopped rather than attributing a verdict "
                    "to the envelope while the plant also moved"
                )
                entry["skipped"] = True
                entry["plant_changed_before_step"] = True
                selfplay["requires_rebase"] = True
                print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
                break

        # 4) Refuse to re-drive an identical envelope: no refit AND no scale movement means the
        #    step could only repeat the previous iteration verbatim (#577 AC: never silently
        #    retry the same envelope).
        if not refined and scale is None:
            selfplay["stopped"] = (
                f"envelope unchanged at iteration {index} (no ladder rung above the validated "
                f"scale {prev_scale} under --max-scale {args.max_scale}, and the refit did not "
                "change the plant) — refusing to retry the same envelope"
            )
            entry["skipped"] = True
            entry["ggv_scale"] = prev_scale
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break

        # 5) Drive the (possibly rebuilt) line at this iteration's envelope.
        settled = wait_sidecar_port_settled(args.sidecar_url or DEFAULT_SIDECAR_URL)
        entry["sidecar_port_before"] = settled
        stage_dir = Path(evidence_root) / f"iter{index:02d}"
        print(
            f"auto-alien: iteration {index}/{args.iterations} {step_kind} step drive "
            f"(ggv_scale={scale}, laps={args.laps or 1})"
        )
        code = run_stage(drive_argv(args, stage_dir, ggv_scale=scale))
        entry["exit_code"] = code
        entry["evidence_dir"] = str(stage_dir)
        outcome = load_stage_outcome(stage_dir)
        iter_l3 = stage_l3_summary(outcome)
        if iter_l3 is not None:
            entry["l3"] = iter_l3
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
        # The pre-drive check above narrows the window but cannot close it: `auto_drive` loads the
        # plant after taking the rig lock, which we do not hold. So confirm afterwards that the
        # step really did run the plant we expected, and refuse to attribute the verdict when it
        # did not (#703 Codex P1 — honest about the residual race rather than silent).
        #
        # This covers BOTH step kinds. `validated_plant_bytes` is the candidate a plant step just
        # persisted, or the untouched fit an envelope step must find — so a peer that rewrote the
        # artifact after `persist_selfplay_refinement` released the rig lock is caught here too.
        # Restricting it to envelope steps let a plant step record a peer's plant as "this refit,
        # validated" (#703 Codex P1, round 3).
        plant_moved_during_step = _read_plant_bytes(plant_path) != validated_plant_bytes
        if plant_moved_during_step:
            entry["plant_changed_during_step"] = True

        if not valid:
            # 6) Keep-last-valid: revert the refined plant so the falsified envelope never
            #    becomes the combo's persisted fit (#244 pattern). Only touch the artifact when
            #    it is still byte-identical to what THIS iteration persisted — a peer worktree
            #    may have re-identified the combo meanwhile.
            #
            #    Because the step moved exactly one knob, the verdict is attributable (#703): a
            #    plant step falsifies the REFIT (revert it — the monotone merge has no other way
            #    down), an envelope step falsifies the SCALE RUNG and leaves every earlier,
            #    independently validated refit persisted.
            entry["falsified"] = reason
            if plant_moved_during_step:
                # Two knobs moved (ours + a peer's), so neither can be blamed honestly.
                entry["falsified_component"] = "unattributable"
            else:
                entry["falsified_component"] = "plant" if step_kind == "plant" else "envelope"
            retained_refits = list(selfplay["refit_iterations"])
            if refined and last_valid_bytes is not None:
                try:
                    if revert_plant_artifact(
                        plant_path,
                        last_valid_bytes,
                        expected_current_bytes=candidate_bytes,
                        car_id=args.car,
                        track_id=args.track,
                        lock_timeout=lock_timeout,
                    ):
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
                except (OSError, RigSessionBusy) as exc:
                    # The falsified candidate may still be on disk.  This is a pipeline failure,
                    # not an honest early stop: future alien runs could consume unsafe state.
                    entry["reverted"] = False
                    entry["revert_error"] = f"artifact rollback failed: {type(exc).__name__}: {exc}"
                    selfplay["ok"] = False
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
            if entry["falsified_component"] == "envelope":
                # The whole point of #703: this rung is disproven, the plant is not.
                inherited = selfplay["inherited_selfplay_merges"]
                entry["plant_refit_retained"] = retained_refits
                entry["inherited_selfplay_merges"] = inherited
                if retained_refits:
                    retained = (
                        f"this run's plant refit from iteration(s) {retained_refits} is RETAINED"
                    )
                elif inherited:
                    # No refit landed THIS run, but the plant still carries earlier self-play
                    # evidence that this rung's failure did not disturb — saying "nothing was
                    # retained" here would be false (#703, Codex P2).
                    retained = (
                        f"this run landed no refit of its own; the inherited plant "
                        f"({inherited} prior self-play merge(s)) is RETAINED"
                    )
                else:
                    retained = "the plant carries no self-play refit, so there was none to retain"
                print(
                    f"auto-alien: the falsified knob was the ENVELOPE (ggv_scale {scale}); "
                    f"{retained}"
                )
            if entry["falsified_component"] == "envelope":
                component = f"envelope step, ggv_scale {scale}"
            elif entry["falsified_component"] == "plant":
                component = f"plant step (ggv_scale held at {scale})"
            else:
                component = (
                    f"UNATTRIBUTABLE — the plant changed on disk during this envelope step at "
                    f"ggv_scale {scale}, so the verdict belongs to neither knob alone"
                )
            if selfplay["ok"]:
                selfplay["stopped"] = f"falsified at iteration {index} ({component}): {reason}"
            else:
                selfplay["stopped"] = (
                    f"rollback failed at iteration {index}: {entry['revert_error']} "
                    f"(falsified: {reason})"
                )
            break

        print(
            f"auto-alien: iteration {index} VALID ({step_kind} step) — laps "
            + ", ".join(f"{ms / 1000.0:.3f}s" for ms in lap_times)
        )
        if lap_times:
            it_best = min(lap_times)
            best = it_best if best is None else min(best, it_best)
        if plant_moved_during_step:
            # A PASS is no safer to build on than a failure here: the ladder would carry forward
            # archives and a scale earned under a plant it did not choose (#703 Codex P1). The
            # batch is also barred from seeding the scientist baseline — `run_scientist` would
            # otherwise pick this newest "valid" evidence dir and run setup experiments on the
            # exact batch this message says cannot be attributed (#703 Codex P1, round 3).
            entry["usable_as_evidence"] = False
            selfplay["requires_rebase"] = True
            selfplay["stopped"] = (
                f"plant changed on disk during iteration {index}'s {step_kind} step (peer "
                "re-identification?) — self-play stopped; the step passed but its evidence "
                "cannot be attributed to this ladder's plant"
            )
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break
        if refined:
            # This refit has now been driven and survived the oracle on its own, with the
            # envelope held — it is validated evidence, not an untested candidate (#703).
            selfplay["refit_iterations"].append(index)
        if step_kind == "envelope":
            rung += 1
        next_step_kind = "envelope" if step_kind == "plant" else "plant"
        prev_archives = archives
        prev_scale = scale

    selfplay["best_lap_ms"] = best
    return selfplay


def _scientist_baseline_outcome(selfplay: dict, base_outcome: dict | None) -> dict | None:
    """Newest oracle-valid self-play outcome, falling back to the valid base batch.

    A batch whose plant moved under it mid-drive is oracle-valid but **not attributable to this
    ladder's plant**, so it is barred from seeding a setup experiment — otherwise the scientist
    would compare setups across two different plants and could persist a corrupted verdict
    (#703 Codex P1).
    """
    for entry in reversed(selfplay.get("iterations", [])):
        if entry.get("usable_as_evidence") is False:
            continue
        if entry.get("valid") is True and entry.get("evidence_dir"):
            outcome = load_stage_outcome(Path(entry["evidence_dir"]))
            if outcome is not None:
                return outcome
    base = selfplay.get("base") if isinstance(selfplay.get("base"), dict) else {}
    return base_outcome if base.get("valid") is True else None


def _load_scientist_proposals(path: Path | None) -> list[dict] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"--scientist-proposals is unreadable: {exc}") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("--scientist-proposals must contain a JSON array of objects")
    return payload


def run_scientist(
    args: argparse.Namespace,
    *,
    run_stage: StageRunner,
    evidence_root: Path,
    user_dir: Path,
    setup_ini: str | Path | None,
    selfplay: dict,
    base_outcome: dict | None,
) -> dict:
    """Plan and execute #529 P4 setup experiments through the normal auto-alien oracle."""
    from tools.ac_harness.alien_scientist import (
        LEDGER_NAME,
        ScientistError,
        build_plan,
        ensure_state_root,
        evaluate_experiment,
        load_ledger,
        persist_completed_run,
        state_root,
        write_candidate_setup,
    )
    from tools.ai_sidecar.car_schema import load_latest_schema

    result: dict = {"configured": True, "ok": False, "stage": "plan", "outcomes": []}
    try:
        if setup_ini is None:
            raise ScientistError("scientist_requires_resolved_setup")
        schema = load_latest_schema(args.car)
        if schema is None:
            raise ScientistError("scientist_car_schema_missing")
        baseline_outcome = _scientist_baseline_outcome(selfplay, base_outcome)
        if baseline_outcome is None:
            raise ScientistError("scientist_valid_baseline_batch_missing")
        baseline_payloads, load_errors = load_archive_payloads(stage_lap_archives(baseline_outcome))
        baseline_payloads, foreign = combo_filter_payloads(
            baseline_payloads,
            car_id=args.car,
            track_id=args.track,
            layout=args.track_layout,
        )
        baseline_valid, baseline_reason = evaluate_selfplay_iteration(
            0, baseline_outcome, baseline_payloads
        )
        baseline_lap_times = stage_lap_times_ms(baseline_outcome)
        if (
            load_errors
            or foreign
            or not baseline_valid
            or len(baseline_lap_times) < args.laps
            or len(baseline_payloads) < args.laps
        ):
            raise ScientistError(
                "scientist_baseline_batch_unverifiable:"
                f"{baseline_reason}:requested_laps={args.laps}:"
                f"timed_laps={len(baseline_lap_times)}:archives={len(baseline_payloads)}:"
                f"load_errors={len(load_errors)}:foreign={foreign}"
            )
        scope = {
            "mechanical_platform": args.scientist_mechanical_platform or args.car,
            "aero_platform": args.scientist_aero_platform or args.car,
            "tyre_family": args.scientist_tyre_family or f"car:{args.car}",
            "track_archetype": args.scientist_track_archetype or args.track,
        }
        stopped = str(selfplay.get("stopped") or "").strip()
        trigger = args.scientist_trigger or (
            "pace_plateau_after_selfplay" if stopped == "completed" else stopped or "pace_plateau"
        )
        scientist_root = ensure_state_root(user_dir)
        ledger_path = scientist_root / LEDGER_NAME
        plan = build_plan(
            trigger=trigger,
            combo={"car": args.car, "track": args.track, "layout": args.track_layout},
            scope=scope,
            baseline_payloads=baseline_payloads,
            schema=schema,
            ledger=load_ledger(ledger_path, allowed_root=scientist_root),
            proposed_hypotheses=_load_scientist_proposals(args.scientist_proposals),
            batch_size=args.scientist_batch_size,
        )
        result["plan"] = plan
        result["stage"] = "execute"
        for index, experiment in enumerate(plan["experiments"], 1):
            candidate_path = write_candidate_setup(
                setup_ini,
                user_dir=user_dir,
                plan_id=plan["plan_id"],
                experiment=experiment,
            )
            candidate_root = evidence_root / "scientist" / f"candidate_{index:02d}"
            candidate_args = argparse.Namespace(**vars(args))
            candidate_args.setup = str(candidate_path)
            candidate_args.force_identify = False
            candidate_args.iterations = 0
            candidate_args.scientist = False
            candidate_args.scientist_proposals = None
            candidate_args.evidence_dir = candidate_root
            code, candidate_report = run_pipeline(candidate_args, run_stage=run_stage)
            candidate_root.mkdir(parents=True, exist_ok=True)
            (candidate_root / "alien_report.json").write_text(
                json.dumps(candidate_report, indent=2), encoding="utf-8"
            )
            drive_stage = candidate_report.get("stages", {}).get("drive", {})
            candidate_outcome = (
                load_stage_outcome(Path(drive_stage["evidence_dir"]))
                if drive_stage.get("evidence_dir")
                else None
            )
            candidate_payloads, candidate_load_errors = load_archive_payloads(
                stage_lap_archives(candidate_outcome)
            )
            candidate_payloads, candidate_foreign = combo_filter_payloads(
                candidate_payloads,
                car_id=args.car,
                track_id=args.track,
                layout=args.track_layout,
            )
            candidate_lap_times = stage_lap_times_ms(candidate_outcome)
            if (
                candidate_outcome is None
                or len(candidate_lap_times) < args.laps
                or len(candidate_payloads) < args.laps
                or candidate_load_errors
                or candidate_foreign
            ):
                raise ScientistError(
                    "scientist_candidate_batch_incomplete:"
                    f"exit={code}:requested_laps={args.laps}:"
                    f"timed_laps={len(candidate_lap_times)}:"
                    f"archives={len(candidate_payloads)}:"
                    f"load_errors={len(candidate_load_errors)}:foreign={candidate_foreign}"
                )
            candidate_valid, candidate_reason = evaluate_selfplay_iteration(
                code, candidate_outcome, candidate_payloads
            )
            outcome = evaluate_experiment(
                plan=plan,
                experiment=experiment,
                baseline_payloads=baseline_payloads,
                candidate_payloads=candidate_payloads,
                candidate_valid=candidate_valid,
                candidate_reason=candidate_reason,
            )
            outcome["candidate_setup"] = str(candidate_path)
            outcome["evidence_root"] = str(candidate_root)
            if outcome.get("promoted"):
                outcome["recommended_setup"] = str(candidate_path)
            result["outcomes"].append(outcome)

        result["stage"] = "persist"
        run_path = persist_completed_run(
            user_dir,
            plan=plan,
            outcomes=result["outcomes"],
            created_utc=_utc_stamp(),
        )
        result["run_path"] = str(run_path)
        result["ledger_path"] = str(ledger_path)
        result["ok"] = True
        result["stage"] = "completed"
        return result
    except Exception as exc:  # noqa: BLE001 - report must retain the complete failed-stage trace
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        # A later candidate failure must not erase earlier completed measurements. Persist only
        # outcomes that reached evaluate_experiment; never record the incomplete candidate as a
        # falsification (#654 state-consistency contract).
        if result["outcomes"] and isinstance(result.get("plan"), dict):
            try:
                partial_path = persist_completed_run(
                    user_dir,
                    plan=result["plan"],
                    outcomes=result["outcomes"],
                    created_utc=_utc_stamp(),
                )
                result["partial_run_path"] = str(partial_path)
                result["ledger_path"] = str(state_root(user_dir) / LEDGER_NAME)
            except Exception as persist_exc:  # noqa: BLE001 - retain both failure traces
                result["partial_persist_error"] = f"{type(persist_exc).__name__}: {persist_exc}"
        return result


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
    if args.strict_app_version:
        # #575: both stages must agree on the app version — an identification session run against
        # a stale app produces the plant artifact the drive stage then trusts.
        out.append("--strict-app-version")
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
    """Delegate the composed alien stage to ``auto_drive``'s budget contract."""
    return resolve_lap_window_drive_seconds(args.drive_seconds, args.laps)


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
    if not args.no_l3:
        # #582 L3 rides every alien stage of the pipeline by default: the per-corner refinement
        # only relaxes measured, low-variance bins under the stability barrier, and the same
        # keep-last-valid oracle that guards the envelope ladder falsifies a refined profile
        # that reality rejects.
        argv.append("--l3")
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
    p.add_argument(
        "--strict-app-version",
        action="store_true",
        help="fail preflight on every stage when the AC-installed trainer app does not match "
        "this checkout (default: warn) (#575)",
    )
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
        help="#577 progressive-envelope self-play: after the base drive, run K drive iterations "
        "with keep-last-valid falsification (0 = off). #703: iterations ALTERNATE between a "
        "plant step (refit from the last valid batch, ggv-scale held) and an envelope step "
        "(next ggv-scale rung, plant untouched), so a falsification names which knob it "
        "falsified and a falsified rung no longer discards a validated refit. Budget ~2 "
        "iterations per envelope rung",
    )
    p.add_argument(
        "--scale-step",
        type=float,
        default=0.05,
        help="per-rung ggv-scale increment for the self-play envelope ladder (#244 pattern)",
    )
    p.add_argument(
        "--max-scale",
        type=float,
        default=1.1,
        help="self-play envelope ladder cap (hard limit 1.2; >1 probes above the uncertainty-"
        "safe QSS floor, falsification-gated)",
    )
    p.add_argument(
        "--no-l3",
        action="store_true",
        help="disable the #582 beyond-QSS per-corner refinement on the alien stages "
        "(default: enabled — corners without measured low-variance evidence revert to "
        "safe-QSS per corner anyway, named in the stage report)",
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
    p.add_argument(
        "--scientist",
        action="store_true",
        help="#529 P4: after self-play, run evidence-gated one-parameter setup experiments",
    )
    p.add_argument("--scientist-trigger", default=None, help="named failure or pace plateau")
    p.add_argument(
        "--scientist-proposals", type=Path, default=None, help="optional bounded JSON hypotheses"
    )
    p.add_argument(
        "--scientist-batch-size", type=int, default=1, help="bounded candidate count (1-3)"
    )
    p.add_argument("--scientist-mechanical-platform", default=None)
    p.add_argument("--scientist-aero-platform", default=None)
    p.add_argument("--scientist-tyre-family", default=None)
    p.add_argument("--scientist-track-archetype", default=None)
    p.add_argument(
        "--stint",
        action="store_true",
        help=(
            "#674 Layer-4: apply stint pace_scale to the base alien drive when a plant is ready "
            "(environment/stint report blocks attach whenever computable, even without this flag)"
        ),
    )
    p.add_argument("--stint-laps", type=int, default=None, help="laps remaining for L4 planning")
    p.add_argument("--stint-fuel-start-l", type=float, default=30.0)
    p.add_argument("--stint-fuel-burn-l-per-lap", type=float, default=2.2)
    p.add_argument("--stint-tyre-temp-target-c", type=float, default=90.0)
    p.add_argument("--stint-tyre-temp-tolerance-c", type=float, default=5.0)
    p.add_argument("--stint-wear-budget", type=float, default=0.35)
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
    if args.scientist and (args.iterations < 1 or args.laps < 2 or not args.setup):
        raise ValueError("--scientist requires --setup, --iterations >= 1, and --laps >= 2")
    if not 1 <= args.scientist_batch_size <= 3:
        raise ValueError("--scientist-batch-size must be between 1 and 3")
    if args.stint_laps is not None and args.stint_laps < 1:
        raise ValueError(f"--stint-laps must be >= 1 (got {args.stint_laps})")
    if not 0.0 < args.stint_wear_budget <= 1.0:
        raise ValueError("--stint-wear-budget must be in (0, 1]")
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

    plant = load_plant_artifact(
        user_dir,
        args.car,
        args.track,
        setup_key,
        setup_ini,
        layout=args.track_layout,
    )
    stint_layers = compose_stint_layers(
        plant_artifact=plant,
        archive_payloads=[],
        laps_remaining=args.stint_laps or max(1, args.laps or 1),
        fuel_start_l=args.stint_fuel_start_l,
        fuel_burn_l_per_lap=args.stint_fuel_burn_l_per_lap,
        tyre_temp_target_c=args.stint_tyre_temp_target_c,
        tyre_temp_tolerance_c=args.stint_tyre_temp_tolerance_c,
        wear_budget_fraction=args.stint_wear_budget,
        v_top_kmh=args.max_speed,
    )
    report["layers"] = {"pre_drive": stint_layers}
    drive_scale = None
    if args.stint and stint_layers.get("ok") and isinstance(stint_layers.get("inner_loop"), dict):
        drive_scale = float(stint_layers["inner_loop"]["ggv_scale"])
        report["stint_applied"] = {"ggv_scale": drive_scale, "source": "pre_drive"}
        print(f"auto-alien: Layer-4 stint pace_scale={drive_scale}")
    elif args.stint:
        report["stint_applied"] = {
            "ggv_scale": None,
            "source": "pre_drive",
            "skipped": stint_layers.get("error") or "stint_layers_unavailable",
        }
        print(
            "auto-alien: --stint requested but Layer-4 plan unavailable — "
            f"{report['stint_applied']['skipped']}; driving with baseline ggv_scale"
        )

    stage_dir = evidence_root / "drive"
    code = run_stage(drive_argv(args, stage_dir, ggv_scale=drive_scale))
    report["stages"]["drive"] = {"exit_code": code, "evidence_dir": str(stage_dir)}
    if code != 0:
        report["error"] = f"alien drive stage failed (exit {code})"
        print(f"auto-alien: FAIL — {report['error']}")
        return code or 1, report

    base_outcome = load_stage_outcome(stage_dir)
    post_payloads, post_errors = load_archive_payloads(stage_lap_archives(base_outcome))
    post_layers = compose_stint_layers(
        plant_artifact=plant,
        archive_payloads=post_payloads,
        laps_remaining=args.stint_laps or max(1, args.laps or 1),
        fuel_start_l=args.stint_fuel_start_l,
        fuel_burn_l_per_lap=args.stint_fuel_burn_l_per_lap,
        tyre_temp_target_c=args.stint_tyre_temp_target_c,
        tyre_temp_tolerance_c=args.stint_tyre_temp_tolerance_c,
        wear_budget_fraction=args.stint_wear_budget,
        v_top_kmh=args.max_speed,
        environment_prior=(
            stint_layers.get("environment_state")
            if isinstance(stint_layers.get("environment_state"), dict)
            else None
        ),
    )
    if post_errors:
        post_layers = {**post_layers, "archive_load_errors": post_errors}
    report["layers"]["post_drive"] = post_layers
    report["environment"] = post_layers.get("environment") or stint_layers.get("environment")
    report["stint"] = post_layers.get("stint") or stint_layers.get("stint")

    if args.iterations > 0:
        # #577 progressive-envelope self-play. A falsified/stopped ladder is a VALID pipeline
        # outcome — the base drive passed and the report names exactly where and why the ladder
        # ended (keep-last-valid already restored the plant). Only the base stages gate exit.
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
            # The scale the base drive ACTUALLY ran — `--stint` may have overridden
            # `--ggv-scale` above, and a plant step holds the last validated scale (#703).
            base_scale=args.ggv_scale if drive_scale is None else drive_scale,
        )
        if not report["selfplay"].get("ok", True):
            report["error"] = report["selfplay"]["stopped"]
            report["ok"] = False
            return 1, report
        best = report["selfplay"].get("best_lap_ms")
        print(
            f"auto-alien: selfplay done — {report['selfplay']['stopped']}"
            + (f"; best lap {best / 1000.0:.3f}s" if isinstance(best, int) else "")
        )
        if args.scientist and report["selfplay"].get("requires_rebase"):
            # A peer replaced the plant mid-ladder. The scientist would pick a baseline captured
            # under the OLD plant while its experiment drives load the peer's current one — the
            # comparison would change both the setup and the plant and could persist a corrupted
            # verdict. Skip it honestly until a fresh run rebases (#703 Codex P1).
            report["scientist"] = {
                "ok": True,
                "skipped": (
                    "self-play stopped for a peer plant change; a setup experiment would compare "
                    "across two different plants — re-run to rebase before running the scientist"
                ),
                "selfplay_stopped": report["selfplay"]["stopped"],
            }
            print(f"auto-alien: scientist SKIPPED — {report['scientist']['skipped']}")
        elif args.scientist:
            report["scientist"] = run_scientist(
                args,
                run_stage=run_stage,
                evidence_root=evidence_root,
                user_dir=user_dir,
                setup_ini=setup_ini,
                selfplay=report["selfplay"],
                base_outcome=base_outcome,
            )
            if not report["scientist"].get("ok"):
                report["error"] = (
                    f"scientist stage {report['scientist'].get('stage')} failed: "
                    f"{report['scientist'].get('error')}"
                )
                return 1, report
            print(f"auto-alien: scientist done — {report['scientist']['run_path']}")

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
