"""Auto-skip Content Manager's pre-drive "Custom Shaders Patch data" dialog (#738).

On some boots CM's pre-drive patch-data fetch (``PatchBaseDataUpdater.TriggerAutoLoadAsync``)
hangs on a failing online request (CM Main Log: ``Cannot get data: The request was aborted``)
and the "Loading data for Custom Shaders Patch…" dialog blocks the launch: ``acs.exe`` never
spawns, the harness treats the attempt as stuck and relaunch-loops, and every relaunch re-opens
the same dialog (~2x launch cycles per drive; the fetch hangs ~60 s per data category and the
categories are walked sequentially, so one dialog outlives any sane attempt timeout). The
dialog exposes a real "Skip" button; invoking it makes CM proceed on its local cache and the
launch lands normally (proven live on AG_PC, 2026-08-08).

:class:`CmSkipWatcher` runs that skip inside the launcher: a daemon thread polls the desktop
for visible top-level windows owned by the Content Manager process, finds a UI Automation
button named "Skip" among their descendants, and invokes it. Design constraints:

* **stdlib-only** (raw ctypes COM; no comtypes/pywinauto) — the module rides in the
  PyInstaller-frozen Game Point launcher via :mod:`tools.ac_harness.resilient_launch`.
* **imports cleanly off-Windows** — CI exercises the click policy with a fake backend; every
  Win32/COM access happens at call time inside :class:`_UiaBackend` (rig-only).
* **never breaks a launch** — every poll tick is exception-bounded; failures land in
  ``last_error`` and are logged once per distinct message, and the launch proceeds exactly as
  it would have without the watcher.

Click policy: a candidate window must be seen on ``confirm_polls`` consecutive polls before
its Skip is invoked (a healthy fetch that closes the dialog quickly is left alone), and a
persisting window is re-clicked only after ``click_cooldown`` (the failing fetch walks several
data categories through one dialog, so one click is not always enough).

Diagnostic CLI (rig-only; **not** a production entrypoint — production behavior enters through
``auto_drive`` / ``resilient_launch``, which arm the watcher themselves)::

    python -m tools.ac_harness.cm_dialog_watcher --scan            # one probe, print candidates
    python -m tools.ac_harness.cm_dialog_watcher --list-buttons    # print every button name seen
    python -m tools.ac_harness.cm_dialog_watcher --watch 30        # run the watcher for 30 s
    # point at another process image (used by the synthetic-WPF live proof):
    python -m tools.ac_harness.cm_dialog_watcher --scan --process-image powershell.exe
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

DEFAULT_PROCESS_IMAGE = "Content Manager.exe"
DEFAULT_BUTTON_NAME = "Skip"
DEFAULT_POLL_INTERVAL_S = 1.0
DEFAULT_CONFIRM_POLLS = 2
DEFAULT_CLICK_COOLDOWN_S = 5.0

#: Case-insensitive substrings that identify the CSP patch-data dialog by its **content**
#: (Codex #743: only click Skip on the known dialog, not any CM window that happens to expose
#: a Skip button). The live dialog's *window title* is the generic "Waiting…", so title alone
#: is not a reliable discriminator — the durable identity is the dialog's own text. CM is a WPF
#: app, so its content TextBlocks are exposed as UIA elements whose Name the backend can read.
#: Verified live on AG_PC 2026-08-09: the real dialog text carries "Loading data for Custom
#: Shaders Patch" / "Config for track …" / "Loading entries list". A candidate qualifies only
#: when a signature matches its title OR any descendant text — and a Skip-bearing CM window that
#: matches NONE is logged and left alone, so a signature miss is self-diagnosing.
DEFAULT_DIALOG_SIGNATURES: tuple[str, ...] = (
    "custom shaders patch",
    "loading data for",
    "loading entries",
    "config for track",
    "patch data",
)

#: Env override so any launch path (including the frozen Game Point launcher, which cannot pass
#: new CLI args to its resilient child) can disable the default-on watcher (Codex #743).
ENV_DIALOG_SKIP = "AC_COPILOT_CM_DIALOG_SKIP"
_ENV_DISABLE_VALUES = frozenset({"0", "false", "no", "off", "disable", "disabled"})

#: Upper bound on distinct window titles retained for forensics (memory hygiene).
_MAX_TITLES_TRACKED = 32
_MAX_TITLE_LEN = 120


def dialog_skip_enabled(cli_opt_out: bool, *, env: dict[str, str] | None = None) -> bool:
    """Resolve whether the CSP-dialog watcher should arm for this launch.

    Default-on; disabled by either the CLI opt-out (``--no-cm-dialog-skip``) or the
    ``AC_COPILOT_CM_DIALOG_SKIP`` env override (Codex #743 — the frozen Game Point launcher
    cannot add CLI args to its resilient child, so an env override is the operator's kill-switch).
    """

    if cli_opt_out:
        return False
    source = os.environ if env is None else env
    raw = source.get(ENV_DIALOG_SKIP)
    if raw is not None and raw.strip().casefold() in _ENV_DISABLE_VALUES:
        return False
    return True


@dataclass(frozen=True)
class DialogCandidate:
    """A visible top-level window of the target process that exposes a Skip button."""

    hwnd: int
    title: str


class SkipBackend(Protocol):
    """Mechanism half of the watcher: window discovery + one button invoke."""

    def find_candidates(self) -> list[DialogCandidate]:
        """Return target-process windows currently exposing an invokable Skip button."""

    def invoke_skip(self, hwnd: int) -> bool:
        """Invoke the Skip button under ``hwnd``; True when the invoke was delivered."""

    def close(self) -> None:
        """Release native resources (called on the watcher thread at shutdown)."""


def available() -> bool:
    """Whether the real UIA backend can run here (Windows only)."""

    return sys.platform == "win32"


class CmSkipWatcher:
    """Poll for the CM patch-data dialog and invoke its own Skip button (#738).

    Policy lives here (confirm-before-click, per-window cooldown, forensic counters);
    the OS mechanism is behind ``backend_factory`` so CI can drive :meth:`_tick`
    synchronously with a fake. Thread-safe counters; ``start``/``stop`` are idempotent.
    """

    def __init__(
        self,
        *,
        log: Callable[[str], None] | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
        confirm_polls: int = DEFAULT_CONFIRM_POLLS,
        click_cooldown: float = DEFAULT_CLICK_COOLDOWN_S,
        process_image: str = DEFAULT_PROCESS_IMAGE,
        button_name: str = DEFAULT_BUTTON_NAME,
        dialog_signatures: Sequence[str] = DEFAULT_DIALOG_SIGNATURES,
        backend_factory: Callable[[], SkipBackend] | None = None,
        clock: Callable[[], float] = time.monotonic,
        join_timeout: float = 5.0,
    ) -> None:
        self._log = log
        self._poll_interval = max(0.05, float(poll_interval))
        self._confirm_polls = max(1, int(confirm_polls))
        self._click_cooldown = max(0.0, float(click_cooldown))
        self.process_image = process_image
        self.button_name = button_name
        self.dialog_signatures = tuple(dialog_signatures)
        self._backend_factory = backend_factory
        self._clock = clock
        self._join_timeout = max(0.0, float(join_timeout))
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        # Groups _tick's stop-check with its Skip invoke so a tick entering after stop() has set
        # _stop_event skips instead of clicking (Codex #743 TOCTOU). stop() sets the event WITHOUT
        # this lock (P1: a hung invoke holds it, and a lock-taking stop() would block forever), so
        # this lock only orders the check+invoke pair — it never gates shutdown.
        self._invoke_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # Forensic state (guarded by _lock; read by the launch loop for report suffixes).
        self.skips = 0
        self.clicks_failed = 0
        self.last_error: str | None = None
        self.titles_seen: dict[str, int] = {}
        # Per-window policy state (watcher thread only).
        self._seen_polls: dict[int, int] = {}
        self._last_click: dict[int, float] = {}
        self._last_reported_error: str | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Arm the watcher. Returns False (and stays a no-op) where UIA is unavailable."""

        if self.running:
            return True
        if self._backend_factory is None:
            if not available():
                self._emit("disabled: UI Automation unavailable on this platform")
                return False
            self._backend_factory = lambda: _UiaBackend(  # pragma: no cover - rig-only
                process_image=self.process_image,
                button_name=self.button_name,
                dialog_signatures=self.dialog_signatures,
            )
        self._stop_event.clear()
        thread = threading.Thread(target=self._run, name="cm-dialog-skip", daemon=True)
        try:
            thread.start()
        except (RuntimeError, OSError) as exc:  # e.g. OS cannot allocate another thread
            # The watcher is best-effort: a failure to arm must never break the launch (Codex #743).
            self._thread = None
            self._note_error(f"could not start watcher thread: {exc!r}")
            return False
        self._thread = thread
        self._emit(
            f"armed (process={self.process_image!r} button={self.button_name!r} "
            f"poll={self._poll_interval:g}s confirm={self._confirm_polls} "
            f"cooldown={self._click_cooldown:g}s)"
        )
        return True

    def stop(self) -> None:
        """Disarm and join the watcher thread (bounded; safe to call repeatedly).

        If the join times out — the thread is blocked in a cross-process UIA scan longer than
        the join budget — the live thread reference is **kept**, not discarded (Codex #743): a
        cleared reference would let ``running`` read False and a later ``start()`` spawn a second
        watcher that coexists with the orphan. The orphan itself checks ``_stop_event`` after its
        scan (see :meth:`_tick`), so it will not invoke Skip once stop was requested.

        The event is set FIRST and **without** ``_invoke_lock`` (Codex #743 P1): a cross-process
        ``invoke_skip`` that hangs holds the lock, so acquiring it here would make ``stop()`` — on
        every launch path's success/exit — block forever and never reach the bounded join. Setting
        the event before the join still prevents any NEW click: ``_tick`` re-reads it under the
        lock immediately before invoking, so a tick entering after the signal skips. Only a click
        already past that check can still fire, and that lands on the CSP dialog's own Skip (the
        intended action, merely late) — a benign, unavoidable in-flight residual.
        """

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._join_timeout)
        if thread is None or not thread.is_alive():
            self._thread = None

    def __enter__(self) -> CmSkipWatcher:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # -- reporting ---------------------------------------------------------

    def summary(self) -> str | None:
        """Short evidence string for launch detail messages; None when nothing happened."""

        with self._lock:
            if not self.skips and not self.clicks_failed and self.last_error is None:
                return None
            parts = [f"csp_dialog_skips={self.skips}"]
            if self.clicks_failed:
                parts.append(f"skip_clicks_failed={self.clicks_failed}")
            if self.last_error is not None:
                parts.append(f"skip_watcher_error={self.last_error!r}")
            return " ".join(parts)

    def as_dict(self) -> dict[str, object]:
        """Structured forensic snapshot (report embedding / tests)."""

        with self._lock:
            return {
                "skips": self.skips,
                "clicks_failed": self.clicks_failed,
                "last_error": self.last_error,
                "titles_seen": dict(self.titles_seen),
            }

    # -- internals ---------------------------------------------------------

    def _emit(self, msg: str) -> None:
        if self._log is None:
            return
        try:
            self._log(f"csp-dialog-skip: {msg}")
        except Exception:  # noqa: BLE001 - a logging fault must never hurt the launch
            pass

    def _note_error(self, msg: str) -> None:
        with self._lock:
            self.last_error = msg
        if msg != self._last_reported_error:
            self._last_reported_error = msg
            self._emit(f"error: {msg}")

    def _run(self) -> None:
        backend: SkipBackend | None = None
        try:
            backend = self._backend_factory()  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - backend init is best-effort
            self._note_error(f"backend init failed: {exc!r}")
            return
        try:
            while not self._stop_event.wait(self._poll_interval):
                self._tick(backend)
        except Exception as exc:  # noqa: BLE001 - the watcher must never propagate
            self._note_error(f"watcher thread aborted: {exc!r}")
        finally:
            try:
                backend.close()
            except Exception as exc:  # noqa: BLE001
                self._note_error(f"backend close failed: {exc!r}")

    def _tick(self, backend: SkipBackend) -> None:
        """One poll: observe candidates, click the confirmed ones off cooldown."""

        try:
            candidates = backend.find_candidates()
        except Exception as exc:  # noqa: BLE001 - scan faults are recorded, never raised
            self._note_error(f"scan failed: {exc!r}")
            # A failed scan invalidates the pending confirmation (Codex #743): otherwise a window
            # seen once, then a transient UIA fault, then seen again would count as the 2nd
            # consecutive poll and be clicked immediately, bypassing the confirm-before-click gate.
            self._seen_polls.clear()
            self._last_click.clear()
            return
        # The scan is a cross-process UIA call that can outlast stop()'s join budget (Codex #743):
        # if a stop was requested while we were blocked in it, do NOT invoke anything — the launch
        # phase is over and a click now would be an unrelated CM action after the fact.
        if self._stop_event.is_set():
            return
        now = self._clock()
        live: set[int] = set()
        for cand in candidates:
            live.add(cand.hwnd)
            polls = self._seen_polls.get(cand.hwnd, 0) + 1
            self._seen_polls[cand.hwnd] = polls
            self._record_title(cand.title)
            if polls < self._confirm_polls:
                continue
            last = self._last_click.get(cand.hwnd)
            if last is not None and (now - last) < self._click_cooldown:
                continue
            # Invoke under _invoke_lock with the stop-check INSIDE the lock: stop() also sets the
            # event under this lock, so a stop can never land between the check and the click
            # (Codex #743 TOCTOU). skipped==True means the event was set → bail without invoking.
            skipped = False
            with self._invoke_lock:
                if self._stop_event.is_set():
                    skipped = True
                else:
                    self._last_click[cand.hwnd] = now
                    try:
                        delivered = backend.invoke_skip(cand.hwnd)
                    except Exception as exc:  # noqa: BLE001 - a failed click must not stop polling
                        with self._lock:
                            self.clicks_failed += 1
                        self._note_error(f"invoke failed on {cand.title!r}: {exc!r}")
                        continue
            if skipped:
                return
            if delivered:
                with self._lock:
                    self.skips += 1
                self._emit(f"skipped dialog {cand.title!r} (hwnd={cand.hwnd:#x})")
            else:
                with self._lock:
                    self.clicks_failed += 1
                self._emit(f"skip button vanished before invoke on {cand.title!r}")
        # A window that vanished (dialog closed) drops its policy state; a NEW dialog —
        # even at a recycled hwnd — then earns a fresh confirm window before being clicked.
        self._seen_polls = {h: c for h, c in self._seen_polls.items() if h in live}
        self._last_click = {h: t for h, t in self._last_click.items() if h in live}

    def _record_title(self, title: str) -> None:
        clipped = title[:_MAX_TITLE_LEN]
        with self._lock:
            if clipped in self.titles_seen:
                self.titles_seen[clipped] += 1
            elif len(self.titles_seen) < _MAX_TITLES_TRACKED:
                self.titles_seen[clipped] = 1


# ---------------------------------------------------------------------------
# Real Windows backend: raw-ctypes UI Automation COM client. Rig-only.
# ---------------------------------------------------------------------------

# UIA constants (UIAutomationClient.h).
_TREESCOPE_DESCENDANTS = 0x4
_UIA_CONTROLTYPE_PROPERTY_ID = 30003
_UIA_BUTTON_CONTROLTYPE_ID = 50000
_UIA_TEXT_CONTROLTYPE_ID = 50020
_UIA_INVOKE_PATTERN_ID = 10000

_CLSID_CUIAUTOMATION = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
_IID_IUIAUTOMATION = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
_IID_IUIAUTOMATION_INVOKE_PATTERN = "{fb377fbe-8ea6-46d5-9c73-6499642d3059}"

# Vtable slot indices (after IUnknown 0-2), per UIAutomationClient.idl method order.
_VT_AUTOMATION_ELEMENT_FROM_HANDLE = 6
_VT_AUTOMATION_CREATE_PROPERTY_CONDITION = 23
_VT_ELEMENT_FIND_ALL = 6
_VT_ELEMENT_GET_CURRENT_PATTERN = 16
_VT_ELEMENT_GET_CURRENT_NAME = 23
_VT_ELEMENT_ARRAY_GET_LENGTH = 3
_VT_ELEMENT_ARRAY_GET_ELEMENT = 4
_VT_INVOKE_PATTERN_INVOKE = 3
_VT_IUNKNOWN_QUERY_INTERFACE = 0
_VT_IUNKNOWN_RELEASE = 2


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_ulong),
        ("data2", ctypes.c_ushort),
        ("data3", ctypes.c_ushort),
        ("data4", ctypes.c_ubyte * 8),
    ]


