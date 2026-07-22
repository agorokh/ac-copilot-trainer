"""Off-rig tests for the freeze-forensics verdict logic (#630 Part F / #627 §6.1).

The instrument's whole value is that its PASS is honest: it decides whether a wedged ``acs.exe`` is
spinning, blocked, or still computing, and #627 gates the upstream CSP bug report on that answer.
So the decision is a pure function and every branch is pinned here — including the two verdicts that
exist because both mistakes were made for real during the 2026-07-19 session.
"""

from __future__ import annotations

import subprocess

from tools.ac_harness.freeze_forensics import (
    DEFAULT_TIGHT_LOOP_BYTES,
    ForensicVerdict,
    classify_forensics,
    rip_span,
)


def _classify(**overrides):
    """A confirmed-livelock observation set, with individual signals overridden per test."""
    args = {
        "burning_cpu": True,
        "gfx_static": True,
        "phys_advancing": True,
        "rips": [0x7FF000001000, 0x7FF000001020, 0x7FF000001040],
    }
    args.update(overrides)
    return classify_forensics(**args)


def test_livelock_is_confirmed_when_all_three_signals_agree() -> None:
    verdict, reading = _classify()
    assert verdict is ForensicVerdict.LIVELOCK_CONFIRMED
    assert "tight loop" in reading
    # Hottest-thread residual must stay visible in the reading — S1/S2 do not identify render.
    assert "hottest sampled thread" in reading
    assert "physics worker" in reading


def test_a_recovered_session_is_not_a_wedge() -> None:
    """The mistake made for real: a trial whose graphics packet advanced had RECOVERED.

    It was a transient init stall reported as a freeze, and calling it a confirmed spin was wrong.
    An advancing render packet must short-circuit before any livelock claim.
    """
    verdict, reading = _classify(gfx_static=False)
    assert verdict is ForensicVerdict.NOT_WEDGED
    assert "recovered" in reading


def test_a_recovered_session_wins_over_every_other_signal() -> None:
    """Even with CPU burning and a pinned RIP, an advancing render packet means no wedge."""
    verdict, _ = _classify(gfx_static=False, burning_cpu=True, rips=[0x1000, 0x1008])
    assert verdict is ForensicVerdict.NOT_WEDGED


def test_both_streams_stopped_is_not_a_render_wedge() -> None:
    """#627 §2: a render wedge keeps PHYSICS advancing. Both stopped is a pause or a dead sim."""
    verdict, reading = _classify(phys_advancing=False)
    assert verdict is ForensicVerdict.NOT_RENDER_WEDGE
    assert "physics" in reading


def test_idle_thread_is_a_block_not_a_spin() -> None:
    verdict, reading = _classify(burning_cpu=False)
    assert verdict is ForensicVerdict.BLOCKED_NOT_SPIN
    assert "WAITING" in reading


def test_one_rip_sample_is_inconclusive_not_a_long_computation() -> None:
    """The audit's catch: a single sample carries no information about wandering.

    Falling through to LONG_COMPUTATION would print "RIP wanders" from one point — and that is the
    one verdict that would wrongly kill the livelock hypothesis the upstream report rests on.
    """
    verdict, reading = _classify(rips=[0x1000])
    assert verdict is ForensicVerdict.INCONCLUSIVE_INSUFFICIENT_RIP_SAMPLES
    assert "cannot be decided" in reading


def test_zero_rip_samples_is_inconclusive() -> None:
    verdict, _ = _classify(rips=[])
    assert verdict is ForensicVerdict.INCONCLUSIVE_INSUFFICIENT_RIP_SAMPLES


def test_wandering_rip_is_a_long_computation() -> None:
    verdict, reading = _classify(rips=[0x1000, 0x1000 + DEFAULT_TIGHT_LOOP_BYTES * 4])
    assert verdict is ForensicVerdict.LONG_COMPUTATION
    assert "wanders" in reading


def test_the_tight_loop_boundary_is_exclusive() -> None:
    assert _classify(rips=[0x1000, 0x1000 + DEFAULT_TIGHT_LOOP_BYTES - 1])[0] is (
        ForensicVerdict.LIVELOCK_CONFIRMED
    )
    assert _classify(rips=[0x1000, 0x1000 + DEFAULT_TIGHT_LOOP_BYTES])[0] is (
        ForensicVerdict.LONG_COMPUTATION
    )


