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
    artifact_selfplay_merge_count,
    load_plant_artifact,
    plant_artifact_from_bytes,
    plant_artifact_path,
    plant_ready_for_full_consumption,
)

StageRunner = Callable[[list[str]], int]

DEFAULT_SIDECAR_URL = "ws://127.0.0.1:8765"

# Flying-lap spread above which a self-play iteration is falsified as unrepeatable (#746).
# Calibrated against every self-play-era batch on the rig: 31 oracle-passing batches, MEDIAN
# spread 0.02% and only 4 above 1% — the deterministic controller normally repeats to within
# milliseconds. 5% sits far above that noise floor and below the observed pathologies (5.2%,
# 17.7%, 22.0%), so it separates "unrepeatable" from "normal" with room on both sides.
SELFPLAY_MAX_FLYING_LAP_SPREAD = 0.05


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


def flying_lap_consistency(
    archive_payloads: list[dict], *, expected_lap_times_ms: list[int] | None = None
) -> dict:
    """Lap-time spread across the batch's FLYING laps (pure; #746).

    The batch's lowest ``lap_n`` is the standing-start out-lap and is legitimately far slower
    than the rest — comparing it against the flyers would make every batch look inconsistent
    (measured: including it turns a 0.02% median spread into a 19% one). So the out-lap is
    dropped and only the flying laps are compared.

    ``expected_lap_times_ms`` is the list of TIMED lap times the stage itself reported, and the
    archive set must reproduce it EXACTLY (as a multiset). ``collect_lap_archives`` returns every
    combo-matching archive newer than ``since_epoch``, which need not be this batch: a lap can
    complete after the tap stopped counting, an expected async archive can be missing, and a
    neighbouring stint can fall inside the window.

    Matching on count alone is not enough, and neither is count + single ``session_uuid`` +
    unique ``lap_n`` (#746 Codex, round 8). Concrete counter-example: reported
    ``[106655, 81505, 95122]`` against same-session archives ``lap_n`` 1, 2, 4 holding
    ``[106655, 81505, 81519]`` satisfies every one of those heuristics, yet the *unrepeatable*
    third lap has been silently replaced by a repeatable post-window one — and the batch is then
    reported at a 0.02% spread, hiding the 17% the drive actually produced. Comparing the times
    themselves is the identity check those proxies were standing in for.

    Returns ``{"judged": False, "malformed": bool, "reason": ...}`` whenever consistency cannot
    be established, and the two cases are NOT the same (#746 self-hosted review):

    * ``malformed=True`` — an archive contradicts its own schema: it carried ``is_valid: True``
      (so it already passed the validity gate) yet has no integer ``lap_n`` or no positive
      ``lap_ms``. That is corrupt evidence, and the caller FALSIFIES, matching how a payload
      with no validity verdict is treated.
    * ``malformed=False`` — the batch is well-formed but not judgeable *here*: too few flying
      laps (an ordinary ``--laps 2`` run) or a count mismatch. These are known harness
      situations, not corrupt data. Falsifying them would revert the plant and stop the ladder
      for no physical reason — and would break every two-lap ladder outright.

    ORDER MATTERS. Schema and duplicate checks run BEFORE the count check (#746 Codex P2 +
    Qodo, round 3). A retry that leaves one archive from the failed attempt alongside the final
    attempt's laps produces BOTH a count mismatch and a duplicate ``lap_n``; returning on the
    count first labelled that mixed-session batch ``malformed=False``, the oracle accepted it as
    merely unjudged, and ``run_selfplay`` then handed the whole archive list to the next refit as
    ``prev_archives`` — exactly the contamination the duplicate check exists to stop.
    """
    laps: list[tuple[int, float]] = []
    for payload in archive_payloads:
        lap = payload.get("lap") if isinstance(payload.get("lap"), dict) else {}
        lap_n = lap.get("lap_n")
        lap_ms = lap.get("lap_ms")
        if not isinstance(lap_n, int) or isinstance(lap_n, bool):
            return {
                "judged": False,
                "malformed": True,
                "reason": "a lap archive has no integer lap_n (cannot identify the out-lap)",
            }
        # Completed in-game laps start at 1. A non-positive lap_n violates the archive contract
        # and would sort FIRST, so a corrupt `-1` record would be silently dropped as the
        # "out-lap" while the real flyers were compared — hiding the corruption rather than
        # reporting it (#746 Codex P2, round 6).
        if lap_n < 1:
            return {
                "judged": False,
                "malformed": True,
                "reason": f"lap_n={lap_n} is not a completed lap number (must be >= 1)",
            }
        # Finiteness is load-bearing, not defensive: Python's json decoder accepts a bare `NaN`,
        # and every comparison with NaN is False — so `lap_ms <= 0` does NOT reject it. A NaN lap
        # time then produces a NaN spread, `spread > threshold` is False, and the corrupt batch
        # was reported VALID with "flying-lap spread nan%" (#746 Codex P2).
        #
        # The float() conversion must be GUARDED: Python ints are arbitrary precision, so a
        # corrupt archive carrying `lap_ms: 10**309` makes `math.isfinite` raise OverflowError.
        # That escapes this malformed-evidence return and aborts the whole self-play/scientist
        # pipeline instead of failing the batch closed — the opposite of the intent (#746 Codex
        # P2, round 4). Convert first, judge second, and treat an unconvertible value as corrupt.
        lap_ms_value: float | None = None
        if isinstance(lap_ms, (int, float)) and not isinstance(lap_ms, bool):
            try:
                lap_ms_value = float(lap_ms)
            except (OverflowError, ValueError):
                lap_ms_value = None
        if lap_ms_value is None or not math.isfinite(lap_ms_value) or lap_ms_value <= 0:
            return {
                "judged": False,
                "malformed": True,
                "reason": f"lap_n={lap_n} has no finite positive lap_ms (cannot measure spread)",
            }
        laps.append((lap_n, lap_ms_value))
    # Duplicate lap_n is CONTAMINATION, not just an attribution nuisance (#746 Codex P2): when
    # `auto_drive` retries after a sim death that already produced an archive, `run_started_epoch`
    # spans both attempts while the Lua session resets `lap_n`, so the set mixes two sessions with
    # DIFFERENT TYRE STATES. That batch also feeds `persist_selfplay_refinement`, whose merge is
    # strictly monotone (raise-only) — so a hotter session's grip would be adopted permanently.
    # Treating it as merely "unjudged" let exactly that through, so it fails closed.
    # Scoping the archive set to the batch at the source is the real fix (#751).
    if len({lap_n for lap_n, _ in laps}) != len(laps):
        return {
            "judged": False,
            "malformed": True,
            "reason": "duplicate lap_n in the batch (archives from more than one session)",
        }
    # `session_uuid` is the DIRECT attribution fact; unique lap numbers are only a proxy for it.
    # A missing current archive replaced by a uniquely-numbered lap from a neighbouring stint
    # yields the expected count AND unique lap_n, so the duplicate check above passes while the
    # batch still spans two sessions (#746 Codex P2, round 6). Every in-game archive carries one
    # (`src/ac_copilot_trainer/modules/lap_archive.lua`). Two distinct non-empty UUIDs PROVE
    # contamination; absence proves nothing, so it is not treated as corruption here.
    sessions = {
        payload.get("session_uuid")
        for payload in archive_payloads
        if isinstance(payload.get("session_uuid"), str) and payload.get("session_uuid")
    }
    if len(sessions) > 1:
        return {
            "judged": False,
            "malformed": True,
            "reason": (
                f"batch spans {len(sessions)} session_uuids (archives from more than one session)"
            ),
        }
    # A drive's timed laps are CONTIGUOUS, so a gap in lap_n is an observable attribution failure
    # even when the times happen to line up: archives for lap_n 1, 2, 4 mean lap 3's validity and
    # telemetry are absent and lap 4 stood in for it, so lap 4 would feed refinement in its place
    # (#746 Codex P2, round 9). Cheaper and stricter than relying on the times alone, which can
    # coincide to the millisecond.
    lap_numbers = sorted(lap_n for lap_n, _ in laps)
    if lap_numbers and lap_numbers[-1] - lap_numbers[0] != len(lap_numbers) - 1:
        return {
            "judged": False,
            "malformed": False,
            "attributable": False,
            "reason": (
                f"lap numbers {lap_numbers} are not contiguous — a counted lap is missing "
                "and another stood in for it"
            ),
        }
    # …and it must start at lap 1, because each stage launches a fresh session and drives from a
    # standing start (#746 Codex P2, round 10). A SHIFTED window is worse than a gapped one: with
    # reported [96000, 80000, 95000] and archives (2,80000) (3,95000) (4,96000), the multiset and
    # contiguity checks both pass, the helper then drops lap 2 as the "out-lap", and an 18.8%
    # flying spread is reported as 1.1% — the gate inverted into hiding exactly what it exists to
    # catch.
    #
    # Measured cost, stated because it is not zero: 1 of 80 real self-play-era sessions on the
    # rig starts at lap_n 3 (a coherent 145.4 s + 109.110/109.107 batch), and this rejects it.
    # That failure is CONSERVATIVE — it stops a ladder and corrupts nothing — whereas the
    # inversion above retains an unrepeatable envelope, which is the defect #746 exists to fix.
    # #751's source-side scoping removes the guesswork entirely.
    if lap_numbers and lap_numbers[0] != 1:
        return {
            "judged": False,
            "malformed": False,
            "attributable": False,
            "reason": (
                f"batch starts at lap_n={lap_numbers[0]}, not 1 — a standing-start stage's "
                "laps begin at 1, so this window is shifted"
            ),
        }
    # The archive set must REPRODUCE the times the stage reported, not merely have the same
    # cardinality (#746 Codex, round 8). This subsumes the count check and closes the
    # missing-archive-replaced-by-a-post-window-lap case that count + session + lap_n all pass.
    #
    # Matched IN LAP ORDER, not as a multiset (#746 Codex P2, round 11): the report's
    # `lap_times_ms` is the tap's ordered stream, so sorting both sides accepts a PERMUTATION —
    # archives whose lap_n↔time correspondence is scrambled relative to the drive. That matters
    # because the out-lap is chosen by lap_n: a permutation can move the slow lap out of position
    # 1 and change which lap is discarded, the same inversion round 10 closed for shifts.
    if expected_lap_times_ms is not None:
        observed = [int(round(lap_ms)) for _, lap_ms in sorted(laps)]
        reported = [int(round(value)) for value in expected_lap_times_ms]
        if observed != reported:
            return {
                "judged": False,
                "malformed": False,
                # The caller FALSIFIES on this: a batch that is not demonstrably this drive's own
                # evidence may not validate a rung, seed a refit, or feed the scientist (#746).
                "attributable": False,
                "reason": (
                    f"archive lap times {observed} do not match the "
                    f"{len(reported)} timed lap(s) {reported} — batch not attributable"
                ),
            }
    if len(laps) < 3:
        flying_count = max(0, len(laps) - 1)
        return {
            "judged": False,
            "malformed": False,
            "reason": f"only {flying_count} flying lap(s) after the out-lap (need 2 to compare)",
        }
    laps.sort()
    flying = [lap_ms for _, lap_ms in laps[1:]]
    best, worst = min(flying), max(flying)
    return {
        "judged": True,
        "spread": (worst - best) / best,
        "best_ms": best,
        "worst_ms": worst,
        "out_lap_ms": laps[0][1],
        "flying_ms": flying,
    }


