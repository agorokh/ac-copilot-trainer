"""Racing Atelier design tokens for the Game Point launcher (epic #432, Part B).

The single source of truth for the palette is the design package:
``docs/10_Development/design/racing-atelier/project/tokens/colors.css``.
``tests/test_rig_launcher_theme.py`` parses that CSS and asserts the hex values
below match it, so this adapter cannot silently drift from the design of record
(fleet pitfall: *redundant-code-drift* — do not hand-copy tokens into N runtimes
without a conformance check binding them back to one source).

Only the hex tokens are mirrored here; the CSS hairline tokens (``--line`` etc.)
are ``rgba()`` overlays that Tk cannot render, so ``LINE`` is a solid-hex
approximation and is intentionally *not* part of the conformance set.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps theme display/runtime free
    from tools.rig_launcher.supervisor import GamePointStatus

# --- Carbon ground (mirrors colors.css :root) ---
CARBON = "#0B0C0D"
GRAPHITE = "#141618"
SLAB = "#191C1F"
RAISE = "#20242A"
EDGE = "#2A2F35"
BLACK = "#000000"

# --- Ink ---
CHALK = "#EEF1F3"
MUTE = "#9BA1A8"
DIM = "#79808A"
FAINT = "#4A4E55"

# --- Brass: house mark + structure ---
BRASS = "#C8983E"
BRASS_INK = "#0B0C0D"

# --- Signal fields (flat, matte; state only) ---
BRAKE = "#F23B2C"
LIFT = "#F4A52C"
CLEAR = "#2FBE6E"
DATA = "#49B6C9"

# Tk-only approximation of the rgba(255,255,255,0.07) hairline over graphite.
# Not part of the conformance set (the CSS value is rgba, not hex).
LINE = "#22262B"

# Tk-only approximation of the stronger --line-2 rgba(255,255,255,0.16) hairline
# over graphite — the secondary-button border. Not in the conformance set.
LINE_2 = "#3A3F46"

# Primary-button press state. The design darkens the brass field with a press
# opacity; Tk has no opacity, so this is a pre-multiplied darker brass. It is
# deliberately NOT the amber LIFT signal (state colors never double as chrome).
BRASS_PRESS = "#A87F33"

#: hex tokens validated against colors.css by the conformance test.
TOKENS: dict[str, str] = {
    "carbon": CARBON,
    "graphite": GRAPHITE,
    "slab": SLAB,
    "raise": RAISE,
    "edge": EDGE,
    "black": BLACK,
    "chalk": CHALK,
    "mute": MUTE,
    "dim": DIM,
    "faint": FAINT,
    "brass": BRASS,
    "brass-ink": BRASS_INK,
    "brake": BRAKE,
    "lift": LIFT,
    "clear": CLEAR,
    "data": DATA,
}

# Font preference ladders: the bundled design faces first, then faces that ship
# with Windows (Bahnschrift is condensed like Saira SC; Consolas is the mono
# default), so the launcher looks on-brand even before the design fonts install.
FONT_DISPLAY: tuple[str, ...] = (
    # Real name-table family of the bundled SemiCondensed statics loaded by
    # tools.rig_launcher.fonts (note: no space inside "SemiCondensed").
    "Saira SemiCondensed",
    # Family name Windows uses when the face is system-installed from Google.
    "Saira Semi Condensed",
    "Bahnschrift",
    "Segoe UI Semibold",
    "Segoe UI",
)
FONT_READ: tuple[str, ...] = ("Saira", "Segoe UI", "Helvetica")
FONT_MONO: tuple[str, ...] = ("Spline Sans Mono", "Cascadia Mono", "Consolas", "Courier New")

#: state -> signal tone. ``idle`` is the demoted (dim) tone for absent/skipped rows.
TONE_COLORS: dict[str, str] = {
    "clear": CLEAR,
    "lift": LIFT,
    "brake": BRAKE,
    "idle": DIM,
}

#: StatusField ink-on-fill per tone (mirrors the design StatusField TONES ink).
FIELD_INK: dict[str, str] = {
    "clear": "#06140C",
    "brake": CHALK,
}

# States that are healthy-but-quiescent (nothing wrong, nothing lit).
_IDLE_STATES = {"absent", "skipped", "loopback", "available", "stopped"}
# States that are in-progress / attention-but-not-failure. "waiting" is NOT in
# this set: a missing screen peer is a failure the driver must fix (the render
# shows SCREEN WAITING in brake red), not progress.
_WARN_STATES = {"initializing", "starting", "unavailable", "unknown"}


def tone_for(ok: bool, state: str) -> str:
    """Map a ``ProbeResult`` (ok, state) onto a Racing Atelier signal tone.

    ``clear`` (green) = healthy/lit, ``lift`` (amber) = in-progress/caution,
    ``brake`` (red) = failure, ``idle`` (dim) = present-but-quiescent.
    """
    normalized = (state or "").strip().lower()
    if normalized in _IDLE_STATES:
        return "idle"
    if ok:
        # A healthy row that is not merely idle reads as lit unless it is a
        # known in-progress state (e.g. sidecar "starting").
        return "lift" if normalized in _WARN_STATES else "clear"
    return "lift" if normalized in _WARN_STATES else "brake"


def color_for_tone(tone: str) -> str:
    """Return the hex for a tone, defaulting to the demoted dim ink."""
    return TONE_COLORS.get(tone, DIM)


#: sidecar states that mean "no server on the port yet" (ui-kit recovery state).
_SIDECAR_DOWN_STATES = {"stopped", "unreachable"}


def summary_for(status: GamePointStatus, port: int = 8765) -> tuple[str, str, str]:
    """Map a status snapshot onto the summary StatusField chip + mono caption.

    Returns ``(text, tone, caption)`` — the uppercase chip word, the signal tone
    keying :data:`TONE_COLORS` / :data:`FIELD_INK`, and the mono caption beside
    the chip. Mirrors the design ui-kit's two states: ready ("Ready to drive" on
    the CLEAR field) and recovery ("Press start" on the BRAKE field). Total: it
    always returns a caption, deriving it from the first failing row when the
    sidecar itself is up.
    """
    if status.ok:
        return ("READY TO DRIVE", "clear", "sidecar · screen live")
    # A failing preflight check outranks the port-down copy: pressing Start
    # cannot succeed until the blocker is cleared, so the caption must say
    # what is actually wrong (PR #445 review).
    blocker = next(
        (chk for chk in status.checks if not chk.ok and (chk.detail or chk.state)),
        None,
    )
    if blocker is not None:
        return ("PRESS START", "brake", blocker.detail or blocker.state)
    if (status.sidecar.state or "").strip().lower() in _SIDECAR_DOWN_STATES:
        return ("PRESS START", "brake", f"nothing on port {port} yet")
    if not status.resilient.ok:
        return (
            "PRESS STABLE AC",
            "brake",
            status.resilient.detail or status.resilient.state or "AC session needs attention",
        )
    rows = (status.sidecar, status.screen, status.voice, status.simhub, status.tablet)
    caption = next(
        (row.detail or row.state for row in rows if not row.ok and (row.detail or row.state)),
        "needs attention",
    )
    return ("PRESS START", "brake", caption)


def resolve_font(preferences: Iterable[str], available: Iterable[str]) -> str:
    """Return the first preferred family present in ``available``.

    Falls back to the last preference (a guaranteed-safe generic) when none of
    the design faces are installed, so callers always get a usable family name.
    """
    prefs = list(preferences)
    available_lower = {name.lower() for name in available}
    for family in prefs:
        if family.lower() in available_lower:
            return family
    return prefs[-1]
