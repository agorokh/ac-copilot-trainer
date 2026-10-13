"""Contract tests for profiles and routing without touching a real keypad."""

import copy
import json

import pytest

from tools.rig_controls.controller import Controller
from tools.rig_controls.profiles import Context, parse_config
from tools.rig_controls.protocol import capability, command, decode


def config():
    bindings = dict.fromkeys(
        ["button_1", "button_2", "button_3", "knob_cw", "knob_ccw", "knob_press"],
        {"action": "noop"},
    )
    return {
        "version": 1,
        "default": "racing",
        "manual_override": None,
        "profiles": [
            {"name": "racing", "rgb": [255, 0, 0], "bindings": bindings},
            {
                "name": "minecraft",
                "rgb": [0, 255, 0],
                "priority": 10,
                "when": {"foreground_process": ["javaw.exe"], "title_contains": "Minecraft"},
                "bindings": {**bindings, "button_1": {"action": "key", "keys": ["F3"]}},
            },
        ],
    }


def test_foreground_conditions_do_not_select_background_java():
    c = parse_config(config())
    assert c.select(Context("acs.exe", "Assetto", frozenset({"javaw.exe"}))).name == "racing"
    assert c.select(Context("JAVAW.EXE", "Minecraft 1.21")).name == "minecraft"
    assert c.select(Context("javaw.exe", "Other Java application")).name == "racing"


def test_running_condition_and_manual_override():
    data = config()
    data["profiles"][1]["when"] = {"running_process": ["Minecraft.Windows.exe"]}
    assert (
        parse_config(data).select(Context(running=frozenset({"minecraft.windows.exe"}))).name
        == "minecraft"
    )
    data["manual_override"] = "racing"
    assert (
        parse_config(data).select(Context(running=frozenset({"minecraft.windows.exe"}))).name
        == "racing"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.update(version=True),
        lambda c: c.update(default="missing"),
        lambda c: c.update(shell="powershell"),
        lambda c: c["profiles"][0].update(rgb=[256, 0, 0]),
        lambda c: c["profiles"][0]["bindings"].pop("knob_press"),
        lambda c: c["profiles"][0]["bindings"].update(
            button_1={"action": "key", "keys": ["DELETE_ALL"]}
        ),
        lambda c: c["profiles"][1].update(when={"foreground_process": []}),
        lambda c: c["profiles"][1].update(when={"title_contains": ""}),
        lambda c: c["profiles"][1].update(name="racing"),
    ],
)
def test_invalid_config_fails_closed(mutation):
    data = config()
    mutation(data)
    with pytest.raises(ValueError):
        parse_config(data)


def test_protocol_checks_identity_reserved_bytes_and_length():
    assert capability(bytes([7, 65, 67, 1, 4, 255, 0, 0, 0])) == 4
    assert command(5, (0, 255, 0)) == bytes([5, 1, 5, 0, 255, 0, 30, 0, 0])
    for packet in (b"", bytes([7, 65, 88, 1, 4, 255, 0, 0, 0])):
        with pytest.raises(ValueError):
            capability(packet)
    for packet in (bytes([4, 1, 5, 1, 7, 1, 0, 0, 0]), bytes([4, 1, 5, 1, 1, 1, 0, 0, 1])):
        with pytest.raises(ValueError):
            decode(packet)


