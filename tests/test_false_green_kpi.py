"""Meta-validation of the false-green-rate KPI (`false_green_kpi.py`, EPIC #154 Part G).

The KPI measures the harness detector layer's discrimination against a labeled corpus of the real
failure classes the harness exists to catch. These tests assert it is (1) green on the shipped
corpus, (2) NON-vacuous — a defanged oracle visibly leaks false greens above the gate — and (3)
faithful — it drives the same oracle symbols the harness uses, propagates through the real
`run_self_test` report path, and exercises the real `PhysicsStallDetector`. All off-sim.
"""

from __future__ import annotations

from tools.ac_harness import false_green_kpi, self_test
from tools.ac_harness.auto_drive import PhysicsStallDetector
from tools.ac_harness.false_green_kpi import (
    BROKEN_CLASSES,
    GATE_THRESHOLD,
    OUT_OF_SCOPE,
    _report_path_ok,
    _snap,
    build_corpus,
    run_kpi,
)


# --------------------------------------------------------------------------- shipped corpus passes
def test_kpi_passes_on_shipped_corpus():
    r = run_kpi()
    assert r.false_green_rate == 0.0  # zero broken scenarios leak -> well under the 5% gate
    assert r.false_red_rate == 0.0  # no healthy scenario false-fails
    assert r.ok is True
    assert r.broken_total >= 12  # a broad broken corpus, not a token one
    assert r.healthy_total >= 6


def test_every_declared_broken_class_is_covered():
    r = run_kpi()
    assert r.missing_classes == []
    for cls in BROKEN_CLASSES:
        assert cls in r.covered_classes, f"declared class {cls} not represented in the corpus"


def test_report_is_deterministic():
    assert run_kpi().to_dict() == run_kpi().to_dict()


def test_out_of_scope_is_surfaced():
    # The report must name what it cannot see, so it never implies full human-reality coverage.
    r = run_kpi()
    assert r.out_of_scope == list(OUT_OF_SCOPE)
    assert len(r.out_of_scope) >= 3


# --------------------------------------------------------------------------- anti-vacuity (teeth)
def test_weakening_the_sequence_oracle_trips_the_gate():
    # Defang the richest oracle; every sequence-broken scenario must now leak as a false green,
    # pushing the rate well above the gate. Proves the KPI is sensitive to oracle strength.
    weak = run_kpi(weaken="sequence")
    assert weak.false_green_rate > GATE_THRESHOLD
    assert weak.ok is False
    assert weak.broken_false_green >= 5


def test_weakening_the_render_oracle_also_leaks():
    weak = run_kpi(weaken="render")
    assert weak.broken_false_green >= 2  # hud_blank + hud_uniform leak
    assert weak.false_green_rate > GATE_THRESHOLD


def test_gate_is_zero_leaks_not_a_rate():
    # Deterministic arm: a single leaked broken scenario must FAIL even when a large caught corpus
    # dilutes the rate below 5% (the gate must not be diluteable as the corpus grows). Predicate
    # tested directly to isolate it from coverage (workflow review finding on #513).
    from tools.ac_harness.false_green_kpi import KpiReport

    r = KpiReport(
        false_green_rate=1 / 21,  # 4.76% — under the reported 5% bar
        false_red_rate=0.0,
        broken_total=21,
        broken_false_green=1,  # ...but one broken scenario genuinely leaked
        healthy_total=8,
        healthy_false_red=0,
        missing_classes=[],
    )
    assert r.false_green_rate < GATE_THRESHOLD
    assert r.ok is False  # zero-leak gate fails despite the sub-threshold rate


def test_dropping_required_topic_is_red_but_optional_is_green():
    # Granularity: dropping a REQUIRED continuous topic must flag broken; dropping the OPTIONAL
    # `delta` (needs a reference lap) must stay healthy. Both are in the shipped corpus.
    r = run_kpi()
    assert "healthy_dropped_optional_delta" not in r.false_reds
    assert "broken_missing_tire_temps" not in r.false_greens


# --------------------------------------------------------------------------- faithful to production
def test_kpi_uses_the_same_sequence_oracle_symbol_as_self_test():
    # No divergent codepath: the KPI and the live self-test evaluate the identical function object.
    assert false_green_kpi.evaluate_sequence is self_test.evaluate_sequence


