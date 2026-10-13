"""Racing Atelier themed Tk view for the Game Point launcher (epic #432, Part B).

``build_launcher_view`` renders the carbon/brass status panel that maps 1:1 onto
``GamePointStatus`` (sidecar / screen / voice / simhub / tablet / AC session). It owns
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
from pathlib import Path
from tkinter import font as tkfont
from typing import Any

from tools.rig_launcher import theme
from tools.rig_launcher.fonts import load_private_fonts
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointStatus,
    OfflineReportResult,
    ProbeResult,
)

#: (display label, GamePointStatus attribute) for each status row, top to bottom.
_ROWS: tuple[tuple[str, str], ...] = (
    ("Sidecar", "sidecar"),
    ("Screen", "screen"),
    ("Voice", "voice"),
    ("SimHub", "simhub"),
    ("Tablet", "tablet"),
    ("Keypad", "keypad"),
    ("AC Session", "resilient"),
    ("Offline report", "moza_review"),
)

#: (label, action key, is-primary) for each footer button. Labels are uppercase
#: per the design Button treatment; Release AC and Setup Diff are operator
#: functions the static design mock omits.
_BUTTONS: tuple[tuple[str, str, bool], ...] = (
    ("▶ START", "start", True),
    ("STABLE AC", "resilient_launch", False),
    ("RELEASE AC", "resilient_release", False),
    ("REFRESH", "refresh", False),
    ("LOGS", "logs", False),
    ("SETTINGS", "settings", False),
    ("SETUP DIFF", "setup_diff", False),
)

#: grid column weights: Start is 1.5x each secondary action (design
#: grid-template-columns 1.5fr 1fr 1fr 1fr, extended with operator actions).
_BUTTON_WEIGHTS: tuple[int, ...] = (3, 2, 2, 2, 2, 2, 2)

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
        on_toggle_simhub: Callable[[bool], None] | None = None,
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

        # Reserve the actions before allocating the expandable status body.
        self._build_buttons(panel, actions)

        body = tk.Frame(panel, bg=theme.GRAPHITE)
        body.pack(fill="both", expand=True, padx=16, pady=(2, 8))
        for index, (label, key) in enumerate(_ROWS):
            self._rows[key] = self._build_row(body, label, last=index == len(_ROWS) - 1)

        # Optional SimHub auto-start toggle, wired only when the caller supplies
        # the callback (app.run_gui). Keeps the view presentation-only otherwise.
        self._simhub_var: tk.BooleanVar | None = None
        if on_toggle_simhub is not None:
            self._build_simhub_toggle(body, on_toggle_simhub, simhub_autostart)

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
        row.pack(side="bottom", fill="x", padx=16, pady=(10, 14))
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
        if "moza_offline_report" in actions:
            tk.Button(
                row,
                text="OFFLINE REPORT",
                command=actions["moza_offline_report"],
                cursor="hand2",
                relief="flat",
                bd=0,
                padx=10,
                pady=11,
                font=(self._f_disp, 10, "bold"),
                bg=theme.RAISE,
                fg=theme.CHALK,
                activebackground=theme.SLAB,
                activeforeground=theme.CHALK,
                highlightthickness=1,
                highlightbackground=theme.LINE_2,
            ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(9, 0))

    def _build_simhub_toggle(
        self,
        parent: tk.Frame,
        command: Callable[[bool], None],
        initial: bool,
    ) -> None:
        """Render the SimHub auto-start toggle bound to the persisted setting.

        A themed Checkbutton so "start SimHub with the launcher" is reachable
        from the UI, not only by hand-editing settings.json. The var seeds from the
        launch-time config so it reflects the current setting on open; on click Tk
        flips the var first, so ``var.get()`` is the checkbox's NEW state — pass it
        to ``command`` so the model follows the UI (single source of truth) rather
        than the caller re-deriving it (see ``app.run_gui``).
        """
        var = tk.BooleanVar(master=self._root, value=bool(initial))
        self._simhub_var = var
        row = tk.Frame(parent, bg=theme.GRAPHITE)
        row.pack(fill="x", pady=(6, 2))
        tk.Checkbutton(
            row,
            text="AUTO-START SIMHUB",
            variable=var,
            command=lambda: command(bool(var.get())),
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

    def fit_window(self) -> None:
        """Fit the initial window and its minimum size to the actual fonts and controls."""
        root = self._root
        if not isinstance(root, (tk.Tk, tk.Toplevel)):
            return
        root.update_idletasks()
        # Tk's window-manager maximum can be narrower than the virtual desktop.
        # Wrap diagnostic paths before measuring, rather than requesting a width
        # the current monitor cannot allocate.
        maximum_width, _ = root.maxsize()
        details = [widgets["detail"] for widgets in self._rows.values()]
        for detail in [self._summary_caption, *details]:
            assert isinstance(detail, tk.Label)
            row = detail.master
            other_width = row.winfo_reqwidth() - detail.winfo_reqwidth()
            detail.configure(wraplength=max(160, maximum_width - 68 - other_width))
        root.update_idletasks()
        minimum_width, minimum_height = root.minsize()
        width = max(620, minimum_width, root.winfo_reqwidth())
        height = max(400, minimum_height, root.winfo_reqheight())
        root.minsize(width, height)

    def mark_pending(self) -> None:
        """Show a neutral 'checking' state until the first real status lands.

        The launcher polls asynchronously (#568 review): if the first poll is slow — e.g. a
        wedged ADB/USB stack on the managed tablet path — the window must not read as a green
        READY-TO-DRIVE before any probe has actually run. Seed a dim, non-committal state.
        """
        self._summary_field.configure(
            text="CHECKING…",
            bg=theme.color_for_tone("idle"),
            fg=theme.FIELD_INK.get("idle", theme.CHALK),
        )
        self._summary_caption.configure(text="running first status check…")
        for widgets in self._rows.values():
            state = widgets["state"]
            if isinstance(state, tk.Label):
                state.configure(text="…", fg=theme.DIM)
            detail = widgets["detail"]
            if isinstance(detail, tk.Label):
                detail.configure(text="")

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
            if key == "moza_review":
                # Offline availability is advisory and must never look like a live arm state.
                tone = "clear" if probe.state == "analysis_available" else "lift"
                if probe.state == "not_run":
                    tone = "idle"
                color = theme.color_for_tone(tone)
            state = widgets["state"]
            assert isinstance(state, tk.Label)
            state.configure(text=probe.state.upper(), fg=color)
            detail = widgets["detail"]
            assert isinstance(detail, tk.Label)
            detail.configure(text=probe.detail or "")
        self.fit_window()


class MozaReviewView:
    """File choices and last offline outcome, with no process or report logic in the view."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        config: GamePointConfig,
        on_generate: Callable[[dict[str, Any]], None],
        on_open: Callable[[Path], None],
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Game Point · Offline report")
        self.window.configure(bg=theme.GRAPHITE)
        self.window.minsize(660, 420)
        frame = tk.Frame(self.window, bg=theme.GRAPHITE, padx=18, pady=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        tk.Label(
            frame,
            text="OFFLINE LAP REVIEW",
            bg=theme.GRAPHITE,
            fg=theme.BRASS,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        tk.Label(
            frame,
            text="Choose a native archive or readable MOZA cache JSON.\n"
            "Cache charts may support inspection only. This action does not enable live coaching.",
            bg=theme.GRAPHITE,
            fg=theme.MUTE,
            justify="left",
            anchor="w",
            wraplength=650,
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        self._vars: dict[str, tk.StringVar] = {}
        self._controls: list[Any] = []
        selections = (
            ("selected_file", "Native lap / MOZA cache", config.moza_offline_file),
            ("matched_native_file", "Matched native (optional)", config.moza_offline_native_file),
            ("evaluation_file", "Evaluation (optional)", config.moza_offline_evaluation_file),
        )
        for row, (key, label, initial) in enumerate(selections, start=2):
            var = tk.StringVar(master=self.window, value=initial or "")
            self._vars[key] = var
            tk.Label(frame, text=label, bg=theme.GRAPHITE, fg=theme.CHALK, anchor="w").grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 10),
                pady=5,
            )
            entry = tk.Entry(
                frame,
                textvariable=var,
                bg=theme.SLAB,
                fg=theme.CHALK,
                insertbackground=theme.CHALK,
                width=48,
            )
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            button = tk.Button(
                frame,
                text="Browse…",
                command=lambda v=var, title=label: self._browse(v, title),
                bg=theme.RAISE,
                fg=theme.CHALK,
                relief="flat",
                padx=10,
                pady=6,
            )
            button.grid(row=row, column=2, padx=(8, 0), pady=5)
            self._controls.extend((entry, button))
        self._oracle = tk.BooleanVar(master=self.window, value=config.moza_offline_oracle)
        oracle = tk.Checkbutton(
            frame,
            text="Inspect MOZA advice availability (offline)",
            variable=self._oracle,
            bg=theme.GRAPHITE,
            fg=theme.CHALK,
            selectcolor=theme.SLAB,
            activebackground=theme.GRAPHITE,
            activeforeground=theme.CHALK,
            anchor="w",
        )
        oracle.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 12))
        self._controls.append(oracle)
        self._status = tk.Label(
            frame,
            text="",
            bg=theme.GRAPHITE,
            fg=theme.MUTE,
            anchor="nw",
            justify="left",
            wraplength=650,
        )
        self._status.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(0, 14))
        frame.rowconfigure(6, weight=1)
        self._generate = tk.Button(
            frame,
            text="SAVE SELECTIONS & GENERATE",
            command=lambda: on_generate(self.selection()),
            bg=theme.BRASS,
            fg=theme.BRASS_INK,
            relief="flat",
            padx=12,
            pady=10,
        )
        self._generate.grid(row=7, column=0, columnspan=2, sticky="w")
        self._controls.append(self._generate)
        self._report_path: Path | None = None
        self._open = tk.Button(
            frame,
            text="OPEN REPORT",
            state="disabled",
            command=lambda: on_open(self._report_path) if self._report_path else None,
            bg=theme.RAISE,
            fg=theme.CHALK,
            relief="flat",
            padx=12,
            pady=10,
        )
        self._open.grid(row=7, column=2, sticky="e")
        for var in (*self._vars.values(), self._oracle):
            var.trace_add("write", self._selection_changed)

    def selection(self) -> dict[str, Any]:
        return {
            **{key: var.get() for key, var in self._vars.items()},
            "oracle_enabled": bool(self._oracle.get()),
        }

    def _selection_changed(self, *_args: Any) -> None:
        self._report_path = None
        self._open.configure(state="disabled")
        self._status.configure(text="Selection changed. Generate a report to check these files.")

    def _browse(self, var: tk.StringVar, title: str) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=self.window,
            title=title,
            filetypes=[("JSON files", "*.json")],
        )
        if path:
            var.set(path)

    def set_running(self) -> None:
        self._report_path = None
        self._open.configure(state="disabled")
        for control in self._controls:
            control.configure(state="disabled")
        self._status.configure(text="Generating offline report…")

    def show_result(self, result: OfflineReportResult) -> None:
        for control in self._controls:
            control.configure(state="normal")
        self._report_path = result.report_path
        self._open.configure(state="normal" if result.report_path else "disabled")
        text = result.status.state.replace("_", " ").upper() + "\n" + result.status.detail
        if result.report_path:
            text += "\nSaved report: " + str(result.report_path)
        self._status.configure(text=text)


def build_launcher_view(
    root: tk.Misc,
    *,
    actions: Mapping[str, Callable[[], None]],
    status_path: str,
    port: int = 8765,
    simhub_autostart: bool = False,
    on_toggle_simhub: Callable[[bool], None] | None = None,
) -> LauncherView:
    """Construct the themed launcher panel inside ``root`` and return its handle."""
    return LauncherView(
        root,
        actions=actions,
        status_path=status_path,
        port=port,
        simhub_autostart=simhub_autostart,
        on_toggle_simhub=on_toggle_simhub,
    )