def test_rip_span_needs_two_samples() -> None:
    assert rip_span([]) is None
    assert rip_span([0x7FF000001000]) is None
    assert rip_span([0x7FF000001000, 0x7FF000001040]) == 0x40


def test_rip_span_is_the_full_spread_not_the_last_step() -> None:
    assert rip_span([0x1000, 0x1010, 0x1004]) == 0x10


def test_two_identical_rips_are_a_zero_span_tight_loop() -> None:
    """A perfectly pinned RIP is span 0 — the strongest livelock evidence, not a missing span."""
    verdict, _ = _classify(rips=[0x7FF000001000, 0x7FF000001000])
    assert verdict is ForensicVerdict.LIVELOCK_CONFIRMED


def test_parse_rip_handles_both_windbg_address_forms() -> None:
    """WinDbg prints 64-bit addresses flat OR backtick-separated (``00007ff6`00001234``).

    Missing the backtick form yields zero parsed RIPs, silently degrading every diagnosis to
    INCONCLUSIVE — the instrument would look like it works while proving nothing. The test
    must exercise the production parser itself so the sanitization cannot drift away from it.
    """
    from tools.ac_harness.freeze_forensics import parse_rip

    assert parse_rip("rax=0000000000000001 rip=00007ff600001234 rsp=...") == 0x00007FF600001234
    assert parse_rip("rax=0000000000000001 rip=00007ff6`00001234 rsp=...") == 0x00007FF600001234
    assert parse_rip("no registers captured") is None


def test_selected_tid_confirmed_only_for_the_requested_thread() -> None:
    """A failed ``~~[tid]s`` leaves cdb in the default (parked) context but still prints
    registers — only the post-switch marker separates real evidence from a wrong-thread RIP."""
    from tools.ac_harness.freeze_forensics import selected_tid_confirmed

    assert selected_tid_confirmed("AC_TID=1a2b\nrip=00007ff600001234", 0x1A2B)
    assert not selected_tid_confirmed("AC_TID=3c4d\nrip=00007ff600001234", 0x1A2B)
    # The requested tid as a hex PREFIX of the actual thread must not confirm (substring trap).
    assert not selected_tid_confirmed("AC_TID=1a2b\nrip=00007ff600001234", 0x1A)
    assert not selected_tid_confirmed("no marker at all", 0x1A2B)


def test_thaw_cdb_command_is_noninvasive_and_detaches() -> None:
    """The thaw must stay ``-pv`` (never become the process debugger) and end with ``qd``."""
    from pathlib import Path

    from tools.ac_harness.freeze_forensics import thaw_cdb_command

    cmd = thaw_cdb_command(Path("/fake/cdb.exe"), 4242)
    assert cmd[0].endswith("cdb.exe")
    assert "-pv" in cmd
    assert cmd[cmd.index("-p") + 1] == "4242"
    assert cmd[-2:] == ["-c", "qd"]


def test_best_effort_thaw_never_raises_on_timeout(monkeypatch) -> None:
    """A stuck thaw must not promote a capture failure into a second exception."""
    from pathlib import Path

    from tools.ac_harness.freeze_forensics import best_effort_thaw

    def _timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["cdb"], timeout=15)

    monkeypatch.setattr(
        "tools.ac_harness.freeze_forensics.subprocess.run",
        _timeout,
    )
    assert best_effort_thaw(Path("/fake/cdb.exe"), 99) == "thaw=timeout"


def test_best_effort_thaw_never_raises_on_oserror(monkeypatch) -> None:
    from pathlib import Path

    from tools.ac_harness.freeze_forensics import best_effort_thaw

    def _boom(*_args, **_kwargs):
        raise OSError("CreateProcess failed")

    monkeypatch.setattr(
        "tools.ac_harness.freeze_forensics.subprocess.run",
        _boom,
    )
    assert best_effort_thaw(Path("/fake/cdb.exe"), 99).startswith("thaw=failed:")


def test_best_effort_thaw_requires_zero_exit(monkeypatch) -> None:
    """A nonzero cdb exit is a failed thaw — subprocess.run still returns normally."""
    from pathlib import Path

    from tools.ac_harness.freeze_forensics import best_effort_thaw

    def _nonzero(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["cdb"], returncode=1, stdout="", stderr="Could not attach"
        )

    monkeypatch.setattr(
        "tools.ac_harness.freeze_forensics.subprocess.run",
        _nonzero,
    )
    status = best_effort_thaw(Path("/fake/cdb.exe"), 99)
    assert status.startswith("thaw=failed:")
    assert "rc=1" in status
    assert "Could not attach" in status


