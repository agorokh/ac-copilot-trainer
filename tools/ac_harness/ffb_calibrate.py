"""Per-car FFB gain auto-calibration (issue #533).

Drives a car (composing on :mod:`tools.ac_harness.auto_drive`, or the operator drives with
``--observe-only``), samples ``acpmf_physics.finalFF`` — the normalized force AC sends to the
wheel — and derives the per-car gain that makes the force peak near full scale **without
clipping**. The gain is AC's own per-car multiplier stored in ``Documents/Assetto Corsa/cfg/
user_ff.ini`` (``[car_id] VALUE=x.xxx``); this tool never touches the AC/CSP install tree.

The ``finalFF`` byte offset (308) is validated against the live signal before any write: a wrong
offset yields out-of-range or all-zero samples, which :func:`offset_looks_valid` rejects, forcing
a report-only pass. Writing is opt-in: the tool only reports the recommendation unless you pass
``--write`` (FFB strength is operator-subjective — confirm the signal first, then apply by feel).

Pure helpers (``summarize`` / ``recommend_gain`` / ``update_user_ff_value``) are unit-tested; the
launch + sample loop is rig-only (``# pragma: no cover``).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

CLIP_THRESHOLD = 0.99
# Calibrate on a high percentile, not the raw max: AC's finalFF spikes past 1.0 on kerbs
# (live-observed peak ~1.85 on a clean 911 Spa lap), so targeting the max would gut the gain for
# rare transients. Aim the 99th percentile of |finalFF| at TARGET_LEVEL instead.
CALIB_PERCENTILE = 99.0
TARGET_LEVEL = 0.95
GAIN_FLOOR = 0.30
GAIN_CEILING = 2.00
DEFAULT_SAMPLE_SECONDS = 45.0
DEFAULT_HZ = 100.0
# finalFF is normalized but NOT clamped to 1.0 — kerb strikes push it to ~2 (live-observed). A
# read far past that (or an all-silent / static capture) means the offset is wrong for this
# AC/CSP build, so the sample must not drive a gain write.
OFFSET_SANE_PEAK = 5.0
OFFSET_MIN_PEAK = 0.02
OFFSET_MIN_SAMPLES = 200


def _pos_float(value: str) -> float:
    """argparse type: a strictly-positive, FINITE float (rejects 0, negatives, inf, nan)."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a finite number > 0, got {value!r}")
    return parsed


