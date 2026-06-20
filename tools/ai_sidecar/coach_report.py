"""Render a pro-engineer coaching debrief from the attribution layer, + a CLI.

Ties :mod:`setup_model`, :mod:`lap_dynamics`, and :mod:`corner_attribution` into a human-readable
debrief: the setup at a glance, the aero-vs-mechanical balance verdict, and a per-corner "where you
lost time and whether it's setup or technique" breakdown.

CLI::

    python -m tools.ai_sidecar.coach_report LAP.json [--reference REF.json] [--setup SETUP.ini]
                                            [--grip-ceiling-g 1.5]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.ai_sidecar.corner_attribution import (
    BalanceFinding,
    CornerCoaching,
    analyze_balance,
    coach_lap,
    compare_laps,
)
from tools.ai_sidecar.lap_dynamics import corner_signatures, lap_trace_from_archive, segment_corners
from tools.ai_sidecar.setup_model import CarSetup, from_lap_archive, load_setup_file


def format_debrief(
    corners: list[CornerCoaching],
    balance: BalanceFinding | None = None,
    setup: CarSetup | None = None,
    *,
    title: str = "Coaching debrief",
) -> str:
    """Render the full debrief as text."""
    out: list[str] = [f"=== {title} ==="]
    if setup is not None and setup.tunables():
        out.append("\nSetup at a glance:")
        out.extend("  " + line for line in setup.human_summary())
    if balance is not None:
        out.append("\nBalance (aero vs mechanical):")
        out.append(f"  verdict: {balance.verdict}"
                   + (f" → {balance.lever_class} levers" if balance.lever_class else ""))
        out.append(f"  {balance.coaching}")
        gu = []
        if balance.low_band_grip_used is not None:
            gu.append(f"low-speed grip used {balance.low_band_grip_used:.0%}")
        if balance.high_band_grip_used is not None:
            gu.append(f"high-speed grip used {balance.high_band_grip_used:.0%}")
        if gu:
            out.append("  (" + "; ".join(gu) + ")")
        out.append(f"  caveat: {balance.caveat}")
    lost = [c for c in corners if c.delta_s is not None and c.delta_s > 0.03]
    total_lost = sum(c.delta_s for c in lost if c.delta_s)
    out.append(f"\nPer-corner ({len(corners)} corners"
               + (f", {len(lost)} losing time, {total_lost:.2f}s total" if lost else "") + "):")
    for c in corners:
        out.append("  " + c.headline)
        for a in c.attributions[:2]:
            kind = "SETUP" if a.setup_causes and not a.technique_causes else (
                "TECHNIQUE" if a.technique_causes and not a.setup_causes else "SETUP+TECH")
            flag = " [suspected]" if a.advisory else ""
            out.append(f"      - [{kind}{flag}] {a.symptom} (conf {a.confidence:.0%})")
    return "\n".join(out)


def _load_archive(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_debrief(
    lap_archive: dict,
    *,
    reference_archive: dict | None = None,
    setup: CarSetup | None = None,
    grip_ceiling_g: float | None = None,
) -> str:
    """End-to-end: archive(s) → debrief text."""
    lap = lap_trace_from_archive(lap_archive)
    setup = setup or from_lap_archive(lap_archive)
    ref = lap_trace_from_archive(reference_archive) if reference_archive else None
    report = coach_lap(lap, setup, reference=ref, grip_ceiling_g=grip_ceiling_g)
    sigs = corner_signatures(lap, segment_corners(lap))
    deltas = compare_laps(lap, ref) if ref is not None else None
    balance = analyze_balance(lap, sigs, deltas=deltas, grip_ceiling_g=grip_ceiling_g)
    return format_debrief(report, balance, setup,
                          title=f"Coaching debrief — {lap.car_id or '?'} @ {lap.track_id or '?'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Per-corner setup-vs-technique coaching debrief")
    p.add_argument("lap", help="lap archive JSON to coach")
    p.add_argument("--reference", help="reference lap archive JSON (e.g. a faster lap)")
    p.add_argument("--setup", help="setup .ini to use instead of the lap's snapshot")
    p.add_argument("--grip-ceiling-g", type=float, default=None,
                   help="lateral grip ceiling in g (separates grip-limited from technique)")
    args = p.parse_args(argv)
    setup = load_setup_file(args.setup) if args.setup else None
    ref = _load_archive(args.reference) if args.reference else None
    print(build_debrief(_load_archive(args.lap), reference_archive=ref, setup=setup,
                        grip_ceiling_g=args.grip_ceiling_g))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
