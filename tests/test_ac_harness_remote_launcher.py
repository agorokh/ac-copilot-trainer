"""Off-rig tests for the #697 console-session transport.

The ``schtasks`` and Windows-session calls are rig-only; everything that decides *what* gets run —
run ids, wrapper text, ``schtasks`` argv, status/sentinel parsing, the bounded wait, and
cleanup's refusal to delete an unfinished run — is pure and tested here. Each case pins a defect
measured on the rig during #693/#699 rather than a hypothetical.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.ac_harness import remote_launcher as rl


@pytest.fixture(autouse=True)
def _isolated_control_root(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:  # noqa: ANN001
    """Keep the control plane (sentinels, control files) out of the real user profile.

    `control_dir_for` resolves under LOCALAPPDATA, falling back to the home directory off-Windows —
    without this every test that marks a run finished would litter the developer's profile.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("localappdata")))


# ---------------------------------------------------------------------------
# Run ids and task names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "a b", "a/b", "a\\b", "..", "a..b", "a:b", "a<b", "a>b"])
def test_validate_run_component_rejects_path_and_task_metacharacters(bad: str) -> None:
    with pytest.raises(rl.RemoteLaunchError):
        rl.validate_run_component("run label", bad)


def test_build_run_id_is_unique_per_pid_and_nonce_within_one_second() -> None:
    """Second resolution alone would let two same-second agents share a run directory."""
    moment = datetime(2026, 7, 26, 19, 59, 1, tzinfo=UTC)
    first = rl.build_run_id("alien-529", now=moment, pid=17748, nonce=7359)
    second = rl.build_run_id("alien-529", now=moment, pid=17749, nonce=7359)
    third = rl.build_run_id("alien-529", now=moment, pid=17748, nonce=1111)
    assert first == "alien-529-20260726-195901-17748-7359"
    assert len({first, second, third}) == 3
    # The id becomes a path component and a task name, so it must survive its own validator.
    assert rl.task_name_for(first) == f"{rl.TASK_PREFIX}{first}"


def test_build_run_id_rejects_an_unsafe_label() -> None:
    with pytest.raises(rl.RemoteLaunchError):
        rl.build_run_id("alien <529>", now=datetime(2026, 7, 26, tzinfo=UTC), pid=1, nonce=2)


# ---------------------------------------------------------------------------
# Wrapper rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "--car=<car>",  # cmd parses < as stdin redirection before the harness ever starts
        "out>log",
        "a&b",
        "a|b",
        "a^b",
        "%USERPROFILE%",
        'say"hi"',
        "caf\u00e9",  # non-ASCII is mangled to '?' by the ascii-encoded wrapper
        "line\nbreak",
    ],
)
def test_validate_wrapper_token_rejects_injection_and_redirection(bad: str) -> None:
    with pytest.raises(rl.RemoteLaunchError):
        rl.validate_wrapper_token(bad)


@pytest.mark.parametrize(
    "good",
    [
        "-m",
        "tools.ac_harness.auto_alien",
        "--car",
        "ks_porsche_911_gt3_r_2016",
        "--ggv-scale",
        "1.15",
        r".scratch\harness-evidence\alien-529",
        "C:/Users/arsen/Projects/ac-copilot-trainer",
    ],
)
def test_validate_wrapper_token_accepts_real_harness_argv(good: str) -> None:
    assert rl.validate_wrapper_token(good) == good


@pytest.mark.parametrize("bad", ["C:/repo%USERNAME%", 'C:/re"po', "C:/a&b", "C:/a|b", "C:/a>b"])
def test_validate_wrapper_path_rejects_cmd_specials_that_survive_quoting(bad: str) -> None:
    """`%` expands INSIDE double quotes and `"` breaks out — both are legal ASCII path chars."""
    with pytest.raises(rl.RemoteLaunchError, match="unsafe"):
        rl.validate_wrapper_path("repo root", Path(bad))


def test_harness_repo_root_does_not_import_the_payload_module() -> None:
    """The transport must not drag `auto_drive` (the in-sim payload) in just to resolve a path."""
    source = (Path(rl.__file__)).read_text(encoding="utf-8")
    assert "from tools.ac_harness.auto_drive import" not in source
    assert rl.harness_repo_root().joinpath("tools", "ac_harness").is_dir()


# ---------------------------------------------------------------------------
# schtasks argv
# ---------------------------------------------------------------------------


def test_schtasks_create_argv_carries_the_console_session_flags() -> None:
    argv = rl.schtasks_create_argv(
        task="ac-harness-x",
        tr_path="C:/RUN~1.CMD",
        when=datetime(2026, 7, 26, 20, 4, tzinfo=UTC),
        run_as="a",
    )
    assert argv[:4] == ["schtasks", "/create", "/tn", "ac-harness-x"]
    # /it is what puts the task in the console session; /f stops the interactive replace prompt
    # from blocking a non-interactive create.
    assert "/it" in argv and "/f" in argv
    assert argv[argv.index("/sc") + 1] == "once"
    assert argv[argv.index("/st") + 1] == "20:04"
    assert argv[argv.index("/sd") + 1] == "07/26/2026"


def test_schtasks_create_argv_carries_the_day_across_a_midnight_rollover() -> None:
    """A bare clock time computed after ~23:55 reads as earlier *today* and fails /create."""
    argv = rl.schtasks_create_argv(
        task="t",
        tr_path="p",
        when=datetime(2026, 7, 26, 23, 58, tzinfo=UTC) + timedelta(minutes=5),
        run_as="a",
    )
    assert argv[argv.index("/st") + 1] == "00:03"
    assert argv[argv.index("/sd") + 1] == "07/27/2026"


def test_schtasks_date_format_is_the_only_one_the_rig_accepts() -> None:
    """M/d/yyyy, dd/MM/yyyy and yyyy/MM/dd were all rejected with 0x80004005 (#693)."""
    assert datetime(2026, 7, 6, tzinfo=UTC).strftime(rl.SCHTASKS_DATE_FORMAT) == "07/06/2026"


# ---------------------------------------------------------------------------
# Status / sentinel parsing
# ---------------------------------------------------------------------------


