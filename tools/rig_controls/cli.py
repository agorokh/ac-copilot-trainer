"""Validation/read-only diagnostics and an explicit hardware-free scenario runner."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from tools.rig_controls.controller import Controller
from tools.rig_controls.ownership import Ownership
from tools.rig_controls.profiles import CONTROLS, Context, load_config
from tools.rig_controls.protocol import PID, USAGE, USAGE_PAGE, VID, open_device
from tools.rig_controls.runtime import Worker
from tools.rig_controls.windows import foreground_context


class SimulatedDevice:
    """Transport double: these acknowledgments are not real LED observations."""

    def __init__(self):
        self.incoming = []
        self.epoch = 0
        self.sequence = 0

    def get_feature_report(self, report_id, length):
        return [7, 65, 67, 1, self.epoch, 255, 0, 0, 0]

    def write(self, packet):
        if self.epoch != packet[2]:
            self.sequence = 0
        self.epoch = packet[2]
        self.incoming.append(bytes([6, 1, self.epoch, *packet[3:6], 1, 0, 0]))
        return len(packet)

    def read(self, length, timeout_ms=0):
        return self.incoming.pop(0) if self.incoming else []

    def close(self):
        pass

    def event(self, event):
        control = CONTROLS.index(event["control"]) + 1
        if type(event.get("pressed")) is not bool:
            raise ValueError("scenario event pressed must be boolean")
        self.incoming.append(
            bytes([4, 1, self.epoch, self.sequence, control, int(event["pressed"]), 0, 0, 0])
        )
        self.sequence = (self.sequence + 1) & 255


class RecordingActions:
    def __init__(self):
        self.events = []
        self.releases = 0

    def perform(self, binding, pressed, impulse=False):
        self.events.append(
            {
                "action": binding.action,
                "keys": list(binding.keys),
                "name": binding.name,
                "pressed": pressed,
                "impulse": impulse,
            }
        )

    def release_all(self):
        self.releases += 1


def simulate(config, steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 1000:
        raise ValueError("scenario must be a list of 1..1000 steps")
    device, actions = SimulatedDevice(), RecordingActions()
    controller = Controller(config, lambda: device, actions)
    snapshots = []
    try:
        for index, row in enumerate(steps):
            context = Context(
                row.get("foreground_process", ""),
                row.get("title", ""),
                frozenset(row.get("running", [])),
            )
            now = index * 0.1
            controller.step(context, now)
            for event in row.get("events", []):
                device.event(event)
            controller.step(context, now + 0.001)
            snapshots.append(controller.status())
    finally:
        controller.close()
    return {
        "simulation": True,
        "steps": snapshots,
        "actions": actions.events,
        "release_boundaries": actions.releases,
    }


def inspect_devices():
    import hid

    rows = hid.enumerate(VID, PID)
    matching = [r for r in rows if r.get("usage_page") == USAGE_PAGE and r.get("usage") == USAGE]
    result = {
        "stock_count": len(hid.enumerate(0x1189, 0x8890)),
        "prepared_candidates": len(matching),
        "outputs_sent": 0,
    }
    if len(matching) == 1:
        owner = Ownership()
        try:
            device = open_device()
            try:
                result["capability"] = list(device.get_feature_report(7, 9))
            finally:
                device.close()
        finally:
            owner.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Game Point keypad profiles: no flash operations")
    parser.add_argument("--config", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true")
    group.add_argument(
        "--context", action="store_true", help="Read Windows foreground context only"
    )
    group.add_argument("--inspect", action="store_true", help="Enumerate/identify, no HID output")
    group.add_argument("--simulate", type=Path, help="JSON context/input scenario; no real device")
    group.add_argument(
        "--run", action="store_true", help="Diagnostic worker; Game Point is the usual owner"
    )
    args = parser.parse_args(argv)
    try:
        if args.context:
            result = asdict(foreground_context())
            result["running"] = sorted(result["running"])
        elif args.inspect:
            result = inspect_devices()
        else:
            if args.config is None:
                parser.error("--config is required for validate/simulate/run")
            config = load_config(args.config)
            if args.validate:
                result = {
                    "valid": True,
                    "profiles": [p.name for p in config.profiles],
                    "default": config.default,
                    "controls": list(CONTROLS),
                }
            elif args.simulate:
                result = simulate(config, json.loads(args.simulate.read_text(encoding="utf-8")))
            else:
                worker = Worker(args.config)
                worker.start()
                try:
                    while True:
                        print(json.dumps(worker.status()), flush=True)
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
                finally:
                    worker.stop()
                return 0
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