def test_report_path_propagates_broken_verdict():
    # An oracle FAIL must reach SelfTestReport.ok through the full orchestration (no swallowing).
    assert _report_path_ok([_snap("connection"), _snap("coaching.snapshot")]) is False


def test_report_path_propagates_healthy_verdict():
    assert (
        _report_path_ok(
            [
                _snap("connection"),
                _snap("session"),
                _snap("lap"),
                _snap("tire_temps"),
                _snap("coaching.snapshot"),
            ]
        )
        is True
    )


def test_corpus_expected_labels_and_oracles_are_valid():
    for sc in build_corpus():
        assert sc.expected in ("GREEN", "RED")
        assert sc.oracle in ("sequence", "schema", "sim_death", "render", "report_path")
        assert callable(sc.run)


# ------------------------------------------------------------------- extracted sim-death oracle
def test_physics_stall_advancing_never_trips():
    det = PhysicsStallDetector(sim_dead_seconds=1.0)
    tripped = [det.update(i * 0.1, i + 1) for i in range(25)]
    assert not any(tripped)


def test_physics_stall_frozen_packet_trips():
    det = PhysicsStallDetector(sim_dead_seconds=1.0)
    assert det.update(0.0, 5) is False
    assert det.update(0.5, 5) is False
    assert det.update(1.6, 5) is True  # frozen > sim_dead_seconds


def test_physics_stall_none_does_not_reset_timer():
    # A None (physics mmap gone) must NOT reset the death timer (#460 review).
    det = PhysicsStallDetector(sim_dead_seconds=1.0)
    assert det.update(0.0, 5) is False
    assert det.update(0.5, None) is False
    assert det.update(1.7, None) is True


def test_physics_stall_real_advance_resets_timer():
    det = PhysicsStallDetector(sim_dead_seconds=1.0)
    det.update(0.0, 5)
    assert det.update(0.9, 6) is False  # advance just before the deadline resets it
    assert det.update(1.8, 6) is False  # 0.9s since the reset -> still alive


def test_physics_stall_anchored_at_start_trips_on_late_none():
    # Sim already dead at loop start, packet mmap gone: the first sample arrives after the deadline.
    # Anchored at construction (now=0.0) the veto must fire, not be delayed a full window (codex on
    # #513) — the inline rig watchdog started its timer at loop begin; this restores that.
    det = PhysicsStallDetector(sim_dead_seconds=1.0, now=0.0)
    assert det.update(1.5, None) is True


def test_physics_stall_default_anchors_on_first_update():
    # Without a start anchor the timer begins at the first sample (the KPI oracle's per-sample mode)
    det = PhysicsStallDetector(sim_dead_seconds=1.0)
    assert det.update(1.5, None) is False


def test_coverage_counts_only_broken_scenarios():
    # A declared broken class present ONLY as a mislabeled GREEN scenario must read as NOT covered,
    # so the gate can never pass on a hollowed-out failure class (codex on #513).
    from tools.ac_harness.false_green_kpi import Scenario

    hollow = [Scenario("mislabeled", "missing_connection", "-", "GREEN", "sequence", lambda: True)]
    r = run_kpi(hollow)
    assert "missing_connection" not in r.covered_classes
    assert "missing_connection" in r.missing_classes
    assert r.ok is False


# --------------------------------------------------------------------------- CLI
def test_main_returns_zero_on_pass():
    assert false_green_kpi._main([]) == 0


def test_main_writes_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # outputs are contained under cwd (#204 convention)
    rc = false_green_kpi._main(["--json", "kpi.json"])
    assert rc == 0
    import json

    data = json.loads((tmp_path / "kpi.json").read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert data["false_green_rate"] == 0.0
    assert data["kpi"] == "known_failure_discrimination"
    assert "out_of_scope" in data


def test_main_rejects_json_path_escaping_cwd(tmp_path, monkeypatch):
    # --json must not write outside cwd (qodo on #513): a `..` traversal is refused with exit 2.
    monkeypatch.chdir(tmp_path)
    rc = false_green_kpi._main(["--json", "../escape.json"])
    assert rc == 2
    assert not (tmp_path.parent / "escape.json").exists()
