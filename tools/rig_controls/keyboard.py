"""Read-only compatibility with the existing CH552 Ctrl+Alt+A/M/S bindings.

No hooks, hotkey registration, input injection, HID output or firmware changes.
Raw Input identifies the source keyboard. Other keyboards' input is discarded.
Only the existing declaration actions can be configured for this backend.
"""

from __future__ import annotations

import ctypes
import os
from collections import deque

from tools.rig_controls.controller import Controller


def is_baseline_keyboard(path: str) -> bool:
    parts = path.upper().split("#")
    return any({"VID_1209", "PID_C55D"} <= set(part.split("&")) for part in parts)


class ShortcutDecoder:
    """Per-device key state: no global modifier state or repeat declarations."""

    def __init__(self):
        self.held = set()
        self.active = set()

    def reset(self):
        self.held.clear()
        self.active.clear()

    def feed(self, vk: int, pressed: bool):
        letters = {0x41: 0, 0x4D: 1, 0x53: 2}
        relevant = set(letters) | {0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6)}
        if vk not in relevant:
            return None
        if not pressed:
            self.held.discard(vk)
            if vk in self.active:
                self.active.remove(vk)
                return letters[vk], False
            return None
        if vk in self.held:
            return None
        self.held.add(vk)
        ctrl = self.held & {0x11, 0xA2, 0xA3}
        alt = self.held & {0x12, 0xA4, 0xA5}
        extra = self.held & {0x10, 0xA0, 0xA1, 0x5B, 0x5C}
        if vk in letters and ctrl and alt and not extra:
            self.active.add(vk)
            return letters[vk], True
        return None


class KeyboardController(Controller):
    """Reuse the worker's ownership/reload/actions without inventing HID acknowledgments."""

    def __init__(self, config, source_factory, actions):
        super().__init__(config, source_factory, actions)
        self.keys = ShortcutDecoder()
        self.last_poll = None

    def status(self):
        return {**super().status(), "backend": "baseline_keyboard", "rgb": None}

    def close(self):
        self.keys.reset()
        self.last_poll = None
        super().close()

    def step(self, context, now):
        try:
            if self.last_poll is not None and now - self.last_poll > 0.5:
                raise OSError("keyboard input polling stalled; discard pending declaration")
            if self.device is None:
                if now < self.retry_at:
                    return
                self.device = self.open_device()
            events = self.device.read()
            self.last_poll = now
            selected = self.config.select(context)
            if selected != self.active:
                self._release()
                self.keys.reset()
                self.active = selected
                self.state, self.error = "active", ""
                # Do not reinterpret a shortcut queued under the previous context/profile.
                return
            for vk, pressed in events:
                event = self.keys.feed(vk, pressed)
                if event is not None:
                    control, down = event
                    self.actions.perform(self.active.bindings[control], down)
        except (OSError, ValueError, RuntimeError) as exc:
            self.error = str(exc)
            self.close()
            self.retry_at = now + 1.0


U32, U16 = ctypes.c_uint32, ctypes.c_uint16
PTR = ctypes.c_void_p


class Header(ctypes.Structure):
    _fields_ = [("kind", U32), ("size", U32), ("device", PTR), ("wparam", ctypes.c_size_t)]


class Key(ctypes.Structure):
    _fields_ = [
        ("scan", U16),
        ("flags", U16),
        ("reserved", U16),
        ("vk", U16),
        ("message", U32),
        ("extra", U32),
    ]


class Device(ctypes.Structure):
    _fields_ = [("handle", PTR), ("kind", U32)]


class Registration(ctypes.Structure):
    _fields_ = [("page", U16), ("usage", U16), ("flags", U32), ("target", PTR)]


def decode_packet(data: bytes, expected_device: int):
    if len(data) < ctypes.sizeof(Header):
        raise ValueError("truncated Raw Input header")
    header = Header.from_buffer_copy(data)
    if header.size != len(data):
        raise ValueError("Raw Input size mismatch")
    if header.kind != 1 or header.device != expected_device:
        return None
    if len(data) != ctypes.sizeof(Header) + ctypes.sizeof(Key):
        raise ValueError("truncated Raw Input keyboard")
    key = Key.from_buffer_copy(data, ctypes.sizeof(Header))
    if key.vk == 255:
        raise ValueError("keyboard overrun; discard pending declaration")
    if key.message not in (0x100, 0x101, 0x104, 0x105):
        raise ValueError("unexpected Raw Input keyboard message")
    pressed = not bool(key.flags & 1)
    if pressed != (key.message in (0x100, 0x104)):
        raise ValueError("inconsistent Raw Input key state")
    return key.vk, pressed