def test_parse_task_status_reads_status_and_last_result() -> None:
    text = "TaskName:      \\ac-harness-x\nStatus:        Running\nLast Result:   267009\n"
    assert rl.parse_task_status(text) == {"status": "Running", "last_result": "267009"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("[wrapper] exit=0\n", 0),
        ("[wrapper] exit=1\n", 1),
        (
            "[wrapper] exit=3\n[wrapper] exit=0\n",
            3,
        ),  # first wins: a later append cannot forge success
        ("[wrapper] exit=%ERRORLEVEL%\n", None),
    ],
)
def test_parse_sentinel(text: str, expected: int | None) -> None:
    assert rl.parse_sentinel(text) == expected


def test_remote_run_round_trips_through_json_payload() -> None:
    run = rl.RemoteRun(
        run_id="r",
        task="ac-harness-r",
        repo_root="/repo",
        run_dir="/repo/run",
        argv=["-m", "x"],
        started_at="2026-07-26T19:59:01",
    )
    assert rl.RemoteRun.from_dict(run.to_dict()) == run
    assert run.directory == Path("/repo/run")


# ---------------------------------------------------------------------------
# Wait / cleanup behaviour
# ---------------------------------------------------------------------------


def _run_handle(tmp_path: Path) -> rl.RemoteRun:
    return rl.RemoteRun(
        run_id="r",
        task="ac-harness-r",
        repo_root=str(tmp_path),
        run_dir=str(tmp_path),
        argv=["-m", "x"],
        started_at="2026-07-26T19:59:01",
    )


def test_wait_for_run_returns_as_soon_as_the_sentinel_lands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    polls = iter(
        [
            {"verified_complete": False},
            {"verified_complete": True, "finished": True, "exit_code": 0},
        ]
    )
    monkeypatch.setattr(rl, "poll_run", lambda run, **kw: next(polls))
    slept: list[float] = []
    status = rl.wait_for_run(
        _run_handle(tmp_path),
        timeout_s=600,
        interval_s=30,
        sleep=slept.append,
        monotonic=lambda: 0.0,
    )
    assert status["verified_complete"] is True
    assert status["exit_code"] == 0
    assert slept == [30]


def test_wait_for_run_is_bounded_when_the_run_never_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unbounded wait would hang forever with no diagnosis on a task that never launched."""
    monkeypatch.setattr(rl, "poll_run", lambda run, **kw: {"verified_complete": False})
    clock = iter([0.0, 0.0, 10.0, 10.0, 10.0])
    status = rl.wait_for_run(
        _run_handle(tmp_path),
        timeout_s=5,
        interval_s=30,
        sleep=lambda _s: None,
        monotonic=lambda: next(clock),
    )
    assert status["timed_out"] is True


def test_cleanup_run_refuses_to_delete_an_unfinished_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """schtasks /run is asynchronous — an early delete can cancel a start that has not spawned."""
    monkeypatch.setattr(rl, "poll_run", lambda run, **kw: {"verified_complete": False})
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: calls.append(list(argv)))
    result = rl.cleanup_run(_run_handle(tmp_path))
    assert result["deleted"] is False
    assert calls == []


def test_cleanup_run_force_deletes_without_the_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rl, "poll_run", lambda run, **kw: {"verified_complete": False})
    calls: list[list[str]] = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Done())[1])
    assert rl.cleanup_run(_run_handle(tmp_path), force=True)["deleted"] is True
    assert calls == [["schtasks", "/delete", "/tn", "ac-harness-r", "/f"]]


def test_list_stale_tasks_only_claims_this_modules_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Query:
        returncode = 0
        stdout = (
            "TaskName: \\ac-harness-alien-529-1\n"
            "TaskName: \\OneDrive Reporting Task\n"
            "TaskName: \\ac-harness-alien-529-2\n"
        )

    monkeypatch.setattr(rl, "_run", lambda argv: _Query())
    assert rl.list_stale_tasks() == ["ac-harness-alien-529-1", "ac-harness-alien-529-2"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_start_without_an_argv_fails_loudly() -> None:
    assert rl.main(["start", "--label", "alien-529"]) == 3


def test_cli_start_strips_the_argv_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def _fake_start(argv, *, label, **kwargs):  # noqa: ANN001, ANN202
        seen["argv"] = list(argv)
        seen["label"] = label
        return rl.RemoteRun(
            run_id="r", task="t", repo_root="/r", run_dir="/r/run", argv=list(argv), started_at="x"
        )

    monkeypatch.setattr(rl, "start_run", _fake_start)
    assert (
        rl.main(["start", "--label", "alien-529", "--", "-m", "tools.ac_harness.auto_alien"]) == 0
    )
    assert seen == {"argv": ["-m", "tools.ac_harness.auto_alien"], "label": "alien-529"}


def test_cleanup_run_refuses_a_task_name_that_does_not_match_its_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`run.json` is on disk; a stray edit must not let cleanup reap a peer's task."""
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: calls.append(list(argv)))
    hijacked = rl.RemoteRun(
        run_id="r",
        task="ac-harness-someone-elses-run",
        repo_root=str(tmp_path),
        run_dir=str(tmp_path),
        argv=["-m", "x"],
        started_at="2026-07-26T19:59:01",
    )
    with pytest.raises(rl.RemoteLaunchError, match="does not match this run id"):
        rl.cleanup_run(hijacked, force=True)
    assert calls == []


# ---------------------------------------------------------------------------
# Payload-identity binding, trailing backslash, reap (2nd daemon round)
# ---------------------------------------------------------------------------


def _write_run_json(root: Path, run_id: str, payload: dict) -> None:
    d = root.joinpath(*rl.RUN_DIR_RELPATH, run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / rl.RUN_JSON_NAME).write_text(json.dumps(payload), encoding="utf-8")


def test_load_run_rejects_a_payload_naming_a_different_run(tmp_path: Path) -> None:
    """A self-consistent forgery must not pass: the REQUESTED id is authoritative."""
    _write_run_json(
        tmp_path,
        "mine",
        {
            "run_id": "someone-else",
            "task": rl.task_name_for("someone-else"),
            "repo_root": str(tmp_path),
            "run_dir": str(tmp_path / "planted"),
            "argv": [],
            "started_at": "x",
        },
    )
    with pytest.raises(rl.RemoteLaunchError, match="names a different run"):
        rl.load_run("mine", repo_root=tmp_path)


def test_load_run_rejects_a_payload_claiming_another_task(tmp_path: Path) -> None:
    _write_run_json(
        tmp_path,
        "mine",
        {
            "run_id": "mine",
            "task": "ac-harness-a-peers-run",
            "repo_root": str(tmp_path),
            "run_dir": str(tmp_path),
            "argv": [],
            "started_at": "x",
        },
    )
    with pytest.raises(rl.RemoteLaunchError, match="does not own"):
        rl.load_run("mine", repo_root=tmp_path)


