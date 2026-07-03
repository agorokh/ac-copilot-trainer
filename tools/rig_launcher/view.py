"""Racing Atelier themed Tk view for the Game Point launcher (epic #432, Part B).

``build_launcher_view`` renders the carbon/brass status panel that maps 1:1 onto
``GamePointStatus`` (sidecar / screen / voice / simhub). It owns
*presentation only*: every behaviour (start, refresh, open logs/settings, setup
diff) is passed in via ``actions`` and the caller drives redraws with
``LauncherView.update(status)``. Keeping the view free of supervisor/polling
logic preserves ``app.run_gui``'s Tk-init fallback contract and lets the palette
be unit-tested through :mod:`tools.rig_launcher.theme` without a display.

Tk waiver: Tk text has no letter-spacing control, so the design's 0.04-0.12em
caps tracking is not reproduced. Do NOT fake it by injecting hair-space
characters — that corrupts copy/paste, accessibility, and text measurement.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import font as tkfont

from tools.rig_launcher import theme
from tools.rig_launcher.fonts import load_private_fonts
from tools.rig_launcher.supervisor import GamePointStatus, ProbeResult

#: (display label, GamePointStatus attribute) for each status row, top to bottom.
_ROWS: tuple[tuple[str, str], ...] = (
    ("Sidecar", "sidecar"),
    ("Screen", "screen"),
    ("Voice", "voice"),
    ("SimHub", "simhub"),
)

#: (label, action key, is-primary) for each footer button. Labels are uppercase
#: per the design Button treatment; Setup Diff is functional substance the
#: design mock omits, kept as a fifth column.
_BUTTONS: tuple[tuple[str, str, bool], ...] = (
    ("▶ START", "start", True),
    ("REFRESH", "refresh", False),
    ("LOGS", "logs", False),
    ("SETTINGS", "settings", False),
    ("SETUP DIFF", "setup_diff", False),
)

#: grid column weights: Start is 1.5x each secondary action (design
#: grid-template-columns 1.5fr 1fr 1fr 1fr, extended with the Setup Diff column).
_BUTTON_WEIGHTS: tuple[int, ...] = (3, 2, 2, 2, 2)

_ARM = 15  # px arm length of the brass corner brackets


class LauncherView:
    """The carbon/brass launcher panel, bound to :class:`GamePointStatus`."""

    def __init__(
        self,
        root: tk.Misc,
        *,
        actions: Mapping[str, Callable[[], None]],
        status_path: str,
        port: int = 8765,
        simhub_autostart: bool = False,
    ) -> None:
        self._root = root
        self._port = port
        load_private_fonts()  # register design faces before Tk enumerates families
        families = set(tkfont.families(root))
        self._f_disp = theme.resolve_font(theme.FONT_DISPLAY, families)
        self._f_read = theme.resolve_font(theme.FONT_READ, families)
        self._f_mono = theme.resolve_font(theme.FONT_MONO, families)
        self._rows: dict[str, dict[str, object]] = {}

        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.configure(bg=theme.CARBON)

        # Debug footer lives on the carbon ground *below* the card — the design
        # card carries no path line, but the operator info must survive.
        tk.Label(
            root,
            text=status_path,
            bg=theme.CARBON,
            fg=theme.FAINT,
            font=(self._f_mono, 8),
            anchor="w",
        ).pack(side="bottom", fill="x", padx=18, pady=(0, 6))

        panel = tk.Frame(
            root,
            bg=theme.GRAPHITE,
            highlightbackground=theme.EDGE,
            highlightcolor=theme.EDGE,
            highlightthickness=1,
            bd=0,
        )
        panel.pack(fill="both", expand=True, padx=16, pady=(16, 6))

        self._build_header(panel)
        tk.Frame(panel, bg=theme.LINE, height=1).pack(fill="x")
        self._build_summary(panel)

        body = tk.Frame(panel, bg=theme.GRAPHITE)
        body.pack(fill="both", expand=True, padx=16, pady=(2, 8))
        for index, (label, key) in enumerate(_ROWS):
            self._rows[key] = self._build_row(body, label, last=index == len(_ROWS) - 1)

        # Optional SimHub auto-start toggle, wired only when the caller supplies
        # the action (app.run_gui). Keeps the view presentation-only otherwise.
        self._simhub_var: tk.BooleanVar | None = None
        toggle_simhub = actions.get("toggle_simhub")
        if toggle_simhub is not None:
            self._build_simhub_toggle(body, toggle_simhub, simhub_autostart)

        self._build_buttons(panel, actions)
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
        tab = tk.Canvas(header, width=6, height=16, bg=theme.BRASS, highlightthickness=0, bd=0)
        tab.pack(side="left")
        tk.Label(
            header,
            text="GAME POINT",
            bg=theme.GRAPHITE,
            fg=theme.CHALK,
            font=(self._f_disp, 14, "bold"),
        ).pack(side="left", padx=(12, 0))
        tk.Label(
            header,
            text=f":{self._port}",
            bg=theme.GRAPHITE,
            fg=theme.DIM,
            font=(self._f_mono, 10),
        ).pack(side="right")

    def _build_summary(self, panel: tk.Frame) -> None:
        row = tk.Frame(panel, bg=theme.GRAPHITE)
        row.pack(fill="x", padx=16, pady=(14, 10))
        field = tk.Label(
            row,
            text="READY TO DRIVE",
            bg=theme.CLEAR,
            fg=theme.FIELD_INK["clear"],
            font=(self._f_disp, 12, "bold"),
            padx=9,
            pady=3,
        )
        field.pack(side="left")
        caption = tk.Label(
            row,
            text="sidecar · screen live",
            bg=theme.GRAPHITE,
            fg=theme.MUTE,
            font=(self._f_mono, 11),
        )
        caption.pack(side="left", padx=(12, 0))
        self._summary_field = field
        self._summary_caption = caption

    def _build_row(self, body: tk.Frame, label: str, *, last: bool = False) -> dict[str, object]:
        row = tk.Frame(body, bg=theme.GRAPHITE)
        row.pack(fill="x", pady=(8, 8))
        tk.Label(
            row,
            text=label.upper(),
            bg=theme.GRAPHITE,
            fg=theme.MUTE,
            font=(self._f_disp, 12),
            width=10,
            anchor="w",
        ).pack(side="left")
        state = tk.Label(
            row,
            text="—",
            bg=theme.GRAPHITE,
            fg=theme.CHALK,
            font=(self._f_disp, 13, "bold"),
            width=12,
            anchor="w",
        )
        state.pack(side="left")
        detail = tk.Label(
            row, text="", bg=theme.GRAPHITE, fg=theme.DIM, font=(self._f_mono, 11), anchor="e"
        )
        detail.pack(side="right")
        if not last:
            tk.Frame(body, bg=theme.LINE, height=1).pack(fill="x")
        return {"state": state, "detail": detail}

    def _build_buttons(self, panel: tk.Frame, actions: Mapping[str, Callable[[], None]]) -> None:
        row = tk.Frame(panel, bg=theme.GRAPHITE)
        row.pack(fill="x", padx=16, pady=(10, 14))
        for column, weight in enumerate(_BUTTON_WEIGHTS):
            row.columnconfigure(column, weight=weight, uniform="actions")
        for column, (label, key, primary) in enumerate(_BUTTONS):
            button = tk.Button(
                row,
                text=label,
                command=actions[key],
                cursor="hand2",
                relief="flat",
                bd=0,
                padx=10,
                pady=11,  # ~40px min height with the 10pt display face
                font=(self._f_disp, 10, "bold"),
                bg=theme.BRASS if primary else theme.RAISE,
                fg=theme.BRASS_INK if primary else theme.CHALK,
                # Press state: darker brass (press-opacity approximation), never
                # the amber LIFT signal; secondaries sink to the slab.
                activebackground=theme.BRASS_PRESS if primary else theme.SLAB,
                activeforeground=theme.BRASS_INK if primary else theme.CHALK,
                highlightthickness=0 if primary else 1,
                highlightbackground=theme.GRAPHITE if primary else theme.LINE_2,
            )
            button.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 9, 0))

    def _build_simhub_toggle(
        self,
        parent: tk.Frame,
        command: Callable[[], None],
        initial: bool,
    ) -> None:
        """Render the SimHub auto-start toggle bound to the persisted setting.

        A themed Checkbutton so "start SimHub with the launcher" is reachable
        from the UI, not only by hand-editing settings.json. ``command`` flips and
        persists the preference (see ``app.run_gui``); the var seeds from the
        launch-time config so it reflects the current setting on open.
        """
        var = tk.BooleanVar(master=self._root, value=bool(initial))
        self._simhub_var = var
        row = tk.Frame(parent, bg=theme.GRAPHITE)
        row.pack(fill="x", pady=(6, 2))
        tk.Checkbutton(
            row,
            text="AUTO-START SIMHUB",
            variable=var,
            command=command,
            onvalue=True,
            offvalue=False,
            bg=theme.GRAPHITE,
            fg=theme.MUTE,
            activebackground=theme.GRAPHITE,
            activeforeground=theme.CHALK,
            selectcolor=theme.SLAB,
            font=(self._f_disp, 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        ).pack(side="left")

    # -- refresh --------------------------------------------------------------

    def update(self, status: GamePointStatus) -> None:
        """Repaint the summary chip and every status row from a fresh snapshot."""
        text, tone, caption = theme.summary_for(status, port=self._port)
        self._summary_field.configure(
            text=text,
            bg=theme.color_for_tone(tone),
            fg=theme.FIELD_INK.get(tone, theme.CHALK),
        )
        self._summary_caption.configure(text=caption)
        for key, widgets in self._rows.items():
            probe = getattr(status, key, None)
            if not isinstance(probe, ProbeResult):
                continue
            color = theme.color_for_tone(theme.tone_for(probe.ok, probe.state))
            state = widgets["state"]
            assert isinstance(state, tk.Label)
            state.configure(text=probe.state.upper(), fg=color)
            detail = widgets["detail"]
            assert isinstance(detail, tk.Label)
            detail.configure(text=probe.detail or "")


def build_launcher_view(
    root: tk.Misc,
    *,
    actions: Mapping[str, Callable[[], None]],
    status_path: str,
    port: int = 8765,
    simhub_autostart: bool = False,
) -> LauncherView:
    """Construct the themed launcher panel inside ``root`` and return its handle."""
    return LauncherView(
        root,
        actions=actions,
        status_path=status_path,
        port=port,
        simhub_autostart=simhub_autostart,
    )
