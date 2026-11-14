"""Synthetic prospective campaign accounting; no live journal, audio or AC."""

from __future__ import annotations

import copy
import json
import threading
import time

import pytest

from tools import human_session
from tools.human_session import PRACTICE_COMBO, HumanSessionError, HumanSessionPermit

ASSISTANCE = {
    "human_steering": True,
    "human_throttle": True,
    "human_brake": True,
    "ai": False,
    "shared": False,
    "harness": False,
    "mode": "live",
    "abs": "factory",
    "tc": "factory",
    "gears": "manual",
    "clutch": "off",
    "blip": "off",
    "stability": "off",
    "abs_level": "1",
    "tc_level": "1",
    "stability_level": "0",
}


def native_identity(**changes):
    return {
        "car_id": PRACTICE_COMBO[0],
        "track_id": PRACTICE_COMBO[1],
        "session_uuid": "synthetic-native-session",
        "session_index": 0,
        "archive_lap_n": 1,
        "lap_time_ms": 0,
        "is_live": True,
        "is_ai": False,
        "is_replay": False,
        **changes,
    }


def payload(ordinal=1, elapsed=0, spline=0, **changes):
    return {
        "archive_session_uuid": "synthetic-native-session",
        "archive_lap_n": ordinal,
        "lap_time_ms": elapsed,
        "spline": spline,
        "is_live": True,
        "is_ai": False,
        "is_replay": False,
        **changes,
    }


def session_fixture(tmp_path, *, admit=True):
    root = tmp_path / "journal" / "laps"
    root.mkdir(parents=True, exist_ok=True)
    permit = HumanSessionPermit.prepare(
        tmp_path / "campaign.json",
        driver_id="synthetic-driver",
        assistance=ASSISTANCE,
    )
    if admit:
        permit.admit(native_identity(), archive_root=root)
    return permit, root


def complete_native_lap(permit, ordinal=1, *, lap_ms=60000, begin=True):
    """240 chronological native samples and closing boundary, with a synthetic clock."""
    if begin:
        permit.observe_native(payload(ordinal), now=(ordinal - 1) * (lap_ms / 1000 + 0.25))
    origin = (ordinal - 1) * (lap_ms / 1000 + 0.25)
    for elapsed in range(250, lap_ms + 1, 250):
        permit.observe_native(
            payload(ordinal, elapsed, min(0.999, elapsed / lap_ms)), now=origin + elapsed / 1000
        )
    permit.observe_native(payload(ordinal + 1), now=origin + lap_ms / 1000 + 0.25)


@pytest.mark.parametrize("driver", ["unknown", " Unconfirmed ", "unspecified", "?", "n/a"])
def test_unknown_driver_cannot_arm_or_create_a_campaign(tmp_path, driver):
    path = tmp_path / "campaign.json"
    with pytest.raises(HumanSessionError, match="driver_declaration_required"):
        HumanSessionPermit.prepare(path, driver_id=driver, assistance=ASSISTANCE)
    assert not path.exists()


def test_prepare_is_private_explicit_and_cannot_replace_a_campaign(tmp_path):
    permit, _ = session_fixture(tmp_path, admit=False)
    assert permit.status() == {
        "configured": True,
        "active": False,
        "phase": "prepared",
        "reason": "awaiting_native_session",
    }
    assert "synthetic-driver" not in json.dumps(permit.status())
    assert permit.status(private=True)["assistance"] == ASSISTANCE
    original = permit.path.read_bytes()
    with pytest.raises(HumanSessionError, match="campaign_already_exists"):
        HumanSessionPermit.prepare(permit.path, driver_id="different", assistance=ASSISTANCE)
    assert permit.path.read_bytes() == original


@pytest.mark.parametrize(
    "change",
    [
        {"ai": True},
        {"shared": True},
        {"harness": True},
        {"human_brake": False},
        {"mode": "replay"},
        {"abs": "unknown"},
        {"tc_level": ""},
        {"stability_level": "unknown"},
    ],
)
def test_missing_or_nonhuman_declarations_never_prepare(tmp_path, change):
    with pytest.raises(HumanSessionError):
        HumanSessionPermit.prepare(
            tmp_path / "campaign.json", driver_id="synthetic", assistance={**ASSISTANCE, **change}
        )
    assert not (tmp_path / "campaign.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"is_ai": True},
        {"is_ai": None},
        {"is_replay": True},
        {"is_live": False},
        {"track_id": "other"},
        {"archive_lap_n": 2},
        {"lap_time_ms": 500},
    ],
)
def test_native_admission_cannot_infer_control_or_start_mid_session(tmp_path, change):
    permit, root = session_fixture(tmp_path, admit=False)
    with pytest.raises(HumanSessionError):
        permit.admit(native_identity(**change), archive_root=root)
    assert permit.status()["phase"] == "prepared"


