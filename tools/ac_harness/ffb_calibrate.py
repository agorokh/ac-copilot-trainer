"""Per-car FFB gain auto-calibration (issue #533).

Assetto Corsa stores a **per-car force-feedback gain** in
``Documents/Assetto Corsa/cfg/user_ff.ini`` as ``[car_id]  VALUE=x.xxx`` — one multiplier per car.
Today it is trimmed by hand in-seat by watching the in-game FFB app for **clipping** (the force
pinned at ±1.0). ``acpmf_physics.finalFF`` (−1..1) is that exact force, so clipping is directly
measurable and the trim can be made objective and automatic:

    drive the car flat-out for ≥1 lap → sample ``finalFF`` at ~100 Hz → measure peak + clipping %
    → recommend the ``VALUE`` that puts peak at ~0.90 with no sustained clip → write it back.

Design split (so CI verifies the maths on any OS with zero Assetto Corsa / Windows):

* **Pure core** — :func:`summarize_final_ff`, :func:`recommend_gain`, and the ``user_ff.ini``
  read/write helpers (:func:`parse_user_ff_gain`, :func:`set_user_ff_gain`, :func:`write_user_ff`).
  Unit-tested with synthetic sample lists and in-memory INI text.
* **Rig-only** — :func:`collect_final_ff` (the ~100 Hz sampling loop; testable with a fake reader +
  injected clock) and the CLI, which composes on ``tools.ac_harness.auto_drive`` to actually drive.

Safety invariants (mirrors the ``race.ini`` write guard in ``auto_drive``):

* The ONLY file ever written is ``<AC Documents>/Assetto Corsa/cfg/user_ff.ini`` (validated by
  :func:`validate_user_ff_write_target`) plus its sibling ``.backup`` — **never** the AC/CSP install
  tree. A pre-write backup is always taken.
* Every other car's entry, comments, and the file's newline style are preserved byte-for-byte
  (the preserve-manual-work invariant): only the target car's ``VALUE`` line changes.
* Recommended gains are floor/ceiling-clamped, and a non-finite ``finalFF`` (torn read / wrong
  offset) is rejected upstream in :func:`shared_memory.parse_final_ff` rather than averaged in.

CLI::

    # drive + calibrate (composes on auto_drive's ggv flat-out driver):
    python -m tools.ac_harness.ffb_calibrate --car ks_porsche_911_gt3_r_2016 --track spa
    # sample a session that is already live (operator- or peer-driven), don't launch:
    python -m tools.ac_harness.ffb_calibrate --car bmw_m3_gt2 --attach --seconds 120
    # preview only, never touch user_ff.ini:
    python -m tools.ac_harness.ffb_calibrate --car bmw_m3_gt2 --attach --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.ac_harness.shared_memory import PHYSICS_FINAL_FF_OFFSET

# ---------------------------------------------------------------------------
# Calibration constants (all overridable on the CLI).
# ---------------------------------------------------------------------------
#: |finalFF| at or above this counts the frame as clipping. finalFF saturates at ±1.0; 0.99 keeps a
#: hair of margin off the exact rail so a value quantised just below 1.0 still reads as clipped.
CLIP_THRESHOLD = 0.99
#: Target peak |finalFF| the recommended gain aims for — full wheel range with headroom, no clip.
TARGET_PEAK = 0.90
#: Fraction of samples allowed at/above CLIP_THRESHOLD before the recommendation is forced to reduce
#: gain ("no sustained clip"). A brief kerb strike is fine; a lap spent on the rail is not.
CLIP_TOLERANCE = 0.01
#: Hard clamps on the written multiplier — AC per-car VALUEs sit near 1.0 (hand-tuned 1.01–1.05); a
#: recommendation outside this band means something is wrong (bad signal), so clamp and flag it.
GAIN_FLOOR = 0.30
GAIN_CEIL = 2.0
#: The AC default when a car has no user_ff.ini entry yet (100 % of the computed physics force).
DEFAULT_GAIN = 1.0
#: Sampling rate for the finalFF collector (~physics-adjacent; finer than needed but cheap).
SAMPLE_HZ = 100
#: Default sampling window for --attach mode (drive mode samples for the whole auto_drive drive).
DEFAULT_ATTACH_SECONDS = 120.0

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_VALUE_KEY_RE = re.compile(r"^\s*VALUE\s*=", re.IGNORECASE)
_VALUE_LINE_RE = re.compile(r"^\s*VALUE\s*=\s*(.+?)\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure core — statistics + gain recommendation.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FfbObservation:
    """Summary statistics of a ``finalFF`` sample window."""

    sample_count: int
    peak: float  # max |finalFF| observed
    clip_fraction: float  # fraction of samples with |finalFF| >= clip_threshold
    mean_abs: float  # mean |finalFF| (drive intensity sanity signal)
    clip_threshold: float


@dataclass(frozen=True)
class GainRecommendation:
    """A recommended ``user_ff.ini`` VALUE plus the reasoning and guard state."""

    current_gain: float
    recommended: float
    reason: str
    clamped: bool
    enough_signal: bool


def summarize_final_ff(
    samples: Sequence[float], *, clip_threshold: float = CLIP_THRESHOLD
) -> FfbObservation:
    """Reduce a ``finalFF`` sample list to peak / clip-fraction / mean-abs (pure)."""
    n = len(samples)
    if n == 0:
        return FfbObservation(0, 0.0, 0.0, 0.0, clip_threshold)
    mags = [abs(s) for s in samples]
    peak = max(mags)
    clipped = sum(1 for m in mags if m >= clip_threshold)
    return FfbObservation(
        sample_count=n,
        peak=peak,
        clip_fraction=clipped / n,
        mean_abs=sum(mags) / n,
        clip_threshold=clip_threshold,
    )


def recommend_gain(
    current_gain: float,
    obs: FfbObservation,
    *,
    target_peak: float = TARGET_PEAK,
    clip_tolerance: float = CLIP_TOLERANCE,
    gain_floor: float = GAIN_FLOOR,
    gain_ceil: float = GAIN_CEIL,
) -> GainRecommendation:
    """Recommend the ``user_ff.ini`` VALUE putting peak at ``target_peak`` with no sustained clip.

    ``finalFF`` already includes the current gain, so peak scales ~linearly with it: to move the
    observed ``peak`` onto ``target_peak`` the multiplier scales by ``target_peak / peak``. When the
    signal is clipping, ``peak`` is capped near 1.0 and so *underestimates* the true force — the
    resulting gain is an **upper bound**: a guaranteed reduction that may need a second
    pass to fully converge (surfaced in ``reason`` and via ``clip_fraction``). The result is rounded
    to 3 dp (AC's VALUE precision) and clamped to ``[gain_floor, gain_ceil]``.
    """
    if obs.sample_count == 0 or obs.peak <= 0.0:
        return GainRecommendation(
            current_gain=current_gain,
            recommended=round(current_gain, 3),
            reason="insufficient signal (no non-zero finalFF samples) — kept current gain",
            clamped=False,
            enough_signal=False,
        )

    raw = current_gain * (target_peak / obs.peak)
    clamped = False
    if raw < gain_floor:
        raw, clamped = gain_floor, True
    elif raw > gain_ceil:
        raw, clamped = gain_ceil, True
    recommended = round(raw, 3)

    clip_pct = obs.clip_fraction * 100.0
    tol_pct = clip_tolerance * 100.0
    if obs.clip_fraction > clip_tolerance:
        reason = (
            f"clipping {clip_pct:.1f}% of samples (> {tol_pct:.1f}% tolerance) — reduce gain; "
            f"peak underestimates true force while clipped, so re-run to confirm convergence"
        )
    elif obs.peak < target_peak:
        reason = f"peak {obs.peak:.3f} below target {target_peak:.2f} — raise gain for full range"
    else:
        reason = f"peak {obs.peak:.3f} near target {target_peak:.2f} — small trim"
    if clamped:
        reason += f" [clamped to [{gain_floor}, {gain_ceil}]]"
    return GainRecommendation(
        current_gain=current_gain,
        recommended=recommended,
        reason=reason,
        clamped=clamped,
        enough_signal=True,
    )


# ---------------------------------------------------------------------------
# Pure core — user_ff.ini parse / surgical update / write-target guard.
# ---------------------------------------------------------------------------
def format_gain(value: float) -> str:
    """Format a gain as AC writes it in user_ff.ini (3 decimal places)."""
    return f"{value:.3f}"


def parse_user_ff_gain(text: str, car_id: str) -> float | None:
    """Return the current ``VALUE`` for ``car_id``, or ``None`` if absent/unparseable."""
    current: str | None = None
    for line in text.splitlines():
        section = _SECTION_RE.match(line)
        if section:
            current = section.group(1).strip()
            continue
        if current == car_id:
            m = _VALUE_LINE_RE.match(line)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    return None
    return None


def _trailing_eol(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def set_user_ff_gain(text: str, car_id: str, value: float) -> str:
    """Return ``text`` with car ``car_id``'s ``VALUE`` set to ``value``, preserving everything else.

    Surgical (preserve-manual-work invariant): only the target car's ``VALUE`` line is replaced (or
    inserted); every other car's entry, comment, blank line, and the file's newline style are kept
    byte-for-byte. If ``car_id`` has no section, a new ``[car_id]`` section is appended.
    """
    value_str = format_gain(value)
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)

    header_idx: int | None = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m and m.group(1).strip() == car_id:
            header_idx = i
            break

    if header_idx is None:
        body = "".join(lines)
        if body and not body.endswith("\n"):
            body += eol
        separator = (
            eol if body.strip() else ""
        )  # blank line before a new section in a non-empty file
        return f"{body}{separator}[{car_id}]{eol}VALUE={value_str}{eol}"

    # Scan the target section (header+1 .. next header / EOF) for an existing VALUE line.
    value_idx: int | None = None
    for j in range(header_idx + 1, len(lines)):
        if _SECTION_RE.match(lines[j]):
            break
        if value_idx is None and _VALUE_KEY_RE.match(lines[j]):
            value_idx = j

    if value_idx is not None:
        line_eol = _trailing_eol(lines[value_idx]) or eol
        lines[value_idx] = f"VALUE={value_str}{line_eol}"
    else:
        if not _trailing_eol(lines[header_idx]):
            lines[header_idx] = lines[header_idx] + eol
        lines.insert(header_idx + 1, f"VALUE={value_str}{eol}")
    return "".join(lines)


def validate_user_ff_write_target(path: Path) -> Path:
    """Return ``path`` only when it is ``<AC Documents>/Assetto Corsa/cfg/user_ff.ini``.

    Mirrors ``auto_drive.validate_race_ini_write_target``: the calibrator must NEVER write into the
    AC/CSP install tree, only the user-data ``cfg/user_ff.ini``. Raises :class:`ValueError` else.
    """
    logical = path.absolute()
    if (
        logical.name.lower() != "user_ff.ini"
        or logical.parent.name.lower() != "cfg"
        or logical.parent.parent.name.lower() != "assetto corsa"
    ):
        raise ValueError(
            "user_ff.ini write target must be <AC Documents>/Assetto Corsa/cfg/user_ff.ini: "
            f"{logical}"
        )
    return logical


def resolve_user_ff_ini(ac_user_dir: Path) -> Path:
    """``<ac_user_dir>/cfg/user_ff.ini`` (pure path join; existence not required)."""
    return ac_user_dir / "cfg" / "user_ff.ini"


def read_user_ff_text(path: Path) -> str:
    """Read user_ff.ini text (empty string if it does not exist yet), newline-preserving.

    Reads via bytes (not ``read_text``) so the exact CRLF/LF bytes survive: ``read_text`` does
    universal-newline translation that would collapse the file's CRLFs, and its ``newline`` kwarg
    only exists on Python 3.13+.
    """
    if not path.is_file():
        return ""
    return path.read_bytes().decode("utf-8", "surrogateescape")


def write_user_ff(path: Path, text: str, *, backup_suffix: str = ".backup") -> Path | None:
    """Atomically write ``text`` to the validated user_ff.ini, backing up any existing file first.

    Returns the backup path, or ``None`` when there was no pre-existing file to back up. Only ever
    writes ``user_ff.ini`` and its sibling ``.backup`` (target validated).
    """
    target = validate_user_ff_write_target(path)
    backup_path: Path | None = None
    if target.is_file():
        backup_path = target.with_name(target.name + backup_suffix)
        backup_path.write_bytes(target.read_bytes())
    tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    # Write via bytes so the exact CRLF/LF bytes embedded in ``text`` survive (no translation, and
    # no dependency on write_text's 3.13-only ``newline`` kwarg).
    tmp.write_bytes(text.encode("utf-8", "surrogateescape"))
    os.replace(tmp, target)
    return backup_path


# ---------------------------------------------------------------------------
# Rig sampler — testable with a fake reader + injected clock (loop logic is pure).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SampleMeta:
    """Bookkeeping from a :func:`collect_final_ff` run."""

    read_ok: int
    torn_reads: int  # frames where parse_final_ff raised (short/non-finite) — skipped
    no_physics: int  # frames where read_final_ff returned None (physics unmapped)
    elapsed_s: float
    offset_ok: bool  # every sample had |finalFF| <= 1 + eps (validates PHYSICS_FINAL_FF_OFFSET)


class _FinalFfReader:  # pragma: no cover - structural Protocol-ish; real impl is SharedMemoryReader
    def read_final_ff(self) -> float | None: ...


def collect_final_ff(
    reader: _FinalFfReader,
    *,
    sample_hz: float = SAMPLE_HZ,
    duration_s: float = DEFAULT_ATTACH_SECONDS,
    stop: object | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    offset_eps: float = 1e-3,
) -> tuple[list[float], SampleMeta]:
    """Sample ``reader.read_final_ff()`` at ~``sample_hz`` for ``duration_s`` (or until ``stop``).

    Duration-based on purpose: AC only counts VALID laps in ``completedLaps`` (a kerb clip
    invalidates a lap), so a lap counter is an unreliable stop condition here — a fixed flat-out
    window that spans ≥1 lap is both simpler and more robust for capturing peak/clip. Torn reads
    (:class:`ValueError` from the parser) and unmapped-physics frames (``None``) are counted and
    skipped, never mixed into the samples. ``stop`` (if given) is anything with ``.is_set()``.
    """
    interval = 1.0 / sample_hz if sample_hz > 0 else 0.0
    samples: list[float] = []
    torn = 0
    no_phys = 0
    offset_ok = True
    t0 = clock()
    while True:
        now = clock()
        if now - t0 >= duration_s:
            break
        if stop is not None and getattr(stop, "is_set", lambda: False)():
            break
        try:
            value = reader.read_final_ff()
        except ValueError:
            # Torn read / non-finite (short buffer or wrong offset) — skip, don't also count as
            # "no physics" (that is reserved for a genuinely unmapped physics page).
            torn += 1
            if interval:
                sleep(interval)
            continue
        if value is None:
            no_phys += 1
        else:
            if abs(value) > 1.0 + offset_eps:
                offset_ok = False
            samples.append(value)
        if interval:
            sleep(interval)
    return samples, SampleMeta(
        read_ok=len(samples),
        torn_reads=torn,
        no_physics=no_phys,
        elapsed_s=clock() - t0,
        offset_ok=offset_ok,
    )


# ---------------------------------------------------------------------------
# CLI / orchestration (rig-only).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CalibrationResult:
    """Everything the CLI reports for one car."""

    car_id: str
    observation: FfbObservation
    recommendation: GainRecommendation
    user_ff_path: Path
    written: bool
    backup_path: Path | None


def format_result(result: CalibrationResult) -> str:
    """Human-readable one-block summary (also the acceptance-criterion CLI output)."""
    obs = result.observation
    rec = result.recommendation
    lines = [
        f"FFB calibration — {result.car_id}",
        f"  samples          : {obs.sample_count} (mean|FF| {obs.mean_abs:.3f})",
        f"  observed peak    : {obs.peak:.3f}",
        f"  clipping         : {obs.clip_fraction * 100:.1f}% of samples >= {obs.clip_threshold}",
        f"  current VALUE    : {format_gain(rec.current_gain)}",
        f"  recommended VALUE: {format_gain(rec.recommended)}  ({rec.reason})",
    ]
    if result.written:
        lines.append(
            f"  written VALUE    : {format_gain(rec.recommended)} -> {result.user_ff_path}"
        )
        if result.backup_path is not None:
            lines.append(f"  backup           : {result.backup_path}")
    else:
        lines.append(f"  written VALUE    : (dry-run — {result.user_ff_path} unchanged)")
    return "\n".join(lines)


def calibrate_from_samples(
    samples: Sequence[float],
    *,
    car_id: str,
    user_ff_path: Path,
    write: bool,
    clip_threshold: float = CLIP_THRESHOLD,
    target_peak: float = TARGET_PEAK,
    clip_tolerance: float = CLIP_TOLERANCE,
) -> CalibrationResult:
    """Turn collected ``finalFF`` samples into an observation + recommendation, optionally writing.

    Pure except for the optional file write (guarded/backed-up in :func:`write_user_ff`). The write
    is skipped when there is not enough signal to recommend a change, so a bad/empty drive never
    clobbers a hand-tuned VALUE.
    """
    obs = summarize_final_ff(samples, clip_threshold=clip_threshold)
    current = parse_user_ff_gain(read_user_ff_text(user_ff_path), car_id)
    current_gain = DEFAULT_GAIN if current is None else current
    rec = recommend_gain(current_gain, obs, target_peak=target_peak, clip_tolerance=clip_tolerance)

    written = False
    backup_path: Path | None = None
    if write and rec.enough_signal:
        updated = set_user_ff_gain(read_user_ff_text(user_ff_path), car_id, rec.recommended)
        backup_path = write_user_ff(user_ff_path, updated)
        written = True
    return CalibrationResult(
        car_id=car_id,
        observation=obs,
        recommendation=rec,
        user_ff_path=user_ff_path,
        written=written,
        backup_path=backup_path,
    )


def _drive_and_sample(  # pragma: no cover - rig-only
    args: argparse.Namespace, reader_factory: Callable[[], _FinalFfReader]
) -> tuple[list[float], SampleMeta]:
    """Compose on ``auto_drive``: launch a ggv flat-out drive in a subprocess, sample concurrently.

    Two independent shared-memory readers is fine — the section is read-only. auto_drive owns the
    launch/hijack/drive/veto machinery (single-rig, one-driver); this process only reads finalFF.
    """
    import subprocess
    import threading

    stop = threading.Event()
    cmd = [
        sys.executable,
        "-m",
        "tools.ac_harness.auto_drive",
        "--car",
        args.car,
        "--track",
        args.track,
        "--driver",
        "ggv",
        "--drive-seconds",
        str(args.seconds),
    ]
    if args.no_setup:
        cmd.append("--no-setup")
    print(f"ffb-calibrate: composing on auto_drive: {' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(cmd)  # noqa: S603 - fixed argv, no shell
    samples: list[float] = []
    meta_box: dict[str, SampleMeta] = {}

    def _sample() -> None:
        reader = reader_factory()
        try:
            s, m = collect_final_ff(
                reader, sample_hz=args.sample_hz, duration_s=args.seconds + 60.0, stop=stop
            )
        finally:
            close = getattr(reader, "close", None)
            if callable(close):
                close()
        samples.extend(s)
        meta_box["meta"] = m

    worker = threading.Thread(target=_sample, name="finalff-sampler")
    worker.start()
    proc.wait()
    stop.set()
    worker.join()
    return samples, meta_box.get("meta", SampleMeta(0, 0, 0, 0.0, True))


def _attach_and_sample(  # pragma: no cover - rig-only
    args: argparse.Namespace, reader_factory: Callable[[], _FinalFfReader]
) -> tuple[list[float], SampleMeta]:
    """Sample a session that is already live (operator- or peer-driven) — no launch."""
    print(
        f"ffb-calibrate: attaching to live AC, sampling finalFF for {args.seconds:.0f}s "
        f"(drive the car flat-out now)",
        flush=True,
    )
    reader = reader_factory()
    try:
        return collect_final_ff(reader, sample_hz=args.sample_hz, duration_s=args.seconds)
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Per-car FFB gain auto-calibration from acpmf_physics.finalFF clipping (#533)"
    )
    p.add_argument("--car", required=True, help="AC car id, e.g. ks_porsche_911_gt3_r_2016")
    p.add_argument("--track", help="AC track id (required unless --attach)")
    p.add_argument(
        "--attach",
        action="store_true",
        help="sample a session already on track instead of launching a drive",
    )
    p.add_argument(
        "--seconds",
        type=float,
        default=DEFAULT_ATTACH_SECONDS,
        help="drive/sample window seconds (must span >=1 flat-out lap)",
    )
    p.add_argument("--sample-hz", type=float, default=SAMPLE_HZ, help="finalFF sampling rate")
    p.add_argument("--target-peak", type=float, default=TARGET_PEAK, help="target peak |finalFF|")
    p.add_argument(
        "--clip-threshold", type=float, default=CLIP_THRESHOLD, help="|finalFF| counted as clipping"
    )
    p.add_argument(
        "--clip-tolerance",
        type=float,
        default=CLIP_TOLERANCE,
        help="fraction of clipped samples tolerated before forcing a gain reduction",
    )
    p.add_argument("--no-setup", action="store_true", help="pass --no-setup to auto_drive")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="compute + print the recommendation but do NOT write user_ff.ini",
    )
    p.add_argument(
        "--ac-user-dir",
        type=Path,
        default=None,
        help="AC user-data root (Documents/Assetto Corsa; auto-detects OneDrive redirect)",
    )
    return p


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig-only CLI wiring
    args = _build_arg_parser().parse_args(argv)
    if not args.attach and not args.track:
        print("error: --track is required unless --attach is given", file=sys.stderr)
        return 2

    # Lazy import so the pure core (and its tests) never pull auto_drive's heavier deps.
    from tools.ac_harness.auto_drive import resolve_ac_user_dir
    from tools.ac_harness.shared_memory import SharedMemoryReader

    ac_user_dir = resolve_ac_user_dir(args.ac_user_dir)
    user_ff_path = resolve_user_ff_ini(ac_user_dir)
    # Fail loud BEFORE driving if the write target is not the AC user-data cfg file.
    validate_user_ff_write_target(user_ff_path)

    def reader_factory() -> _FinalFfReader:
        return SharedMemoryReader(with_physics=True)

    sampler = _attach_and_sample if args.attach else _drive_and_sample
    samples, meta = sampler(args, reader_factory)
    print(
        f"ffb-calibrate: collected {meta.read_ok} finalFF samples "
        f"(torn={meta.torn_reads}, no_physics={meta.no_physics}, {meta.elapsed_s:.0f}s)",
        flush=True,
    )
    if not meta.offset_ok:
        print(
            f"ffb-calibrate: WARNING |finalFF| exceeded 1.0 — PHYSICS_FINAL_FF_OFFSET "
            f"({PHYSICS_FINAL_FF_OFFSET}) may be wrong on this CSP build; NOT writing",
            file=sys.stderr,
        )
        return 1
    if meta.read_ok == 0:
        print("ffb-calibrate: no finalFF samples (is AC live and driving?)", file=sys.stderr)
        return 1

    result = calibrate_from_samples(
        samples,
        car_id=args.car,
        user_ff_path=user_ff_path,
        write=not args.dry_run,
        clip_threshold=args.clip_threshold,
        target_peak=args.target_peak,
        clip_tolerance=args.clip_tolerance,
    )
    print(format_result(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    import sys as _sys
    from pathlib import Path as _Path

    _repo_root = str(_Path(__file__).resolve().parents[2])
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
