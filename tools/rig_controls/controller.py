"""Single-thread controller: acknowledge colour before routing that profile's inputs."""

from __future__ import annotations

from pathlib import Path

from tools.rig_controls.profiles import Config, Context, load_config
from tools.rig_controls.protocol import capability, command, decode


class Controller:
    def __init__(self, config: Config, open_device, actions):
        self.config, self.open_device, self.actions = config, open_device, actions
        self.device = None
        self.active = None
        self.pending = None
        self.epoch = 0
        self.sequence = None
        self.held = set()
        self.deadline = 0.0
        self.renew_at = 0.0
        self.retry_at = 0.0
        self.state = "unavailable"
        self.error = ""
        self.reload_error = ""
        self.awaiting_ack = False

    def status(self) -> dict:
        return {
            "state": self.state,
            "profile": self.active.name if self.active else None,
            "rgb": list(self.active.rgb) if self.active else None,
            "error": self.error,
            "reload_error": self.reload_error,
        }

    def reload(self, path: Path) -> bool:
        try:
            config = load_config(path)
        except (OSError, UnicodeError, ValueError) as exc:
            self.reload_error = str(exc)
            return False
        self.reload_error = ""
        if config != self.config:
            self.config = config
        return True

    def _release(self):
        try:
            self.actions.release_all()
        finally:
            self.held.clear()
            self.sequence = None

    def close(self):
        try:
            self._release()
        except OSError as exc:
            self.error = str(exc)
        finally:
            try:
                if self.device:
                    self.device.close()
            except OSError as exc:
                self.error = str(exc)
            finally:
                self.device = self.active = self.pending = None
                self.awaiting_ack = False
                self.state = "unavailable"

    def _send(self, profile, now):
        packet = command(self.epoch, profile.rgb)
        if self.device.write(packet) != len(packet):
            raise OSError("short keypad profile write")
        self.renew_at = now + 1.0
        self.deadline = now + 0.5
        self.awaiting_ack = True

    def _negotiate(self, profile, now):
        self._release()
        self.active = None
        self.pending = profile
        self.epoch = (self.epoch + 1) & 255
        self.deadline = now + 0.5
        self.state = "negotiating"
        self._send(profile, now)

    def step(self, context: Context, now: float):
        try:
            if self.active and now >= self.renew_at + 0.5:
                raise TimeoutError("missed keypad lease renewal; discarding stale input")
            if self.device and self.awaiting_ack and now >= self.deadline:
                raise TimeoutError("keypad did not acknowledge profile")
            selected = self.config.select(context)
            if self.device is None:
                if now < self.retry_at:
                    return
                self.device = self.open_device()
                self.epoch = capability(bytes(self.device.get_feature_report(7, 9)))
                self._negotiate(selected, now)
            elif selected != (self.pending or self.active):
                self._negotiate(selected, now)
            for _ in range(32):
                packet = self.device.read(9, timeout_ms=0)
                if not packet:
                    break
                report = decode(bytes(packet))
                if report.epoch != self.epoch:
                    continue
                if report.kind == 6:
                    expected = self.pending or self.active
                    if expected and report.rgb == expected.rgb:
                        self.active, self.pending = expected, None
                        self.state, self.error = "active", ""
                        self.awaiting_ack = False
                    else:
                        raise ValueError("keypad colour acknowledgment mismatch")
                    continue
                if self.active is None:
                    continue
                if self.sequence is None and report.sequence != 0:
                    self._negotiate(selected, now)
                    continue
                if self.sequence is not None:
                    delta = (report.sequence - self.sequence) & 255
                    if delta == 0:
                        continue
                    if delta != 1:
                        self._negotiate(selected, now)
                        continue
                self.sequence = report.sequence
                impulse = report.control in (4, 5)
                if not impulse:
                    if report.pressed:
                        if report.control in self.held:
                            continue
                        self.held.add(report.control)
                    else:
                        if report.control not in self.held:
                            continue
                        self.held.remove(report.control)
                binding = self.active.bindings[report.control - 1]
                self.actions.perform(binding, report.pressed, impulse)
            if self.awaiting_ack and now >= self.deadline:
                raise TimeoutError("keypad did not acknowledge profile")
            if self.active and now >= self.renew_at:
                self._send(self.active, now)
        except (OSError, ValueError, RuntimeError, TimeoutError, ImportError) as exc:
            self.error = str(exc)
            self.close()
            self.retry_at = now + 1.0