def evaluate_selfplay_iteration(
    exit_code: int,
    outcome: dict | None,
    archive_payloads: list[dict],
    *,
    max_flying_lap_spread: float = SELFPLAY_MAX_FLYING_LAP_SPREAD,
    consistency: dict | None = None,
) -> tuple[bool, str]:
    """The keep-last-valid falsification oracle for one envelope step (pure; #577/#244).

    An iteration is VALID only when the drive stage passed, the car never needed a recovery,
    at least one TIMED lap completed with its archive present, no counted lap is AC-invalid,
    and — since #746 — the flying laps are REPEATABLE. Anything else falsifies the step: the
    caller reverts to the last-valid plant and reports the named reason (never a silent retry
    of the same envelope).

    Why repeatability belongs here: validity + zero recoveries only prove the envelope was
    *survivable* once. An envelope the controller cannot reproduce (measured: 80.791 s then
    95.122 s in one clean stint, #529) was retained as VALID and compounded into the plant,
    which is exactly the evidence the pace ladder is built on.
    """
    if outcome is None:
        return False, "stage report missing (drive stage did not produce report.json)"
    report = outcome.get("report") if isinstance(outcome.get("report"), dict) else {}
    if exit_code != 0:
        stage = report.get("stage")
        # `error` is only set for an exception-shaped failure. A drive that ran and was VETOED —
        # recovery cap, sim death, spawn trap — finishes `stage=done` with `error=None` and puts
        # the cause in `reason`, so reporting `error` alone rendered a real physics falsification
        # as "stage=done, error=None" and hid why the rung failed (#746, observed at ggv_scale
        # 1.20: `recovery cap (6) exceeded at 10366m`, 7 recoveries).
        drive_report = report.get("drive") if isinstance(report.get("drive"), dict) else {}
        cause = report.get("error") or report.get("reason") or drive_report.get("reason")
        return False, f"drive stage failed (exit {exit_code}, stage={stage}, cause={cause})"
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
    # Repeatability last: a batch that fails any gate above is already falsified for a more
    # specific reason, and naming the spread instead would hide it (#746).
    #
    # The caller may pass the measurement it already made, so the verdict and the value recorded
    # in the ladder report cannot drift apart from two independent computations (#746
    # self-hosted review).
    if consistency is None:
        consistency = flying_lap_consistency(archive_payloads, expected_lap_times_ms=lap_times)
    # Corrupt evidence fails CLOSED, exactly like a payload with no validity verdict: an archive
    # that passed `is_valid` yet has no usable lap_n/lap_ms contradicts its own schema, and the
    # refit would consume that same batch.
    if consistency.get("malformed"):
        return False, f"unusable lap evidence for repeatability: {consistency['reason']}"
    # An UNATTRIBUTABLE batch falsifies too (#746 Codex P1, round 7). This was first modelled as
    # "valid but withheld from the refit", which is a third state — neither validated nor
    # rejected — and it had to be re-defended at every consumer: the refit, the scientist
    # baseline, the scientist candidate, the rung counter, the persisted plant candidate. Four of
    # those were missed. If the batch cannot be shown to be this drive's own evidence, nothing it
    # produced may validate anything, so it takes the ordinary keep-last-valid path: the plant
    # reverts, the rung does not advance, and the ladder stops with a named reason. The cost is a
    # wasted ladder on a harness artifact; the cost of the middle state was silent contamination.
    if consistency.get("attributable") is False:
        return False, f"batch not attributable to this drive: {consistency['reason']}"
    if consistency["judged"] and consistency["spread"] > max_flying_lap_spread:
        flying = ", ".join(f"{ms / 1000.0:.3f}s" for ms in consistency["flying_ms"])
        return False, (
            f"flying laps not repeatable at this envelope: spread "
            f"{consistency['spread'] * 100:.1f}% > {max_flying_lap_spread * 100:.1f}% "
            f"({flying}) — drivable once, not reproducible"
        )
    if consistency["judged"]:
        suffix = f", flying-lap spread {consistency['spread'] * 100:.2f}%"
    else:
        suffix = f", consistency unjudged ({consistency['reason']})"
    return True, (
        f"{len(lap_times)} timed lap(s), all archived laps AC-valid, zero recoveries{suffix}"
    )


