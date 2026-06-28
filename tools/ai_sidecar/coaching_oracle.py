"""CoachingOracle — a swappable source of external coaching, with a Track Titan provider.

Empirical basis (see ``docs/01_Vault/AcCopilotTrainer/03_Investigations/
track-titan-telemetry-extraction-feasibility-2026-06-27.md``): Track Titan's coaching is computed
cloud-side and rendered **only in its in-sim overlay** — it does NOT cross the local
``ws://localhost:9121`` channel (telemetry-only). So the extraction path is **screen-capture + OCR**
of the overlay, not a wire tap.

Design mirrors ``ac_harness`` (e.g. :mod:`tools.ac_harness.custom_ai`,
:mod:`tools.ac_harness.hud_capture`): the parse logic is **pure** (CI-testable on any OS — feed
OCR lines, assert a snapshot); the Windows-only capture/OCR plumbing
(:class:`TrackTitanScreenOracle`) is pragma-guarded. OCR uses the native ``Windows.Media.Ocr``
engine via a bundled PowerShell helper (``tools/ai_sidecar/tt_overlay_ocr.ps1``) run through
``subprocess`` — no third-party deps (tesseract is absent on the rig). The helper only captures +
OCRs (raw lines); **all parsing lives here**, so there is one tested implementation.

Guardrails (from the strategy ADR): this reads the operator's OWN on-screen overlay for
personal/local use. It never touches Track Titan's cloud API, never reads/handles auth tokens,
and never fabricates a ``suggested_setup_delta`` — TT's debrief is *technique* advice, so
advisories are ``cause_class="technique"`` with ``suggested_setup_delta=None``. A consumer
(harness referee / human curriculum) treats this as one oracle among several behind
:class:`CoachingOracle`, with no runtime coupling to TT.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from tools.ai_sidecar.coach_handoff import CAUSE_CLASSES

#: A lap delta / gain-loss reads as a signed 3-decimal number (e.g. ``+0.657``); tyre pressures read
#: as 1-decimal (``-9.5 psi``). Requiring exactly 3 decimals + a sane magnitude excludes the psi.
_DELTA_RE = re.compile(r"[+\-]\s?\d+\.\d{3}\b")
_LAPTIME_RE = re.compile(r"\d{1,2}:\d\d\.\d{3}")  # 1-2 minute digits (keep 10:03.123 intact)
_COMPOUND_RE = re.compile(r"Comp(?:ound)?:\s*([A-Za-z0-9]+)", re.IGNORECASE)
#: Require the real TT marker ("post-lap debrief", incl. the common OCR mangling "st-lap") so
#: ``debrief_text`` is set ONLY for a genuine post-lap debrief — never a stray "debrief" token.
_DEBRIEF_RE = re.compile(r"((?:post-?lap|st-?lap)\s+debrief.*)", re.IGNORECASE)
_MAX_PLAUSIBLE_DELTA_S = 30.0

#: focus-area keyword -> a normalized technique coaching line (TT phrases vary; we map the salient
#: cues it surfaces for AC). Order is the emission order.
_FOCUS_COACHING: dict[str, str] = {
    "power application": "Get to full power earlier on corner exit.",
    "throttle": "Apply throttle earlier and more committed on exit.",
    "brake": "Review braking points and brake release.",
    "trail": "Refine trail-braking into the apex.",
    "racing line": "Tighten the racing line.",
    "apex": "Hit the apex more precisely.",
    "earlier": "Bring the flagged input earlier.",
    "later": "Delay the flagged input.",
}


@dataclass(frozen=True)
class CoachingSnapshot:
    """One read of an external coach's current advice (provider-agnostic)."""

    source: str
    suggestion_state: str  # "post_lap_debrief" | "awaiting_valid_lap" | "unknown"
    debrief_text: str | None = None
    focus_areas: list[str] = field(default_factory=list)
    delta_gainloss_s: float | None = None
    lap_times_s: list[str] = field(default_factory=list)
    tyre_compound: str | None = None
    advisories: list[dict[str, Any]] = field(default_factory=list)
    captured_utc: str | None = None
    raw_lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OverlayLayout:
    """Normalized crop of the overlay's debrief/suggestion widget, keyed by screen size.

    Fractions are (x, y, w, h) of the primary screen; ``upscale`` enlarges the crop before OCR
    (stylized overlay text OCRs far better upscaled — full-screen OCR garbles it). Calibrate a new
    entry per resolution; the POC was verified at 3440x1440.
    """

    name: str
    screen_w: int
    screen_h: int
    debrief_crop: tuple[float, float, float, float]
    upscale: float = 3.0