def test_load_run_recomputes_run_dir_instead_of_trusting_the_payload(tmp_path: Path) -> None:
    """A planted `[wrapper] exit=0` outside the canonical dir must not make a run look finished."""
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / rl.SENTINEL_NAME).write_text("[wrapper] exit=0\n", encoding="utf-8")
    _write_run_json(
        tmp_path,
        "mine",
        {
            "run_id": "mine",
            "task": rl.task_name_for("mine"),
            "repo_root": str(tmp_path),
            "run_dir": str(planted),
            "argv": [],
            "started_at": "x",
        },
    )
    run = rl.load_run("mine", repo_root=tmp_path)
    assert run.directory == tmp_path.joinpath(*rl.RUN_DIR_RELPATH, "mine")
    assert not (run.directory / rl.SENTINEL_NAME).exists()


@pytest.mark.parametrize("bad", ["C:/repo\\", "--evidence-dir=x\\"])
def test_trailing_backslash_is_rejected(bad: str) -> None:
    """`\\"` is an ESCAPED QUOTE to the Windows CRT argv parser, so the quoting does not close."""
    with pytest.raises(rl.RemoteLaunchError, match="trailing backslash"):
        rl.validate_wrapper_token(bad)
    # A Path reaches the wrapper as ``str(path)``, and TWO different mechanisms keep that text
    # safe depending on the host: on POSIX ``\`` is an ordinary character, so it survives
    # normalization and the validator rejects it; on Windows ``pathlib`` strips the trailing
    # separator before the validator is ever called. Asserting the rejection unconditionally
    # made this test red on Windows — the very platform the rig runs on — while staying green
    # on Linux CI. Assert the invariant (nothing ending in ``\`` reaches the wrapper), not one
    # platform's mechanism for upholding it.
    path = Path(bad)
    if str(path).endswith("\\"):
        with pytest.raises(rl.RemoteLaunchError, match="trailing backslash"):
            rl.validate_wrapper_path("repo root", path)
    else:
        assert not str(rl.validate_wrapper_path("repo root", path)).endswith("\\")


def test_trailing_backslash_path_guard_is_live_on_windows() -> None:
    """A Windows drive root is the case where ``pathlib`` DOES keep the trailing separator.

    Without this, the path-side guard would have no Windows coverage at all once the
    normalization above is accounted for.
    """
    root = Path("C:/")
    if not str(root).endswith("\\"):
        pytest.skip("pathlib only preserves a trailing separator at a Windows drive root")
    with pytest.raises(rl.RemoteLaunchError, match="trailing backslash"):
        rl.validate_wrapper_path("repo root", root)


# ---------------------------------------------------------------------------
# reap safety, bounded-wait finiteness, corrupt payload (3rd daemon round)
# ---------------------------------------------------------------------------


def _seed_finished_run(root: Path, run_id: str) -> None:
    """Mark a run finished. The sentinel lives in the CONTROL dir, keyed by run id."""
    root.joinpath(*rl.RUN_DIR_RELPATH, run_id).mkdir(parents=True, exist_ok=True)
    d = rl.control_dir_for(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / rl.SENTINEL_NAME).write_text("[wrapper] exit=0\n", encoding="utf-8")


class _Ready:
    returncode = 0
    stdout = "Status:  Ready\nLast Result:  0\n"


def test_reap_skips_a_task_with_no_exit_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`Status: Ready` is NOT completion — /run is async, so Ready covers the pre-spawn window."""
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Ready())[1])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: ["ac-harness-launching"])
    outcome = rl.reap_tasks()
    assert outcome["reaped"]["ac-harness-launching"]["deleted"] is False
    assert "no exit sentinel" in outcome["reaped"]["ac-harness-launching"]["skipped"]
    assert not any("/delete" in c for c in calls)


def test_reap_fails_closed_when_the_status_query_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient /query failure must not become a licence to delete a live peer task."""
    _seed_finished_run(tmp_path, "done")
    calls: list[list[str]] = []

    class _Broken:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Broken())[1])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: ["ac-harness-done"])
    outcome = rl.reap_tasks()
    assert outcome["reaped"]["ac-harness-done"]["deleted"] is False
    assert "query failed" in outcome["reaped"]["ac-harness-done"]["skipped"]
    assert not any("/delete" in c for c in calls)


def test_reap_fails_closed_on_an_unrecognised_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_finished_run(tmp_path, "done")
    calls: list[list[str]] = []

    class _Weird:
        returncode = 0
        stdout = "Status:  Somethingelse\nLast Result:  0\n"

    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Weird())[1])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: ["ac-harness-done"])
    assert rl.reap_tasks()["reaped"]["ac-harness-done"]["deleted"] is False
    assert not any("/delete" in c for c in calls)


def test_reap_skips_a_running_task_even_with_a_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_finished_run(tmp_path, "live")
    calls: list[list[str]] = []

    class _Running:
        returncode = 0
        stdout = "Status:  Running\nLast Result:  267009\n"

    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Running())[1])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: ["ac-harness-live"])
    assert rl.reap_tasks()["reaped"]["ac-harness-live"]["deleted"] is False
    assert not any("/delete" in c for c in calls)


def test_reap_deletes_a_finished_ready_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sentinel present AND a known-dead status — the only combination that authorises delete."""
    _seed_finished_run(tmp_path, "done")
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Ready())[1])
    seq = iter([["ac-harness-done"], []])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: next(seq))
    outcome = rl.reap_tasks()
    assert outcome["reaped"]["ac-harness-done"]["deleted"] is True
    assert outcome["remaining"] == []
    assert ["schtasks", "/delete", "/tn", "ac-harness-done", "/f"] in calls


def test_reap_force_bypasses_both_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class _Running:
        returncode = 0
        stdout = "Status:  Running\nLast Result:  267009\n"

    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Running())[1])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: ["ac-harness-live"])
    rl.reap_tasks(force=True)
    assert ["schtasks", "/delete", "/tn", "ac-harness-live", "/f"] in calls


def test_reap_skips_a_task_name_that_is_not_a_valid_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Ready())[1])
    monkeypatch.setattr(rl, "list_stale_tasks", lambda: ["ac-harness-bad/../id"])
    outcome = rl.reap_tasks()
    assert outcome["reaped"]["ac-harness-bad/../id"]["deleted"] is False
    assert not any("/delete" in c for c in calls)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), -1.0])
def test_wait_for_run_rejects_a_non_finite_timeout(bad: float, tmp_path: Path) -> None:
    """`--timeout-s inf` would never expire — the exact hang the bounded wait exists to prevent."""
    with pytest.raises(rl.RemoteLaunchError, match="finite"):
        rl.wait_for_run(_run_handle(tmp_path), timeout_s=bad, sleep=lambda _s: None)


def test_load_run_reports_a_corrupt_payload_as_a_launch_error(tmp_path: Path) -> None:
    """A truncated run.json must take the module's error path, not raise a raw JSONDecodeError."""
    d = tmp_path.joinpath(*rl.RUN_DIR_RELPATH, "mine")
    d.mkdir(parents=True)
    (d / rl.RUN_JSON_NAME).write_text('{"run_id": "mi', encoding="utf-8")
    with pytest.raises(rl.RemoteLaunchError, match="unreadable run payload"):
        rl.load_run("mine", repo_root=tmp_path)


