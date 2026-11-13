"""Synthetic permit/scope checks; no physical rig, process or scored trial starts."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_setup_prescription import UNITS, inputs

from tools.ai_sidecar.pressure_bench import (
    AUTHORITY,
    CARD_MODE,
    MODE,
    PERMIT_ENV,
    BenchDenied,
    PressureBenchGuard,
    canonical_sha256,
    pressure_spinners_sha256,
)
from tools.ai_sidecar.setup_prescription import build_prescription
from tools.lap_qualification import USES, build_qualification, payload_sha256, qualify_archive


def write(path: Path, data) -> str:
    path.write_text(json.dumps(data, sort_keys=True, allow_nan=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh_seal(f) -> None:
    """Reseal explicit synthetic structural bindings, never a scored real label."""
    f.oracle_receipt.update(
        identity=f.case["identity"],
        sources=[
            {
                **source,
                "canonical_sha256": canonical_sha256(archive),
                "payload_sha256": payload_sha256(archive),
                "session_id": archive["session_uuid"],
                "lap_uuid": archive["lap_uuid"],
                "lap_n": archive["lap"]["lap_n"],
            }
            for source, archive in zip(f.sources, f.archives, strict=True)
        ],
        archive_hashes=[canonical_sha256(archive) for archive in f.archives],
        targets_sha256=f.case["targets_sha256"],
        spinners_sha256=f.case["spinners_sha256"],
    )
    f.case["oracle_seal"]["sha256"] = write(f.seal_path, f.oracle_receipt)
    f.seal_hash = f.case["oracle_seal"]["sha256"]
    write(f.case_path, f.case)


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    ledger = tmp_path / "attributions.json"
    write(ledger, {"schema_version": 1, "entries": []})
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    archives, spinners, identity, targets = inputs()
    lap_dir = tmp_path / "journal/laps"
    lap_dir.mkdir(parents=True)
    sources = []
    for archive in archives:
        archive.pop("qualification", None)
        archive["qualification"] = build_qualification(
            archive,
            authority="ai",
            origin="synthetic_native_ai",
            supported_uses={use: use == "analysis" for use in USES},
            channels={key: {"unit": unit, "basis": "measured"} for key, unit in UNITS.items()},
            evidence=[{"kind": "observed_native_ai_control", "sha256": "b" * 64}],
        )
        path = lap_dir / f"lap_{archive['lap']['lap_n']}.json"
        sources.append({"path": str(path), "sha256": write(path, archive)})
    run_root = tmp_path / "run"
    run_root.mkdir()
    seal_path = run_root / "oracle-hidden.json"
    permit_path, case_path = run_root / "permit.json", run_root / "case.json"
    owner = {"pid": 1234, "cwd": str(tmp_path), "started_at": "2026-11-12T00:00:00Z"}
    lock_path = tmp_path / "canonical-test.lock"
    now = [1000.0]
    guard = PressureBenchGuard(
        "a" * 64,
        "b" * 64,
        permit_path=permit_path,
        lock_path=lock_path,
        runtime_id="runtime-one",
        clock=lambda: now[0],
        owner_reader=lambda _: owner.copy(),
        process_create_time=lambda _pid: 42.125,
    )
    permit = {
        "schema_version": 1,
        "mode": MODE,
        "issue": 956,
        "authority": AUTHORITY,
        "allow_native_ai": True,
        "allow_setup_writes": True,
        "run_id": "run-one",
        "runtime_id": guard.runtime_id,
        "issued_at": 990.0,
        "expires_at": 2000.0,
        "run_root": str(run_root),
        "rig_lock_path": str(lock_path),
        "rig_owner": owner.copy(),
        "owner_create_time": 42.125,
        "candidate_sha256": "a" * 64,
        "oracle_sha256": "b" * 64,
    }
    case = {
        "schema_version": 1,
        "mode": MODE,
        "run_id": "run-one",
        "case_id": "case-one",
        "sealed_at": 1000.0,
        "expires_at": 1120.0,
        "identity": identity,
        "sources": sources,
        "targets_sha256": canonical_sha256(targets),
        "spinners_sha256": pressure_spinners_sha256(spinners),
        "oracle_sha256": "b" * 64,
        "oracle_seal": {"path": str(seal_path), "sha256": ""},
    }
    ctx = {
        "identity": identity,
        "spinners": spinners,
        "lap_dir": str(lap_dir),
        "is_in_pit": True,
        "reset_allowed": True,
        "capture_isolated": True,
    }
    write(permit_path, permit)
    oracle_receipt = {
        "schema_version": 1,
        "mode": "956_ai_bench_oracle",
        "run_id": "run-one",
        "case_id": "case-one",
        "oracle_sha256": "b" * 64,
        "enrollable": True,
        "authority": "ai",
        "sealed_at": 1000.0,
        "expires_at": 1120.0,
        "label": "synthetic_unscored",
        "directions": {},
    }
    result = SimpleNamespace(**locals())
    refresh_seal(result)
    return result


def arm(f):
    return f.guard.arm(f.case_path, f.ctx, f.archives, f.targets, f.owner)


def test_presence_of_run_permission_never_arms_or_survives_restart(sealed, monkeypatch):
    f = sealed
    monkeypatch.setenv(PERMIT_ENV, str(f.permit_path))
    fresh = PressureBenchGuard("a" * 64, "b" * 64)
    assert fresh.status()["active"] is False
    assert fresh.runtime_id != f.guard.runtime_id
    with pytest.raises(BenchDenied, match="explicit arm"):
        fresh.validate(f.ctx, f.archives, f.targets, object())
    with pytest.raises(BenchDenied):
        fresh.arm(f.case_path, f.ctx, f.archives, f.targets, object())


def test_analysis_and_native_ai_are_not_write_permission_without_explicit_arm(sealed):
    f = sealed
    for archive in f.archives:
        decision = qualify_archive(archive, use="analysis")
        assert decision.allowed and decision.authority == "ai"
        assert not qualify_archive(
            archive, use="live_reference", expected_combo=("test_car", "test_track", None)
        ).allowed
    assert (
        build_prescription(f.archives, f.spinners, identity=f.identity, targets=f.targets)["status"]
        == "abstained"
    )
    with pytest.raises(BenchDenied):
        f.guard.build_prescription(f.archives, f.spinners, identity=f.identity, targets=f.targets)
    metadata = arm(f)
    assert metadata["mode"] == CARD_MODE and metadata["readback_only"] is False
    card = f.guard.build_prescription(
        f.archives, f.spinners, identity=f.identity, targets=f.targets
    )
    assert card["status"] == "proposed" and len(card["changes"]) == 4
    assert card["mode"] == CARD_MODE and card["authority"] == AUTHORITY
    assert card["run_id"] == "run-one" and card["case_id"] == "case-one"
    assert card["ttl_s"] == 120 and "956 AI BENCH" in card["summary"]
    assert "hidden_label" not in json.dumps(card)
    # Neither wrapper changes canonical ordinary eligibility after bench use.
    assert (
        build_prescription(f.archives, f.spinners, identity=f.identity, targets=f.targets)["status"]
        == "abstained"
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("authority", "analysis_is_enough"),
        ("allow_native_ai", False),
        ("allow_setup_writes", False),
        ("runtime_id", "previous-runtime"),
        ("candidate_sha256", "c" * 64),
        ("oracle_sha256", "c" * 64),
        ("expires_at", 999.0),
        ("issued_at", 1001.0),
        ("expires_at", 16000.0),
        ("owner_create_time", 43.0),
        ("schema_version", True),
    ],
)
def test_invalid_run_permission_fails_closed(sealed, key, value):
    f = sealed
    f.permit[key] = value
    write(f.permit_path, f.permit)
    with pytest.raises(BenchDenied):
        arm(f)
    assert not f.guard.status()["active"]


@pytest.mark.parametrize("length", [64, 65, 80])
def test_permit_run_id_bound_matches_screen_wire_admission(sealed, length):
    from tools.ai_sidecar.external_protocol import validate_inbound

    run_id = "r" * length
    sealed.permit["run_id"] = sealed.case["run_id"] = sealed.oracle_receipt["run_id"] = run_id
    write(sealed.permit_path, sealed.permit)
    refresh_seal(sealed)
    wire = {"v": 1, "type": "setup.bench.get", "mode": "ai_bench", "run_id": run_id}
    if length == 64:
        arm(sealed)
        assert sealed.guard.status()["active"] is True
        assert validate_inbound(wire) is None
    else:
        with pytest.raises(
            BenchDenied, match="Bench run authority or implementation binding is invalid"
        ):
            arm(sealed)
        assert validate_inbound(wire) is not None


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "selection",
        "target",
        "baseline",
        "identity",
        "seal",
        "permission",
        "case",
        "pit",
        "owner",
        "expired",
    ],
)
def test_every_scope_change_disarms_and_restoration_does_not_auto_rearm(sealed, mutation):
    f = sealed
    arm(f)
    if mutation == "source":
        Path(f.sources[0]["path"]).write_text("{}")
    elif mutation == "selection":
        f.archives.reverse()
    elif mutation == "target":
        f.targets["fl"]["pressure_ideal_psi"] += 1
    elif mutation == "baseline":
        f.ctx["spinners"][0]["value"] += 1
    elif mutation == "identity":
        f.ctx["identity"]["session_id"] = "new-session"
    elif mutation == "seal":
        f.seal_path.write_text("changed")
    elif mutation == "permission":
        f.permit["extra"] = True
        write(f.permit_path, f.permit)
    elif mutation == "case":
        f.case["extra"] = True
        write(f.case_path, f.case)
    elif mutation == "pit":
        f.ctx["is_in_pit"] = False
    elif mutation == "owner":
        f.owner.clear()
    elif mutation == "expired":
        f.now[0] = 1121.0
    with pytest.raises(BenchDenied):
        f.guard.validate(f.ctx, f.archives, f.targets, object())
    assert f.guard.status()["active"] is False
    f.now[0] = 1000.0
    with pytest.raises(BenchDenied, match="explicit arm"):
        f.guard.validate(f.ctx, f.archives, f.targets, object())


@pytest.mark.parametrize("failure", ["owner", "expiry", "file"])
def test_status_watchdog_disarms_without_get_or_accept(sealed, failure):
    f = sealed
    arm(f)
    if failure == "owner":
        f.owner.clear()
    elif failure == "expiry":
        f.now[0] = 1121
    else:
        f.case_path.write_text("{}")
    status = f.guard.status()
    assert status["active"] is False and status["reason"]
    assert "sources" not in status and "rig_owner" not in status and "run_root" not in status


def test_disconnect_of_control_or_participating_screen_disarms(sealed):
    f = sealed
    arm(f)
    screen = object()
    f.guard.validate(f.ctx, f.archives, f.targets, screen)
    f.guard.disconnected(screen)
    assert not f.guard.status()["active"]
    arm(f)
    f.guard.disconnected(f.owner)
    assert not f.guard.status()["active"]


def test_partial_current_values_allow_only_readback_for_the_exact_issued_card(sealed):
    f = sealed
    arm(f)
    card = f.guard.build_prescription(
        f.archives, f.spinners, identity=f.identity, targets=f.targets
    )
    card.update(decision="accept", status="accepted_unverified")
    changed = {row["section"]: row["to"] for row in card["changes"]}
    f.ctx["spinners"][0]["value"] = changed[f.ctx["spinners"][0]["section"]]
    result = f.guard.validate(f.ctx, f.archives, f.targets, object(), card=card)
    assert result["readback_only"] is True
    with pytest.raises(BenchDenied):
        f.guard.build_prescription(
            f.archives, f.ctx["spinners"], identity=f.identity, targets=f.targets
        )
    assert not f.guard.status()["active"]


@pytest.mark.parametrize("change", ["bounds", "value", "proposal", "mode"])
def test_readback_does_not_relax_bounds_or_authorize_another_proposal(sealed, change):
    f = sealed
    arm(f)
    card = f.guard.build_prescription(
        f.archives, f.spinners, identity=f.identity, targets=f.targets
    )
    card.update(decision="accept", status="accepted_unverified")
    if change == "bounds":
        f.ctx["spinners"][0]["max"] += 1
    elif change == "value":
        f.ctx["spinners"][0]["value"] += 3
    elif change == "proposal":
        card["changes"][0]["to"] -= 1
    else:
        card["mode"] = "ordinary"
    with pytest.raises(BenchDenied):
        f.guard.validate(f.ctx, f.archives, f.targets, object(), card=card)
    assert not f.guard.status()["active"]


@pytest.mark.parametrize("authority", ["human", "unknown"])
def test_analysis_eligible_non_ai_evidence_cannot_enter_bench(sealed, authority):
    f = sealed
    for archive, source in zip(f.archives, f.sources, strict=True):
        archive.pop("qualification")
        if authority != "unknown":
            archive["qualification"] = build_qualification(
                archive,
                authority="human",
                origin="synthetic_test",
                supported_uses={use: True for use in USES},
                channels={key: {"unit": unit, "basis": "measured"} for key, unit in UNITS.items()},
                evidence=[{"kind": "verified_human_control", "sha256": "a" * 64}],
            )
        source["sha256"] = write(Path(source["path"]), archive)
    write(f.case_path, f.case)
    assert qualify_archive(f.archives[0], use="analysis").allowed
    with pytest.raises(BenchDenied, match="native-AI"):
        arm(f)


def test_case_enrollment_cannot_reuse_sources_or_rewrite_an_existing_case(sealed):
    f = sealed
    arm(f)
    f.case["case_id"] = "case-two"
    other = f.run_root / "case-two.json"
    write(other, f.case)
    with pytest.raises(BenchDenied, match="another case"):
        f.guard.arm(other, f.ctx, f.archives, f.targets, object())
    f.case["case_id"] = "case-one"
    f.case["extra"] = "rewritten after enrollment"
    write(f.case_path, f.case)
    with pytest.raises(BenchDenied, match="previously enrolled"):
        arm(f)


@pytest.mark.parametrize("trap", ["cold", "lockup", "short", "bounds"])
def test_bench_keeps_existing_numerical_confounder_guards(sealed, trap):
    f = sealed
    if trap == "short":
        f.archives.pop(0)
        f.sources.pop(0)
    elif trap in {"cold", "lockup"}:
        fields = f.archives[-1]["trace"]["fields"]
        prefix = "tyreCoreTemp_fl" if trap == "cold" else "wheelAngularSpeed_fl"
        for row in f.archives[-1]["trace"]["samples"]:
            row[fields.index(prefix)] = 40 if trap == "cold" else 0
    else:
        f.ctx["spinners"][0]["range_known"] = False
        f.case["spinners_sha256"] = pressure_spinners_sha256(f.ctx["spinners"])
    for archive, source in zip(f.archives, f.sources, strict=True):
        archive.pop("qualification")
        archive["qualification"] = build_qualification(
            archive,
            authority="ai",
            origin="synthetic_native_ai",
            supported_uses={use: use == "analysis" for use in USES},
            channels={key: {"unit": unit, "basis": "measured"} for key, unit in UNITS.items()},
        )
        source["sha256"] = write(Path(source["path"]), archive)
    refresh_seal(f)
    arm(f)
    card = f.guard.build_prescription(
        f.archives, f.ctx["spinners"], identity=f.identity, targets=f.targets
    )
    assert card["status"] == "abstained" and card["changes"] == [] and card["reason"]


def test_native_windows_owner_creation_reader_matches_current_process():
    if os.name != "nt":
        pytest.skip("Windows process creation API")
    from tools.ai_sidecar.pressure_bench import _process_creation_time

    assert 0 < _process_creation_time(os.getpid()) <= time.time()


def test_actual_temporary_os_lock_loss_disarms_without_any_process_start(sealed):
    from tools.ac_harness.rig_lock import RigSessionLock, RigSessionOwner, read_rig_session_owner
    from tools.ai_sidecar.pressure_bench import _process_creation_time

    f = sealed
    owner = RigSessionOwner(pid=os.getpid(), cwd=str(f.tmp_path), started_at=f.owner["started_at"])
    f.permit["rig_owner"] = owner.to_dict()
    f.permit["owner_create_time"] = _process_creation_time(os.getpid())
    write(f.permit_path, f.permit)
    f.guard.owner_reader = read_rig_session_owner
    f.guard.process_create_time = _process_creation_time
    # This is a temporary unit-test lock, never the physical rig's canonical path.
    with RigSessionLock(f.lock_path, owner=owner):
        arm(f)
        assert f.guard.status()["active"] is True
    assert f.guard.status()["active"] is False


def test_missing_private_receipt_does_not_expose_its_path_in_status(sealed):
    f = sealed
    arm(f)
    f.case_path.unlink()
    status = f.guard.status()
    assert status["active"] is False
    assert str(f.run_root) not in status["reason"]


@pytest.mark.parametrize("clock_failure", ["wall_rollback", "monotonic_expiry"])
def test_clock_changes_cannot_extend_an_armed_case(sealed, clock_failure):
    f = sealed
    tick = [100.0]
    f.guard.monotonic_clock = lambda: tick[0]
    arm(f)
    if clock_failure == "wall_rollback":
        f.now[0] = 999.5  # Still after sealing, but before the actual arm time.
    else:
        tick[0] += 121  # Wall time stays frozen; permission must still expire.
    assert f.guard.status()["active"] is False
    assert "clock" in f.guard.status()["reason"] or "deadline" in f.guard.status()["reason"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", True),
        ("mode", "ordinary"),
        ("run_id", "other-run"),
        ("case_id", "other-case"),
        ("oracle_sha256", "c" * 64),
        ("enrollable", False),
        ("authority", "shared"),
        ("sealed_at", 1001.0),
        ("expires_at", 999.0),
        ("expires_at", 1119.5),
        ("expires_at", 2000.0),
        ("targets_sha256", "c" * 64),
        ("spinners_sha256", "c" * 64),
    ],
)
def test_matching_seal_file_hash_cannot_replace_admitted_case_bindings(sealed, key, value):
    f = sealed
    f.oracle_receipt[key] = value
    # The wrapper knows this changed file's exact byte hash. That alone must
    # never authorize a receipt for another case, unadmitted source or lifetime.
    f.case["oracle_seal"]["sha256"] = write(f.seal_path, f.oracle_receipt)
    write(f.case_path, f.case)
    with pytest.raises(BenchDenied, match="oracle"):
        arm(f)
    assert f.guard.status()["active"] is False


@pytest.mark.parametrize(
    "binding",
    [
        "path",
        "sha256",
        "canonical_sha256",
        "payload_sha256",
        "session_id",
        "lap_uuid",
        "lap_n",
        "identity",
        "archive_hashes",
    ],
)
def test_oracle_seal_sources_are_bound_to_exact_current_native_inputs(sealed, binding):
    f = sealed
    if binding == "identity":
        f.oracle_receipt["identity"] = {**f.identity, "session_id": "other-session"}
    elif binding == "archive_hashes":
        f.oracle_receipt["archive_hashes"][0] = "c" * 64
    elif binding == "path":
        f.oracle_receipt["sources"][0]["path"] = str(f.lap_dir / "lap_other.json")
    else:
        f.oracle_receipt["sources"][0][binding] = 99 if binding == "lap_n" else "c" * 64
    f.case["oracle_seal"]["sha256"] = write(f.seal_path, f.oracle_receipt)
    write(f.case_path, f.case)
    with pytest.raises(BenchDenied, match="oracle"):
        arm(f)
    assert not f.guard.status()["active"]


def test_capture_isolation_loss_denies_before_any_bench_workflow(sealed):
    f = sealed
    arm(f)
    f.ctx["capture_isolated"] = False
    with pytest.raises(BenchDenied, match="capture isolation"):
        f.guard.validate(f.ctx, f.archives, f.targets, object())
    assert not f.guard.status()["active"]


def test_guard_never_uses_hidden_oracle_label_or_decision_to_produce_card(sealed):
    f = sealed
    f.oracle_receipt.update(label="not_a_label_the_candidate_can_use", directions={"gold": 999})
    f.case["oracle_seal"]["sha256"] = write(f.seal_path, f.oracle_receipt)
    write(f.case_path, f.case)
    arm(f)
    card = f.guard.build_prescription(
        f.archives, f.spinners, identity=f.identity, targets=f.targets
    )
    assert card["status"] == "proposed"
    assert "not_a_label" not in json.dumps(card) and "gold" not in json.dumps(card)


def test_oracle_file_change_disarms_watchdog_before_get(sealed):
    f = sealed
    arm(f)
    f.seal_path.write_text("{}")
    assert f.guard.status()["active"] is False
    assert "oracle seal changed" in f.guard.status()["reason"]