#: Live-verified calibration (this session, AG_PC). Add rows for other resolutions as needed.
DEFAULT_LAYOUTS: dict[tuple[int, int], OverlayLayout] = {
    (3440, 1440): OverlayLayout(
        name="ag_pc_3440x1440",
        screen_w=3440,
        screen_h=1440,
        debrief_crop=(0.385, 0.020, 0.235, 0.175),
        upscale=3.0,
    ),
}

#: Crops are fractional, so an uncalibrated resolution still gets a usable (if approximate) crop.
FALLBACK_LAYOUT = OverlayLayout(
    name="generic", screen_w=0, screen_h=0, debrief_crop=(0.385, 0.020, 0.235, 0.175), upscale=3.0
)


def select_layout(screen_w: int, screen_h: int) -> OverlayLayout:
    """Calibrated layout for an exact screen size, else the generic fractional fallback. Pure."""
    return DEFAULT_LAYOUTS.get((screen_w, screen_h), FALLBACK_LAYOUT)


def _coerce_lines(value: object) -> list[str]:
    """Flatten one level + stringify OCR-helper output (defensive vs nested/scalar/None JSON)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return [str(value)]
    out: list[str] = []
    for item in value:
        if isinstance(item, list):
            out.extend(str(s) for s in item)
        elif item is not None:
            out.append(str(item))
    return out


def _extract_debrief(lines: list[str]) -> str | None:
    """Find a post-lap debrief bounded to a 2-line window (marker line + its wrap), so the greedy
    ``.*`` captures the debrief — not trailing HUD text from a full-screen fallback."""
    # Anchor on the line that actually contains the marker, then include its wrap line.
    for i, ln in enumerate(lines):
        if _DEBRIEF_RE.search(ln):
            m = _DEBRIEF_RE.search(" ".join(lines[i : i + 2]))
            if m:
                return m.group(1).strip()
    # Fallback: the marker is split across two OCR lines.
    for i in range(len(lines) - 1):
        m = _DEBRIEF_RE.search(" ".join(lines[i : i + 2]))
        if m:
            return m.group(1).strip()
    return None


def parse_overlay_text(
    full_lines: list[str],
    debrief_lines: list[str] | None = None,
    *,
    source: str = "track_titan",
    captured_utc: str | None = None,
) -> CoachingSnapshot:
    """Parse OCR'd overlay lines into a :class:`CoachingSnapshot`. Pure — no capture, no OS calls.

    ``full_lines`` are the whole-screen OCR; ``debrief_lines`` (optional) are the cleaner OCR of the
    upscaled debrief crop, preferred for the debrief text. Robust to OCR mangling.
    """
    debrief_lines = debrief_lines or []
    full_join = " ".join(full_lines)

    delta: float | None = None
    for m in _DELTA_RE.finditer(full_join):
        val = float(m.group(0).replace(" ", ""))
        if abs(val) < _MAX_PLAUSIBLE_DELTA_S:
            delta = val
            break

    lap_times = _LAPTIME_RE.findall(full_join)
    comp_m = _COMPOUND_RE.search(full_join)
    tyre_compound = comp_m.group(1) if comp_m else None

    # Prefer the clean upscaled crop; fall back to full screen (both bounded to a 2-line window).
    debrief_text = _extract_debrief(debrief_lines) or _extract_debrief(full_lines)

    # Focus areas are only meaningful inside an actual debrief — derive them from the debrief text,
    # not the whole overlay, so a live HUD label (e.g. "BRAKE"/"THROTTLE") never mints advice.
    focus_src = (debrief_text or "").lower()
    focus_areas = [kw for kw in _FOCUS_COACHING if kw in focus_src]

    if debrief_text:
        suggestion_state = "post_lap_debrief"
    elif "reference will appear" in (full_join + " " + " ".join(debrief_lines)).lower():
        # include the crop OCR — the full-screen pass may have failed while the crop succeeded.
        suggestion_state = "awaiting_valid_lap"
    else:
        suggestion_state = "unknown"

    snap = CoachingSnapshot(
        source=source,
        suggestion_state=suggestion_state,
        debrief_text=debrief_text,
        focus_areas=focus_areas,
        delta_gainloss_s=delta,
        lap_times_s=lap_times,
        tyre_compound=tyre_compound,
        captured_utc=captured_utc,
        raw_lines=list(full_lines),
    )
    return CoachingSnapshot(**{**snap.as_dict(), "advisories": debrief_to_advisories(snap)})


def debrief_to_advisories(snap: CoachingSnapshot) -> list[dict[str, Any]]:
    """Map a TT debrief snapshot to coach_handoff-compatible advisories (technique-only).

    Reuses the :data:`CAUSE_CLASSES` vocabulary. ``suggested_setup_delta`` is ALWAYS ``None`` — TT's
    overlay debrief is driver-technique advice; we never fabricate a setup change from it.
    """
    assert "technique" in CAUSE_CLASSES  # vocabulary contract with coach_handoff
    if not snap.debrief_text:
        return []  # only a real post-lap debrief yields advice (never stray live-HUD labels)
    advisories: list[dict[str, Any]] = []
    for kw in snap.focus_areas:
        advisories.append(
            {
                "source": snap.source,
                "cause_class": "technique",
                "confidence": 0.5,  # external OCR'd advice — modest, not a measured verdict
                "advisory": True,
                "coaching": _FOCUS_COACHING[kw],
                "suggested_setup_delta": None,
            }
        )
    if not advisories and snap.debrief_text:
        advisories.append(
            {
                "source": snap.source,
                "cause_class": "technique",
                "confidence": 0.4,
                "advisory": True,
                "coaching": snap.debrief_text,
                "suggested_setup_delta": None,
            }
        )
    return advisories


class CoachingOracle(ABC):
    """A swappable source of coaching.

    Implementations: our own coach, Track Titan (overlay screen OCR), and future providers.
    """

    @abstractmethod
    def get_coaching(self) -> CoachingSnapshot | None:
        """Return the current coaching snapshot, or None when unavailable."""
        raise NotImplementedError


def _primary_screen_size() -> tuple[int, int]:  # pragma: no cover - Windows-only
    """Primary screen (width, height) via GDI; (0, 0) off-Windows so select_layout falls back."""
    if sys.platform != "win32":
        return (0, 0)
    import ctypes

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - DPI awareness is best-effort
        pass
    return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


class TrackTitanScreenOracle(CoachingOracle):  # pragma: no cover - Windows/rig-only plumbing
    """Reads Track Titan's on-screen overlay via screen-capture + native Windows OCR.

    Shells out to ``tools/ai_sidecar/tt_overlay_ocr.ps1`` (capture + crop/upscale +
    ``Windows.Media.Ocr``), emitting ``{"full_lines": [...], "debrief_lines": [...]}``; all
    parsing is done here by the pure :func:`parse_overlay_text`. Windows-only; returns None
    off-Windows or on any helper failure.
    """

    def __init__(
        self,
        *,
        ps_helper: str | None = None,
        layout: OverlayLayout | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.ps_helper = ps_helper
        self.layout = layout
        self.timeout_s = timeout_s

    def get_coaching(self) -> CoachingSnapshot | None:
        if sys.platform != "win32":
            return None
        from datetime import datetime

        layout = self.layout or select_layout(*_primary_screen_size())
        # Resolve the helper next to THIS module so it works regardless of cwd / install location.
        helper = self.ps_helper or str(Path(__file__).with_name("tt_overlay_ocr.ps1"))
        args = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            helper,
        ]
        if layout is not None:
            fx, fy, fw, fh = layout.debrief_crop
            args += [
                "-CropX",
                str(fx),
                "-CropY",
                str(fy),
                "-CropW",
                str(fw),
                "-CropH",
                str(fh),
                "-Scale",
                str(layout.upscale),
            ]
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=self.timeout_s, check=True
            )
            data = json.loads(proc.stdout)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return parse_overlay_text(
            _coerce_lines(data.get("full_lines")),
            _coerce_lines(data.get("debrief_lines")),
            captured_utc=datetime.now(UTC).isoformat(),
        )