def test_load_run_reports_a_payload_missing_required_keys(tmp_path: Path) -> None:
    d = tmp_path.joinpath(*rl.RUN_DIR_RELPATH, "mine")
    d.mkdir(parents=True)
    (d / rl.RUN_JSON_NAME).write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(rl.RemoteLaunchError, match="unreadable run payload"):
        rl.load_run("mine", repo_root=tmp_path)


# ---------------------------------------------------------------------------
# Shared deletion verdict, run-id correlation, CLI exit codes (5th daemon round)
# ---------------------------------------------------------------------------


def test_verdict_refuses_a_planted_sentinel_before_the_task_ever_ran(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`Ready` covers the PRE-SPAWN window too, so a planted sentinel must not authorise delete."""
    _seed_finished_run(tmp_path, "victim")

    class _NeverRan:
        returncode = 0
        stdout = f"Status:  Ready\nLast Result:  {rl.SCHED_S_TASK_HAS_NOT_YET_RUN}\n"

    monkeypatch.setattr(rl, "_run", lambda argv: _NeverRan())
    ok, reason = rl.task_deletion_verdict("ac-harness-victim", "victim")
    assert ok is False
    assert "not yet run" in reason


def test_verdict_refuses_an_unreadable_last_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_finished_run(tmp_path, "r")

    class _NoResult:
        returncode = 0
        stdout = "Status:  Ready\n"

    monkeypatch.setattr(rl, "_run", lambda argv: _NoResult())
    ok, reason = rl.task_deletion_verdict("ac-harness-r", "r")
    assert ok is False
    assert "unreadable" in reason


def test_cleanup_run_now_applies_the_same_live_status_gate_as_reap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """cleanup was the WEAKER path: a planted sentinel could delete a still-Running task."""
    d = tmp_path.joinpath(*rl.RUN_DIR_RELPATH, "r")
    d.mkdir(parents=True)
    (d / rl.SENTINEL_NAME).write_text("[wrapper] exit=0\n", encoding="utf-8")
    calls: list[list[str]] = []

    class _Running:
        returncode = 0
        stdout = "Status:  Running\nLast Result:  267009\n"

    monkeypatch.setattr(rl, "_run", lambda argv: (calls.append(list(argv)), _Running())[1])
    monkeypatch.setattr(rl, "poll_run", lambda run, **kw: {"verified_complete": False})
    run = rl.RemoteRun(
        run_id="r",
        task="ac-harness-r",
        repo_root=str(tmp_path),
        run_dir=str(d),
        argv=["-m", "x"],
        started_at="x",
    )
    monkeypatch.setattr(
        rl, "_await_deletion_verdict", lambda n, rid, **kw: rl.task_deletion_verdict(n, rid)
    )
    outcome = rl.cleanup_run(run)
    assert outcome["deleted"] is False
    assert not any("/delete" in c for c in calls)


def test_substitute_run_placeholders_links_payload_to_transport() -> None:
    """Without this the payload picks its own evidence dir and cannot be correlated with the run."""
    argv = ["-m", "tools.ac_harness.auto_alien", "--evidence-dir", ".scratch/e/{run_id}"]
    out = rl.substitute_run_placeholders(argv, run_id="abc-1", run_dir=Path("/r/abc-1"))
    assert out[-1] == ".scratch/e/abc-1"


def test_substitute_run_placeholders_resolves_run_dir() -> None:
    out = rl.substitute_run_placeholders(["{run_dir}"], run_id="abc", run_dir=Path("/r/abc"))
    assert out == [str(Path("/r/abc"))]


def test_cli_cleanup_exits_non_zero_when_delete_was_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Automation cannot see a refusal if the CLI always exits 0."""
    monkeypatch.setattr(rl, "load_run", lambda rid, **kw: _run_handle(tmp_path))
    monkeypatch.setattr(
        rl, "cleanup_run", lambda run, force=False: {"deleted": False, "reason": "x"}
    )
    assert rl.main(["cleanup", "r"]) == 1


def test_cli_cleanup_exits_zero_on_a_real_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rl, "load_run", lambda rid, **kw: _run_handle(tmp_path))
    monkeypatch.setattr(
        rl, "cleanup_run", lambda run, force=False: {"deleted": True, "delete_rc": 0}
    )
    assert rl.main(["cleanup", "r"]) == 0


# ---------------------------------------------------------------------------
# Qodo persistent-review findings 2-7
# ---------------------------------------------------------------------------


def test_sentinel_read_failure_does_not_abort_a_reap_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An OSError on the sentinel must skip the task, not crash the CLI with a traceback.

    The sentinel lives in the CONTROL directory — an earlier version of this test seeded the run
    directory instead, so `is_file()` was False and the OSError branch was never reached.
    """
    _seed_finished_run(tmp_path, "r")
    assert rl.sentinel_path_for("r").is_file()  # precondition: we reach the read at all
    monkeypatch.setattr(
        Path, "read_text", lambda self, **kw: (_ for _ in ()).throw(OSError("permission denied"))
    )
    assert rl._sentinel_exit_code("r") is None


def test_list_stale_tasks_raises_rather_than_reporting_an_empty_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty list reads as 'nothing left behind' — it must never come from a FAILED query."""

    class _Broken:
        returncode = 1
        stdout = ""
        stderr = "ERROR: access denied"

    monkeypatch.setattr(rl, "_run", lambda argv: _Broken())
    with pytest.raises(rl.RemoteLaunchError, match="refusing to report an empty task list"):
        rl.list_stale_tasks()


