"""Real WS routing with real sealed guard; native actuator is an explicit adapter."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from test_pressure_bench import sealed as sealed_fixture
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from tools.ai_sidecar import external_protocol as ep
from tools.ai_sidecar import server as srv
from tools.ai_sidecar.setup_prescription import PrescriptionJournal

sealed = sealed_fixture


@pytest.mark.parametrize(
    "session,filename_token",
    [
        ("test_session", "testsess"),
        ("abc-defghi", "abcdefgh"),
        ("aabbccddeeff", "aabbccdd"),
        ("_-------", "sess"),
    ],
)
def test_native_source_discovery_matches_lua_filename_contract(sealed, session, filename_token):
    ctx = copy.deepcopy(sealed.ctx)
    ctx["identity"]["session_id"] = session
    selected = []
    for n in (1, 2, 10):
        path = sealed.lap_dir / f"lap_20261113-010000_{filename_token}_{n}_90000_key{n}.json"
        path.write_text(json.dumps({"session_uuid": session, "lap": {"lap_n": n}}))
        if n > 1:
            selected.append(path.resolve())
    collision = sealed.lap_dir / f"lap_20261113-010000_{filename_token}_99_90000_other.json"
    collision.write_text(json.dumps({"session_uuid": session + "other", "lap": {"lap_n": 99}}))
    store = sealed.lap_dir.parent / "setup_experiments/experiments.jsonl"
    assert srv._bench_source_paths(ctx, store) == selected


@pytest.mark.parametrize("operation", ["arm", "get"])
def test_native_file_failure_never_exposes_paths_on_screen(sealed, monkeypatch, operation):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                async with peer(url, client="ac-copilot-screen-test", screen=True) as screen:
                    if operation == "get":
                        await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                        assert (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is True
                    private = str(sealed.tmp_path / "hidden-oracle/secret-case.json")

                    def unavailable(*_):
                        raise FileNotFoundError(2, "Synthetic missing evidence", private)

                    monkeypatch.setattr(srv, "_bench_inputs", unavailable)
                    if operation == "arm":
                        await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                        response = await receive(owner, "error")
                    else:
                        await send(
                            owner, ep.TYPE_SETUP_BENCH_GET, mode="ai_bench", run_id="run-one"
                        )
                        response = await receive(owner, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert private not in json.dumps(response) and str(
                        sealed.tmp_path
                    ) not in json.dumps(response)
                    for _ in range(3):
                        status = await receive(screen, ep.TYPE_SETUP_BENCH_STATUS)
                        assert str(sealed.tmp_path) not in json.dumps(status)
                        if status["active"] is False:
                            break
                    assert status["active"] is False and state.applies == 0
                    assert private not in sealed.guard.status()["reason"]

    asyncio.run(run())


def test_bench_health_hides_runtime_file_paths(monkeypatch):
    monkeypatch.setenv("AC_COPILOT_PRESSURE_BENCH_PERMIT", "configured-test-path")

    def unavailable():
        raise FileNotFoundError(2, "Synthetic missing runtime", "C:/private/runtime.exe")

    monkeypatch.setattr(srv, "_bench_guard", unavailable)
    status = srv._bench_status()
    assert status["active"] is False and status["configured"] is True
    assert "C:/private" not in json.dumps(status)


def test_shared_normal_prescription_file_errors_also_keep_paths_private(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            # Isolated software-only negative control, never the rig runtime.
            monkeypatch.setenv("AC_COPILOT_PRESSURE_EXPERIMENT", "1")

            def unavailable(*_):
                raise FileNotFoundError(
                    2, "Synthetic missing journal", "C:/private/experiments.jsonl"
                )

            monkeypatch.setattr(srv, "_prescription_inputs", unavailable)
            async with peer(url) as external:
                await send(external, ep.TYPE_SETUP_PRESCRIPTION_GET)
                response = await receive(external, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                assert "C:/private" not in json.dumps(response) and state.applies == 0

    asyncio.run(run())


async def receive(ws, kind):
    for _ in range(30):
        frame = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if frame.get("type", frame.get("event")) in (kind, "error"):
            return frame
    raise AssertionError("No correlated response")


async def send(ws, kind, **fields):
    await ws.send(json.dumps({"v": 1, "type": kind, **fields}))


@asynccontextmanager
async def peer(url, *, client=None, screen=False):
    headers = {ep.CLIENT_HEADER: client} if client else None
    async with connect(url, additional_headers=headers) as ws:
        await send(
            ws, "hello", client="bench-test", client_class="screen" if screen else "external"
        )
        assert (await receive(ws, "hello_ack"))["type"] == "hello_ack"
        if screen:
            await receive(ws, ep.TYPE_SETUP_BENCH_STATUS)
        yield ws


@asynccontextmanager
async def running(fixture, monkeypatch):
    srv._reset_external_state()
    monkeypatch.delenv("AC_COPILOT_PRESSURE_EXPERIMENT", raising=False)
    monkeypatch.setenv("AC_COPILOT_PRESSURE_BENCH_PERMIT", str(fixture.permit_path))
    monkeypatch.setattr(srv, "_pressure_bench_guard", fixture.guard)
    store = fixture.lap_dir.parent / "setup_experiments/experiments.jsonl"
    monkeypatch.setattr(srv, "_setup_experiment_store_path", store)
    monkeypatch.setattr(srv, "_bench_inputs", lambda *_: (fixture.archives, fixture.targets))
    state = SimpleNamespace(
        ctx=copy.deepcopy(fixture.ctx),
        applies=0,
        store=store,
        context_requests=0,
        latest_context=None,
        before_apply=None,
    )
    async with serve(
        lambda ws: srv._handler(ws, reply_coaching=False),
        "127.0.0.1",
        0,
        process_request=srv.make_process_request(None),
    ) as listener:
        url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
        async with connect(url, additional_headers={ep.CLIENT_HEADER: ep.LUA_CLIENT_ID}) as lua:
            await send(lua, "hello", client="native-fixture", client_class="lua")
            await receive(lua, "hello_ack")

            async def native():
                async for raw in lua:
                    request = json.loads(raw)
                    if request.get("type") != ep.TYPE_SETUP_PRESCRIPTION_RPC:
                        continue
                    op = request["operation"]
                    reply = {"operation": op, "request_id": request["request_id"], "ok": True}
                    if op == "context":
                        state.context_requests += 1
                        state.latest_context = request["request_id"]
                        reply.update(copy.deepcopy(state.ctx), context_id=request["request_id"])
                    else:
                        if op == "apply":
                            if state.before_apply is not None:
                                await state.before_apply()
                            if request.get("context_id") != state.latest_context:
                                reply.update(ok=False, error="Prescription context expired")
                            elif state.ctx["is_in_pit"] is not True:
                                reply.update(ok=False, error="Pit box exited")
                            else:
                                state.applies += 1
                                changes = {r["section"]: r["to"] for r in request["changes"]}
                                for row in state.ctx["spinners"]:
                                    row["value"] = changes.get(row["section"], row["value"])
                        reply["readback"] = {
                            r["section"]: r["value"] for r in state.ctx["spinners"]
                        }
                    await send(lua, ep.TYPE_SETUP_PRESCRIPTION_RPC_RESULT, **reply)

            task = asyncio.create_task(native())
            try:
                yield url, state
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    srv._reset_external_state()


def test_explicit_arm_and_screen_accept_are_isolated_from_normal_namespace(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                armed = await receive(owner, ep.TYPE_SETUP_BENCH_STATUS)
                assert armed["active"] is True
                async with peer(url, client="ac-copilot-screen-test", screen=True) as screen:
                    await send(screen, ep.TYPE_SETUP_PRESCRIPTION_GET)
                    inactive = await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert inactive["reason"] == "Pressure experiment inactive"
                    await send(screen, ep.TYPE_SETUP_BENCH_GET, mode="ai_bench", run_id="run-one")
                    card = await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert card["status"] == "proposed" and card["mode"] == "ai_bench"
                    decision = {"prescription_id": card["prescription_id"], "decision": "accept"}
                    await send(screen, ep.TYPE_SETUP_PRESCRIPTION_DECIDE, **decision)
                    denied = await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert denied["status"] == "blocked" and state.applies == 0
                    await send(
                        screen,
                        ep.TYPE_SETUP_BENCH_DECIDE,
                        mode="ai_bench",
                        run_id="run-one",
                        **decision,
                    )
                    applied = await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert applied["status"] == "verified_applied", applied
                    await send(
                        screen,
                        ep.TYPE_SETUP_BENCH_DECIDE,
                        mode="ai_bench",
                        run_id="run-one",
                        **decision,
                    )
                    assert (await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD))[
                        "status"
                    ] == "verified_applied"
                    assert state.applies == 1
                    await send(
                        screen,
                        ep.TYPE_SETUP_BENCH_GET,
                        mode="ai_bench",
                        run_id="run-one",
                        prescription_id=card["prescription_id"],
                    )
                    reconciled = await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert (
                        reconciled["status"] == "verified_applied"
                        and reconciled["decision"] == "accept"
                    )
                    assert state.applies == 1
                    assert (
                        PrescriptionJournal(state.store).get(card["prescription_id"])["mode"]
                        == "ai_bench"
                    )
                for _ in range(10):
                    if (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is False:
                        break
                assert sealed.guard.status()["active"] is False

    asyncio.run(run())


def test_actor_poll_cannot_replace_screen_decision_native_context(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                async with peer(url, client="ac-copilot-screen-test", screen=True) as screen:
                    await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                    assert (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is True
                    await send(owner, ep.TYPE_SETUP_BENCH_GET, mode="ai_bench", run_id="run-one")
                    card = await receive(owner, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    assert card["status"] == "proposed"
                    entered, release = asyncio.Event(), threading.Event()
                    loop = asyncio.get_running_loop()
                    calls = 0

                    def delayed(*_):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            loop.call_soon_threadsafe(entered.set)
                            assert release.wait(5)
                        return sealed.archives, sealed.targets

                    monkeypatch.setattr(srv, "_bench_inputs", delayed)
                    count = state.context_requests
                    try:
                        await send(
                            screen,
                            ep.TYPE_SETUP_BENCH_DECIDE,
                            mode="ai_bench",
                            run_id="run-one",
                            prescription_id=card["prescription_id"],
                            decision="accept",
                        )
                        await asyncio.wait_for(entered.wait(), 2)
                        await send(
                            owner,
                            ep.TYPE_SETUP_BENCH_GET,
                            mode="ai_bench",
                            run_id="run-one",
                            prescription_id=card["prescription_id"],
                        )
                        await asyncio.sleep(0.05)
                        assert state.context_requests == count + 1
                        release.set()
                        assert (await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD))[
                            "status"
                        ] == "verified_applied"
                        assert (await receive(owner, ep.TYPE_SETUP_PRESCRIPTION_CARD))[
                            "status"
                        ] == "verified_applied"
                        assert state.applies == 1
                    finally:
                        release.set()

    asyncio.run(run())


def test_arm_waits_for_inflight_accept_before_disarming(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                async with peer(url, client="ac-copilot-screen-test", screen=True) as screen:
                    await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                    assert (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is True
                    await send(owner, ep.TYPE_SETUP_BENCH_GET, mode="ai_bench", run_id="run-one")
                    card = await receive(owner, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                    entered, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()
                    original = srv._handle_bench_control

                    async def before_apply():
                        entered.set()
                        await asyncio.wait_for(release.wait(), 3)

                    async def notice_control(ws, data):
                        if data["type"] == ep.TYPE_SETUP_BENCH_ARM:
                            queued.set()
                        await original(ws, data)

                    state.before_apply = before_apply
                    monkeypatch.setattr(srv, "_handle_bench_control", notice_control)
                    try:
                        await send(
                            screen,
                            ep.TYPE_SETUP_BENCH_DECIDE,
                            mode="ai_bench",
                            run_id="run-one",
                            prescription_id=card["prescription_id"],
                            decision="accept",
                        )
                        await asyncio.wait_for(entered.wait(), 2)
                        assert (
                            PrescriptionJournal(state.store).get(card["prescription_id"])["status"]
                            == "accepted_unverified"
                        )
                        epoch = sealed.guard.disarm_epoch
                        await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                        await asyncio.wait_for(queued.wait(), 2)
                        await asyncio.sleep(0.01)
                        assert sealed.guard.disarm_epoch == epoch
                        assert sealed.guard.status()["active"] is True
                        release.set()
                        final = await receive(screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                        assert final["status"] == "verified_applied" and state.applies == 1
                        assert (await receive(owner, "error"))["type"] == "error"
                        assert state.applies == 1
                    finally:
                        release.set()

    asyncio.run(run())


def test_hello_class_alone_cannot_arm_or_redeem_a_bench_card(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, screen=True) as claimed_screen:
                await send(claimed_screen, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                assert (await receive(claimed_screen, ep.TYPE_SETUP_BENCH_STATUS))[
                    "type"
                ] == "error"
                await send(
                    claimed_screen, ep.TYPE_SETUP_BENCH_GET, mode="ai_bench", run_id="run-one"
                )
                denied = await receive(claimed_screen, ep.TYPE_SETUP_PRESCRIPTION_CARD)
                assert denied["status"] == "blocked" and state.applies == 0

    asyncio.run(run())


@pytest.mark.parametrize("kind", [ep.TYPE_SETUP_SPINNER_SET, ep.TYPE_SETUP_LOAD])
def test_other_setup_actuators_are_blocked_while_armed(sealed, monkeypatch, kind):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                assert (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is True
                await send(owner, kind, name="PRESSURE_LF", value=22)
                assert (await receive(owner, "error"))["type"] == "error"
                assert state.applies == 0

    asyncio.run(run())


def test_capture_does_not_run_legacy_coaching_or_seed_unknown_archives(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, _state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                await owner.send(
                    json.dumps({"event": "lap_complete", "lap": 2, "lapTimeMs": 90000})
                )
                assert (await receive(owner, "bench_capture"))["status"] == "analysis_only"
                await send(
                    owner,
                    ep.TYPE_SETUP_EXPERIMENT_RECORD,
                    archive_path=str(sealed.sources[0]["path"]),
                )
                ack = await receive(owner, ep.TYPE_SETUP_EXPERIMENT_RECORD_ACK)
                assert ack["ok"] is True and "qualification" in ack["deferred"]

    asyncio.run(run())


def test_capture_does_not_feed_realtime_learning_or_advisories(monkeypatch):
    def forbidden(_frame):
        raise AssertionError("AI capture reached realtime coaching")

    monkeypatch.setenv("AC_COPILOT_PRESSURE_BENCH_PERMIT", "configured-test-path")
    monkeypatch.setattr(srv, "_observer", SimpleNamespace(observe=forbidden))
    monkeypatch.setattr(srv, "_coach_runtime", None)
    asyncio.run(srv._publish_coaching_cues({"v": 1, "type": "telemetry_tick"}, exclude=object()))


def test_screen_run_rejection_disarms_before_any_application(sealed, monkeypatch):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                async with peer(url, client="ac-copilot-screen-test", screen=True) as screen:
                    await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                    assert (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is True
                    await send(
                        screen, ep.TYPE_SETUP_BENCH_STATUS_ACK, ok=False, active=False, run_id=""
                    )
                    for _ in range(10):
                        if (await receive(owner, ep.TYPE_SETUP_BENCH_STATUS))["active"] is False:
                            break
                    assert sealed.guard.status()["active"] is False and state.applies == 0

    asyncio.run(run())


@pytest.mark.parametrize("invalidate", ["disconnect", "explicit_disarm"])
def test_pending_arm_cannot_survive_disconnect_or_later_disarm(sealed, monkeypatch, invalidate):
    async def run():
        async with running(sealed, monkeypatch) as (url, state):
            entered, release, finished = asyncio.Event(), threading.Event(), asyncio.Event()
            loop = asyncio.get_running_loop()
            original_arm = sealed.guard.arm

            def delayed(*_):
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)
                loop.call_soon_threadsafe(finished.set)
                return sealed.archives, sealed.targets

            def forbidden_arm(*args):
                raise AssertionError("An invalidated pending arm reached the guard")

            monkeypatch.setattr(srv, "_bench_inputs", delayed)
            monkeypatch.setattr(sealed.guard, "arm", forbidden_arm)
            async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as owner:
                await send(owner, ep.TYPE_SETUP_BENCH_ARM, case_file=str(sealed.case_path))
                await asyncio.wait_for(entered.wait(), 2)
                try:
                    if invalidate == "disconnect":
                        await owner.close()
                        # The handler is still awaiting the loader, so its
                        # finally-cleanup cannot remove membership yet.
                        assert all(
                            p.close_code is not None for p in srv._pressure_bench_authorized_peers
                        )
                    else:
                        async with peer(url, client=ep.PRESSURE_BENCH_CLIENT_ID) as other:
                            await send(other, ep.TYPE_SETUP_BENCH_DISARM)
                            assert (await receive(other, ep.TYPE_SETUP_BENCH_STATUS))[
                                "active"
                            ] is False
                    release.set()
                    await asyncio.wait_for(finished.wait(), 2)
                    if invalidate == "explicit_disarm":
                        assert (await receive(owner, "error"))["type"] == "error"
                    else:
                        await asyncio.sleep(0.05)
                    assert sealed.guard.status()["active"] is False and state.applies == 0
                finally:
                    release.set()
                    monkeypatch.setattr(sealed.guard, "arm", original_arm)

    asyncio.run(run())
