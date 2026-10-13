"""Per-session Windows mutex: one Game Point/diagnostic owner for this keypad."""

import ctypes
import os


class Ownership:
    def __init__(self):
        if os.name != "nt":
            raise OSError("keypad controller ownership requires Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, True, "Local\\AC-Copilot-Keypad-Profiles-v1")
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, "cannot acquire keypad controller ownership")
        if error == 183:  # ERROR_ALREADY_EXISTS; initial ownership was NOT granted.
            self.kernel.CloseHandle(handle)
            raise OSError("another controller owns the keypad in this Windows session")
        self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SimulatedOwnership:
    """Explicit test transport ownership; never selected for the real HID opener."""

    def close(self):
        pass