def test_tail_zero_means_no_tail_not_the_whole_file(tmp_path: Path) -> None:
    """cleanup_run polls with tail=0; returning the whole file printed megabytes of sidecar logs."""
    log = tmp_path / "stdout.log"
    log.write_text("\n".join(f"line {i}" for i in range(5000)), encoding="utf-8")
    assert rl._tail(log, 0) == []
    assert rl._tail(log, 3) == ["line 4997", "line 4998", "line 4999"]


def test_tail_reads_only_the_end_of_a_large_log(tmp_path: Path) -> None:
    log = tmp_path / "stderr.log"
    log.write_text("x" * (rl._TAIL_MAX_BYTES * 2) + "\nlast line\n", encoding="utf-8")
    assert rl._tail(log, 1) == ["last line"]


def test_tail_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert rl._tail(tmp_path / "nope.log", 10) == []


def test_verdict_reason_names_which_last_result_it_saw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Refusing on 'currently running' must not report 'has not yet run'."""
    _seed_finished_run(tmp_path, "r")

    class _Running:
        returncode = 0
        stdout = f"Status:  Ready\nLast Result:  {rl.SCHED_S_TASK_IS_CURRENTLY_RUNNING}\n"

    monkeypatch.setattr(rl, "_run", lambda argv: _Running())
    ok, reason = rl.task_deletion_verdict("ac-harness-r", "r")
    assert ok is False
    assert "currently running" in reason
    assert "not yet run" not in reason


def test_docs_do_not_advertise_a_load_subcommand() -> None:
    """The runbook claimed a `load` command binds the payload; no such subcommand exists."""
    commands = {a.dest for a in rl.build_parser()._subparsers._group_actions}  # noqa: SLF001
    doc = (rl.harness_repo_root() / "docs/10_Development/18_Autonomous_Harness.md").read_text(
        encoding="utf-8"
    )
    assert "remote_launcher load" not in doc
    assert "`load` binds" not in doc
    assert commands  # parser still exposes its subcommands


def test_tail_keeps_a_single_very_long_line_instead_of_returning_nothing(tmp_path: Path) -> None:
    """Dropping the partial first row must not empty the tail when the chunk has no newline."""
    log = tmp_path / "stdout.log"
    log.write_text("y" * (rl._TAIL_MAX_BYTES + 4096), encoding="utf-8")
    rows = rl._tail(log, 5)
    assert rows and rows[-1].startswith("y")


def test_resolve_short_path_retries_with_the_required_buffer_size() -> None:
    """A too-small buffer is not a failure — GetShortPathNameW returns the size it needs."""
    long_value = "C:/" + "a" * 2000
    calls: list[int] = []

    def _fake_get_short(path, buf, size):  # noqa: ANN001, ANN202
        calls.append(size)
        if size <= len(long_value):
            return len(long_value) + 1  # "buffer too small" -> required length
        buf.value = long_value
        return len(long_value)

    assert rl.resolve_short_path(Path("C:/whatever"), _fake_get_short) == long_value
    assert len(calls) == 2 and calls[1] > calls[0]


def test_resolve_short_path_raises_when_the_call_genuinely_fails() -> None:
    assert_raises = pytest.raises(rl.RemoteLaunchError, match="GetShortPathNameW failed")
    with assert_raises:
        rl.resolve_short_path(Path("C:/x"), lambda path, buf, size: 0)


def test_resolve_short_path_uses_one_call_when_the_first_buffer_fits() -> None:
    calls: list[int] = []

    def _fake_get_short(path, buf, size):  # noqa: ANN001, ANN202
        calls.append(size)
        buf.value = "C:/SHORT~1"
        return len("C:/SHORT~1")

    assert rl.resolve_short_path(Path("C:/short"), _fake_get_short) == "C:/SHORT~1"
    assert len(calls) == 1


def test_wait_refuses_a_planted_sentinel_while_the_task_is_still_launching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A peer can write wrapper.log; `start --wait` must not call that success."""
    monkeypatch.setattr(
        rl,
        "poll_run",
        lambda run, **kw: {"finished": True, "verified_complete": False, "exit_code": 0},
    )
    clock = iter([0.0, 0.0, 99.0, 99.0, 99.0])
    status = rl.wait_for_run(
        _run_handle(tmp_path),
        timeout_s=5,
        interval_s=1,
        sleep=lambda _s: None,
        monotonic=lambda: next(clock),
    )
    assert status["timed_out"] is True


def test_poll_run_survives_an_unreadable_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """cleanup polls first, so a sharing error on wrapper.log must not abort with a traceback."""
    monkeypatch.setattr(
        rl, "_sentinel_exit_code", lambda run_id: (_ for _ in ()).throw(AssertionError("unused"))
    )
    monkeypatch.setattr(rl, "_sentinel_exit_code", lambda run_id: None)
    monkeypatch.setattr(rl, "task_deletion_verdict", lambda name, rid: (False, "no sentinel"))

    class _Q:
        returncode = 0
        stdout = "Status:  Ready\nLast Result:  0\n"

    monkeypatch.setattr(rl, "_run", lambda argv: _Q())
    monkeypatch.setattr(rl, "read_rig_session_owner", lambda p: None)
    status = rl.poll_run(_run_handle(tmp_path))
    assert status["finished"] is False
    assert status["verified_complete"] is False


def test_cli_start_wait_reports_a_refused_cleanup_in_the_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On the unattended path a leftover live task must be visible from the exit code."""
    run = _run_handle(tmp_path)
    monkeypatch.setattr(rl, "start_run", lambda argv, **kw: run)
    monkeypatch.setattr(
        rl, "wait_for_run", lambda r, **kw: {"exit_code": 0, "verified_complete": True}
    )
    monkeypatch.setattr(rl, "cleanup_run", lambda r, **kw: {"deleted": False, "reason": "refused"})
    assert rl.main(["start", "--wait-timeout-s", "1", "--", "-m", "x"]) == 1


def test_poll_run_issues_exactly_one_schtasks_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two queries doubled subprocess cost AND let the reported status disagree with the verdict."""
    queries: list[list[str]] = []

    class _Q:
        returncode = 0
        stdout = "Status:  Ready\nLast Result:  0\n"

    def _fake_run(argv):  # noqa: ANN001, ANN202
        if argv[:2] == ["schtasks", "/query"]:
            queries.append(list(argv))
        return _Q()

    monkeypatch.setattr(rl, "_run", _fake_run)
    monkeypatch.setattr(rl, "_sentinel_exit_code", lambda run_id: 0)
    monkeypatch.setattr(rl, "read_rig_session_owner", lambda p: None)
    status = rl.poll_run(_run_handle(tmp_path))
    assert len(queries) == 1
    assert status["verified_complete"] is True
    # The reported fields and the verdict come from that single snapshot.
    assert status["status"] == "Ready"


