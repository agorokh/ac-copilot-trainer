"""Tkinter UI and CLI entrypoint for the AC Copilot Game Point launcher."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointStatus,
    GamePointSupervisor,
    build_pyinstaller_args,
    default_paths,
    render_status_lines,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AC Copilot Game Point launcher")
    parser.add_argument("--once", action="store_true", help="Probe once and exit.")
    parser.add_argument("--start", action="store_true", help="Start supervised processes first.")
    parser.add_argument("--json", action="store_true", help="Print status JSON in --once mode.")
    parser.add_argument("--no-gui", action="store_true", help="Do not open the Tk status window.")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--external-bind", default=None)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--start-simhub", action="store_true")
    parser.add_argument(
        "--build-exe",
        action="store_true",
        help="Run PyInstaller to build the windowed launcher executable.",
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
        paths=paths,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--sidecar-child":
        return run_sidecar_child(argv[1:])

    args = build_arg_parser().parse_args(argv)
    if args.build_exe:
        project_root = Path(__file__).resolve().parents[2]
        cmd = [sys.executable, "-m", "PyInstaller", *build_pyinstaller_args(project_root)]
        return subprocess.call(cmd)

    supervisor = GamePointSupervisor(config_from_args(args))
    try:
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
        from tkinter import ttk
    except Exception as exc:  # noqa: BLE001 - fall back to visible CLI status
        status = supervisor.poll_status()
        print(f"GUI unavailable: {exc}", file=sys.stderr)
        print("\n".join(render_status_lines(status)))
        return 1 if not status.ok else 0

    root = tk.Tk()
    root.title("AC Copilot Game Point")
    root.geometry("620x360")
    root.minsize(560, 320)

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    header = ttk.Label(frame, text="AC Copilot Game Point", font=("", 16, "bold"))
    header.pack(anchor="w")
    status_var = tk.StringVar(value="Starting")
    status_label = ttk.Label(frame, textvariable=status_var, justify="left")
    status_label.pack(anchor="w", fill="x", pady=(12, 8))

    button_row = ttk.Frame(frame)
    button_row.pack(anchor="w", pady=(8, 0))

    last_status: dict[str, GamePointStatus | None] = {"status": None}

    def refresh() -> None:
        status = supervisor.poll_status()
        last_status["status"] = status
        status_var.set("\n".join(render_status_lines(status)))

    def start() -> None:
        supervisor.start_sidecar()
        refresh()

    def open_logs() -> None:
        path = supervisor.paths.logs_dir
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])

    ttk.Button(button_row, text="Start", command=start).pack(side="left", padx=(0, 8))
    ttk.Button(button_row, text="Refresh", command=refresh).pack(side="left", padx=(0, 8))
    ttk.Button(button_row, text="Logs", command=open_logs).pack(side="left")
    ttk.Label(frame, text=f"Status: {supervisor.paths.status_path}").pack(anchor="w", pady=(16, 0))

    refresh()
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
