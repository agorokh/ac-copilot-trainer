"""Per-car FFB gain auto-calibration (issue #533).

Drives a car (composing on :mod:`tools.ac_harness.auto_drive`, or the operator drives with
``--observe-only``), samples ``acpmf_physics.finalFF`` — the normalized force AC sends to the
wheel — and derives the per-car gain that makes the force peak near full scale **without
clipping**. The gain is AC's own per-car multiplier stored in ``Documents/Assetto Corsa/cfg/
user_ff.ini`` (``[car_id] VALUE=x.xxx``); this tool never touches the AC/CSP install tree.

The ``finalFF`` byte offset (308) is validated against the live signal before any write: a wrong
offset yields out-of-range or all-zero samples, which :func:`offset_looks_valid` rejects, forcing
a report-only pass. Run ``--dry-run`` (or ``--observe-only``) first to confirm the signal, then a
real pass to write the gains.

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
TARGET_PEAK = 0.90
GAIN_FLOOR = 0.30
GAIN_CEILING = 2.00
DEFAULT_SAMPLE_SECONDS = 45.0
DEFAULT_HZ = 100.0
# A correct finalFF read stays within about [-1, 1]; allow a little headroom for transient
# overshoot. Peaks far outside this (or an all-silent capture) mean the offset is wrong for this
# AC/CSP build and the sample must not drive a gain write.
OFFSET_SANE_PEAK = 1.10
OFFSET_MIN_PEAK = 0.02
OFFSET_MIN_SAMPLES = 200


@dataclass(frozen=True)
class FfbStats:
    """Summary of a finalFF sample window."""

    n: int
    peak: float
    rms: float
    clip_fraction: float
    clip_threshold: float


def summarize(samples: Sequence[float], *, clip_threshold: float = CLIP_THRESHOLD) -> FfbStats:
    """Reduce raw finalFF samples to peak / rms / clipping fraction (pure).

    ``clip_fraction`` is the share of samples whose magnitude reaches ``clip_threshold`` — the
    fraction of the lap where the wheel is pinned at full force and detail is lost. NaN samples
    are ignored.
    """
    vals = [float(s) for s in samples if not math.isnan(float(s))]
    if not vals:
        return FfbStats(n=0, peak=0.0, rms=0.0, clip_fraction=0.0, clip_threshold=clip_threshold)
    mags = [abs(v) for v in vals]
    peak = max(mags)
    rms = math.sqrt(sum(v * v for v in vals) / len(vals))
    clipped = sum(1 for m in mags if m >= clip_threshold)
    return FfbStats(
        n=len(vals),
        peak=peak,
        rms=rms,
        clip_fraction=clipped / len(vals),
        clip_threshold=clip_threshold,
    )


def recommend_gain(
    current_gain: float,
    observed_peak: float,
    *,
    target_peak: float = TARGET_PEAK,
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
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                return None
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
            in_section = m.group("car").strip() == car_id
            out.append(line)
            continue
        if in_section and not replaced and _VALUE_RE.match(line):
            out.append(f"VALUE={rendered}")
            replaced = True
            in_section = False
            continue
        out.append(line)
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
    reader_factory: Callable[[], object] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> list[float]:
    """Sample ``finalFF`` from AC shared memory for ``duration_s`` at ~``hz`` (live frames only)."""
    from tools.ac_harness.shared_memory import SharedMemoryReader

    factory = reader_factory or (lambda: SharedMemoryReader(with_physics=True))
    period = 1.0 / hz if hz > 0 else 0.0
    samples: list[float] = []
    reader = factory()
    try:
        deadline = now() + duration_s
        last_packet: int | None = None
        while now() < deadline:
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
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if path.exists():
        path.with_suffix(path.suffix + ".backup").write_text(original, encoding="utf-8")
    updated = update_user_ff_value(original, car_id, value)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, path)


def _run(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only CLI/orchestration
    args = _parse_args(argv)

    user_ff = _user_ff_path(args.ac_user_dir)
    car = args.car

    drive_proc = None
    log_path = None
    try:
        if not args.observe_only:
            drive_proc, log_path = _launch_drive(car, args.track, args.driver, args.evidence_dir)
            print(
                f"[ffb-calibrate] launched drive for {car} @ {args.track}; waiting for hijack ..."
            )
            if not _wait_for_hijack(log_path, timeout_s=args.launch_timeout):
                print(
                    "[ffb-calibrate] drive did not reach hijack in time; aborting", file=sys.stderr
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
        samples = sample_final_ff(duration_s=args.sample_seconds, hz=args.hz)
    finally:
        if drive_proc is not None:
            drive_proc.terminate()

    stats = summarize(samples)
    valid, reason = offset_looks_valid(stats)

    current = 1.0
    if user_ff.exists():
        found = read_user_ff_value(user_ff.read_text(encoding="utf-8"), car)
        current = found if found is not None else 1.0
    recommended = recommend_gain(
        current, stats.peak, target_peak=args.target_peak, floor=args.floor, ceiling=args.ceiling
    )

    will_write = valid and not args.dry_run and not args.observe_only
    print("\n=== FFB calibration ===")
    print(f"car            : {car}")
    print(f"samples        : {stats.n}")
    print(f"peak |finalFF| : {stats.peak:.3f}")
    print(f"rms            : {stats.rms:.3f}")
    print(f"clip% (>= {stats.clip_threshold:.2f}): {stats.clip_fraction * 100:.2f}%")
    print(f"offset valid   : {valid} ({reason})")
    print(f"current gain   : {current:.3f}")
    print(f"recommended    : {recommended:.3f}  (target peak {args.target_peak:.2f})")
    print(f"action         : {'WRITE user_ff.ini' if will_write else 'report only (no write)'}")

    report = {
        "car": car,
        "track": args.track,
        "stats": asdict(stats),
        "offset_valid": valid,
        "offset_reason": reason,
        "current_gain": current,
        "recommended_gain": recommended,
        "wrote": will_write,
        "user_ff_path": str(user_ff),
    }
    _write_report(args.evidence_dir, car, args.track, report)

    if will_write:
        _write_user_ff(user_ff, car, recommended)
        print(f"[ffb-calibrate] wrote VALUE={recommended:.3f} for [{car}] -> {user_ff}")
    elif not valid:
        print(f"[ffb-calibrate] NOT writing: {reason}", file=sys.stderr)
        return 3
    return 0


def _launch_drive(  # pragma: no cover - rig-only
    car: str, track: str, driver: str, evidence_dir: Path
) -> tuple[object, Path]:
    import subprocess

    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / f"drive_{car}_{track}.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tools.ac_harness.auto_drive",
            "--car",
            car,
            "--track",
            track,
            "--driver",
            driver,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return proc, log_path


def _wait_for_hijack(log_path: Path, *, timeout_s: float) -> bool:  # pragma: no cover - rig-only
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if "hijack landed" in log_path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            pass
        time.sleep(2.0)
    return False


def _write_report(  # pragma: no cover - rig-only
    evidence_dir: Path, car: str, track: str, report: dict[str, object]
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / f"ffb_{car}_{track}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[ffb-calibrate] report -> {out}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:  # pragma: no cover - CLI wiring
    p = argparse.ArgumentParser(description="Per-car FFB gain auto-calibration from finalFF.")
    p.add_argument("--car", required=True, help="AC car id (e.g. ks_porsche_911_gt3_r_2016)")
    p.add_argument("--track", default="spa", help="Track id (default: spa)")
    p.add_argument("--driver", default="ggv", help="auto_drive driver profile (default: ggv)")
    p.add_argument(
        "--sample-seconds", dest="sample_seconds", type=float, default=DEFAULT_SAMPLE_SECONDS
    )
    p.add_argument(
        "--hz", type=float, default=DEFAULT_HZ, help="finalFF sample rate (default: 100)"
    )
    p.add_argument("--target-peak", dest="target_peak", type=float, default=TARGET_PEAK)
    p.add_argument("--floor", type=float, default=GAIN_FLOOR)
    p.add_argument("--ceiling", type=float, default=GAIN_CEILING)
    p.add_argument("--ramp-seconds", dest="ramp_seconds", type=float, default=10.0)
    p.add_argument("--launch-timeout", dest="launch_timeout", type=float, default=180.0)
    p.add_argument(
        "--observe-only",
        dest="observe_only",
        action="store_true",
        help="Do not launch auto_drive; the operator drives while this samples.",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Report peak/clip% and recommendation without writing user_ff.ini.",
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
