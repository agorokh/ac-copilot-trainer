"""Tkinter UI and CLI entrypoint for the AC Copilot Game Point launcher."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from tools.ai_sidecar.setup_advisor import diff_setup_files
from tools.rig_launcher.install import default_exe_path, install_desktop_shortcut
from tools.rig_launcher.settings import ensure_settings_file
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointStatus,
    GamePointSupervisor,
    build_pyinstaller_args,
    default_paths,
    render_status_lines,
)

#: GUI auto-refresh cadence (ms). Drives the periodic re-poll so the tablet tunnel keeper
#: and every status probe self-heal while the launcher window is open (issue #567).
_GUI_POLL_INTERVAL_MS = 5000


def _open_path(path: Path) -> None:
    if os.name == "nt":
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError:
            fallback = "explorer.exe" if path.is_dir() else "notepad.exe"
            subprocess.Popen([fallback, str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AC Copilot Game Point launcher")
    parser.add_argument("--once", action="store_true", help="Probe once and exit.")
    parser.add_argument("--start", action="store_true", help="Start supervised processes first.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print status or setup output as JSON where supported.",
    )
    parser.add_argument("--no-gui", action="store_true", help="Do not open the Tk status window.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Start the sidecar, assert it serves /tablet/dash and /tablet/voice (200), "
        "then exit non-zero if a stale build 426s them. Release gate for issue #567.",
    )
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--external-bind", default=None)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--start-simhub", action="store_true")
    parser.add_argument(
        "--build-exe",
        action="store_true",
        help="Run PyInstaller to build the windowed launcher executable.",
    )
    parser.add_argument(
        "--install-shortcut",
        action="store_true",
        help="Create or update the Windows Desktop shortcut to the packaged launcher.",
    )
    parser.add_argument(
        "--shortcut-target",
        default=None,
        help="Override the exe path used by --install-shortcut.",
    )
    parser.add_argument(
        "--setup-diff",
        nargs=2,
        metavar=("BASELINE_INI", "CANDIDATE_INI"),
        help="Compare two setup INI files and show a driver-readable setup diff.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> GamePointConfig:
    paths = default_paths(os.environ)
    if args.log_dir:
        paths = type(paths)(Path(args.log_dir).expanduser())
    config = GamePointConfig.from_env(paths=paths)
    return GamePointConfig(
        host=config.host,
        port=args.port or config.port,
        external_bind=args.external_bind
        if args.external_bind is not None
        else config.external_bind,
        token=config.token,
        reference_archive=config.reference_archive,
        voice_bank=config.voice_bank,
        voice_tts=config.voice_tts,
        setup_store=config.setup_store,
        simhub_exe=config.simhub_exe,
        start_simhub=args.start_simhub or config.start_simhub,
        manage_tablet_tunnel=config.manage_tablet_tunnel,
        adb_path=config.adb_path,
        adb_serial=config.adb_serial,
        paths=paths,
    )


def render_setup_diff_lines(diff: dict[str, Any]) -> list[str]:
    if not diff.get("ok", False):
        return [f"setup diff: {diff.get('error', 'failed')}"]
    changed_count = int(diff.get("changed_count") or 0)
    lines = [f"setup diff: {changed_count} changed knob{'s' if changed_count != 1 else ''}"]
    baseline = diff.get("baseline")
    candidate = diff.get("candidate")
    if isinstance(baseline, dict) and isinstance(candidate, dict):
        base_path = baseline.get("path")
        candidate_path = candidate.get("path")
        if base_path and candidate_path:
            lines.append(f"baseline: {base_path}")
            lines.append(f"candidate: {candidate_path}")
    display_lines = diff.get("display_lines")
    if isinstance(display_lines, list) and display_lines:
        lines.extend(str(line) for line in display_lines)
    else:
        lines.append("no setup changes")
    return lines


def _setup_diff_error(baseline_path: str, candidate_path: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "setup_diff_failed",
        "baseline": {"path": baseline_path},
        "candidate": {"path": candidate_path},
        "changed_count": 0,
        "rows": [],
        "display_lines": [],
        "error": str(exc) or exc.__class__.__name__,
    }


def _open_setup_diff_window(diff: dict[str, Any], *, parent: Any | None = None) -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Toplevel(parent) if parent is not None else tk.Tk()
    root.title("Setup Diff")
    root.geometry("760x460")
    root.minsize(560, 320)

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Setup Diff", font=("", 16, "bold")).pack(anchor="w")
    text = tk.Text(frame, wrap="word", height=16)
    text.pack(fill="both", expand=True, pady=(12, 0))
    text.insert("1.0", "\n".join(render_setup_diff_lines(diff)))
    text.configure(state="disabled")
    ttk.Button(frame, text="Close", command=root.destroy).pack(anchor="e", pady=(12, 0))
    if parent is None:
        root.mainloop()
    return 0 if diff.get("ok", False) else 1


def run_setup_diff_gui(diff: dict[str, Any]) -> int:
    try:
        return _open_setup_diff_window(diff)
    except Exception as exc:  # noqa: BLE001 - keep launcher useful on headless machines
        print(f"Setup diff window unavailable: {exc}", file=sys.stderr)
        print("\n".join(render_setup_diff_lines(diff)))
        return 0 if diff.get("ok", False) else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--sidecar-child":
        return run_sidecar_child(argv[1:])

    args = build_arg_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    if args.build_exe:
        cmd = [sys.executable, "-m", "PyInstaller", *build_pyinstaller_args(project_root)]
        rc = subprocess.call(cmd)
        if rc != 0 or not args.install_shortcut:
            return rc
    if args.install_shortcut:
        target = (
            Path(args.shortcut_target).expanduser()
            if args.shortcut_target
            else default_exe_path(project_root)
        )
        try:
            result = install_desktop_shortcut(target, working_directory=project_root)
        except Exception as exc:  # noqa: BLE001 - CLI should report the install failure plainly
            print(f"Shortcut install failed: {exc}", file=sys.stderr)
            return 1
        print(f"Installed Desktop shortcut: {result.shortcut_path}")
        print(f"Target: {result.target_path}")
        return 0

    if args.setup_diff:
        baseline_path, candidate_path = args.setup_diff
        try:
            diff = diff_setup_files(baseline_path, candidate_path)
        except Exception as exc:  # noqa: BLE001 - CLI should report bad setup files plainly
            diff = _setup_diff_error(baseline_path, candidate_path, exc)
        if args.json:
            print(json.dumps(diff, indent=2, sort_keys=True))
            return 0 if diff.get("ok", False) else 1
        if args.no_gui:
            print("\n".join(render_setup_diff_lines(diff)))
            return 0 if diff.get("ok", False) else 1
        return run_setup_diff_gui(diff)

    supervisor = GamePointSupervisor(config_from_args(args))
    try:
        if args.self_test:
            # The self-test owns the sidecar it starts: stop it as soon as the checks finish so
            # a release-gate run never leaves an orphaned sidecar for the next launch to adopt
            # (#568 review — the outer finally also closes it, but the ownership is explicit here).
            # stop_sidecar() is a no-op when start_sidecar() adopted an already-running instance.
            started = supervisor.start_sidecar()
            # If a sidecar was already listening on the port, start_sidecar ADOPTS it — the
            # self-test would then validate that OTHER process (e.g. a fresh source sidecar),
            # so a stale packaged EXE could pass. Refuse: the release gate must exercise the
            # build under test, not a foreign one (#568 review). stop_sidecar won't kill the
            # adopted process (we didn't spawn it).
            if started.ok and "adopted" in (started.detail or ""):
                print(
                    "self-test: another sidecar is already running on port "
                    f"{supervisor.config.port} and was adopted — cannot validate this build. "
                    "Stop the existing sidecar and retry.",
                    file=sys.stderr,
                )
                return 1
            try:
                results = supervisor.self_test_endpoints()
            finally:
                supervisor.stop_sidecar()
            ok = all(row.ok for row in results)
            if args.json:
                print(json.dumps([row.to_dict() for row in results], indent=2, sort_keys=True))
            else:
                for row in results:
                    detail = f" - {row.detail}" if row.detail else ""
                    print(f"{row.name}: {row.state}{detail}")
            return 0 if ok else 1
        if args.start:
            supervisor.start_sidecar()
        if args.once or args.no_gui:
            status = supervisor.poll_status()
            if args.json:
                print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
            else:
                print("\n".join(render_status_lines(status)))
            return 0 if status.ok else 1
        return run_gui(supervisor)
    finally:
        supervisor.close()


def run_gui(supervisor: GamePointSupervisor) -> int:
    try:
        import tkinter as tk

        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - fall back to visible CLI status
        status = supervisor.poll_status()
        print(f"GUI unavailable: {exc}", file=sys.stderr)
        print("\n".join(render_status_lines(status)))
        return 1 if not status.ok else 0

    from tools.rig_launcher.view import build_launcher_view

    root.title("AC Copilot Game Point")
    root.geometry("660x440")
    root.minsize(620, 400)

    last_status: dict[str, GamePointStatus | None] = {"status": None}
    _poll_busy: dict[str, bool] = {"v": False}

    def _poll_worker() -> None:
        try:
            # Read-only: the continuous poll must never re-launch SimHub on each tick — starting
            # it is an explicit user action (START / toggle-on) below (#568 review).
            status = supervisor.poll_status(start_simhub=False)
        finally:
            _poll_busy["v"] = False

        def apply() -> None:
            try:
                if root.winfo_exists():
                    last_status["status"] = status
                    view.update(status)
            except tk.TclError:
                return

        try:
            root.after(0, apply)
        except (tk.TclError, RuntimeError):
            return

    def refresh() -> None:
        # NON-BLOCKING. poll_status() can wait on adb subprocesses (managed tablet tunnel), so
        # every refresh path — startup, START, REFRESH, the SimHub toggle, and the periodic tick
        # — goes through the worker thread; a wedged ADB/USB stack must never freeze the Tk UI
        # (#568 review r2+r3). A refresh while one is in flight is coalesced (busy flag).
        if _poll_busy["v"]:
            return
        _poll_busy["v"] = True
        threading.Thread(target=_poll_worker, daemon=True).start()

    def _launch_simhub_and_report() -> None:
        # Explicit one-shot SimHub launch (not on the read-only ticks). The next refresh is
        # read-only and would only show `available`, hiding a start failure — so surface a
        # failed explicit launch directly to the operator here (#568 review).
        res = supervisor.probe_simhub(start=True)
        if not res.ok:
            from tkinter import messagebox

            messagebox.showwarning("SimHub", res.detail or "SimHub failed to start", parent=root)

    def start() -> None:
        supervisor.start_sidecar()
        if supervisor.config.start_simhub:
            _launch_simhub_and_report()
        refresh()

    def open_logs() -> None:
        path = supervisor.paths.logs_dir
        path.mkdir(parents=True, exist_ok=True)
        _open_path(path)

    def open_settings() -> None:
        path = ensure_settings_file(supervisor.paths)
        _open_path(path)

    def open_setup_diff() -> None:
        from tkinter import filedialog, messagebox

        baseline = filedialog.askopenfilename(
            parent=root,
            title="Choose baseline setup",
            filetypes=[("Assetto Corsa setup", "*.ini"), ("All files", "*.*")],
        )
        if not baseline:
            return
        candidate = filedialog.askopenfilename(
            parent=root,
            title="Choose candidate setup",
            filetypes=[("Assetto Corsa setup", "*.ini"), ("All files", "*.*")],
        )
        if not candidate:
            return
        try:
            _open_setup_diff_window(diff_setup_files(baseline, candidate), parent=root)
        except Exception as exc:  # noqa: BLE001 - surface file/UI errors in the launcher
            messagebox.showerror("Setup Diff", str(exc), parent=root)

    def toggle_simhub(enabled: bool) -> None:
        # Apply the checkbox's new state (the view passes it in, so the model follows the UI).
        # Toggling ON is an explicit action → launch SimHub once here; the read-only status
        # ticks never (re)start it. SimHub is never a blocking status row.
        supervisor.set_start_simhub(enabled)
        if enabled:
            _launch_simhub_and_report()
        refresh()

    view = build_launcher_view(
        root,
        actions={
            "start": start,
            "refresh": refresh,
            "logs": open_logs,
            "settings": open_settings,
            "setup_diff": open_setup_diff,
        },
        status_path=str(supervisor.paths.status_path),
        port=supervisor.config.port,
        simhub_autostart=supervisor.config.start_simhub,
        on_toggle_simhub=toggle_simhub,
    )

    def poll_tick() -> None:
        # Continuous re-poll so the tablet tunnel keeper (and every other probe) self-heals
        # while the launcher is open — an unplug / tablet sleep / `adb kill-server` after launch
        # is otherwise only noticed on a manual REFRESH (issue #567). refresh() is already the
        # non-blocking worker path, so the periodic tick reuses it.
        try:
            if not root.winfo_exists():
                return
            refresh()
            root.after(_GUI_POLL_INTERVAL_MS, poll_tick)
        except tk.TclError:
            return

    view.mark_pending()  # neutral state until the first async poll lands (#568 review)
    # Honor the configured SimHub auto-start ONCE at launch (the periodic ticks are read-only,
    # so without this the documented AC_COPILOT_START_SIMHUB / checkbox would be a no-op until
    # the operator pressed START — #568 review).
    if supervisor.config.start_simhub:
        _launch_simhub_and_report()
    refresh()
    root.after(_GUI_POLL_INTERVAL_MS, poll_tick)
    root.mainloop()
    status = last_status["status"]
    return 0 if status is None or status.ok else 1


def run_sidecar_child(argv: list[str]) -> int:
    """Run the bundled sidecar from inside a frozen Game Point executable."""
    from tools.ai_sidecar import server

    old_argv = sys.argv
    try:
        sys.argv = ["ai_sidecar", *argv]
        server.main()
    finally:
        sys.argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