class RawKeyboardSource:
    """Thread-owned message-only window; unregister on the same worker thread."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("baseline keyboard input requires Windows")
        self.events = deque()
        self.error = ""
        self.window = None
        self.registered = False
        self.atom = 0
        self.api = _WindowsAPI()
        candidates = self.api.baseline_devices()
        if len(candidates) != 1:
            raise OSError(f"expected one baseline keypad keyboard, found {len(candidates)}")
        self.device = candidates[0]
        self.class_name = f"AC-Copilot-Keypad-{id(self):x}"
        self.callback = self.api.callback_type(self._message)
        try:
            self.atom, self.window = self.api.create_window(self.class_name, self.callback)
            self.api.register(self.window)
            self.registered = True
        except BaseException:
            self.close()
            raise

    def _message(self, hwnd, message, wparam, lparam):
        try:
            if message == 0xFE:  # WM_INPUT_DEVICE_CHANGE
                # Registration can announce already-present devices. Only a
                # removal of our handle, replacement, or ambiguity invalidates it.
                if (wparam == 2 and lparam == self.device) or self.api.baseline_devices() != [
                    self.device
                ]:
                    raise OSError("keyboard devices changed; discard pending declaration")
            if message == 0xFF:  # WM_INPUT
                event = decode_packet(self.api.packet(lparam), self.device)
                if event is not None:
                    if len(self.events) >= 64:
                        raise OSError("keyboard input queue overflow")
                    self.events.append(event)
        except Exception as exc:
            # ctypes callbacks cannot propagate errors. Surface them at read(),
            # where the controller closes this source before any action is routed.
            self.error = str(exc)
        return self.api.default(hwnd, message, wparam, lparam)

    def read(self):
        self.api.pump(self.window)
        if self.error:
            raise OSError(self.error)
        events = list(self.events)
        self.events.clear()
        return events

    def close(self):
        self.events.clear()
        errors = []
        for needed, operation in (
            (self.registered, self.api.remove),
            (self.window, lambda: self.api.destroy(self.window)),
            (self.atom, lambda: self.api.unregister(self.class_name)),
        ):
            if needed:
                try:
                    operation()
                except OSError as exc:
                    errors.append(str(exc))
        self.registered, self.window, self.atom = False, None, 0
        if errors:
            raise OSError("; ".join(errors))


class _WindowsAPI:  # pragma: no cover - exercised by the native rig readback
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, PTR, U32, ctypes.c_size_t, ctypes.c_ssize_t
        )
        signatures = {
            "GetRawInputDeviceList": ([PTR, ctypes.POINTER(U32), U32], U32),
            "GetRawInputDeviceInfoW": ([PTR, U32, PTR, ctypes.POINTER(U32)], U32),
            "GetRegisteredRawInputDevices": ([PTR, ctypes.POINTER(U32), U32], U32),
            "RegisterRawInputDevices": ([PTR, U32, U32], ctypes.c_int),
            "GetRawInputData": ([PTR, U32, PTR, ctypes.POINTER(U32), U32], U32),
            "RegisterClassW": ([PTR], U16),
            "CreateWindowExW": (
                [
                    U32,
                    ctypes.c_wchar_p,
                    ctypes.c_wchar_p,
                    U32,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    PTR,
                    PTR,
                    PTR,
                    PTR,
                ],
                PTR,
            ),
            "DefWindowProcW": ([PTR, U32, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t),
            "DestroyWindow": ([PTR], ctypes.c_int),
            "UnregisterClassW": ([ctypes.c_wchar_p, PTR], ctypes.c_int),
            "PeekMessageW": ([PTR, PTR, U32, U32, U32], ctypes.c_int),
            "TranslateMessage": ([PTR], ctypes.c_int),
            "DispatchMessageW": ([PTR], ctypes.c_ssize_t),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        self.kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self.kernel.GetModuleHandleW.restype = PTR
        self.instance = self.kernel.GetModuleHandleW(None)

    def baseline_devices(self):
        count = U32()
        if (
            self.user.GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(Device))
            == 0xFFFFFFFF
        ):
            raise ctypes.WinError()
        rows = (Device * count.value)()
        if (
            self.user.GetRawInputDeviceList(rows, ctypes.byref(count), ctypes.sizeof(Device))
            == 0xFFFFFFFF
        ):
            raise ctypes.WinError()
        matches = []
        for row in rows[: count.value]:
            if row.kind != 1:
                continue
            size = U32()
            if (
                self.user.GetRawInputDeviceInfoW(row.handle, 0x20000007, None, ctypes.byref(size))
                == 0xFFFFFFFF
            ):
                raise ctypes.WinError()
            name = ctypes.create_unicode_buffer(size.value + 1)
            if (
                self.user.GetRawInputDeviceInfoW(row.handle, 0x20000007, name, ctypes.byref(size))
                == 0xFFFFFFFF
            ):
                raise ctypes.WinError()
            if is_baseline_keyboard(name.value):
                matches.append(row.handle)
        return matches

    def create_window(self, name, callback):
        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", U32),
                ("proc", self.callback_type),
                ("extra_class", ctypes.c_int),
                ("extra_window", ctypes.c_int),
                ("instance", PTR),
                ("icon", PTR),
                ("cursor", PTR),
                ("background", PTR),
                ("menu", ctypes.c_wchar_p),
                ("name", ctypes.c_wchar_p),
            ]

        wc = WindowClass(0, callback, 0, 0, self.instance, None, None, None, None, name)
        atom = self.user.RegisterClassW(ctypes.byref(wc))
        if not atom:
            raise ctypes.WinError()
        window = self.user.CreateWindowExW(
            0, name, "", 0, 0, 0, 0, 0, PTR(-3), None, self.instance, None
        )
        if not window:
            self.user.UnregisterClassW(name, self.instance)
            raise ctypes.WinError()
        return atom, window

    def register(self, window):
        count = U32()
        if (
            self.user.GetRegisteredRawInputDevices(
                None, ctypes.byref(count), ctypes.sizeof(Registration)
            )
            == 0xFFFFFFFF
        ):
            raise ctypes.WinError()
        rows = (Registration * count.value)()
        if (
            count.value
            and self.user.GetRegisteredRawInputDevices(
                rows, ctypes.byref(count), ctypes.sizeof(Registration)
            )
            == 0xFFFFFFFF
        ):
            raise ctypes.WinError()
        if any(row.page == 1 and row.usage == 6 for row in rows[: count.value]):
            raise OSError("keyboard Raw Input is already registered in this process")
        # INPUTSINK | DEVNOTIFY. Never NOLEGACY: ordinary shortcuts remain unchanged.
        registration = Registration(1, 6, 0x100 | 0x2000, window)
        if not self.user.RegisterRawInputDevices(
            ctypes.byref(registration), 1, ctypes.sizeof(registration)
        ):
            raise ctypes.WinError()

    def packet(self, handle):
        size = U32()
        if (
            self.user.GetRawInputData(
                handle, 0x10000003, None, ctypes.byref(size), ctypes.sizeof(Header)
            )
            == 0xFFFFFFFF
        ):
            raise ctypes.WinError()
        if not ctypes.sizeof(Header) <= size.value <= 4096:
            raise ValueError("invalid Raw Input packet size")
        data = ctypes.create_string_buffer(size.value)
        length = self.user.GetRawInputData(
            handle, 0x10000003, data, ctypes.byref(size), ctypes.sizeof(Header)
        )
        if length != size.value:
            raise OSError("Raw Input packet read failed")
        return data.raw

    def pump(self, window):
        from ctypes import wintypes

        message = wintypes.MSG()
        for _ in range(64):
            if not self.user.PeekMessageW(ctypes.byref(message), window, 0, 0, 1):
                break
            self.user.TranslateMessage(ctypes.byref(message))
            self.user.DispatchMessageW(ctypes.byref(message))
        else:
            raise OSError("Raw Input message backlog; discard pending declaration")

    def default(self, *args):
        return self.user.DefWindowProcW(*args)

    def remove(self):
        registration = Registration(1, 6, 1, None)
        if not self.user.RegisterRawInputDevices(
            ctypes.byref(registration), 1, ctypes.sizeof(registration)
        ):
            raise ctypes.WinError()

    def destroy(self, window):
        if not self.user.DestroyWindow(window):
            raise ctypes.WinError()

    def unregister(self, name):
        if not self.user.UnregisterClassW(name, self.instance):
            raise ctypes.WinError()