class _Variant(ctypes.Structure):
    """Minimal by-value VARIANT (x64: 8-byte header + 16-byte union)."""

    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("llVal", ctypes.c_longlong),
        ("_pad", ctypes.c_longlong),
    ]


_VT_I4 = 3


class _UiaBackend:  # pragma: no cover - rig-only (Windows UIA COM)
    """Find target-process windows with a UIA "Skip" button and invoke it.

    All COM state is created on the calling (watcher) thread; :meth:`close` must run on
    the same thread. HRESULT failures raise ``OSError`` (ctypes ``HRESULT`` restype),
    which the policy layer converts into recorded errors.
    """

    def __init__(
        self,
        *,
        process_image: str = DEFAULT_PROCESS_IMAGE,
        button_name: str = DEFAULT_BUTTON_NAME,
        dialog_signatures: Sequence[str] = DEFAULT_DIALOG_SIGNATURES,
    ) -> None:
        if not available():
            raise RuntimeError("UIA backend requires Windows")
        self._process_image = process_image.casefold()
        self._button_target = button_name.strip().casefold()
        self._signatures = tuple(s.casefold() for s in dialog_signatures if s)
        self._ole32 = ctypes.windll.ole32
        self._oleaut32 = ctypes.windll.oleaut32
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._declare_win32_prototypes()
        # COINIT_MULTITHREADED: single dedicated worker thread, no message pump needed.
        hr = self._ole32.CoInitializeEx(None, 0)
        # 0/1 = initialized here (owe CoUninitialize); RPC_E_CHANGED_MODE = host thread
        # already has an apartment — usable as-is, nothing owed.
        self._owe_couninit = hr in (0, 1)
        self._automation = self._co_create_automation()
        self._button_condition = self._create_controltype_condition(_UIA_BUTTON_CONTROLTYPE_ID)
        self._text_condition = self._create_controltype_condition(_UIA_TEXT_CONTROLTYPE_ID)

    def _declare_win32_prototypes(self) -> None:
        """Set pointer-width-correct restype/argtypes for the raw HANDLE/HWND APIs (Codex #743).

        Without this, ctypes defaults a function's return type to C ``int`` (32-bit), so on the
        64-bit rig ``OpenProcess`` would truncate a >32-bit HANDLE before
        ``QueryFullProcessImageNameW`` — silently returning an empty image name and making the
        watcher miss every CM window. Declared once here so the whole backend is width-safe.
        """

        from ctypes import wintypes  # Windows-only; backend is constructed only on Windows

        k, u = self._kernel32, self._user32
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        # EnumWindows returns BOOL and takes (WNDENUMPROC, LPARAM); leave its argtypes at the
        # ctypes default so the inline WINFUNCTYPE callback keeps passing cleanly — it returns no
        # HANDLE, so it carries no truncation risk.
        u.EnumWindows.restype = wintypes.BOOL

    # -- SkipBackend interface --------------------------------------------

    def find_candidates(self) -> list[DialogCandidate]:
        out: list[DialogCandidate] = []
        for hwnd, title in self._target_windows():
            button = self._find_skip_button(hwnd)
            if button is None:
                continue
            self._release(button)
            # Codex #743: a Skip button + CM ownership is necessary but not sufficient — clicking
            # Skip on some *other* CM window would be an unrelated action. Require the CSP
            # patch-data dialog's own content/title signature before treating it as a target.
            if self._signatures and not self._window_matches_signature(hwnd, title):
                continue
            out.append(DialogCandidate(hwnd=hwnd, title=title))
        return out

    def invoke_skip(self, hwnd: int) -> bool:
        button = self._find_skip_button(hwnd)
        if button is None:
            return False
        try:
            pattern_unk = ctypes.c_void_p()
            self._call(
                button,
                _VT_ELEMENT_GET_CURRENT_PATTERN,
                (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
                _UIA_INVOKE_PATTERN_ID,
                ctypes.byref(pattern_unk),
            )
            if not pattern_unk.value:
                return False
            try:
                invoke = self._query_interface(pattern_unk, _IID_IUIAUTOMATION_INVOKE_PATTERN)
                try:
                    self._call(invoke, _VT_INVOKE_PATTERN_INVOKE, ())
                finally:
                    self._release(invoke)
            finally:
                self._release(pattern_unk)
            return True
        finally:
            self._release(button)

    def close(self) -> None:
        self._release(self._button_condition)
        self._button_condition = None
        self._release(self._text_condition)
        self._text_condition = None
        self._release(self._automation)
        self._automation = None
        if self._owe_couninit:
            self._ole32.CoUninitialize()
            self._owe_couninit = False

    # -- signature identity (Codex #743) ----------------------------------

    def _window_matches_signature(self, hwnd: int, title: str) -> bool:
        """True when the window's title OR any descendant static-text names a CSP-data signature."""

        haystack = title.casefold()
        if any(sig in haystack for sig in self._signatures):
            return True
        for text in self._descendant_text(hwnd):
            folded = text.casefold()
            if any(sig in folded for sig in self._signatures):
                return True
        return False

    def _descendant_text(self, hwnd: int) -> list[str]:
        """Names of every descendant Text control of ``hwnd`` (elements released, names kept)."""

        names: list[str] = []

        def visit(_element: ctypes.c_void_p, name: str) -> bool:
            names.append(name)
            return False  # keep walking; never take ownership

        self._walk_condition(hwnd, self._text_condition, visit)
        return names

    # -- diagnostics (CLI only) -------------------------------------------

    def enumerate_buttons(self) -> list[tuple[str, list[str]]]:
        """(window title, [button names]) for every target-process window — forensics."""

        out: list[tuple[str, list[str]]] = []
        for hwnd, title in self._target_windows():
            names = [name for _button, name in self._iter_buttons_released(hwnd)]
            out.append((title, names))
        return out

    def dump_windows(self) -> list[dict[str, object]]:
        """Per target-process window: title, button names, text names, signature verdict.

        The ground-truth capture used to confirm the #743 signature gate against the *real*
        CSP-data dialog (its window title is the generic "Waiting…"; identity is in the text).
        """

        out: list[dict[str, object]] = []
        for hwnd, title in self._target_windows():
            buttons = [name for _b, name in self._iter_buttons_released(hwnd)]
            texts = self._descendant_text(hwnd)
            out.append(
                {
                    "hwnd": hwnd,
                    "title": title,
                    "buttons": buttons,
                    "texts": texts,
                    "has_skip": any(n.strip().casefold() == self._button_target for n in buttons),
                    "matches_signature": self._window_matches_signature(hwnd, title),
                }
            )
        return out

    # -- COM plumbing ------------------------------------------------------

    @staticmethod
    def _com_method(ptr: ctypes.c_void_p, index: int, argtypes: tuple) -> Callable[..., int]:
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
        return prototype(vtable[index])

    def _call(self, ptr: ctypes.c_void_p, index: int, argtypes: tuple, *args: object) -> int:
        return self._com_method(ptr, index, argtypes)(ptr, *args)

    def _release(self, ptr: ctypes.c_void_p | None) -> None:
        if ptr is None or not ptr.value:
            return
        try:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[
                    _VT_IUNKNOWN_RELEASE
                ]
            )
            release(ptr)
        except OSError:
            pass

    def _guid_from_string(self, guid_str: str) -> _Guid:
        guid = _Guid()
        hr = self._ole32.CLSIDFromString(ctypes.c_wchar_p(guid_str), ctypes.byref(guid))
        if hr != 0:
            raise OSError(f"CLSIDFromString({guid_str}) failed: {hr:#010x}")
        return guid

    def _co_create_automation(self) -> ctypes.c_void_p:
        clsid = self._guid_from_string(_CLSID_CUIAUTOMATION)
        iid = self._guid_from_string(_IID_IUIAUTOMATION)
        ptr = ctypes.c_void_p()
        hr = self._ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(iid),
            ctypes.byref(ptr),
        )
        if hr != 0 or not ptr.value:
            raise OSError(f"CoCreateInstance(CUIAutomation) failed: {hr:#010x}")
        return ptr

    def _query_interface(self, ptr: ctypes.c_void_p, iid_str: str) -> ctypes.c_void_p:
        iid = self._guid_from_string(iid_str)
        out = ctypes.c_void_p()
        self._call(
            ptr,
            _VT_IUNKNOWN_QUERY_INTERFACE,
            (ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)),
            ctypes.byref(iid),
            ctypes.byref(out),
        )
        if not out.value:
            raise OSError(f"QueryInterface({iid_str}) returned NULL")
        return out

    def _create_controltype_condition(self, control_type_id: int) -> ctypes.c_void_p:
        variant = _Variant()
        variant.vt = _VT_I4
        variant.llVal = control_type_id
        out = ctypes.c_void_p()
        self._call(
            self._automation,
            _VT_AUTOMATION_CREATE_PROPERTY_CONDITION,
            (ctypes.c_int, _Variant, ctypes.POINTER(ctypes.c_void_p)),
            _UIA_CONTROLTYPE_PROPERTY_ID,
            variant,
            ctypes.byref(out),
        )
        if not out.value:
            raise OSError(f"CreatePropertyCondition(ControlType=={control_type_id}) returned NULL")
        return out

    # -- window + element walking -----------------------------------------

    def _target_windows(self) -> list[tuple[int, str]]:
        """Visible top-level windows whose owning process image matches the target."""

        user32 = self._user32
        results: list[tuple[int, str]] = []
        image_cache: dict[int, str] = {}

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        def on_window(hwnd: int, _lparam: int) -> int:
            try:
                if not user32.IsWindowVisible(hwnd):
                    return 1
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return 1
                image = image_cache.get(pid.value)
                if image is None:
                    image = self._process_image_basename(pid.value)
                    image_cache[pid.value] = image
                if image != self._process_image:
                    return 1
                buf = ctypes.create_unicode_buffer(_MAX_TITLE_LEN + 1)
                user32.GetWindowTextW(hwnd, buf, _MAX_TITLE_LEN)
                results.append((hwnd, buf.value or ""))
            except Exception:  # noqa: BLE001 - keep enumerating other windows
                pass
            return 1

        user32.EnumWindows(on_window, 0)
        return results

    def _process_image_basename(self, pid: int) -> str:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            path = buf.value or ""
            return path.rsplit("\\", 1)[-1].casefold()
        finally:
            self._kernel32.CloseHandle(handle)

    def _iter_buttons_released(self, hwnd: int) -> list[tuple[None, str]]:
        """Names of every descendant button (elements released; names retained)."""

        names: list[tuple[None, str]] = []

        def visit(_button: ctypes.c_void_p, name: str) -> bool:
            names.append((None, name))
            return False  # keep walking

        self._walk_condition(hwnd, self._button_condition, visit)
        return names

    def _find_skip_button(self, hwnd: int) -> ctypes.c_void_p | None:
        """The first descendant button whose name case-insensitively equals the target.

        The returned element is owned by the caller (release after use). Name matching
        happens in Python (not a UIA Name condition) so it can be case/whitespace-neutral
        and so diagnostics can observe every button name.
        """

        found: list[ctypes.c_void_p] = []

        def visit(button: ctypes.c_void_p, name: str) -> bool:
            if name.strip().casefold() == self._button_target:
                found.append(button)
                return True  # stop; ownership transferred
            return False

        self._walk_condition(hwnd, self._button_condition, visit)
        return found[0] if found else None

    def _walk_condition(
        self,
        hwnd: int,
        condition: ctypes.c_void_p,
        visit: Callable[[ctypes.c_void_p, str], bool],
    ) -> None:
        """Call ``visit(element, name)`` per descendant of ``hwnd`` matching ``condition``.

        ``visit`` returns True to take ownership of the element and stop the walk;
        otherwise the element is released here.
        """

        element = ctypes.c_void_p()
        self._call(
            self._automation,
            _VT_AUTOMATION_ELEMENT_FROM_HANDLE,
            (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
            hwnd,
            ctypes.byref(element),
        )
        if not element.value:
            return
        try:
            array = ctypes.c_void_p()
            self._call(
                element,
                _VT_ELEMENT_FIND_ALL,
                (ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
                _TREESCOPE_DESCENDANTS,
                condition,
                ctypes.byref(array),
            )
            if not array.value:
                return
            try:
                length = ctypes.c_int()
                self._call(
                    array,
                    _VT_ELEMENT_ARRAY_GET_LENGTH,
                    (ctypes.POINTER(ctypes.c_int),),
                    ctypes.byref(length),
                )
                for index in range(length.value):
                    button = ctypes.c_void_p()
                    self._call(
                        array,
                        _VT_ELEMENT_ARRAY_GET_ELEMENT,
                        (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
                        index,
                        ctypes.byref(button),
                    )
                    if not button.value:
                        continue
                    taken = False
                    try:
                        name = self._element_name(button)
                        taken = visit(button, name)
                        if taken:
                            return
                    finally:
                        if not taken:
                            self._release(button)
            finally:
                self._release(array)
        finally:
            self._release(element)

    def _element_name(self, element: ctypes.c_void_p) -> str:
        bstr = ctypes.c_void_p()
        self._call(
            element,
            _VT_ELEMENT_GET_CURRENT_NAME,
            (ctypes.POINTER(ctypes.c_void_p),),
            ctypes.byref(bstr),
        )
        if not bstr.value:
            return ""
        try:
            return ctypes.wstring_at(bstr.value)
        finally:
            self._oleaut32.SysFreeString(bstr)


# ---------------------------------------------------------------------------
# Diagnostic CLI (rig-only; production entrypoints are auto_drive/resilient_launch).
# ---------------------------------------------------------------------------


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--process-image", default=DEFAULT_PROCESS_IMAGE)
    parser.add_argument("--button-name", default=DEFAULT_BUTTON_NAME)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument("--confirm-polls", type=int, default=DEFAULT_CONFIRM_POLLS)
    parser.add_argument("--click-cooldown", type=float, default=DEFAULT_CLICK_COOLDOWN_S)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true", help="one probe; print candidates")
    mode.add_argument(
        "--list-buttons", action="store_true", help="print every button name per window"
    )
    mode.add_argument(
        "--dump-tree",
        action="store_true",
        help="print title/buttons/texts/signature verdict per window (ground-truth capture)",
    )
    mode.add_argument("--watch", type=float, metavar="SECONDS", help="run the watcher")
    args = parser.parse_args(argv)
    if not available():
        print("UIA unavailable: Windows only", file=sys.stderr)
        return 2
    if args.scan or args.list_buttons or args.dump_tree:
        backend = _UiaBackend(process_image=args.process_image, button_name=args.button_name)
        try:
            if args.scan:
                candidates = backend.find_candidates()
                for cand in candidates:
                    print(f"candidate hwnd={cand.hwnd:#x} title={cand.title!r}")
                print(f"{len(candidates)} candidate(s)")
            elif args.dump_tree:
                import json

                for win in backend.dump_windows():
                    print(json.dumps(win, ensure_ascii=False))
            else:
                for title, names in backend.enumerate_buttons():
                    print(f"window {title!r}: buttons={names}")
        finally:
            backend.close()
        return 0
    watcher = CmSkipWatcher(
        log=print,
        poll_interval=args.poll_interval,
        confirm_polls=args.confirm_polls,
        click_cooldown=args.click_cooldown,
        process_image=args.process_image,
        button_name=args.button_name,
    )
    watcher.start()
    try:
        time.sleep(max(0.0, args.watch))
    finally:
        watcher.stop()
    print(f"done: {watcher.as_dict()}")
    return 0


if __name__ == "__main__":  # pragma: no cover - rig-only
    raise SystemExit(_main())
