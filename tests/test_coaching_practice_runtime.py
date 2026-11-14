"""Independent #529 runtime/server boundary tests over synthetic human archives."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections import deque
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_lap_qualification import UNITS
from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar import coaching_runtime, server
from tools.ai_sidecar.coachable_frontier import build_human_drill_target
from tools.ai_sidecar.coaching_runtime import build_coach_runtime
from tools.ai_sidecar.lap_dynamics import lap_trace_from_archive
from tools.lap_qualification import USES, build_qualification, qualify_archive

COMBO = ("ks_porsche_911_gt3_r_2016", "magione", None)


@pytest.fixture(autouse=True)
def isolated_provenance(tmp_path, monkeypatch):
    ledger = tmp_path / "synthetic-attributions.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    monkeypatch.delenv("AC_COPILOT_COACH_DRILLS", raising=False)


def _reference(*, authority="human"):
    archive = _corner_archive()
    archive.update(
        schema_version=1,
        source="in_game",
        session_uuid="synthetic-session",
        lap_uuid="synthetic-reference",
    )
    archive["track"]["layout"] = None
    archive["lap"]["lap_n"] = 1
    archive["tyres"] = {"optimalTempC": 90.0}
    archive["conditions"] = {"weatherType": "clear", "trackGripLevel": 1.0}
    if authority is not None:
        archive["qualification"] = build_qualification(
            archive,
            authority=authority,
            origin="synthetic-human-test",
            supported_uses={use: True for use in USES},
            channels={name: {"unit": unit, "basis": "measured"} for name, unit in UNITS.items()},
            evidence=[
                {
                    "kind": "verified_human_control"
                    if authority == "human"
                    else "observed_ai_control",
                    "sha256": hashlib.sha256(b"synthetic-control-only").hexdigest(),
                }
            ],
        )
    return archive


def _runtime(reference=None, **kwargs):
    runtime = build_coach_runtime(
        _reference() if reference is None else reference,
        expected_combo=COMBO,
        use_environment=False,
        **kwargs,
    )
    assert runtime is not None
    return runtime


def _thermal_record(*, brake_channels=True):
    record = _reference(authority=None)
    record["trace"]["fields"].extend(f"tyreCoreTemp_{wheel}" for wheel in ("fl", "fr", "rl", "rr"))
    for row in record["trace"]["samples"]:
        row.extend([90.0] * 4)
    if brake_channels:
        record["trace"]["fields"].extend(f"brakeTemp_{wheel}" for wheel in ("fl", "fr", "rl", "rr"))
        for row in record["trace"]["samples"]:
            row.extend([400.0] * 4)
    return record


def test_real_runtime_practice_is_default_off_and_offline_ignores_ambient_opt_in(monkeypatch):
    assert _runtime().practice_status() == {
        "configured": False,
        "active": False,
        "phase": "disabled",
        "reason": "not_configured",
    }
    monkeypatch.setenv("AC_COPILOT_COACH_DRILLS", "1")
    assert _runtime().practice is None
    assert _runtime(practice_drills=False).practice is None
    enabled = _runtime(practice_drills=True)
    assert enabled.practice is not None and enabled.practice_status()["configured"] is True


def test_normal_runtime_environment_opt_in_reaches_practice(monkeypatch):
    monkeypatch.setenv("AC_COPILOT_COACH_DRILLS", "1")
    monkeypatch.delenv("AC_COPILOT_ALIEN_LINE", raising=False)
    runtime = build_coach_runtime(
        _reference(), expected_combo=COMBO, driver_profile={}, use_environment=True
    )
    assert runtime is not None and runtime.practice is not None
    assert runtime.practice_status()["configured"] is True


def test_legacy_reference_can_run_ordinary_coach_but_cannot_enter_human_practice():
    runtime = _runtime(_reference(authority=None), practice_drills=True)
    status = runtime.practice_status()
    assert status["active"] is False and status["phase"] == "unavailable"
    assert status["reason"] == "qualified_human_reference_required"


@pytest.mark.parametrize("authority", ["ai", "shared", "unknown"])
def test_nonhuman_reference_never_enters_real_runtime_practice(authority):
    diagnostic = {}
    runtime = build_coach_runtime(
        _reference(authority=authority),
        expected_combo=COMBO,
        use_environment=False,
        practice_drills=True,
        diagnostics=diagnostic,
    )
    assert runtime is None
    assert diagnostic["reason"] == f"control_authority_not_human:{authority}"


@pytest.mark.parametrize("mode", ["baseline", "ggv_denominator_only"])
def test_practice_requires_the_existing_condition_indexed_capability_gate(mode):
    runtime = _runtime(practice_drills=True, capability_gate_mode=mode)
    assert runtime.practice is None
    assert runtime.practice_status()["reason"] == "qualified_curriculum_reference_required"


def test_missing_curriculum_does_not_create_an_arbitrary_drill(monkeypatch):
    monkeypatch.setattr(coaching_runtime, "next_drill", lambda profile: None)
    runtime = _runtime(practice_drills=True)
    assert runtime.practice is None
    assert runtime.practice_status()["reason"] == "qualified_curriculum_reference_required"


def test_real_target_signature_and_action_anchors_do_not_follow_later_calibration():
    reference = _reference()
    runtime = _runtime(reference, practice_drills=True, practice_drill_id="apex-foundation")
    corner = next(iter(runtime.practice.reference_signatures))
    signature = runtime.practice.reference_signatures[corner]
    qualification = qualify_archive(reference, use="live_reference", expected_combo=COMBO)
    target = build_human_drill_target(
        signature,
        replace(signature, min_speed_kmh=signature.min_speed_kmh - 10.0),
        reference_qualification=qualification,
        baseline_qualification=qualification,
        drill_id="apex-foundation",
        combo=(COMBO[0], COMBO[1], ""),
        baseline_corner_time_s=8.0,
        reference_identity="reference",
        baseline_identity="baseline",
    )
    runtime.ledger.start_drill(target)
    anchors = copy.deepcopy(runtime.anchors[corner])
    frozen_signature = runtime.ref_sigs[corner]
    candidate = copy.deepcopy(reference)
    fields = {name: i for i, name in enumerate(candidate["trace"]["fields"])}
    brake = frozen_signature.brake_point_spline
    assert brake is not None
    for row in candidate["trace"]["samples"]:
        if brake - 0.02 <= row[fields["spline"]] < brake:
            row[fields["brake"]] = 0.8
            row[fields["throttle"]] = 0.0
    lap = lap_trace_from_archive(candidate)
    # Prove this calibration input actually moves an unlocked normal runtime.
    unlocked = _runtime(reference)
    assert unlocked.calibrate_from_driver_lap(lap) > 0
    assert runtime.calibrate_from_driver_lap(lap) == 0
    assert runtime.anchors[corner] == anchors
    assert runtime.ref_sigs[corner] == frozen_signature
    assert runtime.ledger.drill_target == target


def test_completed_archive_thermal_gate_accepts_complete_stable_evidence():
    runtime = _runtime(practice_drills=True)
    assert runtime._practice_archive_conditions(_thermal_record())


def _practice_window(runtime):
    ref = runtime.refs[0]
    return ref.index, runtime._practice_anchors[ref.index].brake - 0.04, ref.spline_hi


def test_practice_corner_time_covers_the_same_brake_entry_window_as_its_signature():
    runtime = _runtime(practice_drills=True)
    record = _reference()
    corner, lower, upper = _practice_window(runtime)
    fields = {name: i for i, name in enumerate(record["trace"]["fields"])}
    rows = record["trace"]["samples"]
    inside = [row for row in rows if lower <= row[fields["spline"]] <= upper]
    before = [row for row in rows if row[fields["spline"]] <= lower][-1]
    after = next(row for row in rows if row[fields["spline"]] >= upper)
    assert len(inside) > 10 and lower < runtime.refs[0].spline_lo
    observation = runtime._practice_observations(record)[corner]
    elapsed = observation[1]
    # Either exact/interpolated boundary times or their bracketing samples can
    # describe the full window. A shorter apex-only/late-entry duration cannot.
    minimum = (inside[-1][fields["eMs"]] - inside[0][fields["eMs"]]) / 1000.0
    maximum = (after[fields["eMs"]] - before[fields["eMs"]]) / 1000.0
    assert minimum <= elapsed <= maximum


@pytest.mark.parametrize("missing", ["entry", "exit", "midcorner"])
def test_practice_observations_cannot_stage_a_partial_target_window(missing):
    runtime = _runtime(practice_drills=True)
    record = _reference()
    corner, lower, upper = _practice_window(runtime)
    fields = {name: i for i, name in enumerate(record["trace"]["fields"])}
    rows = record["trace"]["samples"]
    if missing == "entry":
        record["trace"]["samples"] = [row for row in rows if row[fields["spline"]] > lower + 0.02]
    elif missing == "exit":
        record["trace"]["samples"] = [row for row in rows if row[fields["spline"]] < upper - 0.02]
    else:
        apex = runtime.refs[0].apex_spline
        record["trace"]["samples"] = [
            row for row in rows if abs(row[fields["spline"]] - apex) > 0.06
        ]
    assert corner not in runtime._practice_observations(record)


@pytest.mark.parametrize("corruption", ["elapsed_reversal", "spline_reversal", "sampling_gap"])
def test_practice_observations_require_monotone_contiguous_measurements(corruption):
    runtime = _runtime(practice_drills=True)
    record = _reference()
    corner, lower, upper = _practice_window(runtime)
    fields = {name: i for i, name in enumerate(record["trace"]["fields"])}
    rows = record["trace"]["samples"]
    inside = [i for i, row in enumerate(rows) if lower < row[fields["spline"]] < upper]
    middle = inside[len(inside) // 2]
    if corruption == "elapsed_reversal":
        rows[middle][fields["eMs"]] = rows[middle - 1][fields["eMs"]] - 1.0
    elif corruption == "spline_reversal":
        rows[middle][fields["spline"]] = rows[middle - 1][fields["spline"]] - 0.001
    else:
        # Preserve full-lap and corner boundary coverage, strict spline order
        # and finite values, but expose a 450ms loss of temporal coverage.
        for row in rows[middle:]:
            row[fields["eMs"]] += 450.0
        record["lap"]["lap_ms"] += 450
    assert corner not in runtime._practice_observations(record)


def test_real_magione_trace_with_a_subsecond_corner_hole_cannot_stage_a_trial():
    # The complete committed production-sized fixture is the input; only the
    # named missing-400ms variant is edited in memory, and endpoints stay intact.
    path = Path(__file__).parent / "fixtures" / "magione_gt3r_reference.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    runtime = build_coach_runtime(record, use_environment=False, practice_drills=True)
    assert runtime is not None
    fields = {name: i for i, name in enumerate(record["trace"]["fields"])}
    original = record["trace"]["samples"]
    assert len(original) > 1000
    ref = next(
        ref
        for ref in runtime.refs
        if 0.0 < runtime._practice_anchors[ref.index].brake - 0.04 < ref.spline_hi < 1.0
    )
    lower = runtime._practice_anchors[ref.index].brake - 0.04
    inside = [row for row in original if lower < row[fields["spline"]] < ref.spline_hi]
    middle_time = inside[len(inside) // 2][fields["eMs"]]
    remaining = [row for row in original if abs(row[fields["eMs"]] - middle_time) > 200.0]
    assert remaining[0] == original[0] and remaining[-1] == original[-1]
    gap = max(
        b[fields["eMs"]] - a[fields["eMs"]] for a, b in zip(remaining, remaining[1:], strict=False)
    )
    assert 300.0 < gap < 1000.0
    record["trace"]["samples"] = remaining
    assert ref.index not in runtime._practice_observations(record)


@pytest.mark.parametrize(
    "channel,value",
    [
        ("speed", float("nan")),
        ("eMs", float("inf")),
        ("spline", None),
        ("brake", True),
        ("throttle", "bad"),
        ("steer", float("nan")),
    ],
)
def test_practice_observations_refuse_nonfinite_or_unmeasured_essential_channels(channel, value):
    runtime = _runtime(practice_drills=True)
    record = _reference()
    corner, lower, upper = _practice_window(runtime)
    fields = {name: i for i, name in enumerate(record["trace"]["fields"])}
    row = next(
        row for row in record["trace"]["samples"] if row[fields["spline"]] > (lower + upper) / 2
    )
    row[fields[channel]] = value
    assert corner not in runtime._practice_observations(record)


@pytest.mark.parametrize("corruption", ["short_row", "mapping_row", "none_row", "duplicate_field"])
def test_practice_observations_fail_closed_without_throwing_on_malformed_rows(corruption):
    runtime = _runtime(practice_drills=True)
    record = _reference()
    corner, lower, upper = _practice_window(runtime)
    fields = {name: i for i, name in enumerate(record["trace"]["fields"])}
    rows = record["trace"]["samples"]
    middle = next(i for i, row in enumerate(rows) if row[fields["spline"]] > (lower + upper) / 2)
    if corruption == "short_row":
        rows[middle].pop()
    elif corruption == "mapping_row":
        rows[middle] = {name: rows[middle][i] for name, i in fields.items()}
    elif corruption == "none_row":
        rows[middle] = None
    else:
        record["trace"]["fields"].append("eMs")
        for row in rows:
            row.append(row[fields["eMs"]])
    assert corner not in runtime._practice_observations(record)


def test_thermal_abort_reason_survives_a_later_archive_with_bad_identity():
    runtime = _runtime(practice_drills=True)
    hot = _thermal_record()
    index = hot["trace"]["fields"].index("tyreCoreTemp_fl")
    hot["trace"]["samples"][len(hot["trace"]["samples"]) // 2][index] = 150.0
    assert not runtime._practice_archive_conditions(hot)
    before = runtime.practice_status()
    assert before["phase"] == "aborted"
    assert before["reason"] in {"tyre_temp_overheat", "tyre_temp_critical"}
    malformed = _reference()
    malformed["session_uuid"] = None
    qualification = qualify_archive(malformed, use="human_progression")
    assert not qualification.allowed
    after = runtime.record_practice_archive(malformed, qualification, voice_ready=False)
    assert after["phase"] == "aborted" and after["reason"] == before["reason"]


def test_completed_archive_thermal_gate_does_not_inherit_normal_missing_brake_fail_open():
    runtime = _runtime(practice_drills=True)
    record = _thermal_record(brake_channels=False)
    human = _reference()["qualification"]
    record["qualification"] = build_qualification(
        record,
        authority="human",
        origin="synthetic-human-test",
        supported_uses=human["supported_uses"],
        channels=human["channels"],
        evidence=human["evidence"],
    )
    # This exact archive passes the ordinary source/trace boundary; the stricter
    # practice thermal predicate must refuse its missing brake evidence itself.
    decision = qualify_archive(record, use="human_progression")
    assert decision.allowed and decision.authority == "human"
    assert not runtime._practice_archive_conditions(record)


@pytest.mark.parametrize(
    "channel,value",
    [("tyreCoreTemp_fl", 20.0), ("tyreCoreTemp_rr", 150.0), ("brakeTemp_fl", 1400.0)],
)
def test_completed_archive_thermal_extremes_cannot_be_hidden_by_a_warm_median(channel, value):
    runtime = _runtime(practice_drills=True)
    record = _thermal_record()
    index = record["trace"]["fields"].index(channel)
    record["trace"]["samples"][len(record["trace"]["samples"]) // 2][index] = value
    assert not runtime._practice_archive_conditions(record)


def _private_coach():
    private = {
        "configured": True,
        "active": True,
        "phase": "retention",
        "reason": "target_band_met",
        "target": {"reference_identity": "private-driver-reference", "min_speed_kmh": 123.0},
        "baseline_ids": ["private-human-lap"],
        "cued_successes": 2,
        "retention_successes": 1,
    }
    return SimpleNamespace(practice_status=lambda: private, frontier={})


def test_public_practice_health_strips_targets_driver_ids_and_results(monkeypatch):
    monkeypatch.setattr(server, "_coach_runtime", _private_coach())
    monkeypatch.setattr(server, "_voice_runtime_status", {"enabled": True})
    public = server.public_voice_runtime_status()
    assert set(public["practice_drill"]) == {"configured", "active", "phase", "reason"}
    encoded = json.dumps(public)
    assert (
        "private-" not in encoded
        and "successes" not in encoded
        and "target" not in public["practice_drill"]
    )


def test_public_practice_health_does_not_echo_paths_or_exception_text(monkeypatch):
    coach = _private_coach()
    original = coach.practice_status()
    original.update(phase="path C:/private/driver", reason="failure:/private/driver.json")
    monkeypatch.setattr(server, "_coach_runtime", coach)
    payload = server.public_voice_runtime_status()["practice_drill"]
    assert payload["phase"] == payload["reason"] == "practice_unavailable"


class _Connection:
    remote_address = ("192.0.2.10", 5100)

    def respond(self, status, text):
        return SimpleNamespace(status=status, body=text.encode(), headers={})


def test_anonymous_health_route_preserves_only_operational_practice_fields(monkeypatch):
    monkeypatch.setattr(server, "_coach_runtime", _private_coach())
    monkeypatch.setattr(server, "_voice_runtime_status", {"enabled": True})
    request = SimpleNamespace(path="/health", headers={})
    response = server.make_process_request("synthetic-practice-token")(_Connection(), request)
    assert response.status == HTTPStatus.OK
    public = json.loads(response.body)["voice"]["practice_drill"]
    assert set(public) == {"configured", "active", "phase", "reason"}
    assert b"private-" not in response.body and b"cued_successes" not in response.body


@pytest.mark.parametrize(
    "supplied,expected",
    [
        (None, HTTPStatus.UNAUTHORIZED),
        ("incorrect", HTTPStatus.UNAUTHORIZED),
        ("synthetic-practice-token", HTTPStatus.OK),
    ],
)
def test_private_practice_route_uses_the_existing_external_token_gate(
    monkeypatch, supplied, expected
):
    monkeypatch.setattr(server, "_coach_runtime", _private_coach())
    request = SimpleNamespace(path="/coach/practice", headers={})
    if supplied is not None:
        request.headers[server.AUTH_HEADER] = supplied
    response = server.make_process_request("synthetic-practice-token")(_Connection(), request)
    assert response.status == expected
    assert (b"private-driver-reference" in response.body) is (expected == HTTPStatus.OK)


@pytest.mark.parametrize("replace_runtime", [False, True])
@pytest.mark.parametrize("callback", ["dispatch", "cancel"])
def test_voice_evidence_runs_on_main_loop_and_is_fenced_to_its_original_runtime(
    monkeypatch, replace_runtime, callback
):
    class DeferredLoop:
        calls = []

        def is_closed(self):
            return False

        def call_soon_threadsafe(self, action):
            self.calls.append(action)

    def coach():
        notes = []
        return SimpleNamespace(
            practice=object(),
            notes=notes,
            note_practice_voice=lambda event: notes.append(("dispatch", event)),
            note_practice_voice_cancel=lambda event: notes.append(("cancel", event)),
        )

    payload = {
        "seq": 1,
        "clip_id": "synthetic-clip",
        "kind": "no_trail",
        "corner": 1,
        "t_mono_ms": 1000,
        "duration_ms": 200,
        "instructional": True,
    }
    original, replacement = coach(), coach()
    loop = DeferredLoop()
    monkeypatch.setattr(server, "_coach_runtime", original)
    monkeypatch.setattr(server, "_event_loop", loop)
    monkeypatch.setattr(server, "_background_tasks", set())
    monkeypatch.setattr(server, "_voice_dispatch_log", deque(maxlen=16))

    async def broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(server, "_broadcast_external", broadcast)

    async def exercise():
        if callback == "dispatch":
            server._on_voice_dispatch(SimpleNamespace(to_payload=lambda: dict(payload)))
        else:
            server._on_voice_cancel(dict(payload))
        assert not original.notes and not replacement.notes
        assert len(loop.calls) == 1
        if replace_runtime:
            monkeypatch.setattr(server, "_coach_runtime", replacement)
        loop.calls.pop()()
        if server._background_tasks:
            await asyncio.gather(*list(server._background_tasks))

    asyncio.run(exercise())
    assert not replacement.notes
    assert len(original.notes) == (0 if replace_runtime else 1)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("evidence_ready", [False, True])
def test_completed_archive_server_gate_requires_working_voice_evidence(
    monkeypatch, enabled, evidence_ready
):
    reference = _reference()
    runtime = _runtime(reference, practice_drills=True)
    readiness = []
    original = runtime.record_practice_archive

    def record(archive, qualification, *, voice_ready):
        readiness.append(voice_ready)
        return original(archive, qualification, voice_ready=voice_ready)

    monkeypatch.setattr(runtime, "record_practice_archive", record)
    monkeypatch.setattr(server, "_coach_runtime", runtime)
    monkeypatch.setattr(server, "_voice_runtime_status", {"enabled": enabled})
    monkeypatch.setattr(
        server, "_voice_coach", SimpleNamespace(practice_evidence_ready=evidence_ready)
    )
    monkeypatch.setattr(server, "resolve_lap_archive", lambda inbound: reference)
    monkeypatch.setattr(server, "_recent_between_lap_fold_keys", deque(maxlen=16))
    inbound = {"trace": reference["trace"], "lap": 1, "lapTimeMs": reference["lap"]["lap_ms"]}
    asyncio.run(server._coach_v2_between_lap(object(), inbound, reply_coaching=False))
    assert readiness == [enabled and evidence_ready]
