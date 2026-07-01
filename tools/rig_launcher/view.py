"""Racing Atelier themed Tk view for the Game Point launcher (epic #432, Part B).

``build_launcher_view`` renders the carbon/brass status panel that maps 1:1 onto
``GamePointStatus`` (sidecar / screen / hotspot / voice / simhub). It owns
*presentation only*: every behaviour (start, refresh, open logs/settings, setup
diff) is passed in via ``actions`` and the caller drives redraws with
``LauncherView.update(status)``. Keeping the view free of supervisor/polling
logic preserves ``app.run_gui``'s Tk-init fallback contract and lets the palette
be unit-tested through :mod:`tools.rig_launcher.theme` without a display.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import font as tkfont

from tools.rig_launcher import theme
from tools.rig_launcher.supervisor import GamePointStatus, ProbeResult

#: (display label, GamePointStatus attribute) for each status row, top to bottom.
_ROWS: tuple[tuple[str, str], ...] = (
    ("Sidecar", "sidecar"),
    ("Screen", "screen"),
    ("Hotspot", "hotspot"),
    ("Voice", "voice"),
    ("SimHub", "simhub"),
)

#: (label, action key, is-primary) for each footer button.
_BUTTONS: tuple[tuple[str, str, bool], ...] = (
    ("▶  Start", "start", True),
    ("Refresh", "refresh", False),
    ("Logs", "logs", False),
    ("Settings", "settings", False),
    ("Setup Diff", "setup_diff", False),
)

_ARM = 15  # px arm length of the brass corner brackets


class LauncherView:
    """The carbon/brass launcher panel, bound to :class:`GamePointStatus`."""

    def __init__(
        self,
        root: tk.Misc,
        *,
        actions: Mapping[str, Callable[[], None]],
        status_path: str,
    ) -> None:
        self._root = root
        families = set(tkfont.families(root))
        self._f_disp = theme.resolve_font(theme.FONT_DISPLAY, families)
        self._f_read = theme.resolve_font(theme.FONT_READ, families)
        self._f_mono = theme.resolve_font(theme.FONT_MONO, families)
        self._rows: dict[str, dict[str, object]] = {}

        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.configure(bg=theme.CARBON)

        panel = tk.Frame(
            root,
            bg=theme.GRAPHITE,
            highlightbackground=theme.EDGE,
            highlightcolor=theme.EDGE,
            highlightthickness=1,
            bd=0,
        )
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        self._build_header(panel)
        tk.Frame(panel, bg=theme.LINE, height=1).pack(fill="x")
        self._build_summary(panel)

        body = tk.Frame(panel, bg=theme.GRAPHITE)
        body.pack(fill="both", expand=True, padx=16, pady=(2, 8))
        for label, key in _ROWS:
            self._rows[key] = self._build_row(body, label)

        self._build_buttons(panel, actions)
        tk.Label(
            panel,
            text=f"status.json · {status_path}",
            bg=theme.GRAPHITE,
            fg=theme.FAINT,
            font=(self._f_mono, 8),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 10))

        self._add_corner_brackets(panel)

    # -- construction helpers -------------------------------------------------

    def _add_corner_brackets(self, panel: tk.Frame) -> None:
        """Overlay four brass L-brackets at the panel corners (the house mark)."""
        corners = {
            "nw": ((0.0, 0.0), [(0, 0, _ARM, 0), (0, 0, 0, _ARM)]),
            "ne": ((1.0, 0.0), [(15, 0, 15 - _ARM, 0), (15, 0, 15, _ARM)]),
            "sw": ((0.0, 1.0), [(0, 15, _ARM, 15), (0, 15, 0, 15 - _ARM)]),
            "se": ((1.0, 1.0), [(15, 15, 15 - _ARM, 15), (15, 15, 15, 15 - _ARM)]),
        }
        for anchor, ((relx, rely), segments) in corners.items():
            canvas = tk.Canvas(
                panel, width=16, height=16, bg=theme.GRAPHITE, highlightthickness=0, bd=0
            )
            for x0, y0, x1, y1 in segments:
                canvas.create_line(x0, y0, x1, y1, fill=theme.BRASS, width=2)
            canvas.place(relx=relx, rely=rely, anchor=anchor)

    def _build_header(self, panel: tk.Frame) -> None:
        header = tk.Frame(panel, bg=theme.GRAPHITE)
        header.pack(fill="x", padx=16, pady=(14, 10))
        tab = tk.Canvas(header, width=6, height=18, bg=theme.BRASS, highlightthickness=0, bd=0)
        tab.pack(side="left")
        tk.Label(
            header,
            text="GAME POINT",
            bg=theme.GRAPHITE,
            fg=theme.CHALK,
            font=(self._f_disp, 15, "bold"),
        ).pack(side="left", padx=(10, 0))
        tk.Label(
            header,
            text=":8765",
            bg=theme.GRAPHITE,
            fg=theme.DIM,
            font=(self._f_mono, 10),
        ).pack(side="right")

    def _build_summary(self, panel: tk.Frame) -> None:
        row = tk.Frame(panel, bg=theme.GRAPHITE)
        row.pack(fill="x", padx=16, pady=(12, 10))
        dot = tk.Canvas(row, width=12, height=12, bg=theme.GRAPHITE, highlightthickness=0, bd=0)
        oval = dot.create_oval(1, 1, 11, 11, fill=theme.CLEAR, outline="")
        dot.pack(side="left")
        text = tk.Label(
            row, text="Ready to drive", bg=theme.GRAPHITE, fg=theme.CHALK, font=(self._f_read, 13)
        )
        text.pack(side="left", padx=(10, 0))
        self._summary_dot = dot
        self._summary_oval = oval
        self._summary_text = text

    def _build_row(self, body: tk.Frame, label: str) -> dict[str, object]:
        row = tk.Frame(body, bg=theme.GRAPHITE)
        row.pack(fill="x", pady=3)
        tk.Label(
            row,
            text=label.upper(),
            bg=theme.GRAPHITE,
            fg=theme.MUTE,
            font=(self._f_disp, 10),
            width=9,
            anchor="w",
        ).pack(side="left")
        dot = tk.Canvas(row, width=9, height=9, bg=theme.GRAPHITE, highlightthickness=0, bd=0)
        oval = dot.create_oval(1, 1, 8, 8, fill=theme.DIM, outline="")
        dot.pack(side="left", padx=(2, 8))
        state = tk.Label(
            row,
            text="—",
            bg=theme.GRAPHITE,
            fg=theme.CHALK,
            font=(self._f_disp, 11, "bold"),
            width=12,
            anchor="w",
        )
        state.pack(side="left")
        detail = tk.Label(
            row, text="", bg=theme.GRAPHITE, fg=theme.DIM, font=(self._f_mono, 9), anchor="e"
        )
        detail.pack(side="right")
        return {"dot": dot, "oval": oval, "state": state, "detail": detail}

    def _build_buttons(self, panel: tk.Frame, actions: Mapping[str, Callable[[], None]]) -> None:
        row = tk.Frame(panel, bg=theme.GRAPHITE)
        row.pack(fill="x", padx=16, pady=(6, 12))
        for index, (label, key, primary) in enumerate(_BUTTONS):
            button = tk.Button(
                row,
                text=label,
                command=actions.get(key),
                cursor="hand2",
                relief="flat",
                bd=0,
                padx=10,
                pady=7,
                font=(self._f_disp, 10, "bold"),
                bg=theme.BRASS if primary else theme.RAISE,
                fg=theme.BRASS_INK if primary else theme.CHALK,
                activebackground=theme.LIFT if primary else theme.SLAB,
                activeforeground=theme.BRASS_INK if primary else theme.CHALK,
                highlightthickness=0,
            )
            button.pack(side="left", expand=True, fill="x", padx=(0 if index == 0 else 6, 0))

    # -- refresh --------------------------------------------------------------

    def update(self, status: GamePointStatus) -> None:
        """Repaint the summary and every status row from a fresh snapshot."""
        overall_ok = status.ok
        self._summary_dot.itemconfigure(
            self._summary_oval, fill=theme.CLEAR if overall_ok else theme.BRAKE
        )
        self._summary_text.configure(text="Ready to drive" if overall_ok else "Needs attention")
        for key, widgets in self._rows.items():
            probe = getattr(status, key, None)
            if not isinstance(probe, ProbeResult):
                continue
            color = theme.color_for_tone(theme.tone_for(probe.ok, probe.state))
            dot = widgets["dot"]
            assert isinstance(dot, tk.Canvas)
            dot.itemconfigure(widgets["oval"], fill=color)
            state = widgets["state"]
            assert isinstance(state, tk.Label)
            state.configure(text=probe.state, fg=color)
            detail = widgets["detail"]
            assert isinstance(detail, tk.Label)
            detail.configure(text=probe.detail or "")


def build_launcher_view(
    root: tk.Misc,
    *,
    actions: Mapping[str, Callable[[], None]],
    status_path: str,
) -> LauncherView:
    """Construct the themed launcher panel inside ``root`` and return its handle."""
    return LauncherView(root, actions=actions, status_path=status_path)
