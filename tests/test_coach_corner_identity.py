"""#854: speed-minimum indexes never become turn names without canonical geometry."""

from __future__ import annotations

import asyncio

import pytest

from tools.ai_sidecar.coaching import between_lap
from tools.ai_sidecar.coaching.generation import LatestGenerationQueue
from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.coaching_runtime import CoachRuntime
from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.track_map import bind_reference_corners
from tools.ai_sidecar.track_reference import CornerReference


def ref(index, lo, apex, hi):
    return CornerReference(index, apex, lo, hi, 100)


def archive():
    return {"car": {"id": "ks_porsche_911_gt3_r_2016"}, "track": {"id": "magione"}}


def catalog(*regions, combo=None):
    return {
        "available": True,
        "combo": combo or ("ks_porsche_911_gt3_r_2016", "magione", ""),
        "corners": [
            {"corner_id": label, "s0": lo, "s1": hi, "brake_spline": (lo - 0.01) % 1}
            for label, lo, hi in regions
        ],
    }


def test_measured_102183_reference_regions_do_not_renumber_live_nine_turns():
    # Compact derived geometry from the restored native102183ms Magione archive
    # and the active Lua catalogue. Control provenance stays unknown; these are not
    # fabricated nine-corner dynamics or a certified human/PB reference.
    refs = [
        ref(0, 0.03071, 0.10397, 0.13257),
        ref(1, 0.16326, 0.21144, 0.23305),
        ref(2, 0.26915, 0.33680, 0.41887),
        ref(3, 0.62810, 0.70497, 0.71558),
        ref(4, 0.77250, 0.87810, 0.92768),
    ]
    live = catalog(
        ("T1", 0.04997, 0.15472),
        ("T2", 0.17872, 0.25914),
        ("T3", 0.28314, 0.30596),
        ("T4", 0.32996, 0.34336),
        ("T5", 0.36736, 0.62835),
        ("T6", 0.65235, 0.76342),
        ("T7", 0.78742, 0.81433),
        ("T8", 0.83833, 0.85102),
        ("T9", 0.87502, 0.02597),
    )
    binding = bind_reference_corners(archive(), refs, live)
    assert binding["labels"] == {0: "T1", 1: "T2"}
    assert binding["reason"] == "partial_unique_corner_geometry"
    assert binding["eligible_count"] == 2 and binding["reference_count"] == 5
    assert set(binding["rejected"]) == {2, 3, 4}
    assert [r.index for r in refs] == [0, 1, 2, 3, 4]  # internal facts remain untouched


@pytest.mark.parametrize(
    "refs,live,labels,reason",
    [
        ([ref(0, 0.60, 0.70, 0.75)], catalog(("T6", 0.65, 0.76)), {0: "T6"}, None),
        ([ref(0, 0.90, 0.94, 0.98)], catalog(("T9", 0.85, 0.05)), {0: "T9"}, None),
        (
            [ref(0, 0.20, 0.30, 0.60)],
            catalog(("T1", 0.2, 0.35), ("T2", 0.4, 0.6)),
            {},
            "merged_or_unresolved_reference_region",
        ),
        (
            [ref(0, 0.20, 0.25, 0.30), ref(1, 0.40, 0.45, 0.50)],
            catalog(("T7", 0.15, 0.55)),
            {},
            "split_reference_region",
        ),
        (
            [ref(0, 0.10, 0.11, 0.14)],
            catalog(("T1", 0.12, 0.16)),
            {},
            "apex_outside_canonical_region",
        ),
        (
            [ref(0, 0.10, float("nan"), 0.14)],
            catalog(("T1", 0.12, 0.16)),
            {},
            "invalid_reference_geometry",
        ),
    ],
)
def test_geometry_mapping_is_unique_not_ordinal(refs, live, labels, reason):
    result = bind_reference_corners(archive(), refs, live)
    assert result["labels"] == labels
    if reason:
        assert set(result["rejected"].values()) == {reason}
        assert result["reason"] == "no_unique_corner_geometry"


