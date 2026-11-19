"""The baseline input path never needs firmware writes or keyboard injection."""

import ctypes
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.rig_controls import keyboard
from tools.rig_controls.controller import Controller
from tools.rig_controls.profiles import Context, load_config, parse_config
from tools.rig_controls.runtime import Worker
from tools.rig_controls.windows import Actions

PROFILE = (
    Path(__file__).resolve().parents[1] / "tools/rig_controls/profiles.attestation-baseline.json"
)
ACTIVE = Context(running=frozenset({"acs.exe"}))
PRESS = [(0x11, True), (0x12, True), (0x41, True), (0x41, True)]
RELEASE = [(0x11, False), (0x12, False), (0x41, False)]


def data():
    return json.loads(PROFILE.read_text())


class Source:
    def __init__(self):
        self.events = []
        self.closed = False

    def read(self):
        events, self.events = self.events, []
        return events

    def close(self):
        self.closed = True


def no_keys(*args):
    raise AssertionError("baseline backend attempted keyboard injection")


def controller(sink=None):
    source = Source()
    actions = Actions(sender=no_keys, declare=sink)
    control = keyboard.KeyboardController(load_config(PROFILE), lambda: source, actions)
    control.step(ACTIVE, 0)
    return control, source, actions


def test_profile_preserves_managed_default_and_baseline_is_explicit():
    raw = data()
    assert parse_config(raw).backend == "baseline_keyboard"
    raw.pop("backend")
    assert parse_config(raw).backend == "managed_hid"
    assert parse_config(data()).select(Context()).name == "idle"


@pytest.mark.parametrize("backend", [None, "keyboard", [], True])
def test_unknown_backend_rejected(backend):
    raw = data()
    raw["backend"] = backend
    with pytest.raises(ValueError, match="backend"):
        parse_config(raw)


@pytest.mark.parametrize(
    "binding",
    [
        {"action": "key", "keys": ["A"]},
        {"action": "rig", "name": "shakers.power.toggle"},
    ],
)
def test_baseline_cannot_execute_keys_or_rig_actions(binding):
    raw = data()
    raw["profiles"][1]["bindings"]["button_1"] = binding
    with pytest.raises(ValueError, match="attestation only"):
        parse_config(raw)


@pytest.mark.parametrize("field", ["knob_cw", "knob_ccw", "knob_press"])
def test_no_knob_can_declare(field):
    raw = data()
    raw["profiles"][1]["bindings"][field] = {"action": "attest", "name": "human_control.declare"}
    with pytest.raises(ValueError):
        parse_config(raw)


def test_baseline_does_not_claim_rgb_control():
    raw = data()
    raw["profiles"][1]["rgb"] = [0, 255, 0]
    with pytest.raises(ValueError, match="RGB"):
        parse_config(raw)
    c, _, _ = controller()
    assert c.status()["rgb"] is None


def test_declaration_repeats_and_releases_use_existing_sink(monkeypatch, tmp_path):
    journal = tmp_path / "synthetic-declarations.jsonl"
    monkeypatch.setenv("AC_COPILOT_HUMAN_CONTROL_ATTESTATION", "1")
    monkeypatch.setenv("AC_COPILOT_HUMAN_DECLARATION_JOURNAL", str(journal))
    c, source, actions = controller()
    source.events = PRESS + RELEASE
    c.step(ACTIVE, 0.02)
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["kind"] == "declaration"
    assert actions.last_attestation == "human_control.declare"
    source.events = [(0x11, True), (0x12, True), (0x53, True), (0x53, False)]
    c.step(ACTIVE, 0.04)
    assert actions.last_attestation == "human_control.clear"
    assert len(journal.read_text().splitlines()) == 2
    c.close()
    assert source.closed


def test_default_off_never_writes(monkeypatch, tmp_path):
    journal = tmp_path / "not-created.jsonl"
    monkeypatch.delenv("AC_COPILOT_HUMAN_CONTROL_ATTESTATION", raising=False)
    monkeypatch.setenv("AC_COPILOT_HUMAN_DECLARATION_JOURNAL", str(journal))
    c, source, actions = controller()
    source.events = PRESS + RELEASE
    c.step(ACTIVE, 0.02)
    assert not journal.exists()
    assert "attestation not enabled" in actions.last_unavailable
    assert not actions.last_attestation


def test_failed_write_is_visible_and_never_reported_recorded():
    def broken_sink(action):
        raise OSError("journal not writable")

    c, source, actions = controller(broken_sink)
    source.events = PRESS + RELEASE
    c.step(ACTIVE, 0.02)
    assert "not recorded" in actions.last_error
    assert not actions.last_attestation


def test_desktop_and_context_change_do_not_reinterpret_pending_shortcuts():
    called = []
    c, source, _ = controller(called.append)
    source.events = PRESS
    c.step(Context(), 0.02)
    source.events = PRESS
    c.step(ACTIVE, 0.04)
    assert called == []
    source.events = PRESS + RELEASE
    c.step(ACTIVE, 0.06)
    assert called == ["human_control.declare"]


def test_late_poll_closes_source_without_processing_queued_press():
    called = []
    c, source, _ = controller(called.append)
    source.events = PRESS
    c.step(ACTIVE, 0.6)
    assert source.closed
    assert called == []
    assert "stalled" in c.error


