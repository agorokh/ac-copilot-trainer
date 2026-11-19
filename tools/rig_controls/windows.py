"""Windows context and injected key chords; imports are safe on non-Windows hosts."""

from __future__ import annotations

import ctypes
import os

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


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("usage", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("heap", ctypes.c_size_t),
        ("module", ctypes.c_uint32),
        ("threads", ctypes.c_uint32),
        ("parent", ctypes.c_uint32),
        ("priority", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("exe", ctypes.c_wchar * 260),
    ]


def _running_processes(kernel):
    """Read executable names directly; spawning tasklist can stall the input worker."""
    kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    for function in (kernel.Process32FirstW, kernel.Process32NextW):
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
        function.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if handle == ctypes.c_void_p(-1).value or handle is None:
        raise OSError("running-process snapshot could not be opened")
    try:
        entry = _ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        names = set()
        ctypes.set_last_error(0)
        found = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not found:
            raise OSError("running-process snapshot has no readable first entry")
        while found:
            names.add(entry.exe.casefold())
            ctypes.set_last_error(0)
            found = kernel.Process32NextW(handle, ctypes.byref(entry))
        # Match entry_launcher's existing Toolhelp compatibility convention, but
        # only after a successful First call. Initial failure never means empty.
        if ctypes.get_last_error() not in (0, 18):
            raise OSError("running-process snapshot could not be read completely")
        return frozenset(names)
    finally:
        kernel.CloseHandle(handle)


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
    running = _running_processes(kernel) if include_running else frozenset()
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
    def __init__(self, sender=send_key, declare=None):
        self.sender = sender
        # None resolves the #988 declaration journal lazily on each press, so the
        # default-off opt-in is honoured without restarting the worker.
        self.declare = declare
        self.counts = {}
        self.last_error = ""
        self.last_unavailable = ""
        self.last_attestation = ""

    def _declaration_sink(self):
        if self.declare is not None:
            return self.declare
        from tools.human_control_attestation import declaration_sink

        return declaration_sink()

    @property
    def attestation_enabled(self):
        return self._declaration_sink() is not None

    def perform(self, binding: Binding, pressed: bool, impulse: bool = False):
        if binding.action == "noop":
            return
        if binding.action == "rig":
            if pressed:
                self.last_unavailable = f"{binding.name}: target integration not activated"
            return
        if binding.action == "attest":
            if pressed and not impulse:
                self.last_attestation = ""
                sink = self._declaration_sink()
                if sink is None:
                    self.last_unavailable = f"{binding.name}: attestation not enabled"
                else:
                    try:
                        sink(binding.name)
                    except (OSError, ValueError) as exc:
                        # A lost declaration must be visible; the lap then abstains.
                        self.last_error = f"{binding.name}: declaration not recorded ({exc})"
                    else:
                        self.last_error = self.last_unavailable = ""
                        self.last_attestation = binding.name
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
        self.last_unavailable = ""
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