def iteration_scale(base: float, step: float, index: int, cap: float) -> float:
    """The envelope ladder's ggv-scale for rung ``index`` (1-based), capped.

    Since #703 the rung index advances only on *envelope* steps, so it is no longer the same
    counter as the self-play iteration index (plant steps hold the last validated scale).
    """
    return round(min(base + step * index, cap), 6)


def stage_plant_fit_sha12(outcome: dict | None) -> str | None:
    """The plant-fit hash the stage's alien line was actually built from, or ``None``.

    ``auto_drive`` records ``run.alien_line.plant_provenance`` — a content hash of the exact plant
    artifact the drive consumed. It is the only evidence of WHICH plant produced a batch, and the
    self-play ladder needs it to prove that the drive whose archives it is about to refine from
    ran the same fit the ladder is now holding (#703 Codex P1).
    """
    alien_line = (outcome or {}).get("run")
    alien_line = alien_line.get("alien_line") if isinstance(alien_line, dict) else None
    provenance = alien_line.get("plant_provenance") if isinstance(alien_line, dict) else None
    sha12 = provenance.get("sha12") if isinstance(provenance, dict) else None
    return sha12 if isinstance(sha12, str) and sha12 else None


def _fit_sha12_of_artifact(artifact: dict | None) -> str | None:
    """The plant-fit hash of an ALREADY-VALIDATED artifact, or ``None``.

    Takes the parsed dict rather than raw bytes on purpose: decoding and ``json.loads``-ing the
    bytes here duplicated `plant_id.plant_artifact_from_bytes` and bypassed its schema/identity
    validation, contradicting that function's own "exactly one definition of a usable plant
    artifact" contract (self-hosted reviewer, antigravity). Callers parse once through the shared
    gate and pass the result.

    The hash matches what ``auto_drive`` records for the plant it loaded, which is what makes a
    ladder snapshot comparable to a drive report's ``plant_provenance.sha12``.
    """
    if not isinstance(artifact, dict):
        return None
    from tools.ac_harness.alien_line import plant_provenance

    sha12 = plant_provenance(artifact).get("sha12")
    return sha12 if isinstance(sha12, str) and sha12 else None