def test_cdb_snapshot_thaws_target_after_timeout(monkeypatch) -> None:
    """A hard-killed ``-pv`` attach leaves suspend counts on the target unless ``qd`` re-runs.

    This is the daemon HIGH: ``subprocess.run`` kills ``cdb`` on timeout *before* the primary
    script's trailing ``qd``, so without a follow-up thaw the wedged process is permanently
    suspended — destroying the evidence the tool exists to capture.
    """
    from pathlib import Path

    import tools.ac_harness.freeze_forensics as ff

    calls: list[list[str]] = []
    cdb = Path("/fake/cdb.exe")

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 90))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ff, "find_cdb", lambda: cdb)
    monkeypatch.setattr(ff.subprocess, "run", fake_run)

    sample = ff.cdb_snapshot(1234, tid=0x1A2B, timeout=1.0)
    assert sample.rip is None
    assert "cdb timed out" in sample.raw
    assert "thaw=ok" in sample.raw
    assert len(calls) == 2
    # Second call is the thaw: noninvasive attach + immediate detach.
    # Use str(Path) so the expected path matches production on Windows and POSIX.
    assert calls[1] == [str(cdb), "-pv", "-p", "1234", "-c", "qd"]


# --------------------------------------------------------------------------------------
# Part G — capture-driver decision helpers (pure; the assembly in main() is rig-only).
# --------------------------------------------------------------------------------------


def test_render_stack_candidate_beats_a_hotter_physics_thread() -> None:
    """#630 Part G — a busy physics worker outranking a wedged renderer on cycles must lose."""
    from tools.ac_harness.freeze_forensics import select_capture_tid

    physics_stack = "00 ntdll!NtWaitForSingleObject\n01 acs!physicsWorker"
    render_stack = "00 dwrite!hashLoop\n01 accRenderingAdv+0x1391c02"
    tid, reason = select_capture_tid([(111, physics_stack), (222, render_stack)])
    assert tid == 222
    assert "render-stack hint" in reason


def test_hottest_thread_is_the_fallback_when_no_stack_matches() -> None:
    from tools.ac_harness.freeze_forensics import select_capture_tid

    tid, reason = select_capture_tid([(111, "00 acs!physics"), (222, "00 ntdll!wait")])
    assert tid == 111
    assert "hottest thread" in reason


def test_unconfirmed_candidate_stacks_never_match() -> None:
    """An unconfirmed cdb transcript yields an empty stack — it must simply not match."""
    from tools.ac_harness.freeze_forensics import select_capture_tid

    tid, reason = select_capture_tid([(111, ""), (222, "")])
    assert tid == 111
    assert "hottest" in reason


def test_select_capture_tid_rejects_empty_candidates() -> None:
    import pytest

    from tools.ac_harness.freeze_forensics import select_capture_tid

    with pytest.raises(ValueError, match="candidates"):
        select_capture_tid([])


def test_s3_corpse_readings_are_discarded_not_compared() -> None:
    """Trap §7.1 — a dead sim's pinned packet must not manufacture the wedge signature."""
    from tools.ac_harness.freeze_forensics import evaluate_s3

    # Every reading taken while acs is dead: the corpse holds gfx pinned and phys pinned.
    result = evaluate_s3([(16_983, 121, False), (16_983, 121, False), (16_983, 121, False)])
    assert result.gfx_readings == ()
    assert result.phys_readings == ()
    assert result.sufficient is False
    assert result.gfx_static is False
    assert result.acs_alive_throughout is False


def test_s3_wedge_signature_from_live_readings() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3

    result = evaluate_s3([(23, 100, True), (23, 400, True), (23, 800, True)])
    assert result.gfx_static is True
    assert result.phys_advancing is True
    assert result.acs_alive_throughout is True
    assert result.sufficient is True


def test_s3_recovered_session_is_not_static() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3

    result = evaluate_s3([(23, 100, True), (23, 400, True), (4233, 800, True)])
    assert result.gfx_static is False  # the packet ADVANCED — the session recovered