class Device:
    def __init__(self, valid=True):
        self.valid = valid
        self.sent = []
        self.incoming = []
        self.closed = False

    def get_feature_report(self, report_id, length):
        return [7, 65, 67 if self.valid else 0, 1, 0, 255, 0, 0, 0]

    def write(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def read(self, length, timeout_ms=0):
        return self.incoming.pop(0) if self.incoming else []

    def close(self):
        self.closed = True

    def ack(self):
        p = self.sent[-1]
        self.incoming.append(bytes([6, 1, p[2], *p[3:6], 1, 0, 0]))

    def event(self, control, down=1, sequence=0, epoch=None):
        self.incoming.append(
            bytes(
                [
                    4,
                    1,
                    self.sent[-1][2] if epoch is None else epoch,
                    sequence,
                    control,
                    down,
                    0,
                    0,
                    0,
                ]
            )
        )


class Actions:
    def __init__(self):
        self.calls = []
        self.releases = 0

    def perform(self, binding, pressed, impulse=False):
        self.calls.append((binding, pressed, impulse))

    def release_all(self):
        self.releases += 1


def ready():
    device, actions = Device(), Actions()
    ctl = Controller(parse_config(config()), lambda: device, actions)
    context = Context("javaw.exe", "Minecraft")
    ctl.step(context, 0)
    device.ack()
    ctl.step(context, 0.01)
    assert ctl.status()["profile"] == "minecraft"
    return ctl, device, actions, context


def test_controller_routes_only_after_matching_colour_ack():
    d, a = Device(), Actions()
    ctl = Controller(parse_config(config()), lambda: d, a)
    context = Context("javaw.exe", "Minecraft")
    ctl.step(context, 0)
    d.event(1)
    ctl.step(context, 0.1)
    assert not a.calls
    d.ack()
    d.event(1, sequence=0)
    ctl.step(context, 0.2)
    assert a.calls[0][0].keys == ("F3",)


def test_duplicate_press_is_not_repeated_and_release_is_preserved():
    ctl, d, a, context = ready()
    d.event(1, sequence=0)
    d.event(1, sequence=0)
    d.event(1, sequence=1)
    d.event(1, down=0, sequence=2)
    ctl.step(context, 0.1)
    assert [call[1] for call in a.calls] == [True, False]


def test_all_six_events_and_knob_impulses_are_available():
    ctl, d, a, context = ready()
    for seq, control in enumerate(range(1, 7)):
        d.event(control, sequence=seq)
    ctl.step(context, 0.1)
    assert len(a.calls) == 6
    assert [call[2] for call in a.calls] == [False, False, False, True, True, False]


def test_sequence_gap_and_focus_change_release_held_keys():
    ctl, d, a, context = ready()
    d.event(1, sequence=0)
    ctl.step(context, 0.1)
    epoch = d.sent[-1][2]
    d.event(2, sequence=3)
    ctl.step(context, 0.2)
    assert a.releases >= 2
    assert d.sent[-1][2] != epoch
    assert ctl.status()["profile"] is None
    d.ack()
    ctl.step(Context("acs.exe", "Assetto"), 0.3)
    assert d.sent[-1][3:6] == bytes([255, 0, 0])


def test_ack_timeout_disconnects_and_wrong_capability_never_writes():
    d, a = Device(valid=False), Actions()
    ctl = Controller(parse_config(config()), lambda: d, a)
    ctl.step(Context(), 0)
    assert not d.sent and d.closed
    d = Device()
    ctl = Controller(parse_config(config()), lambda: d, a)
    ctl.step(Context(), 0)
    ctl.step(Context(), 0.6)
    assert d.closed and ctl.status()["state"] == "unavailable"


def test_reload_is_atomic_and_releases_previous_binding(tmp_path):
    ctl, d, a, context = ready()
    path = tmp_path / "profiles.json"
    path.write_text("{broken")
    assert not ctl.reload(path)
    assert ctl.status()["profile"] == "minecraft"
    data = copy.deepcopy(config())
    data["profiles"][1]["bindings"]["button_1"] = {"action": "key", "keys": ["E"]}
    path.write_text(json.dumps(data))
    assert ctl.reload(path)
    ctl.step(context, 0.1)
    assert ctl.status()["profile"] is None
    d.ack()
    d.event(1)
    ctl.step(context, 0.2)
    assert a.calls[-1][0].keys == ("E",)


def test_heartbeat_without_ack_releases_and_disconnects():
    ctl, d, a, context = ready()
    ctl.step(context, 1.1)
    ctl.step(context, 1.7)
    assert d.closed and ctl.status()["profile"] is None


def test_worker_reload_and_shutdown_own_the_handle(tmp_path):
    from tools.rig_controls.runtime import Worker

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(config()))
    d, a = Device(), Actions()
    worker = Worker(path, opener=lambda: d, actions=a, context_provider=lambda: Context())
    worker.tick(0)
    d.ack()
    worker.tick(0.1)
    assert worker.status()["profile"] == "racing"
    path.write_text("bad JSON")
    worker.tick(1)
    assert worker.status()["reload_error"]
    assert worker.status()["profile"] == "racing"
    worker.stop()
    assert d.closed


def test_key_executor_reference_counts_overlapping_chords():
    from tools.rig_controls.profiles import Binding
    from tools.rig_controls.windows import Actions

    events = []
    actions = Actions(sender=lambda key, down: events.append((key, down)))
    one, two = Binding("key", ("CTRL", "A")), Binding("key", ("CTRL", "B"))
    actions.perform(one, True)
    actions.perform(two, True)
    actions.perform(one, False)
    assert ("CTRL", False) not in events
    actions.release_all()
    assert events[-1] == ("CTRL", False)


def test_game_point_loads_opt_in_path_without_touching_device(tmp_path):
    from tools.rig_launcher.supervisor import GamePointConfig, GamePointSupervisor, LauncherPaths

    paths = LauncherPaths(tmp_path)
    paths.settings_path.write_text(json.dumps({"keypad_profiles": "profiles.json"}))
    cfg = GamePointConfig.from_env({}, paths=paths)
    assert cfg.keypad_profiles == "profiles.json"
    supervisor = GamePointSupervisor(GamePointConfig(paths=paths), environ={})
    assert supervisor.probe_keypad().state == "disabled"
    assert supervisor._keypad_worker is None