def _nonneg_float(value: str) -> float:
    """argparse type: a non-negative, FINITE float (0 allowed; rejects negatives, inf, nan)."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(f"must be a finite number >= 0, got {value!r}")
    return parsed


def _evidence_key(car: str, track: str, layout: str | None) -> str:
    """Evidence-bundle filename stem — includes the layout so two layouts of the same base track
    don't overwrite each other's log/report (``car_track`` or ``car_track_layout``)."""
    return f"{car}_{track}_{layout}" if layout else f"{car}_{track}"


@dataclass(frozen=True)
class FfbStats:
    """Summary of a finalFF sample window."""

    n: int
    peak: float
    rms: float
    clip_fraction: float
    clip_threshold: float
    p95: float = 0.0
    p99: float = 0.0
    p999: float = 0.0


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated ``q``-th percentile of an already-sorted sequence (pure)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (q / 100.0) * (len(sorted_values) - 1)
    lo = int(math.floor(rank))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def summarize(samples: Sequence[float], *, clip_threshold: float = CLIP_THRESHOLD) -> FfbStats:
    """Reduce raw finalFF samples to peak / rms / clip fraction / percentiles (pure).

    ``clip_fraction`` is the share of samples whose magnitude reaches ``clip_threshold`` — the
    fraction of the lap where the wheel is pinned at full force and detail is lost. The p95/p99/
    p999 magnitudes drive calibration (a high percentile, not the kerb-spike max). Non-finite
    samples (NaN / ±inf — e.g. a wrong offset reading garbage) are dropped so reports stay valid
    JSON and the stats are never poisoned.
    """
    vals = [float(s) for s in samples if math.isfinite(float(s))]
    if not vals:
        return FfbStats(n=0, peak=0.0, rms=0.0, clip_fraction=0.0, clip_threshold=clip_threshold)
    mags = sorted(abs(v) for v in vals)
    rms = math.sqrt(sum(v * v for v in vals) / len(vals))
    clipped = sum(1 for m in mags if m >= clip_threshold)
    return FfbStats(
        n=len(vals),
        peak=mags[-1],
        rms=rms,
        clip_fraction=clipped / len(vals),
        clip_threshold=clip_threshold,
        p95=_percentile(mags, 95.0),
        p99=_percentile(mags, 99.0),
        p999=_percentile(mags, 99.9),
    )


def recommend_gain(
    current_gain: float,
    observed_peak: float,
    *,
    target_peak: float = TARGET_LEVEL,
    floor: float = GAIN_FLOOR,
    ceiling: float = GAIN_CEILING,
) -> float:
    """Gain that would move ``observed_peak`` to ``target_peak``, clamped to [floor, ceiling].

    Linear: the force scales with the gain, so ``new = current * target_peak / observed_peak``.
    Returns ``current_gain`` (clamped) when the observed peak is non-positive — there is no signal
    to calibrate against. Rounded to 3 decimals (``user_ff.ini`` precision).
    """
    if not (floor <= ceiling):
        raise ValueError(f"floor {floor} must be <= ceiling {ceiling}")
    if observed_peak <= 0.0 or current_gain <= 0.0:
        return round(min(max(current_gain, floor), ceiling), 3)
    scaled = current_gain * (target_peak / observed_peak)
    return round(min(max(scaled, floor), ceiling), 3)


def offset_looks_valid(stats: FfbStats) -> tuple[bool, str]:
    """Sanity-check that the sampled finalFF is a real force signal, not a wrong-offset read."""
    if stats.n < OFFSET_MIN_SAMPLES:
        return False, f"only {stats.n} samples (< {OFFSET_MIN_SAMPLES}); car not driven long enough"
    if stats.peak > OFFSET_SANE_PEAK:
        return False, f"peak {stats.peak:.3f} > {OFFSET_SANE_PEAK} — finalFF offset likely wrong"
    if stats.peak < OFFSET_MIN_PEAK:
        return False, f"peak {stats.peak:.3f} < {OFFSET_MIN_PEAK} — signal effectively silent"
    return True, "ok"


def should_write(offset_valid: bool, write: bool, dry_run: bool) -> bool:
    """Whether to write user_ff.ini: only on an explicit ``--write``, a valid offset, and not
    ``--dry-run`` (pure decision, so the report-only-by-default contract is unit-tested).

    ``--observe-only`` is deliberately NOT a veto here — an operator who drives manually and passes
    ``--write`` has explicitly opted in.
    """
    return offset_valid and write and not dry_run


_SECTION_RE = re.compile(r"^\s*\[(?P<car>[^\]]+)\]\s*$")
_VALUE_RE = re.compile(r"^\s*VALUE\s*=", re.IGNORECASE)


def read_user_ff_value(text: str, car_id: str) -> float | None:
    """Return the ``VALUE`` under ``[car_id]`` in a ``user_ff.ini`` body, or ``None`` if absent."""
    in_section = False
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m is not None:
            in_section = m.group("car").strip() == car_id
            continue
        if in_section and _VALUE_RE.match(line):
            # Strip an inline ``;`` or ``#`` comment before parsing (``VALUE=1.0 ; note``).
            raw = line.split("=", 1)[1].split(";", 1)[0].split("#", 1)[0].strip()
            try:
                parsed = float(raw)
            except ValueError:
                return None
            # A corrupt/hand-edited ``VALUE=nan``/``inf`` is unusable — treat it as absent so the
            # caller falls back to gain 1.0 instead of propagating a non-finite gain / report.
            return parsed if math.isfinite(parsed) else None
    return None


def update_user_ff_value(text: str, car_id: str, value: float) -> str:
    """Return ``text`` with ``[car_id]``'s ``VALUE`` set to ``value``, preserving all else.

    Updates the first ``VALUE`` line inside an existing ``[car_id]`` section; appends a new
    section when the car is absent. Every other line (other cars, comments, spacing) is kept
    byte-for-byte so the operator's hand-tuned entries are never disturbed.
    """
    rendered = f"{value:.3f}"
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    replaced = False
    for line in lines:
        m = _SECTION_RE.match(line)
        if m is not None:
            # Leaving a section header. If we were inside the target section and never found a
            # VALUE to overwrite, insert one before this next section — updating in place rather
            # than appending a duplicate [car_id] block (an existing section with no VALUE key).
            if in_section and not replaced:
                out.append(f"VALUE={rendered}")
                replaced = True
            in_section = m.group("car").strip() == car_id
            out.append(line)
            continue
        if in_section and not replaced and _VALUE_RE.match(line):
            out.append(f"VALUE={rendered}")
            replaced = True
            in_section = False
            continue
        out.append(line)
    # Target section was the file's last section and had no VALUE line — insert it at EOF.
    if in_section and not replaced:
        out.append(f"VALUE={rendered}")
        replaced = True
    body = "\n".join(out)
    if not replaced:
        prefix = body.rstrip("\n")
        block = f"[{car_id}]\nVALUE={rendered}"
        body = f"{prefix}\n{block}" if prefix else block
    if text.endswith("\n"):
        body += "\n"
    return body


# --------------------------------------------------------------------------------------------
# Rig-only orchestration (validated on the physical rig; excluded from coverage).
# --------------------------------------------------------------------------------------------


def _user_ff_path(ac_user_dir: Path | None) -> Path:  # pragma: no cover - path helper, rig-only
    from tools.ac_harness.auto_drive import resolve_ac_user_dir

    return resolve_ac_user_dir(ac_user_dir) / "cfg" / "user_ff.ini"


def sample_final_ff(  # pragma: no cover - rig-only shared-memory loop
    *,
    duration_s: float,
    hz: float,
    proc: object | None = None,
    reader_factory: Callable[[], object] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> list[float]:
    """Sample ``finalFF`` from AC shared memory for ``duration_s`` at ~``hz`` (live frames only).

    If ``proc`` (the auto_drive child) exits mid-window — e.g. its sidecar tap fails after the
    hijack, which releases/brakes the controller — sampling stops so a stationary tail cannot
    poison the stats.
    """
    from tools.ac_harness.shared_memory import SharedMemoryReader

    factory = reader_factory or (lambda: SharedMemoryReader(with_physics=True))
    period = 1.0 / hz if hz > 0 else 0.0
    samples: list[float] = []
    reader = factory()
    try:
        deadline = now() + duration_s
        last_packet: int | None = None
        while now() < deadline:
            if proc is not None and getattr(proc, "poll", lambda: None)() is not None:
                break  # drive exited (controller released) — do not sample a stationary car
            snap = reader.read_physics()
            if snap is not None and snap.final_ff is not None and snap.packet_id != last_packet:
                samples.append(float(snap.final_ff))
                last_packet = snap.packet_id
            sleep(period)
    finally:
        reader.close()
    return samples


def _write_user_ff(path: Path, car_id: str, value: float) -> None:  # pragma: no cover - rig-only
    """Atomically set ``car_id``'s gain in ``user_ff.ini``, backing up the original first."""
    # utf-8-sig tolerates a UTF-8 BOM (AC/CM INIs are BOM-prone) so a leading ﻿ cannot hide
    # the first section from the parser; the write below emits plain utf-8 (no BOM).
    original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    if path.exists():
        path.with_suffix(path.suffix + ".backup").write_text(original, encoding="utf-8")
    updated = update_user_ff_value(original, car_id, value)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, path)