def test_backend_reload_requires_restart(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(PROFILE.read_text())
    c, _, _ = controller()
    raw = data()
    raw["backend"] = "managed_hid"
    path.write_text(json.dumps(raw))
    assert not c.reload(path)
    assert c.config.backend == "baseline_keyboard"
    assert "restarting" in c.reload_error
    managed = Controller(parse_config(raw), lambda: None, Actions())
    path.write_text(PROFILE.read_text())
    assert not managed.reload(path)


def test_decoder_needs_per_device_modifiers_and_rejects_extra_modifiers():
    decoder = keyboard.ShortcutDecoder()
    assert decoder.feed(0x41, True) is None
    decoder.reset()
    for vk in (0x11, 0x12, 0x10, 0x41):
        assert decoder.feed(vk, True) is None
    decoder.reset()
    assert [decoder.feed(vk, down) for vk, down in PRESS + RELEASE].count((0, True)) == 1
    assert decoder.feed(0xFF, True) is None


def packet(device=7, vk=0x41, pressed=True, kind=1):
    header = keyboard.Header(
        kind, ctypes.sizeof(keyboard.Header) + ctypes.sizeof(keyboard.Key), device, 0
    )
    key = keyboard.Key(0, 0 if pressed else 1, 0, vk, 0x100 if pressed else 0x101, 0)
    return bytes(header) + bytes(key)


def test_packet_ignores_other_keyboards_and_non_keyboard_devices():
    assert keyboard.decode_packet(packet(), 7) == (0x41, True)
    assert keyboard.decode_packet(packet(pressed=False), 7) == (0x41, False)
    assert keyboard.decode_packet(packet(device=8), 7) is None
    assert keyboard.decode_packet(packet(kind=0), 7) is None


@pytest.mark.parametrize("value", [b"", packet()[:-1], packet(vk=255)])
def test_corrupt_packet_and_overrun_fail_closed(value):
    with pytest.raises(ValueError):
        keyboard.decode_packet(value, 7)


@pytest.mark.parametrize(
    "path,allowed",
    [
        (r"\\?\HID#VID_1209&PID_C55D&COL01#unit", True),
        (r"\\?\HID#vid_1209&pid_c55d#unit", True),
        (r"\\?\HID#VID_1209&PID_C55D0#unit", False),
        (r"\\?\HID#VID_1189&PID_8890#unit", False),
        (r"\\?\HID#VID_0000&PID_0000#unit", False),
    ],
)
def test_baseline_identity_is_exact(path, allowed):
    assert keyboard.is_baseline_keyboard(path) is allowed


class API:
    def __init__(self, devices=None):
        self.devices = [7] if devices is None else devices
        self.closed = []
        self.callback_type = lambda callback: callback
        self.next_packet = packet()

    def baseline_devices(self):
        return self.devices

    def create_window(self, name, callback):
        return 1, 2

    def register(self, window):
        pass

    def pump(self, window):
        pass

    def packet(self, handle):
        return self.next_packet

    def default(self, *args):
        return 0

    def remove(self):
        self.closed.append("remove")

    def destroy(self, window):
        self.closed.append("destroy")

    def unregister(self, name):
        self.closed.append("unregister")


def raw_source(monkeypatch, api):
    monkeypatch.setattr(keyboard, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(keyboard, "_WindowsAPI", lambda: api)
    return keyboard.RawKeyboardSource()


@pytest.mark.parametrize("devices", [[], [7, 8]])
def test_missing_or_ambiguous_device_is_unavailable(monkeypatch, devices):
    with pytest.raises(OSError, match="expected one"):
        raw_source(monkeypatch, API(devices))


def test_raw_source_filter_cleanup_and_no_output_api(monkeypatch):
    api = API()
    source = raw_source(monkeypatch, api)
    api.next_packet = packet(device=8)
    source._message(2, 0xFF, 0, 1)
    assert source.read() == []
    api.next_packet = packet()
    source._message(2, 0xFF, 0, 1)
    assert source.read() == [(0x41, True)]
    source.close()
    source.close()
    assert api.closed == ["remove", "destroy", "unregister"]
    assert not hasattr(source, "write")


def test_device_change_discards_pending_events(monkeypatch):
    source = raw_source(monkeypatch, API())
    source._message(2, 0xFF, 0, 1)
    source._message(2, 0xFE, 2, 7)
    with pytest.raises(OSError, match="devices changed"):
        source.read()
    source.close()


def test_initial_or_unrelated_device_arrival_does_not_invalidate_reader(monkeypatch):
    source = raw_source(monkeypatch, API())
    source._message(2, 0xFE, 1, 7)
    source._message(2, 0xFE, 1, 99)
    assert source.read() == []
    source.close()


def test_second_baseline_keyboard_invalidates_reader(monkeypatch):
    api = API()
    source = raw_source(monkeypatch, api)
    api.devices = [7, 8]
    source._message(2, 0xFE, 1, 8)
    with pytest.raises(OSError, match="devices changed"):
        source.read()
    source.close()


def test_raw_callback_fault_is_visible(monkeypatch):
    api = API()
    api.next_packet = b"bad"
    source = raw_source(monkeypatch, api)
    source._message(2, 0xFF, 0, 1)
    with pytest.raises(OSError, match="truncated"):
        source.read()
    source.close()


def test_close_continues_after_unregister_failure(monkeypatch):
    api = API()

    def broken_remove():
        api.closed.append("remove")
        raise OSError("remove failed")

    api.remove = broken_remove
    source = raw_source(monkeypatch, api)
    with pytest.raises(OSError, match="remove failed"):
        source.close()
    assert api.closed == ["remove", "destroy", "unregister"]


def test_worker_uses_same_lifecycle_for_baseline(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(PROFILE.read_text())
    source, called = Source(), []
    worker = Worker(
        path,
        keyboard_source=lambda: source,
        actions=Actions(sender=no_keys, declare=called.append),
        context_provider=lambda: ACTIVE,
    )
    worker.tick(0)
    source.events = PRESS + RELEASE
    worker.tick(0.02)
    assert called == ["human_control.declare"]
    assert worker.status()["backend"] == "baseline_keyboard"
    assert worker.status()["declaration"] == "human_control.declare"
    worker.stop()
    assert source.closed