def test_s3_mixed_dead_and_live_readings_keep_only_live_ones() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3

    result = evaluate_s3(
        [
            (16_983, 9_999, False),  # corpse — discarded
            (17, 100, True),
            (17, 400, True),
        ]
    )
    assert result.gfx_readings == (17, 17)
    assert result.phys_readings == (100, 400)
    assert result.gfx_static is True
    assert result.phys_advancing is True
    assert result.acs_alive_throughout is False  # honesty: the process was not alive throughout


def test_s3_single_live_reading_is_insufficient() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3

    result = evaluate_s3([(23, 100, True)])
    assert result.sufficient is False
    assert result.gfx_static is False
    assert result.phys_advancing is False


def test_s3_unreadable_streams_are_not_observations() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3

    result = evaluate_s3([(None, None, True), (None, None, True)])
    assert result.sufficient is False


def test_capture_record_is_json_serializable_and_auditable() -> None:
    import json

    from tools.ac_harness.freeze_forensics import build_capture_record, evaluate_s3

    s3 = evaluate_s3([(23, 100, True), (23, 400, True)])
    record = build_capture_record(
        pid=1234,
        tid=222,
        tid_reason="render-stack hint(s) ['dwrite'] in sampled stack",
        cycles_rows=[{"tid": 222, "cycles_per_s": 2.85e9}, {"tid": 111, "cycles_per_s": 1.0e9}],
        candidate_stacks=[(222, "00 dwrite!loop\n01 acs!frame\nline3\nline4\nline5\nline6\nline7")],
        rips=[0x7FF000001000, 0x7FF000001020],
        s3=s3,
        verdict="livelock_confirmed",
        rationale="test rationale",
        started_at_utc="2026-07-21T00:00:00Z",
        elapsed_s=42.5,
    )
    payload = json.loads(json.dumps(record))
    assert payload["schema"] == "freeze-forensics-capture/v1"
    assert payload["selected_tid"] == 222
    assert payload["rips_hex"] == ["0x7ff000001000", "0x7ff000001020"]
    assert payload["rip_span_bytes"] == 0x20
    assert payload["s3"]["gfx_static"] is True
    assert payload["s3"]["sufficient"] is True
    # Stack heads are capped so the record stays a record, not a transcript dump.
    assert len(payload["candidate_stack_heads"][0]["stack_head"]) == 6


def test_extract_stack_excludes_the_lm_module_listing() -> None:
    """#647 review P1 — d3d11/dxgi are loaded in EVERY AC process; letting the ``lm`` listing
    into the stack text would make the render hints match every candidate and neuter the
    render-TID preference."""
    from tools.ac_harness.freeze_forensics import extract_stack, select_capture_tid

    raw = (
        "AC_TID=1a2b\n"
        " # Child-SP          RetAddr               Call Site\n"
        "00 0000005e`f16df620 00007ff9`1d2080c4     acs!physicsWorker+0x40\n"
        "01 0000005e`f16df8e0 00007ff9`1d207f7a     ntdll!RtlUserThreadStart+0x21\n"
        "start             end                 module name\n"
        "00007ff9`1d000000 00007ff9`1e000000   d3d11      (deferred)\n"
        "00007ff9`1f000000 00007ff9`20000000   nvwgf2umx  (deferred)\n"
    )
    stack = extract_stack(raw)
    assert "physicsWorker" in stack
    assert "d3d11" not in stack
    assert "nvwgf2umx" not in stack
    # The physics thread must NOT be selected as render-side off module-listing pollution.
    tid, reason = select_capture_tid([(0x1A2B, stack)])
    assert "hottest thread" in reason


def test_s3_gate_refuses_a_liveness_gap() -> None:
    """#647 review P1 — acs_alive_throughout must gate: mixed process generations can fabricate
    the wedge signature from two healthy sessions."""
    from tools.ac_harness.freeze_forensics import evaluate_s3, s3_gate

    # Enough live readings on either side of a death to look like a wedge...
    s3 = evaluate_s3([(23, 100, True), (16_983, 9_999, False), (23, 400, True)])
    assert s3.sufficient is True
    refusal = s3_gate(s3)
    assert refusal is not None
    token, rationale = refusal
    assert token == "capture_failed_liveness_gap"
    assert "generations" in rationale