def _run(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only CLI/orchestration
    args = _parse_args(argv)

    from tools.ac_harness.auto_drive import validate_ac_id

    try:  # car/track/layout ids become log/report path segments — reject separators / traversal.
        validate_ac_id("car", args.car)
        validate_ac_id("track", args.track)
        if args.track_layout:
            validate_ac_id("track-layout", args.track_layout)
    except ValueError as exc:
        print(f"[ffb-calibrate] {exc}", file=sys.stderr)
        return 2

    if args.floor > args.ceiling:  # fail fast, before launching auto_drive / driving the rig
        print(
            f"[ffb-calibrate] --floor {args.floor} must be <= --ceiling {args.ceiling}",
            file=sys.stderr,
        )
        return 2

    user_ff = _user_ff_path(args.ac_user_dir)
    car = args.car
    key = _evidence_key(car, args.track, args.track_layout)
    passthrough = _auto_drive_passthrough(args)

    drive_proc = None
    drive_exited_early = False
    try:
        if not args.observe_only:
            # Keep the controller driving across ramp + the whole sample window (+margin).
            # auto_drive's default tap stops the drive thread mid-sample, which would sample a
            # stationary/braking car and write a bad gain.
            drive_seconds = args.ramp_seconds + args.sample_seconds + 20.0
            drive_proc, log_path = _launch_drive(
                car,
                args.track,
                args.driver,
                args.evidence_dir,
                tap_seconds=drive_seconds,
                extra_args=passthrough,
                key=key,
            )
            print(
                f"[ffb-calibrate] launched drive for {car} @ {args.track}; waiting for hijack ..."
            )
            if not _wait_for_hijack(log_path, proc=drive_proc, timeout_s=args.launch_timeout):
                print(
                    "[ffb-calibrate] drive did not reach hijack (or exited early); aborting",
                    file=sys.stderr,
                )
                return 2
            print("[ffb-calibrate] hijack landed; ramping ...")
            time.sleep(args.ramp_seconds)
        else:
            print(
                f"[ffb-calibrate] observe-only: drive {car} now; "
                f"sampling {args.sample_seconds:.0f}s"
            )

        print(f"[ffb-calibrate] sampling finalFF for {args.sample_seconds:.0f}s ...")
        samples = sample_final_ff(duration_s=args.sample_seconds, hz=args.hz, proc=drive_proc)
        # Captured BEFORE the finally kills it: if the child exited on its own during the window,
        # the controller was released and the tail is stationary/truncated — the sample is suspect.
        drive_exited_early = (
            drive_proc is not None and drive_proc.poll() is not None and not args.observe_only
        )
    finally:
        if drive_proc is not None:
            _terminate_tree(drive_proc)

    stats = summarize(samples)
    valid, reason = offset_looks_valid(stats)
    if valid and drive_exited_early:
        valid, reason = False, "auto_drive exited during the sample window (truncated/stationary)"

    current = 1.0
    if user_ff.exists():
        found = read_user_ff_value(user_ff.read_text(encoding="utf-8-sig"), car)
        current = found if found is not None else 1.0
    recommended = recommend_gain(
        current, stats.p99, target_peak=args.target_level, floor=args.floor, ceiling=args.ceiling
    )

    # Report-only by default; writing user_ff.ini requires an explicit --write (FFB strength is
    # operator-subjective — never mutate the wheel feel without opt-in). --dry-run forces no write.
    # --observe-only --write IS honored: the operator drove manually and explicitly opted in.
    will_write = should_write(valid, args.write, args.dry_run)
    print("\n=== FFB calibration ===")
    print(f"car             : {car}")
    print(f"samples         : {stats.n}")
    print(f"peak |finalFF|  : {stats.peak:.3f}  (kerb spikes; not the calibration lever)")
    print(f"p95 / p99 / p999: {stats.p95:.3f} / {stats.p99:.3f} / {stats.p999:.3f}")
    print(f"rms             : {stats.rms:.3f}")
    print(f"clip% (>= {stats.clip_threshold:.2f})  : {stats.clip_fraction * 100:.2f}%")
    print(f"offset valid    : {valid} ({reason})")
    print(f"current gain    : {current:.3f}")
    print(f"recommended     : {recommended:.3f}  (P99 {stats.p99:.3f} -> {args.target_level:.2f})")
    print(f"action          : {'WRITE user_ff.ini' if will_write else 'report only (no write)'}")

    # Write BEFORE emitting the report so "wrote" reflects reality: a failed/locked write must not
    # leave the evidence bundle claiming the gain changed (Codex finding).
    wrote = False
    write_error: str | None = None
    if will_write:
        try:
            _write_user_ff(user_ff, car, recommended)
            wrote = True
            print(f"[ffb-calibrate] wrote VALUE={recommended:.3f} for [{car}] -> {user_ff}")
        except OSError as exc:
            write_error = str(exc)
            print(f"[ffb-calibrate] write FAILED: {exc}", file=sys.stderr)

    report = {
        "car": car,
        "track": args.track,
        "track_layout": args.track_layout,
        "stats": asdict(stats),
        "offset_valid": valid,
        "offset_reason": reason,
        "current_gain": current,
        "recommended_gain": recommended,
        "wrote": wrote,
        "write_error": write_error,
        "user_ff_path": str(user_ff),
    }
    _write_report(args.evidence_dir, key, report)

    if not valid:
        print(f"[ffb-calibrate] NOT writing: {reason}", file=sys.stderr)
        return 3
    if will_write and not wrote:
        return 4
    if not args.write:
        print("[ffb-calibrate] report-only; re-run with --write to apply the recommended gain")
    return 0


def _terminate_tree(proc: object) -> None:  # pragma: no cover - rig-only
    """Kill the auto_drive child AND its descendants (e.g. an auto-started sidecar).

    A bare ``terminate()`` hard-kills only auto_drive, so its own ``finally`` never runs and an
    auto-started sidecar orphans and squats the port. On Windows ``taskkill /T`` takes the whole
    tree; elsewhere fall back to ``terminate()``.
    """
    pid = getattr(proc, "pid", None)
    if pid is None:
        return
    if sys.platform == "win32":
        import subprocess

        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
    else:
        proc.terminate()  # type: ignore[attr-defined]


def _auto_drive_passthrough(args: argparse.Namespace) -> list[str]:
    """Build the auto_drive flags that must match on the child (layout + launch-path overrides).

    Without these the drive subprocess launches/preflights the wrong layout or profile (default
    Steam/CM/sidecar) while the calibrator reads/writes ``user_ff.ini`` in the override.
    """
    extra: list[str] = []
    if args.track_layout:
        extra += ["--track-layout", args.track_layout]
    if args.ac_user_dir is not None:
        extra += ["--ac-user-dir", str(args.ac_user_dir)]
    if args.ac_root is not None:
        extra += ["--ac-root", str(args.ac_root)]
    if args.cm_exe is not None:
        extra += ["--cm-exe", str(args.cm_exe)]
    if args.sidecar_url:
        extra += ["--sidecar-url", args.sidecar_url]
    return extra


def _launch_drive(  # pragma: no cover - rig-only
    car: str,
    track: str,
    driver: str,
    evidence_dir: Path,
    *,
    tap_seconds: float,
    key: str,
    extra_args: Sequence[str] = (),
) -> tuple[object, Path]:
    import subprocess

    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / f"drive_{key}.log"
    log = log_path.open("w", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "tools.ac_harness.auto_drive",
        "--car",
        car,
        "--track",
        track,
        "--driver",
        driver,
        # Cover BOTH auto_drive budgets: the drive thread self-terminates on --drive-seconds
        # (default 300s) and the tap on --tap-seconds, so a long --sample-seconds needs both
        # raised or the car brakes mid-sample.
        "--tap-seconds",
        str(tap_seconds),
        "--drive-seconds",
        str(tap_seconds),
        *extra_args,
    ]
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    return proc, log_path


def _wait_for_hijack(  # pragma: no cover - rig-only
    log_path: Path, *, proc: object, timeout_s: float
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if "hijack landed" in log_path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            pass
        # If auto_drive already exited (preflight/content/sidecar failure) without landing the
        # hijack, stop waiting immediately instead of burning the full launch-timeout.
        if getattr(proc, "poll", lambda: None)() is not None:
            return False
        time.sleep(2.0)
    return False


def _write_report(  # pragma: no cover - rig-only
    evidence_dir: Path, key: str, report: dict[str, object]
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / f"ffb_{key}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[ffb-calibrate] report -> {out}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:  # pragma: no cover - CLI wiring
    p = argparse.ArgumentParser(description="Per-car FFB gain auto-calibration from finalFF.")
    p.add_argument("--car", required=True, help="AC car id (e.g. ks_porsche_911_gt3_r_2016)")
    p.add_argument("--track", default="spa", help="Track id (default: spa)")
    p.add_argument(
        "--track-layout",
        dest="track_layout",
        default=None,
        help="Layout for multi-layout tracks (forwarded to auto_drive for the right line).",
    )
    p.add_argument("--driver", default="ggv", help="auto_drive driver profile (default: ggv)")
    # Launch-path overrides forwarded to the auto_drive child for non-default rigs.
    p.add_argument("--ac-root", dest="ac_root", type=Path, default=None, help="AC content root")
    p.add_argument("--cm-exe", dest="cm_exe", type=Path, default=None, help="Content Manager.exe")
    p.add_argument("--sidecar-url", dest="sidecar_url", default=None, help="auto_drive sidecar URL")
    p.add_argument(
        "--sample-seconds", dest="sample_seconds", type=_pos_float, default=DEFAULT_SAMPLE_SECONDS
    )
    p.add_argument(
        "--hz", type=_pos_float, default=DEFAULT_HZ, help="finalFF sample rate (default: 100)"
    )
    p.add_argument(
        "--target-level",
        dest="target_level",
        type=_pos_float,
        default=TARGET_LEVEL,
        help=f"Aim the {CALIB_PERCENTILE:.0f}th percentile of |finalFF| at this level "
        f"(default: {TARGET_LEVEL}).",
    )
    p.add_argument("--floor", type=_nonneg_float, default=GAIN_FLOOR)
    p.add_argument("--ceiling", type=_pos_float, default=GAIN_CEILING)
    p.add_argument("--ramp-seconds", dest="ramp_seconds", type=_nonneg_float, default=10.0)
    p.add_argument("--launch-timeout", dest="launch_timeout", type=_pos_float, default=180.0)
    p.add_argument(
        "--observe-only",
        dest="observe_only",
        action="store_true",
        help="Do not launch auto_drive; the operator drives while this samples.",
    )
    p.add_argument(
        "--write",
        dest="write",
        action="store_true",
        help="Apply the recommended gain to user_ff.ini. Default is report-only (no write).",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Explicitly force report-only (already the default); overrides --write.",
    )
    p.add_argument(
        "--ac-user-dir",
        dest="ac_user_dir",
        type=Path,
        default=None,
        help="Override Documents/Assetto Corsa (else OneDrive-redirect auto-resolved).",
    )
    p.add_argument(
        "--evidence-dir", dest="evidence_dir", type=Path, default=Path(".scratch/ffb-calibrate")
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - entrypoint
    return _run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
