"""Windows context and injected key chords; imports are safe on non-Windows hosts."""

from __future__ import annotations

import csv
import ctypes
import io
import os
import subprocess

from tools.rig_controls.profiles import Binding, Context

VK = {key: ord(key) for key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}
VK.update({f"F{i}": 0x6F + i for i in range(1, 25)})
VK.update(
    dict(
        CTRL=0x11,
        SHIFT=0x10,
        ALT=0x12,
        WIN=0x5B,
        SPACE=0x20,
        ENTER=0x0D,
        ESC=0x1B,
        TAB=9,
        BACKSPACE=8,
        UP=0x26,
        DOWN=0x28,
        LEFT=0x25,
        RIGHT=0x27,
        HOME=0x24,
        END=0x23,
        PAGEUP=0x21,
        PAGEDOWN=0x22,
        INSERT=0x2D,
        DELETE=0x2E,
    )
)


def _libraries():
    if os.name != "nt":
        raise OSError("keypad context/key injection requires Windows")
    return ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL(
        "kernel32", use_last_error=True
    )


def foreground_context(include_running: bool = False) -> Context:
    user, kernel = _libraries()
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    hwnd = user.GetForegroundWindow()
    pid = ctypes.c_uint32()
    title = ctypes.create_unicode_buffer(1024)
    executable = ""
    if hwnd:
        user.GetWindowTextW(hwnd, title, len(title))
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(32768)
                count = ctypes.c_uint32(len(buf))
                if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(count)):
                    executable = buf.value.rsplit("\\", 1)[-1]
            finally:
                kernel.CloseHandle(handle)
    running = frozenset()
    if include_running:
        try:
            result = subprocess.run(
                ["tasklist.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=0.4,
                check=True,
                creationflags=0x08000000,
            )
        except subprocess.SubprocessError as exc:
            raise OSError("running-process condition could not be read") from exc
        running = frozenset(
            row[0].casefold() for row in csv.reader(io.StringIO(result.stdout)) if row
        )
    return Context(executable, title.value, running)


def send_key(key: str, down: bool):
    user, _ = _libraries()
    ptr = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class Keyboard(ctypes.Structure):
        _fields_ = [
            ("vk", ctypes.c_uint16),
            ("scan", ctypes.c_uint16),
            ("flags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("extra", ptr),
        ]

    class Mouse(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_int32),
            ("dy", ctypes.c_int32),
            ("data", ctypes.c_uint32),
            ("flags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("extra", ptr),
        ]

    class Payload(ctypes.Union):
        _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]

    class Input(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("payload", Payload)]

    extended = key in {
        "UP",
        "DOWN",
        "LEFT",
        "RIGHT",
        "HOME",
        "END",
        "PAGEUP",
        "PAGEDOWN",
        "INSERT",
        "DELETE",
        "WIN",
    }
    flags = (0 if down else 2) | (1 if extended else 0)
    record = Input(1, Payload(keyboard=Keyboard(VK[key], 0, flags, 0, 0)))
    user.SendInput.argtypes = [ctypes.c_uint32, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = ctypes.c_uint32
    if user.SendInput(1, ctypes.byref(record), ctypes.sizeof(record)) != 1:
        raise OSError("Windows rejected keyboard injection (focus/integrity boundary)")


class Actions:
    def __init__(self, sender=send_key):
        self.sender = sender
        self.counts = {}
        self.last_error = ""

    def perform(self, binding: Binding, pressed: bool, impulse: bool = False):
        if binding.action == "noop":
            return
        if binding.action == "rig":
            if pressed:
                self.last_error = f"{binding.name}: target integration not activated"
            return
        keys = binding.keys if pressed else tuple(reversed(binding.keys))
        for key in keys:
            count = self.counts.get(key, 0)
            if pressed:
                if count == 0:
                    # Remember first so release_all can undo a partial chord failure.
                    self.counts[key] = 1
                    self.sender(key, True)
                else:
                    self.counts[key] = count + 1
            elif count:
                if count == 1:
                    self.sender(key, False)
                    del self.counts[key]
                else:
                    self.counts[key] = count - 1
        if impulse and pressed:
            self.perform(binding, False)

    def release_all(self):
        self.last_error = ""
        first_error = None
        for key in reversed(list(self.counts)):
            try:
                self.sender(key, False)
            except OSError as exc:
                first_error = first_error or exc
            else:
                del self.counts[key]
        if first_error:
            raise first_error