def test_s3_gate_refuses_insufficiency_first() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3, s3_gate

    refusal = s3_gate(evaluate_s3([(23, 100, True)]))
    assert refusal is not None
    assert refusal[0] == "capture_failed_insufficient_s3"


def test_s3_gate_passes_a_continuously_live_capture() -> None:
    from tools.ac_harness.freeze_forensics import evaluate_s3, s3_gate

    assert s3_gate(evaluate_s3([(23, 100, True), (23, 400, True)])) is None


class TestResolveRecordPath:
    """#647 review P2 — the --json destination must stay inside an approved output root."""

    def test_inside_root_accepted(self, tmp_path) -> None:
        from tools.ac_harness.freeze_forensics import _resolve_record_path

        target = tmp_path / "captures" / "wedge.json"
        assert _resolve_record_path(target, approved_roots=(tmp_path,)) == target.resolve()

    def test_absolute_outside_rejected(self, tmp_path) -> None:
        import pytest

        from tools.ac_harness.freeze_forensics import _resolve_record_path

        with pytest.raises(ValueError, match="approved output root"):
            _resolve_record_path(tmp_path / "out.json", approved_roots=(tmp_path / "approved",))

    def test_dotdot_traversal_rejected(self, tmp_path) -> None:
        import pytest

        from tools.ac_harness.freeze_forensics import _resolve_record_path

        approved = tmp_path / "approved"
        with pytest.raises(ValueError, match="approved output root"):
            _resolve_record_path(approved / ".." / "escape.json", approved_roots=(approved,))


def test_cli_validators_reject_degenerate_windows() -> None:
    """#647 review P2 — --cycles-window 0 would turn incidental cycle increments into an
    arbitrary burning-CPU rate; negatives raise from time.sleep mid-capture."""
    import pytest

    from tools.ac_harness.freeze_forensics import (
        _non_negative_float,
        _non_negative_int,
        _positive_float,
        _positive_int,
    )

    with pytest.raises(Exception, match="> 0"):
        _positive_float("0")
    with pytest.raises(Exception, match="finite"):
        _positive_float("nan")
    with pytest.raises(Exception, match=">= 0"):
        _non_negative_float("-1")
    with pytest.raises(Exception, match="> 0"):
        _positive_int("0")
    with pytest.raises(Exception, match=">= 0"):
        _non_negative_int("-1")
    assert _positive_float("2.5") == 2.5
    assert _non_negative_float("0") == 0.0
    assert _non_negative_int("0") == 0


def test_record_path_from_an_unapproved_cwd_is_rejected(tmp_path, monkeypatch) -> None:
    """The caller's CWD is not a root — same boundary as PR #646's launcher fix."""
    from pathlib import Path

    import pytest

    from tools.ac_harness.freeze_forensics import _resolve_record_path

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.chdir(downloads)
    with pytest.raises(ValueError, match="approved output root"):
        _resolve_record_path(Path("capture.json"), approved_roots=(tmp_path / "approved",))


def test_repo_checkout_root_is_the_module_checkout() -> None:
    from tools.ac_harness.freeze_forensics import _repo_checkout_root

    root = _repo_checkout_root()
    assert (root / "tools" / "ac_harness" / "freeze_forensics.py").is_file()


def test_s3_physics_regression_is_not_advancing() -> None:
    """#647 review round 2 — an endpoint-only comparison read 100, 5, 200 as advancing; a
    mid-stream regression is a section/session reset and must not feed the wedge signature."""
    from tools.ac_harness.freeze_forensics import evaluate_s3

    result = evaluate_s3([(23, 100, True), (23, 5, True), (23, 200, True)])
    assert result.phys_advancing is False


def test_acs_pid_picks_deterministically_from_the_process_set(monkeypatch) -> None:
    """#647 review round 2 — running_process_ids returns a frozenset; pids[0] was a TypeError
    on the default no---pid path whenever acs.exe was actually running."""
    import tools.ac_harness.entry_launcher as entry_launcher
    from tools.ac_harness.freeze_forensics import _acs_pid

    monkeypatch.setattr(
        entry_launcher, "running_process_ids", lambda name, strict: frozenset({31337, 20001})
    )
    assert _acs_pid() == 20001

    monkeypatch.setattr(entry_launcher, "running_process_ids", lambda name, strict: frozenset())
    assert _acs_pid() is None