def test_merged_rejected_neighbour_cannot_leave_shared_canonical_name_eligible():
    result = bind_reference_corners(
        archive(),
        [ref(0, 0.2, 0.3, 0.35), ref(1, 0.3, 0.5, 0.6)],
        catalog(("T1", 0.2, 0.4), ("T2", 0.45, 0.6)),
    )
    assert result["labels"] == {}
    assert result["rejected"] == {
        0: "split_reference_region",
        1: "merged_or_unresolved_reference_region",
    }
    assert result["reason"] == "no_unique_corner_geometry"


def test_unknown_malformed_and_wrong_combo_do_not_supply_names():
    refs = [ref(0, 0.60, 0.70, 0.75)]
    for live in (
        None,
        {"available": False},
        catalog(("T6", 0.65, 0.76), combo=("other", "magione", "")),
    ):
        result = bind_reference_corners(archive(), refs, live)
        assert result["labels"] == {} and result["reason"] == "canonical_catalog_unavailable"
    native = {**archive(), "corners": [{"label": "T6", "brakePointSpline": 0.64}]}
    assert not bind_reference_corners(native, refs)["ready"]  # labels alone lack geometry


def coach_with_binding():
    refs = [ref(0, 0.2, 0.3, 0.6), ref(1, 0.65, 0.70, 0.75)]
    coach = CoachRuntime(refs, {}, {}, ledger=CoachingLedger(hysteresis=1, assess_laps=0))
    coach.set_corner_identity(
        bind_reference_corners(
            archive(), refs, catalog(("T1", 0.2, 0.35), ("T2", 0.4, 0.6), ("T6", 0.65, 0.76))
        )
    )
    return coach


def test_all_coach_advisory_kinds_require_same_binding_and_reset_clears_it():
    coach = coach_with_binding()
    for kind in ("early_brake", "save", "confirm"):
        ambiguous = Advisory(kind, 0, 0.3, "act", "Brake later.")
        eligible = Advisory(kind, 1, 0.7, "act", "Brake later.")
        assert coach.named_advisory(ambiguous) is None
        named = coach.named_advisory(eligible)
        assert named.corner == 5 and eligible.corner == 1
    coach.reset()
    assert coach.named_advisory(eligible) is None
    assert coach.corner_identity["reason"] == "canonical_catalog_unavailable"


@pytest.mark.parametrize("enabled", [False, True])
def test_between_lap_filters_ambiguous_priority_before_selection_and_names_model_or_rules(
    monkeypatch, enabled
):
    import tools.ai_sidecar.server as server

    coach = coach_with_binding()
    coach.ledger.record_pass(0, Diagnosis(RootError.EARLY_BRAKE, {}), time_lost_s=2, valid=True)
    coach.ledger.record_pass(1, Diagnosis(RootError.EARLY_BRAKE, {}), time_lost_s=1, valid=True)
    monkeypatch.setattr(coach.ledger, "focus_corner", lambda: 0)
    monkeypatch.setattr(server, "_coach_runtime", coach)
    monkeypatch.setattr(server, "_recent_between_lap_advice_keys", [])
    monkeypatch.setattr(between_lap, "debrief_feature_enabled", lambda: enabled)

    def generate(prompt, **kw):
        assert prompt.endswith("NEXT LAP T6: BRAKE LATER.")
        return "NEXT LAP T6: BRAKE LATER."

    monkeypatch.setattr(between_lap, "call_ollama_generate", generate)
    sent = []

    async def send(_socket, message):
        sent.append(message)

    monkeypatch.setattr(server, "_safe_send", send)

    async def run():
        queue = LatestGenerationQueue()
        monkeypatch.setattr(server, "_get_generation_queue", lambda: queue)
        await server._coach_v2_between_lap(object(), {"lap": 3}, reply_coaching=True)

    asyncio.run(run())
    assert len(sent) == 1
    assert sent[0]["corner"] == "T6" and sent[0]["cornerIndex"] == 5
    assert sent[0]["text"].upper() == "NEXT LAP T6: BRAKE LATER."
    assert sent[0]["adviceSource"] == ("model" if enabled else "rules")