def test_verdict_short_circuits_without_a_subprocess_when_no_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: calls.append(list(argv)))
    monkeypatch.setattr(rl, "_sentinel_exit_code", lambda run_id: None)
    ok, reason = rl.task_deletion_verdict("ac-harness-r", "r")
    assert ok is False and "no exit sentinel" in reason
    assert calls == []


def test_evaluate_deletion_is_pure_over_a_snapshot(tmp_path: Path) -> None:
    ok, _ = rl.evaluate_deletion(
        sentinel_exit_code=0,
        query_rc=0,
        fields={"status": "Ready", "last_result": "0"},
        run_id="abc-1",
    )
    assert ok is True
    blocked, reason = rl.evaluate_deletion(
        sentinel_exit_code=0,
        query_rc=0,
        fields={"status": "Ready", "last_result": str(rl.SCHED_S_TASK_HAS_NOT_YET_RUN)},
        run_id="abc-1",
    )
    assert blocked is False and "not yet run" in reason


def test_ghost_suppression_note_does_not_corrupt_the_exit_sentinel() -> None:
    """The suppression note must not be mistaken for a second exit code."""
    assert rl.parse_sentinel("[wrapper] exit=0\n[wrapper] ghost trigger suppressed\n") == 0


# ---------------------------------------------------------------------------
# Safe transport: no peer-writable script is ever executed (9th daemon round)
# ---------------------------------------------------------------------------


def test_control_plane_lives_outside_the_shared_scratch_tree(tmp_path: Path) -> None:
    """`.scratch` is per-worktree and already untrusted — control files must not sit there."""
    control = rl.control_dir_for("abc-1")
    assert ".scratch" not in str(control)
    assert control.name == "abc-1"
    assert rl.sentinel_path_for("abc-1") == control / rl.SENTINEL_NAME


def test_execute_control_file_revalidates_argv_from_disk(tmp_path: Path) -> None:
    """A tampered control file must fail closed, not inject a command."""
    control = rl.control_dir_for("evil")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(
        json.dumps({"argv": ["-m", "x & calc.exe"]}), encoding="utf-8"
    )
    with pytest.raises(rl.RemoteLaunchError, match="unsafe argv token"):
        rl.execute_control_file("evil")


def test_execute_control_file_rejects_a_corrupt_payload(tmp_path: Path) -> None:
    control = rl.control_dir_for("bad")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(rl.RemoteLaunchError, match="unreadable control file"):
        rl.execute_control_file("bad")


def test_execute_control_file_rejects_an_empty_argv(tmp_path: Path) -> None:
    control = rl.control_dir_for("empty")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(json.dumps({"argv": []}), encoding="utf-8")
    with pytest.raises(rl.RemoteLaunchError, match="must start with"):
        rl.execute_control_file("empty")


def test_execute_control_file_spawns_without_a_shell_and_writes_the_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    control = rl.control_dir_for("ok")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(
        json.dumps({"argv": ["-m", "tools.ac_harness.auto_alien"]}), encoding="utf-8"
    )
    seen: dict = {}

    class _Done:
        returncode = 7

    def _fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
        seen["argv"] = list(argv)
        seen["kwargs"] = kwargs
        return _Done()

    monkeypatch.setattr(rl.subprocess, "run", _fake_run)
    assert rl.execute_control_file("ok") == 7
    # The interpreter and cwd are RECOMPUTED, never taken from the control file.
    assert seen["argv"][0].endswith("python.exe")
    assert seen["argv"][1:] == ["-u", "-m", "tools.ac_harness.auto_alien"]
    assert seen["kwargs"]["cwd"] == str(rl.harness_repo_root())
    assert "shell" not in seen["kwargs"]  # subprocess defaults to shell=False
    assert rl.parse_sentinel(rl.sentinel_path_for("ok").read_text(encoding="utf-8")) == 7


def test_parse_sentinel_skips_a_poison_line() -> None:
    """A garbled `exit=` must not hide the real one."""
    assert rl.parse_sentinel("[wrapper] exit=not-an-int\n[wrapper] exit=3\n") == 3


def test_parse_sentinel_ignores_a_forged_success_appended_after_a_real_failure() -> None:
    """The control dir is same-user writable, so a peer can append after the shim's single write."""
    assert rl.parse_sentinel("[wrapper] exit=1\n[wrapper] exit=0\n") == 1


def test_verdict_reason_names_the_sentinel_it_actually_checks(tmp_path: Path) -> None:
    """The sentinel left `.scratch`; a reason pointing at the old path misdirects the operator."""
    ok, reason = rl.evaluate_deletion(
        sentinel_exit_code=None,
        query_rc=0,
        fields={},
        run_id="abc-1",
    )
    assert ok is False
    assert str(rl.sentinel_path_for("abc-1")) in reason
    assert ".scratch" not in reason


@pytest.mark.parametrize(
    "argv",
    [
        ["-c", "import os;os.system(chr(99))"],  # RCE: JSON needs no shell quoting
        ["-c", "print(1)"],
        ["C:/Users/Public/evil.py"],
        ["-m", "runpy"],
        ["-m", "os"],
        ["-"],
        [],
        # The transport must not be able to schedule ITSELF: these two would let a tampered
        # control file reap a peer's live task or execute another run's control file.
        ["-m", "tools.ac_harness.remote_launcher", "reap", "--force"],
        ["-m", "tools.ac_harness._remote_exec", "some-peer-run-id"],
        ["-m", "tools.ac_harness.rig_lock"],
    ],
)
def test_validate_payload_argv_rejects_everything_but_a_harness_module(argv: list[str]) -> None:
    """Token validation alone permitted `python -c <expression>` — console-session RCE."""
    with pytest.raises(rl.RemoteLaunchError):
        rl.validate_payload_argv(argv)


def test_validate_payload_argv_accepts_a_harness_module_with_args() -> None:
    argv = ["-m", "tools.ac_harness.auto_alien", "--car", "ks_x", "--laps", "3"]
    assert rl.validate_payload_argv(argv) == argv