def test_durable_budget_counts_invalid_and_missing_archives_at_lap_start(tmp_path, monkeypatch):
    permit, _ = session_fixture(tmp_path)
    writes = []
    original = human_session._write
    monkeypatch.setattr(
        human_session,
        "_write",
        lambda path, state: (writes.append(state["attempted_laps"]), original(path, state))[1],
    )
    for ordinal in range(1, 11):
        complete_native_lap(permit, ordinal, lap_ms=1000, begin=ordinal == 1)
    status = permit.status(private=True)
    assert status["attempted_laps"] == 10 and status["remaining_laps"] == 0
    assert status["accepted_laps"] == []
    assert status["reason"] == "lap_budget_exhausted"
    assert len(writes) == 11  # Start + ten boundaries, never every telemetry tick.
    permit.observe_native(payload(12), now=13)
    assert permit.status()["phase"] == "aborted"
    assert permit.status(private=True)["attempted_laps"] == 10


def test_live_owner_is_preserved_but_confirmed_process_loss_consumes_permanently(
    tmp_path, monkeypatch
):
    permit, _ = session_fixture(tmp_path)
    permit.observe_native(payload(), now=0)
    before = permit.path.read_bytes()
    with pytest.raises(HumanSessionError, match="campaign_in_use"):
        HumanSessionPermit.load(permit.path)
    assert permit.path.read_bytes() == before
    assert HumanSessionPermit.read_status(permit.path)["active"]
    monkeypatch.setattr(human_session, "_owner_alive", lambda owner: False)
    restarted = HumanSessionPermit.load(permit.path)
    assert restarted.status()["reason"] == "campaign_process_restarted"
    with pytest.raises(HumanSessionError, match="campaign_already_consumed"):
        restarted.admit(native_identity())
    with pytest.raises(HumanSessionError, match="campaign_already_exists"):
        HumanSessionPermit.prepare(permit.path, driver_id="synthetic-driver", assistance=ASSISTANCE)


@pytest.mark.parametrize(
    "next_payload,stamp",
    [
        (payload(1, 250, 0.1, is_ai=True), 0.25),
        (payload(1, 250, 0.1, is_replay=None), 0.25),
        (payload(1, 250, 0.1, archive_session_uuid="other"), 0.25),
        (payload(3), 0.25),
        (payload(1, 1000, 0.1), 0.25),
        (payload(1, 250, 0.1), 0.5),
        (payload(1, 250, 0.1), -0.1),
    ],
)
def test_identity_control_clock_or_continuity_failure_revokes_whole_study(
    tmp_path, next_payload, stamp
):
    permit, _ = session_fixture(tmp_path)
    permit.observe_native(payload(), now=0)
    permit.observe_native(next_payload, now=stamp)
    assert permit.status()["phase"] == "aborted"
    with pytest.raises(HumanSessionError, match="campaign_not_active"):
        permit.observe_native(payload(1, 300, 0.2), now=0.3)


def test_end_declaration_gates_result_and_does_not_change_terminal_reason(tmp_path):
    permit, _ = session_fixture(tmp_path)
    assert permit.close({"driver_id": "synthetic-driver", "assistance": ASSISTANCE})[
        "end_confirmed"
    ]
    assert permit.status()["reason"] == "end_declaration_matched"
    assert permit.revoke("later_callback")["reason"] == "end_declaration_matched"


def test_changed_or_missing_end_declaration_cannot_confirm_result(tmp_path):
    permit, _ = session_fixture(tmp_path)
    changed = copy.deepcopy(ASSISTANCE)
    changed["tc_level"] = "2"
    result = permit.close({"driver_id": "synthetic-driver", "assistance": changed})
    assert result["reason"] == "end_declaration_mismatch" and not result["end_confirmed"]


def test_voice_bank_is_private_and_never_part_of_control_attestation(tmp_path):
    permit = HumanSessionPermit.prepare(
        tmp_path / "campaign.json",
        driver_id="synthetic",
        assistance=ASSISTANCE,
        voice_bank="private/bank",
    )
    assert permit.status(private=True)["voice_bank"] == "private/bank"
    assert "private/bank" not in json.dumps(permit.status())
    assert "voice_bank" not in json.loads(permit.path.read_bytes())["declaration"]


