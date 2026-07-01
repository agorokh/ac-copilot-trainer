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

# States that are healthy-but-quiescent (nothing wrong, nothing lit).
_IDLE_STATES = {"absent", "skipped", "loopback", "available", "stopped"}
# States that are in-progress / attention-but-not-failure.
_WARN_STATES = {"waiting", "initializing", "starting", "unavailable", "unknown"}


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