def test_execute_control_file_records_a_sentinel_when_it_fails(tmp_path: Path) -> None:
    """Without this, poll/wait spin to their deadline and cleanup refuses — no diagnosis."""
    control = rl.control_dir_for("boom")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(
        json.dumps({"argv": ["-c", "print(1)"]}), encoding="utf-8"
    )
    with pytest.raises(rl.RemoteLaunchError):
        rl.execute_control_file("boom")
    recorded = rl.sentinel_path_for("boom").read_text(encoding="utf-8")
    assert rl.parse_sentinel(recorded) == rl.EXEC_FAILURE_RC
    assert "RemoteLaunchError" in recorded


def test_start_run_surfaces_an_armed_trigger_without_deleting_a_live_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The payload is already running — the old fail-closed delete would have ABORTED it."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    monkeypatch.setattr(rl, "short_path", lambda p: str(p))
    monkeypatch.setenv("USERNAME", "someone")
    calls: list[list[str]] = []

    class _R:
        def __init__(self, rc: int) -> None:
            self.returncode = rc
            self.stdout = ""
            self.stderr = "nope"

    def _fake_run(argv):  # noqa: ANN001, ANN202
        calls.append(list(argv))
        return _R(1 if "/change" in argv else 0)

    monkeypatch.setattr(rl, "_run", _fake_run)
    with pytest.raises(rl.RemoteLaunchError, match="ALREADY RUNNING"):
        rl.start_run(
            ["-m", "tools.ac_harness.auto_alien"],
            label="x",
            repo_root=tmp_path,
            sleep=lambda _s: None,
        )
    # It must NOT delete: /run already succeeded, so the payload is live.
    assert not any("/delete" in c for c in calls)
    # ...and it retried the disable before giving up.
    assert sum(1 for c in calls if "/change" in c) == 2
    # A pollable handle survives, so the live run is not orphaned.
    assert list(tmp_path.joinpath(*rl.RUN_DIR_RELPATH).glob("*/run.json"))


def test_start_run_reports_a_failed_cleanup_delete_after_a_failed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """/run failed so nothing is live — but an un-deleted task keeps its one-shot trigger ARMED."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    monkeypatch.setattr(rl, "short_path", lambda p: str(p))
    monkeypatch.setenv("USERNAME", "someone")

    class _R:
        def __init__(self, rc: int) -> None:
            self.returncode = rc
            self.stdout = ""
            self.stderr = "boom"

    def _fake_run(argv):  # noqa: ANN001, ANN202
        if "/run" in argv or "/delete" in argv:
            return _R(1)
        return _R(0)

    monkeypatch.setattr(rl, "_run", _fake_run)
    with pytest.raises(rl.RemoteLaunchError, match="trigger ARMED"):
        rl.start_run(["-m", "tools.ac_harness.auto_alien"], label="x", repo_root=tmp_path)


def test_start_run_rejects_a_non_harness_payload_at_schedule_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`start -- -c print(1)` used to register and RUN a task, rejected only later."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    calls: list[list[str]] = []
    monkeypatch.setattr(rl, "_run", lambda argv: calls.append(list(argv)))
    monkeypatch.setenv("USERNAME", "someone")
    with pytest.raises(rl.RemoteLaunchError, match="must start with"):
        rl.start_run(["-c", "print(1)"], label="x", repo_root=tmp_path)
    assert calls == []  # nothing scheduled


def test_cleanup_removes_the_control_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unique run ids mean an un-removed control dir leaks a folder per run, forever."""
    _seed_finished_run(tmp_path, "gone")
    assert rl.control_dir_for("gone").exists()

    class _Ok:
        returncode = 0
        stdout = "Status:  Ready\nLast Result:  0\n"

    monkeypatch.setattr(rl, "_run", lambda argv: _Ok())
    monkeypatch.setattr(rl, "poll_run", lambda run, **kw: {"verified_complete": True})
    run = rl.RemoteRun(
        run_id="gone",
        task=rl.task_name_for("gone"),
        repo_root=str(tmp_path),
        run_dir=str(tmp_path.joinpath(*rl.RUN_DIR_RELPATH, "gone")),
        argv=["-m", "tools.ac_harness.auto_alien"],
        started_at="x",
    )
    assert rl.cleanup_run(run)["deleted"] is True
    assert not rl.control_dir_for("gone").exists()