def test_late_end_after_abort_preserves_reason_and_never_restores_eligibility(tmp_path):
    permit, _ = session_fixture(tmp_path)
    permit.revoke("native_session_disconnected")
    assert not permit.status(private=True)["end_recorded"]
    assert "end_recorded" not in permit.status()
    permit._last_native_seen = 0
    end = {"driver_id": "synthetic-driver", "assistance": ASSISTANCE}
    result = permit.close(end)
    assert result["phase"] == "aborted" and result["reason"] == "native_session_disconnected"
    assert result["end_confirmed"]
    assert result["end_recorded"]
    before = permit.path.read_bytes()
    permit.close(end)
    assert permit.path.read_bytes() == before
    changed = copy.deepcopy(end)
    changed["assistance"]["abs_level"] = "2"
    assert not permit.close(changed)["end_confirmed"]
    assert permit.status(private=True)["end_recorded"]
    assert permit.status()["reason"] == "native_session_disconnected"
    assert not permit.close(end)["end_confirmed"]


def test_capture_cannot_be_sealed_before_all_ten_immutable_receipts(tmp_path):
    permit, _ = session_fixture(tmp_path)
    with pytest.raises(HumanSessionError, match="campaign_capture_incomplete"):
        permit.seal_capture()
    assert permit.status()["active"]


def test_same_live_handle_rejects_complete_older_valid_state(tmp_path):
    permit, root = session_fixture(tmp_path, admit=False)
    prepared = permit.path.read_bytes()
    permit.admit(native_identity(), archive_root=root)
    admitted = permit.path.read_bytes()
    permit.observe_native(payload(), now=0)
    permit.path.write_bytes(admitted)
    with pytest.raises(HumanSessionError, match="campaign_state_rollback"):
        permit.reload()
    permit.path.write_bytes(prepared)
    with pytest.raises(HumanSessionError, match="campaign_state_rollback"):
        permit.reload()


@pytest.mark.parametrize("field", ["declaration", "native", "owner_process"])
def test_coherent_rechecksummed_admission_identity_change_is_rejected_by_live_handle(
    tmp_path, field
):
    permit, _ = session_fixture(tmp_path)
    state = json.loads(permit.path.read_bytes())
    if field == "declaration":
        state["declaration"]["driver_id"] = "another-driver"
        state["declaration_sha256"] = human_session._digest(state["declaration"])
    elif field == "native":
        state["native"]["session_uuid"] = "another-session"
    else:
        state["owner_process"]["created"] += 1
    state["revision"] += 1
    state["state_sha256"] = human_session._state_digest(state)
    permit.path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(HumanSessionError, match="campaign_identity_changed"):
        permit.reload()


@pytest.mark.parametrize(
    "field,value",
    [
        ("end_confirmed", "yes"),
        ("capture_sealed", 1),
        ("end_conflict", 0),
        ("reason", "private driver / secret path"),
    ],
)
def test_corrupted_public_fields_cannot_leak_private_values(tmp_path, field, value):
    permit, _ = session_fixture(tmp_path)
    state = json.loads(permit.path.read_bytes())
    state[field] = value
    state["revision"] += 1
    state["state_sha256"] = human_session._state_digest(state)
    permit.path.write_text(json.dumps(state), encoding="utf-8")
    public = HumanSessionPermit.read_status(permit.path)
    assert public == {
        "configured": True,
        "active": False,
        "phase": "unavailable",
        "reason": "campaign_state_invalid",
    }
    assert "private driver" not in json.dumps(public)


@pytest.mark.parametrize("operation", ["revoke", "close"])
def test_ui_stop_and_end_retry_short_writer_contention_and_ack_only_durable_state(
    tmp_path, operation
):
    permit, _ = session_fixture(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def writer():
        with human_session._locked(permit.path):
            entered.set()
            assert release.wait(2)

    worker = threading.Thread(target=writer)
    worker.start()
    assert entered.wait(2)
    timer = threading.Timer(0.04, release.set)
    timer.start()
    try:
        if operation == "revoke":
            result = human_session.revoke_campaign(permit.path, "operator_stopped")
            assert result["phase"] == "aborted"
        else:
            result = human_session.close_campaign(
                permit.path, {"driver_id": "synthetic-driver", "assistance": ASSISTANCE}
            )
            assert result["phase"] == "closed" and result["end_confirmed"]
        assert HumanSessionPermit.read_status(permit.path)["phase"] == result["phase"]
    finally:
        release.set()
        timer.cancel()
        worker.join(2)
    assert not worker.is_alive()


@pytest.mark.parametrize("operation", ["revoke", "close"])
def test_ui_stop_and_end_report_busy_instead_of_acknowledging_unwritten_state(tmp_path, operation):
    permit, _ = session_fixture(tmp_path)
    original = permit.path.read_bytes()
    begin = time.perf_counter()
    with human_session._locked(permit.path):
        with pytest.raises(HumanSessionError, match="campaign_writer_busy"):
            if operation == "revoke":
                human_session.revoke_campaign(permit.path, "operator_stopped")
            else:
                human_session.close_campaign(
                    permit.path, {"driver_id": "synthetic-driver", "assistance": ASSISTANCE}
                )
    assert time.perf_counter() - begin < 1.5
    assert permit.path.read_bytes() == original