def _read_plant_bytes(plant_path: Path) -> bytes | None:
    """The plant artifact's current bytes, or ``None`` when the file does not exist.

    An **unreadable** artifact raises. Swallowing every ``OSError`` into ``None`` made a transient
    read failure indistinguishable from "the bytes changed" at each comparison site, so a blip
    after a successful plant step read as a peer change: it tripped keep-last-valid and dropped a
    provenance-validated refit, and reported an I/O fault as peer re-identification with
    ``selfplay.ok`` still true — regressing the #579 fail-closed filesystem path
    (self-hosted reviewer HIGH). Absent and unreadable are different facts; only absence is None.
    """
    try:
        return plant_path.read_bytes()
    except FileNotFoundError:
        return None


#: How far past the algebraic candidate the rung search will look for the six-decimal rounding
#: plateau to end. Generous for any real ``--scale-step`` (1e-7 clears it in ~5 rungs); a step that
#: needs more is below the ladder's own resolution, and leaping that many indices at once would
#: deliver the rounding floor rather than the requested increment (#703).
_MAX_PLATEAU_RUNGS = 4096


def _rung_reaching(base: float, step: float, target: float) -> int | None:
    """Smallest rung whose raw ladder value reaches ``target``; ``None`` when unrepresentable.

    ``--scale-step`` is validated only as finite and > 0, so a legal but absurd value (``1e-320``)
    makes ``(target - base) / step`` overflow to infinity and ``math.ceil`` raise ``OverflowError``
    — crashing the pipeline before it can write its composed report. Returning ``None`` instead
    lets the caller fall back to its other probes and, failing those, stop honestly with "no rung
    above the validated scale": a rung at index ~1e320 is unreachable within any real
    ``--iterations`` budget anyway (#703 Codex P2, round 4).
    """
    try:
        quotient = (target - base) / step
    except (OverflowError, ZeroDivisionError):
        return None
    if not math.isfinite(quotient):
        return None
    try:
        return math.ceil(quotient)
    except (OverflowError, ValueError):
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
    needed = _rung_reaching(base, step, prev_scale + 5e-7)
    if needed is None:
        return None
    # Only rungs derived from the requested step count. A saturating fallback would "find" a rung
    # for a subnormal step (`2e-309`) whose float product cannot move off `base` at all, and the
    # first envelope drive would then jump straight to `--max-scale` — turning an almost-zero
    # requested step into an immediate leap to the safety cap. A step that cannot move the
    # envelope at its own granularity means the ladder is exhausted, not that the cap is due
    # (#703 Codex P2, round 5).
    #
    # The plateau past `needed` can be WIDER than a couple of indices when the step is far below
    # the six-decimal spacing, so a fixed three-probe window wrongly reported an exhausted ladder
    # (#703 Codex P2, round 12). Binary-search the plateau instead — `iteration_scale` is monotone
    # non-decreasing in the rung, so this finds the exact smallest usable rung — bounded by
    # `_MAX_PLATEAU_RUNGS` past `needed`. That bound is the same principle as the round-5 rule:
    # a rung the ladder would have to leap thousands of indices to reach is not a step the
    # operator asked for, it is the rounding floor, and the honest answer is "no rung".
    lo = max(rung, needed)
    hi = lo + _MAX_PLATEAU_RUNGS
    if iteration_scale(base, step, hi, cap) <= prev_scale:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if iteration_scale(base, step, mid, cap) > prev_scale:
            hi = mid
        else:
            lo = mid + 1
    return lo if iteration_scale(base, step, lo, cap) > prev_scale else None


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
    # This is also the ladder's ANCHOR, not just its starting point. Anchoring the rungs to
    # `--ggv-scale` while the base actually drove a derated `--stint` pace made the first envelope
    # step jump two increments (0.85 -> 0.95 with the 0.05 default, skipping 0.90), so a run could
    # falsify at 0.95 having never tested the envelope in between — doubling the progressive step
    # the operator asked for (#703 Codex P2, round 7). With no stint override the two are equal
    # and the ladder is unchanged.
    resolved_base_scale = args.ggv_scale if base_scale is None else float(base_scale)
    # ONE read of the artifact serves every ladder-start fact: the byte snapshot the guards
    # compare against, the provenance the base drive must agree with, and the inherited merge
    # count. Reading it three times let a peer land between them, so the ladder could validate the
    # provenance of one fit while snapshotting another — defeating the very guards these facts
    # feed (self-hosted reviewer HIGH, antigravity).
    try:
        validated_plant_bytes = _read_plant_bytes(plant_path)
    except OSError as exc:
        # Fail closed rather than start a ladder whose every guard compares against bytes we
        # could not read (self-hosted reviewer HIGH).
        return {
            "ok": False,
            "ladder_mode": "decoupled",
            "iterations": [],
            "stopped": (
                f"cannot read the plant artifact ({exc}) — self-play not started; every "
                "attribution guard compares against these bytes"
            ),
            "lap_trajectory_ms": [],
            "best_lap_ms": None,
        }
    ladder_start_artifact = plant_artifact_from_bytes(
        validated_plant_bytes, args.car, args.track, setup_key, layout=args.track_layout
    )
    if ladder_start_artifact is None:
        # No usable plant on disk. Without this the ladder ran anyway: the refit reported
        # "artifact unloadable", fell through to an envelope rung, and that drive's plant-load
        # failure was reported as falsifying the SCALE — a fabricated verdict about the envelope,
        # on a pipeline that could still exit 0 (#703 Codex P2, round 12).
        return {
            "ok": False,
            "ladder_mode": "decoupled",
            "iterations": [],
            "stopped": (
                f"no valid plant artifact for this combo at {plant_path} — self-play not "
                "started; a rung driven without a plant would falsify the envelope for the "
                "wrong reason"
            ),
            "lap_trajectory_ms": [],
            "best_lap_ms": None,
        }
    selfplay: dict = {
        "iterations_requested": args.iterations,
        "laps_per_iteration": args.laps,
        "base_scale": resolved_base_scale,
        # The rung anchor actually in force (== base_scale; `--ggv-scale` is only the default).
        "ladder_base_scale": resolved_base_scale,
        "requested_ggv_scale": args.ggv_scale,
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
        "inherited_selfplay_merges": artifact_selfplay_merge_count(ladder_start_artifact),
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
    base_consistency = flying_lap_consistency(base_payloads, expected_lap_times_ms=base_laps)
    # Same fold as the iteration path: unreadable archives make the batch unverifiable, and that
    # fact lives out here rather than in the payloads the helper can see (#746 Qodo, round 6).
    if base_load_errors and base_consistency.get("attributable") is not False:
        base_consistency = {
            **base_consistency,
            "judged": False,
            "attributable": False,
            "reason": f"{len(base_load_errors)} archive(s) could not be read — batch unverifiable",
        }
    base_valid, base_reason = evaluate_selfplay_iteration(
        0, base_outcome, base_payloads, consistency=base_consistency
    )
    selfplay["base"] = {
        "valid": base_valid,
        "reason": base_reason,
        "lap_times_ms": base_laps,
        "flying_lap_consistency": base_consistency,
    }
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
    # No separate attribution flag is needed here any more: an unattributable or unverifiable
    # base batch now fails the oracle itself, so `base_valid` already carries it (#746 round 7).
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
    #
    # The bytes on disk are NOT self-evidently what the base drive ran: a peer may have
    # re-identified the combo after the base stage finished and before this snapshot. Adopting
    # them unchecked would make the first fallback envelope step pass the byte check while
    # driving a different plant AND a higher scale, or merge the base's evidence into an
    # unvalidated peer fit. `auto_drive` records the fit its line was built from, so require the
    # two to agree before treating the snapshot as validated (#703 Codex P1, round 5).
    base_fit = stage_plant_fit_sha12(base_outcome)
    current_fit = _fit_sha12_of_artifact(ladder_start_artifact)
    # Tracked alongside the byte snapshot so no iteration re-parses raw bytes behind the
    # shared validation gate.
    validated_plant_fit = current_fit
    selfplay["base_plant_fit_sha12"] = base_fit
    # Fail CLOSED on a missing current provenance. If the artifact was deleted or corrupted after
    # a successful base drive, `current_fit` is None while `base_fit` is populated; treating that
    # as "compatible" let the refit fail, fall through to an envelope drive, and report the
    # resulting plant-load failure as falsifying the SCALE RUNG while the bad artifact stayed in
    # place (#703 Codex P2, round 6).
    if base_fit is not None and base_fit != current_fit:
        selfplay["requires_rebase"] = True
        disk = current_fit if current_fit is not None else "no readable plant fit"
        selfplay["stopped"] = (
            f"plant changed since the base drive (base ran fit {base_fit}, disk now carries "
            f"{disk}) — self-play stopped before iteration 1; the base evidence and the "
            "on-disk plant are from different fits, so no step could be attributed"
        )
        print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
        selfplay["best_lap_ms"] = best
        return selfplay
    if base_fit is None:
        # Not a blocker (an older stage report or a failed base drive records no line), so the
        # ladder still runs — envelope rungs are falsification-gated on their own. But its
        # archives may NOT seed a refit: with no recorded provenance there is no proof the plant
        # now on disk is the fit that produced them, so a peer replacement between that drive and
        # this invocation would cross two fits inside the refinement evidence itself. Refuse the
        # evidence rather than the run, until a provenance-carrying drive establishes a baseline
        # (#703 Codex P2, round 8).
        selfplay["base_plant_fit_unverified"] = True
        if prev_archives:
            selfplay["base"]["refit_evidence_withheld"] = (
                "the base drive recorded no plant provenance, so the fit that produced these "
                "archives cannot be proven — not used as refit evidence"
            )
            print(
                "auto-alien: base drive recorded no plant provenance — its archives are usable "
                "as pace evidence but NOT as a refit batch"
            )
            prev_archives = []
    next_step_kind = "plant"
    for index in range(1, args.iterations + 1):
        # 0) Pick this iteration's single knob (#703). When no envelope rung can exceed the
        #    validated scale, the refit is the only remaining lever; if it is also a no-op the
        #    fall-through below reaches the unchanged-envelope stop.
        step_kind = next_step_kind
        usable_rung = next_envelope_rung(
            resolved_base_scale, args.scale_step, args.max_scale, prev_scale, rung
        )
        if usable_rung is not None:
            rung = usable_rung
        envelope_scale = (
            iteration_scale(resolved_base_scale, args.scale_step, rung, args.max_scale)
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
        peer_changed_before_refit = False
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
            elif (pre_refine_bytes := _read_plant_bytes(plant_path)) != validated_plant_bytes:
                # A peer re-identified the combo since our last validated state. The
                # `expected_current_bytes` guard below would accept these bytes happily — it only
                # prevents clobbering a NEWER fit, it does not prove the fit is OURS — so archives
                # produced by plant A would be merged into peer plant B, and the candidate would
                # then become `validated_plant_bytes`, letting the post-drive check and the
                # scientist baseline treat a two-plant transition as this ladder's single-knob
                # refit (#703 Codex P1, round 6).
                peer_changed_before_refit = True
                entry["refine"] = {
                    "ok": False,
                    "reason": (
                        "plant changed since the last validated state (peer re-identification?) "
                        "— refusing to merge this batch's evidence across two different fits"
                    ),
                }
            else:
                # ONE content-bound snapshot serves the equality check above, the refinement, and
                # the persistence guard below. Re-reading the file here would reopen the window it
                # just closed: a peer landing between the two reads would become
                # `pre_refine_bytes`, so `expected_current_bytes` would match the peer's own bytes
                # and the cross-plant candidate would persist as validated (#703 Qodo, round 7).
                # The refine-save still runs outside the drive stage's machine-global rig lock, so
                # a peer that lands after this snapshot makes the save skip rather than clobber a
                # newer fit (#579 Codex P2) — which the peer-skip stop then turns into a rebase.
                #
                # PARSE the snapshot rather than re-reading the file: `load_plant_artifact` would
                # open it again, so plant B could be parsed while `pre_refine_bytes` still held A.
                # If the peer then rolled B back to A while we waited on the rig lock, the write
                # guard would see its expected A bytes and persist a candidate that merged A's
                # archives into B — corrupting the plant while reporting it validated (#703 Codex
                # P1, round 8). Same validation gate; one snapshot for compare, parse, and write.
                artifact = plant_artifact_from_bytes(
                    pre_refine_bytes, args.car, args.track, setup_key, layout=args.track_layout
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
                            validated_plant_fit = _fit_sha12_of_artifact(
                                plant_artifact_from_bytes(
                                    persisted_bytes,
                                    args.car,
                                    args.track,
                                    setup_key,
                                    layout=args.track_layout,
                                )
                            )
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
                        # Name the term that actually rejected the cohort, on the console, so a
                        # ladder that has silently stopped compounding is visible without
                        # re-analysing archives by hand (#749).
                        eligibility = block.get("thermal_eligibility")
                        # Only claim an empty cohort when it IS empty. This branch runs for every
                        # fit exception, so a batch with eligible laps that failed downstream —
                        # too few friction rows, say — would otherwise be announced as a thermal
                        # stall using a dominant term drawn from the ineligible minority, pointing
                        # the next session at the wrong cause (#749 Codex P2).
                        if (
                            isinstance(eligibility, dict)
                            and eligibility.get("eligible_count") == 0
                            and eligibility.get("dominant_terms")
                        ):
                            lap_count = len(eligibility.get("laps") or [])
                            terms = ", ".join(eligibility["dominant_terms"])
                            print(
                                f"auto-alien: iteration {index} thermal cohort empty — "
                                f"{eligibility['dominant_count']}/{lap_count} lap(s): {terms}"
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
        if peer_changed_before_refit:
            selfplay["stopped"] = (
                f"plant changed before iteration {index}'s refit (peer re-identification?) — "
                "self-play stopped; merging this batch's evidence into a fit the ladder never "
                "validated would corrupt both the attribution and the persisted plant "
                "(re-run to rebase on the peer's plant)"
            )
            entry["skipped"] = True
            selfplay["requires_rebase"] = True
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break

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
            try:
                current_plant_bytes = _read_plant_bytes(plant_path)
            except OSError as exc:
                # An unreadable artifact is an I/O fault, NOT evidence of a peer change: it must
                # fail the pipeline loudly, not be laundered into a rebase (self-hosted HIGH).
                selfplay["ok"] = False
                selfplay["stopped"] = (
                    f"cannot read the plant artifact before iteration {index}'s envelope step "
                    f"({exc}) — self-play stopped; unreadable is not the same as changed"
                )
                entry["skipped"] = True
                print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
                break
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
        # Measure once and hand the SAME dict to the oracle, so the recorded value and the
        # verdict can never disagree (#746 self-hosted review). Recorded whether or not it
        # falsified, so a ladder can be audited after the fact for envelopes that were merely
        # survivable rather than repeatable.
        consistency = flying_lap_consistency(archive_payloads, expected_lap_times_ms=lap_times)
        # Unreadable archives are the same unattributability wearing a different hat (#746 Qodo,
        # round 6): `flying_lap_consistency` only ever sees payloads that LOADED, so an unreadable
        # expected archive plus a stray readable one "fills the count" and the batch looks
        # attributable while being unverifiable. `load_errors` is the only evidence that happened,
        # and it lives out here — so fold it into the same verdict rather than inventing a second
        # mechanism for it.
        if load_errors and consistency.get("attributable") is not False:
            consistency = {
                **consistency,
                "judged": False,
                "attributable": False,
                "reason": (f"{len(load_errors)} archive(s) could not be read — batch unverifiable"),
            }
        entry["flying_lap_consistency"] = consistency
        valid, reason = evaluate_selfplay_iteration(
            code, outcome, archive_payloads, consistency=consistency
        )
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
        #
        # Bytes-after-the-drive are necessary but not sufficient: a peer could replace the plant
        # before `auto_drive` loads it and restore the expected bytes right after the rig lock
        # releases, and this comparison would pass while the iteration actually ran a different
        # fit. The drive REPORTS the provenance of the plant its line was built from, so trust
        # that over inference whenever it is present (#703 Codex P2, round 7).
        driven_fit = stage_plant_fit_sha12(outcome)
        expected_fit = validated_plant_fit
        entry["driven_plant_fit_sha12"] = driven_fit
        fit_mismatch = (
            driven_fit is not None and expected_fit is not None and driven_fit != expected_fit
        )
        # Fail CLOSED on missing proof, not just on contradicted proof. Byte equality cannot show
        # WHICH plant was driven — a peer swap restored before the post-drive read looks identical
        # — so an oracle-valid batch with no recorded provenance is unusable as evidence even
        # though nothing contradicts it (#703 Qodo, round 8). Scoped to VALID iterations on
        # purpose: an invalid drive that died before building a line legitimately records no
        # provenance, and that is an ordinary stage failure, not a peer plant change.
        # Gate on "did this drive actually run", not on the oracle verdict. Scoping it to VALID
        # let an AC-invalid TIMED lap with no provenance keep its knob attribution, so an envelope
        # failure could retain earlier refits with no proof the expected plant produced the
        # falsifying lap (#703 Qodo, round 14). A stage that died before building a line records
        # no laps and no archives — that is an ordinary failure and still attributable.
        drove_something = bool(lap_times) or bool(archives)
        missing_driven_fit = drove_something and expected_fit is not None and driven_fit is None
        try:
            post_drive_bytes = _read_plant_bytes(plant_path)
        except OSError as exc:
            # Never let a read blip revert a provenance-VALIDATED refit (self-hosted HIGH). But a
            # FALSIFIED refit is a different case: breaking here would skip the keep-last-valid
            # rollback below and leave the rejected monotone grip increase as the combo's loadable
            # plant. Roll that one back before failing closed — only an oracle-VALID step is
            # protected from the blip (Codex P1 + Qodo + self-hosted HIGH, round 12).
            selfplay["ok"] = False
            selfplay["stopped"] = (
                f"cannot read the plant artifact after iteration {index}'s {step_kind} step "
                f"({exc}) — self-play stopped without judging the plant; an unreadable artifact "
                "is not evidence that it changed"
            )
            if fit_mismatch or missing_driven_fit:
                # The fit evidence already proves this iteration did not run our candidate; the
                # read failure does not erase that, so carry the same taint the normal path sets.
                entry["plant_changed_during_step"] = True
                entry["usable_as_evidence"] = False
                selfplay["requires_rebase"] = True
            # Revert whenever the candidate demonstrably never drove on its own plant — falsified,
            # OR valid-but-on-a-foreign/unprovable fit. Round 12 covered only the falsified case,
            # so a valid drive on a peer plant followed by a read failure left the undriven grip
            # raise loadable for later runs (self-hosted HIGH, round 14). A CONFIRMED attributable
            # valid refit is still protected from the blip.
            if (
                refined
                and last_valid_bytes is not None
                and (not valid or fit_mismatch or missing_driven_fit)
            ):
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
                            f"auto-alien: iteration {index} candidate never drove on its own "
                            "plant and the artifact is unreadable — reverted to the last-valid fit"
                        )
                    else:
                        entry["reverted"] = False
                        entry["revert_skipped"] = (
                            "plant artifact is no longer this iteration's candidate — revert "
                            "skipped"
                        )
                except (OSError, RigSessionBusy) as revert_exc:
                    entry["reverted"] = False
                    entry["revert_error"] = (
                        f"artifact rollback failed: {type(revert_exc).__name__}: {revert_exc}"
                    )
                    print(
                        f"auto-alien: iteration {index} REVERT FAILED — {entry['revert_error']} "
                        "(the falsified fit may still be persisted; re-run --force-identify)"
                    )
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break
        plant_moved_during_step = (
            post_drive_bytes != validated_plant_bytes or fit_mismatch or missing_driven_fit
        )
        if fit_mismatch:
            entry["driven_plant_fit_mismatch"] = {
                "expected": expected_fit,
                "driven": driven_fit,
            }
        if missing_driven_fit:
            entry["driven_plant_fit_missing"] = (
                "the drive recorded no plant provenance, so which plant produced this batch "
                "cannot be proven — refusing to use it as ladder or scientist evidence"
            )
        if plant_moved_during_step:
            # Set BOTH consequences here, at the single point that knows the fact — a peer change
            # taints the batch and requires a rebase whether the drive passed or failed. Setting
            # them only on the pass path left a failed unattributable step running the scientist
            # across two plants (#703 Codex P1, round 4).
            entry["plant_changed_during_step"] = True
            entry["usable_as_evidence"] = False
            selfplay["requires_rebase"] = True

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
                        # A skipped rollback PROVES the on-disk plant is no longer this ladder's,
                        # so the same rebase state every other detected peer change sets applies
                        # here too — otherwise `--scientist` would run a baseline from an older
                        # self-play outcome against experiments loading the peer's plant,
                        # conflating plant and setup in one verdict (#703 Codex P1, round 8).
                        entry["usable_as_evidence"] = False
                        selfplay["requires_rebase"] = True
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
                # Name the kind that actually ran: claiming "envelope" on a falsified PLANT step
                # would make the headline diagnostic contradict `entry["step_kind"]` exactly where
                # the decoupled ladder is supposed to identify the knob (#703 Codex P2, round 5).
                component = (
                    f"UNATTRIBUTABLE — the plant changed on disk during this {step_kind} step at "
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
        if plant_moved_during_step:
            # A PASS is no safer to build on than a failure here: the ladder would carry forward
            # archives and a scale earned under a plant it did not choose (#703 Codex P1). The
            # batch is barred from seeding the scientist baseline — `run_scientist` would
            # otherwise pick this newest "valid" evidence dir and run setup experiments on the
            # exact batch this message says cannot be attributed (#703 Codex P1, round 3) — and
            # its laps must not reach `best_lap_ms` either, or a fast lap set under the peer's
            # unknown plant would be reported as THIS ladder's best result (#703 Codex P2,
            # round 4). Both are handled by rejecting the batch BEFORE the summary is updated,
            # exactly as an oracle-invalid base is rejected.
            selfplay["stopped"] = (
                f"plant changed on disk during iteration {index}'s {step_kind} step (peer "
                "re-identification?) — self-play stopped; the step passed but its evidence "
                "cannot be attributed to this ladder's plant"
            )
            # A refit that was never driven ON ITS OWN PLANT has not survived anything, so it must
            # not stay persisted: the monotone merge only ever RAISES grip and the keep-last-valid
            # revert is its one way down, so leaving it would hand an unvalidated grip increase to
            # every later alien-line consumer (#703 Codex P1, round 8). Guarded exactly like the
            # falsified-plant rollback: if a peer now owns the artifact the revert is skipped and
            # the rebase state stands rather than overwriting their fit.
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
                            f"auto-alien: iteration {index} candidate never drove on its own "
                            "plant — reverted to the last-valid fit"
                        )
                    else:
                        entry["reverted"] = False
                        entry["revert_skipped"] = (
                            "plant artifact is no longer this iteration's candidate (peer owns "
                            "it) — revert skipped; the rebase state stands"
                        )
                        print(f"auto-alien: iteration {index} {entry['revert_skipped']}")
                except (OSError, RigSessionBusy) as exc:
                    entry["reverted"] = False
                    entry["revert_error"] = f"artifact rollback failed: {type(exc).__name__}: {exc}"
                    selfplay["ok"] = False
                    print(
                        f"auto-alien: iteration {index} REVERT FAILED — {entry['revert_error']} "
                        "(an undriven candidate may still be persisted; re-run --force-identify)"
                    )
            print(f"auto-alien: selfplay stop — {selfplay['stopped']}")
            break
        if lap_times:
            it_best = min(lap_times)
            best = it_best if best is None else min(best, it_best)
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
    if selfplay.get("base_plant_fit_unverified"):
        # The base batch is withheld from refinement for want of provenance; the same reasoning
        # bars it from a setup experiment. Falling back to it here would compare an unproven
        # baseline against candidates driven on the current plant, conflating plant and setup in
        # one verdict — the exact confusion the withholding exists to prevent (#703 Qodo).
        return None
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


def _candidate_setup_race_stage(candidate_report: dict) -> str | None:
    """Failed stage name when a scientist candidate died on the transient setup re-bake race.

    A candidate that lost the #466 CM race.ini regeneration race fails its identify/drive stage
    at ``stage="setup"`` with ``setup_race_suspected`` set in the stage report (#737).  Exactly
    that signature is worth ONE fresh pipeline cycle; every other failure keeps aborting the
    batch honestly, so a persistent mismatch can never launder a half-run into the ledger.
    """
    stages = candidate_report.get("stages")
    if not isinstance(stages, dict):
        return None
    for name, stage in stages.items():
        if not isinstance(stage, dict):
            continue
        exit_code = stage.get("exit_code")
        if not isinstance(exit_code, int) or exit_code == 0:
            continue
        evidence_dir = stage.get("evidence_dir")
        if not evidence_dir:
            continue
        outcome = load_stage_outcome(Path(evidence_dir))
        stage_report = (outcome or {}).get("report")
        if (
            isinstance(stage_report, dict)
            and stage_report.get("stage") == "setup"
            and stage_report.get("setup_race_suspected") is True
        ):
            return str(name)
    return None


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
        # These gates only ever caught TOO FEW archives, so an oversized batch — an extra
        # same-combo archive from a neighbouring stint — reached `build_plan` /
        # `evaluate_experiment` and could persist a durable setup verdict measured partly on
        # another stint's lap (#746 Codex P1, round 7). Attribution is now required, not just
        # sufficiency.
        baseline_attribution = flying_lap_consistency(
            baseline_payloads, expected_lap_times_ms=baseline_lap_times
        )
        if (
            load_errors
            or foreign
            or not baseline_valid
            or len(baseline_lap_times) < args.laps
            or len(baseline_payloads) < args.laps
            or baseline_attribution.get("attributable") is False
            # Corrupt / mixed-session candidate evidence must abort too, not only
            # unattributable evidence (#746 Codex P2, round 11).
            or baseline_attribution.get("malformed") is True
        ):
            raise ScientistError(
                "scientist_baseline_batch_unverifiable:"
                f"{baseline_reason}:requested_laps={args.laps}:"
                f"timed_laps={len(baseline_lap_times)}:archives={len(baseline_payloads)}:"
                f"load_errors={len(load_errors)}:foreign={foreign}:"
                f"attributable={baseline_attribution.get('attributable') is not False}"
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
            if code != 0 and (race_stage := _candidate_setup_race_stage(candidate_report)):
                # #737: the candidate lost the #466 setup re-bake race — a confirmed
                # intermittent rig condition, not a verdict about the setup.  One fresh
                # pipeline cycle instead of discarding the completed baseline and any earlier
                # candidates; a second pipeline-level miss still aborts the batch honestly
                # below.  Two scopes on purpose (Codex P2, PR #740): auto_drive's
                # setup_verify_retries is the CHEAP in-stage relaunch for one transient miss;
                # this branch saves the whole batch when a stage exhausted that budget (both
                # launches lost the race).  The budgets therefore compose: each pipeline
                # attempt may burn 1 + setup_verify_retries launches, so a persistently
                # mismatching candidate costs at most 2 * (1 + setup_verify_retries) launches
                # (4 with defaults) before the abort — bounded, and far cheaper than
                # discarding a completed baseline batch on an intermittent rig condition.
                retry_root = evidence_root / "scientist" / f"candidate_{index:02d}_retry"
                print(
                    f"auto-alien: scientist candidate {index} lost the setup re-bake race "
                    f"at the {race_stage} stage — retrying one fresh launch cycle (#737)"
                )
                retry_args = argparse.Namespace(**vars(candidate_args))
                retry_args.evidence_dir = retry_root
                code, candidate_report = run_pipeline(retry_args, run_stage=run_stage)
                retry_root.mkdir(parents=True, exist_ok=True)
                (retry_root / "alien_report.json").write_text(
                    json.dumps(candidate_report, indent=2), encoding="utf-8"
                )
                result.setdefault("setup_race_retries", []).append(
                    {
                        "candidate": index,
                        "stage": race_stage,
                        "first_evidence_root": str(candidate_root),
                        "evidence_root": str(retry_root),
                        "recovered": code == 0,
                    }
                )
                candidate_root = retry_root
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
            # Same one-sided gate as the baseline: too few archives failed, too many passed
            # (#746 Codex P1, round 7).
            candidate_attribution = flying_lap_consistency(
                candidate_payloads, expected_lap_times_ms=candidate_lap_times
            )
            if (
                candidate_outcome is None
                or len(candidate_lap_times) < args.laps
                or len(candidate_payloads) < args.laps
                or candidate_load_errors
                or candidate_foreign
                or candidate_attribution.get("attributable") is False
                or candidate_attribution.get("malformed") is True
            ):
                raise ScientistError(
                    "scientist_candidate_batch_incomplete:"
                    f"exit={code}:requested_laps={args.laps}:"
                    f"timed_laps={len(candidate_lap_times)}:"
                    f"archives={len(candidate_payloads)}:"
                    f"load_errors={len(candidate_load_errors)}:foreign={candidate_foreign}:"
                    f"attributable={candidate_attribution.get('attributable') is not False}"
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
                # `ok` stays true because skipping is the correct outcome, not a stage failure —
                # but a distinct `status` so telemetry reading `scientist.ok` as "ran and
                # succeeded" can tell a skip from a real run (self-hosted reviewer, grok).
                "ok": True,
                "status": "skipped_requires_rebase",
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