def test_execute_control_file_rejects_a_foreign_repo_root(tmp_path: Path) -> None:
    """repo_root selects the INTERPRETER — trusting the control file was the `-c` hole again."""
    control = rl.control_dir_for("foreign")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(
        json.dumps(
            {
                "repo_root": str(tmp_path / "elsewhere"),
                "argv": ["-m", "tools.ac_harness.auto_alien"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(rl.RemoteLaunchError, match="another checkout"):
        rl.execute_control_file("foreign")


def test_discard_control_dir_removes_only_our_files(tmp_path: Path) -> None:
    """A recursive delete would remove peer-planted content in a peer-writable directory."""
    control = rl.control_dir_for("mixed")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text("{}", encoding="utf-8")
    (control / rl.SENTINEL_NAME).write_text("[wrapper] exit=0\n", encoding="utf-8")
    stranger = control / "someone-elses.txt"
    stranger.write_text("not ours", encoding="utf-8")
    rl._discard_control_dir("mixed")
    assert not (control / rl.CONTROL_NAME).exists()
    assert not (control / rl.SENTINEL_NAME).exists()
    assert stranger.exists()  # untouched, and the rmdir therefore refuses
    assert control.exists()


def test_start_run_reports_a_run_dir_collision_as_a_launch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """main() only catches RemoteLaunchError; a bare FileExistsError crashed the CLI."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    monkeypatch.setattr(rl, "build_run_id", lambda label, **kw: "fixed-id")
    tmp_path.joinpath(*rl.RUN_DIR_RELPATH, "fixed-id").mkdir(parents=True)
    monkeypatch.setenv("USERNAME", "someone")
    with pytest.raises(rl.RemoteLaunchError, match="already exists"):
        rl.start_run(["-m", "tools.ac_harness.auto_alien"], label="fixed", repo_root=tmp_path)


@pytest.mark.parametrize(
    "last_result",
    [267008, 267010, 267012, 267016, -2147024894],
)
def test_verdict_fails_closed_on_scheduler_status_and_launch_failure_codes(
    last_result: int, tmp_path: Path
) -> None:
    """Only two SCHED_S_* codes were rejected; the rest read as 'the payload ran and finished'."""
    ok, reason = rl.evaluate_deletion(
        sentinel_exit_code=0,
        query_rc=0,
        fields={"status": "Ready", "last_result": str(last_result)},
        run_id="abc-1",
    )
    assert ok is False
    assert "failing closed" in reason


def test_verdict_still_accepts_a_real_process_exit_code(tmp_path: Path) -> None:
    ok, _ = rl.evaluate_deletion(
        sentinel_exit_code=0,
        query_rc=0,
        fields={"status": "Ready", "last_result": "0"},
        run_id="abc-1",
    )
    assert ok is True


def test_exec_overwrites_a_planted_sentinel_with_the_real_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A planted `exit=0` must be ERASED, not appended beneath — that is first-wins's premise."""
    control = rl.control_dir_for("planted")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(
        json.dumps({"argv": ["-m", "tools.ac_harness.auto_alien"]}), encoding="utf-8"
    )
    (control / rl.SENTINEL_NAME).write_text("[wrapper] exit=0\n", encoding="utf-8")

    class _Done:
        returncode = 7

    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: _Done())
    assert rl.execute_control_file("planted") == 7
    recorded = rl.sentinel_path_for("planted").read_text(encoding="utf-8")
    assert rl.parse_sentinel(recorded) == 7
    assert "pre-existing sentinel was overwritten" in recorded


def test_failure_path_does_not_leave_a_planted_success_authoritative(tmp_path: Path) -> None:
    """The asked-for regression: plant exit=0, force the failure path, assert it lost."""
    control = rl.control_dir_for("forged")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text(
        json.dumps({"argv": ["-c", "print(1)"]}),
        encoding="utf-8",  # rejected by the allowlist
    )
    (control / rl.SENTINEL_NAME).write_text("[wrapper] exit=0\n", encoding="utf-8")
    with pytest.raises(rl.RemoteLaunchError):
        rl.execute_control_file("forged")
    recorded = rl.sentinel_path_for("forged").read_text(encoding="utf-8")
    assert rl.parse_sentinel(recorded) == rl.EXEC_FAILURE_RC
    assert rl.parse_sentinel(recorded) != 0
    # ...and the verdict must not call that run complete.
    ok, _ = rl.evaluate_deletion(
        sentinel_exit_code=rl.parse_sentinel(recorded),
        query_rc=0,
        fields={"status": "Ready", "last_result": "0"},
        run_id="forged",
    )
    assert ok is False


def test_verdict_requires_last_result_to_match_the_sentinel(tmp_path: Path) -> None:
    """Binds the peer-writable file to an off-disk signal the peer does not control."""
    ok, reason = rl.evaluate_deletion(
        sentinel_exit_code=0,
        query_rc=0,
        fields={"status": "Ready", "last_result": "5"},
        run_id="abc-1",
    )
    assert ok is False
    assert "not written by this run's shim" in reason


def test_cli_emits_the_handle_when_the_run_is_live_but_the_trigger_stayed_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Automation parses stdout JSON; without this it cannot poll a run that IS underway."""
    run = _run_handle(tmp_path)

    def _boom(argv, **kwargs):  # noqa: ANN001, ANN202
        raise rl.RemoteLaunchError("trigger still ARMED", run=run)

    monkeypatch.setattr(rl, "start_run", _boom)
    assert rl.main(["start", "--", "-m", "tools.ac_harness.auto_alien"]) == 3
    assert run.run_id in capsys.readouterr().out


def test_start_run_discards_the_control_dir_when_scheduling_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unregistered task is invisible to reap, so its control dir would leak forever."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    monkeypatch.setattr(rl, "short_path", lambda p: str(p))
    monkeypatch.setattr(rl, "build_run_id", lambda label, **kw: "failed-create")
    monkeypatch.setenv("USERNAME", "someone")

    class _R:
        returncode = 1
        stdout = ""
        stderr = "denied"

    monkeypatch.setattr(rl, "_run", lambda argv: _R())
    with pytest.raises(rl.RemoteLaunchError, match="/create failed"):
        rl.start_run(["-m", "tools.ac_harness.auto_alien"], label="x", repo_root=tmp_path)
    assert not rl.control_dir_for("failed-create").exists()


def test_payload_allowlist_is_an_explicit_set_excluding_the_transport() -> None:
    """A `tools.ac_harness.<ident>` pattern still admitted the transport and its shim."""
    assert "tools.ac_harness.auto_alien" in rl._ALLOWED_PAYLOAD_MODULES
    assert "tools.ac_harness.remote_launcher" not in rl._ALLOWED_PAYLOAD_MODULES
    assert "tools.ac_harness._remote_exec" not in rl._ALLOWED_PAYLOAD_MODULES


def test_start_run_leaves_no_run_dir_when_the_argv_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rejected argv used to leave an orphan scratch directory behind for every typo."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    monkeypatch.setenv("USERNAME", "someone")
    with pytest.raises(rl.RemoteLaunchError):
        rl.start_run(["-c", "print(1)"], label="x", repo_root=tmp_path)
    assert (
        not list(tmp_path.joinpath(*rl.RUN_DIR_RELPATH).glob("*"))
        if tmp_path.joinpath(*rl.RUN_DIR_RELPATH).exists()
        else True
    )


def test_start_run_converts_a_permission_error_on_mkdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """main() only catches RemoteLaunchError; a raw PermissionError bypassed the documented exit."""
    monkeypatch.setattr(rl, "assert_transport_needed", lambda: (0, 1))
    monkeypatch.setenv("USERNAME", "someone")
    monkeypatch.setattr(
        Path, "mkdir", lambda self, **kw: (_ for _ in ()).throw(PermissionError("denied"))
    )
    with pytest.raises(rl.RemoteLaunchError, match="cannot create run directory"):
        rl.start_run(["-m", "tools.ac_harness.auto_alien"], label="x", repo_root=tmp_path)


def test_discard_control_dir_survives_a_sharing_violation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A best-effort cleanup step must not turn a successful delete into a traceback."""
    control = rl.control_dir_for("locked")
    control.mkdir(parents=True)
    (control / rl.CONTROL_NAME).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        Path, "unlink", lambda self, **kw: (_ for _ in ()).throw(PermissionError("in use"))
    )
    rl._discard_control_dir("locked")  # must not raise