def test_cli_simulation_selects_red_green_red_and_all_controls():
    from tools.rig_controls.cli import simulate

    result = simulate(
        parse_config(config()),
        [
            {"foreground_process": "acs.exe", "title": "Assetto", "events": []},
            {
                "foreground_process": "javaw.exe",
                "title": "Minecraft",
                "events": [
                    {"control": name, "pressed": True}
                    for name in (
                        "button_1",
                        "button_2",
                        "button_3",
                        "knob_cw",
                        "knob_ccw",
                        "knob_press",
                    )
                ],
            },
            {"foreground_process": "acs.exe", "title": "Assetto", "events": []},
        ],
    )
    assert [row["profile"] for row in result["steps"]] == ["racing", "minecraft", "racing"]
    assert result["steps"][1]["rgb"] == [0, 255, 0]
    assert len(result["actions"]) == 6


def test_open_device_excludes_stock_even_with_same_usage(monkeypatch):
    import sys
    from types import SimpleNamespace

    from tools.rig_controls.protocol import open_device

    calls = []
    fake = SimpleNamespace(
        enumerate=lambda vid, pid: [
            {"vendor_id": 0x1189, "product_id": 0x8890, "usage_page": 0xFF31, "usage": 1}
        ],
        device=lambda: calls.append("opened"),
    )
    monkeypatch.setitem(sys.modules, "hid", fake)
    with pytest.raises(OSError):
        open_device()
    assert not calls


def test_late_ack_does_not_reactivate_expired_negotiation():
    d, a = Device(), Actions()
    ctl = Controller(parse_config(config()), lambda: d, a)
    ctl.step(Context(), 0)
    d.ack()
    ctl.step(Context(), 0.6)
    assert d.closed


def test_invalid_rig_name_is_validation_error():
    data = config()
    data["profiles"][0]["bindings"]["button_1"] = {"action": "rig", "name": []}
    with pytest.raises(ValueError):
        parse_config(data)


def test_chord_normalizes_modifiers_before_letters():
    data = config()
    data["profiles"][0]["bindings"]["button_1"] = {"action": "key", "keys": ["A", "CTRL"]}
    assert parse_config(data).profiles[0].bindings[0].keys == ("CTRL", "A")


def test_release_failure_still_closes_and_updates_status(tmp_path):
    from tools.rig_controls.runtime import Worker

    class BrokenActions(Actions):
        def release_all(self):
            raise OSError("keyup rejected")

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(config()))
    d = Device()
    worker = Worker(path, opener=lambda: d, actions=BrokenActions(), context_provider=Context)
    worker.tick(0)
    worker.stop()
    assert d.closed
    assert worker.status()["state"] == "unavailable"
    assert "keyup rejected" in worker.status()["error"]


def test_shutdown_publishes_unavailable_status(tmp_path):
    from tools.rig_controls.runtime import Worker

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(config()))
    d = Device()
    worker = Worker(path, opener=lambda: d, actions=Actions(), context_provider=Context)
    worker.tick(0)
    d.ack()
    worker.tick(0.1)
    worker.stop()
    assert worker.status()["profile"] is None
    assert worker.status()["state"] == "unavailable"


def test_contended_owner_never_opens_device(tmp_path):
    from tools.rig_controls.runtime import Worker

    def unavailable():
        raise OSError("another controller owns the keypad")

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(config()))
    opened = []
    worker = Worker(
        path,
        opener=lambda: opened.append(1),
        actions=Actions(),
        context_provider=Context,
        owner_factory=unavailable,
    )
    worker.tick(0)
    assert not opened
    assert "another controller" in worker.status()["error"]


def test_first_event_gap_also_requires_new_epoch():
    ctl, d, a, context = ready()
    before = d.sent[-1][2]
    d.event(1, sequence=8)
    ctl.step(context, 0.1)
    assert not a.calls
    assert d.sent[-1][2] != before


def test_resume_discards_queued_inputs_before_renewing():
    ctl, d, a, context = ready()
    d.event(1)
    ctl.step(context, 4.0)
    assert not a.calls
    assert d.closed
    assert "renewal" in ctl.status()["error"]


def test_invalid_typed_reload_keeps_last_good_config(tmp_path):
    ctl, d, a, context = ready()
    data = config()
    data["profiles"][0]["bindings"]["button_1"] = {"action": "rig", "name": []}
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(data))
    assert not ctl.reload(path)
    assert ctl.status()["profile"] == "minecraft"


def test_deep_json_reload_is_rejected_without_losing_config(tmp_path):
    from tools.rig_controls.profiles import load_config

    path = tmp_path / "deep.json"
    path.write_text("[" * 3000 + "0" + "]" * 3000)
    with pytest.raises(ValueError):
        load_config(path)
    ctl, _, _, _ = ready()
    assert not ctl.reload(path)
    assert ctl.status()["profile"] == "minecraft"