def test_binding_change_during_generation_drops_reply_and_unknown_never_calls_model(monkeypatch):
    import tools.ai_sidecar.server as server

    coach = coach_with_binding()
    coach.ledger.record_pass(1, Diagnosis(RootError.EARLY_BRAKE, {}), time_lost_s=1, valid=True)
    monkeypatch.setattr(server, "_coach_runtime", coach)
    monkeypatch.setattr(server, "_recent_between_lap_advice_keys", [])
    monkeypatch.setattr(between_lap, "debrief_feature_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(
        between_lap,
        "call_ollama_generate",
        lambda *a, **kw: calls.append(1) or "NEXT LAP T6: BRAKE LATER.",
    )
    sent = []

    async def send(_socket, message):
        sent.append(message)

    class ChangedQueue:
        async def submit(self, fn, **kw):
            result = fn()
            coach.reset()
            return result

    monkeypatch.setattr(server, "_safe_send", send)
    monkeypatch.setattr(server, "_get_generation_queue", ChangedQueue)
    asyncio.run(server._coach_v2_between_lap(object(), {"lap": 3}, reply_coaching=True))
    assert calls == [1] and not sent
    asyncio.run(server._coach_v2_between_lap(object(), {"lap": 4}, reply_coaching=True))
    assert calls == [1] and not sent
    assert server.public_voice_runtime_status()["coach_corner_identity"]["ready"] is False


def test_live_catalog_drives_both_voice_and_cue_fanout(monkeypatch):
    import tools.ai_sidecar.server as server
    from tests.test_realtime_observer import _corner_archive
    from tools.ai_sidecar.coaching_runtime import build_coach_runtime

    native = _corner_archive()
    coach = build_coach_runtime(native)
    assert coach is not None and len(coach.refs) == 1
    r = coach.refs[0]
    monkeypatch.setattr(server, "_coach_runtime", coach)
    monkeypatch.setattr(server, "_map_reference_archive", native)
    monkeypatch.setattr(server, "_map_latest_archive", None)
    monkeypatch.setattr(server, "_map_corner_catalog", None)
    monkeypatch.setattr(server, "_observer_feed_peer", None)
    monkeypatch.setattr(server, "_lua_authorized_peers", {"lua"})
    monkeypatch.setattr(server, "_external_peer_classes", {"lua": server.CLIENT_CLASS_LUA})
    monkeypatch.setattr(server, "_race_manager", None)
    monkeypatch.setattr(server, "_shift_observer", None)
    monkeypatch.setattr(
        coach,
        "observe",
        lambda frame: [
            Advisory("early_brake", 0, r.apex_spline, "act", "Brake later."),
            Advisory("early_brake", 99, 0.8, "act", "Wrong region"),
        ],
    )
    spoken, frames = [], []

    class Voice:
        def subscribe(self, advisory):
            spoken.append(advisory)

    async def broadcast(frame, *, exclude):
        frames.append(frame)

    monkeypatch.setattr(server, "_voice_coach", Voice())
    monkeypatch.setattr(server, "_broadcast_external", broadcast)
    server._peripheral_rate_limiter.reset()

    async def run():
        car_id, track_id = native["car"]["id"], native["track"]["id"]
        await server._refresh_map_corner_catalog(
            {
                "corner_catalog_available": True,
                "corner_catalog_car_id": car_id,
                "corner_catalog_track_id": track_id,
                "corner_catalog_layout": "",
                "corner_catalog": [
                    {
                        "corner_id": "T6",
                        "s0": r.spline_lo,
                        "s1": r.spline_hi,
                        "brake_spline": r.spline_lo,
                    }
                ],
            },
            "lua",
        )
        assert coach.corner_identity["labels"] == {0: "T6"}
        generation = coach.corner_identity_generation
        await server._refresh_map_corner_catalog({"corner_catalog_available": False}, "browser")
        assert coach.corner_identity_generation == generation
        await server._publish_coaching_cues({"spline": 0.5}, exclude="lua")
        await asyncio.sleep(0)

    asyncio.run(run())
    cues = [f for f in frames if f["topic"] == "coaching.cue"]
    assert len(cues) == 1 and cues[0]["payload"]["corner"] == 5
    assert len(spoken) == 1 and spoken[0].corner == 5
