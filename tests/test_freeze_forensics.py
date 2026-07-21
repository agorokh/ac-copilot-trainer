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


def test_cdb_snapshot_thaws_target_after_timeout(monkeypatch) -> None:
    """A hard-killed ``-pv`` attach leaves suspend counts on the target unless ``qd`` re-runs.

    This is the daemon HIGH: ``subprocess.run`` kills ``cdb`` on timeout *before* the primary
    script's trailing ``qd``, so without a follow-up thaw the wedged process is permanently
    suspended — destroying the evidence the tool exists to capture.
    """
    from pathlib import Path

    import tools.ac_harness.freeze_forensics as ff

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 90))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ff, "find_cdb", lambda: Path("/fake/cdb.exe"))
    monkeypatch.setattr(ff.subprocess, "run", fake_run)

    sample = ff.cdb_snapshot(1234, tid=0x1A2B, timeout=1.0)
    assert sample.rip is None
    assert "cdb timed out" in sample.raw
    assert "thaw=ok" in sample.raw
    assert len(calls) == 2
    # Second call is the thaw: noninvasive attach + immediate detach.
    assert calls[1] == ["/fake/cdb.exe", "-pv", "-p", "1234", "-c", "qd"]
