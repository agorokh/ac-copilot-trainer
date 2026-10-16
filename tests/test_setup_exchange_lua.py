"""Execute production CSP provider/bridge against asynchronous CSP API adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa.luajit21", reason="CSP uses LuaJIT/Lua 5.1")
MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"
REQUEST_ID = "a" * 32


def runtime():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(
        r"""
        _car, _track, _session = 'car_a', 'spa', 0
        _http, _sent, _results = {}, {}, {}
        ac = {
          getCarID = function() return _car end,
          getTrackID = function() return _track end,
          getCarName = function() return 'Car A' end,
          getTrackName = function() return 'Spa' end,
          getSim = function() return {currentSessionIndex = _session} end,
          getPatchVersionCode = function() return 3050 end,
          uniqueMachineKeyAsync = function(cb) _keyCallback = cb end,
          checksumSHA256 = function(value) _hashInput = value; return 'private-user-hash' end,
          encodeBase64 = function(value) return 'base64:' .. value end,
          log = function() end,
        }
        package.preload['shared/utils/signing'] = function()
          return {blob = function(template, key, cb)
            _signTemplate, _signKey, _signCallback = template, key, cb
          end}
        end
        web = {
          request = function(method, url, headers, body, cb)
            _http[#_http + 1] = {method=method, url=url, headers=headers, body=body, cb=cb}
          end,
          socket = function(url, headers, cb, options)
            _recv, _open, _close = cb, options.onOpen, options.onClose
            return setmetatable({close=function() end}, {__call=function(_, data)
              _sent[#_sent+1] = data
            end})
          end,
        }
        function _handle(payload)
          require('setup_exchange').handle(payload, function(result)
            _results[#_results+1] = result
          end)
        end
        """
    )
    rt.execute(f"package.path = {json.dumps(MODULES.as_posix() + '/?.lua;')} .. package.path")

    def to_lua(value):
        if isinstance(value, dict):
            return rt.table_from({key: to_lua(item) for key, item in value.items()})
        if isinstance(value, list):
            return rt.table_from({i + 1: to_lua(item) for i, item in enumerate(value)})
        return value

    def from_lua(value):
        if lupa.lua_type(value) == "table":
            keys = list(value.keys())
            if keys and all(isinstance(key, int) for key in keys):
                return [from_lua(value[i]) for i in range(1, len(keys) + 1)]
            return {key: from_lua(item) for key, item in value.items()}
        return value

    def parse(value):
        try:
            return to_lua(json.loads(value))
        except json.JSONDecodeError:
            return None

    rt.globals().JSON = rt.table_from(
        {
            "parse": parse,
            "stringify": lambda value, *args: json.dumps(from_lua(value)),
        }
    )
    return rt, to_lua, from_lua


def start(rt, to_lua, **kwargs):
    payload = {"request_id": REQUEST_ID, "operation": "search", "car_id": "car_a", **kwargs}
    rt.globals()._handle(to_lua(payload))


def respond(rt, to_lua, index, body, *, status=200, error=None, headers=None):
    response = {"status": status, "body": json.dumps(body), "headers": headers or {}}
    rt.globals()._http[index].cb(error, to_lua(response))


def authenticate(rt, to_lua, *, start_index=1):
    rt.globals()._keyCallback(None, "private-machine-key")
    post = rt.globals()._http[start_index]
    assert post.method == "POST" and post.url == "https://se.acstuff.club/session"
    assert post.headers["X-Session-ID"] == "0"
    assert json.loads(post.body) == {"userID": "private-user-hash"}
    respond(rt, to_lua, start_index, {"key": "private-challenge"})
    assert rt.globals()._signTemplate == "{UniqueMachineKeyChecksum}"
    assert rt.globals()._signKey == "private-challenge"
    rt.globals()._signCallback("private-signature", "private-header")
    patch = rt.globals()._http[start_index + 1]
    assert patch.method == "PATCH"
    assert json.loads(patch.body) == {
        "userID": "private-user-hash",
        "signature": "base64:private-signature",
        "header": "base64:private-header",
        "carID": "car_a",
        "carName": "Car A",
        "trackID": "spa",
        "trackName": "Spa",
    }
    respond(rt, to_lua, start_index + 1, {"sessionID": "private-session", "userID": "private-user"})


def test_signed_search_preserves_author_sort_paging_and_never_returns_auth():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua, track_id="spa", search="race + wet", limit=2, offset=4, order_by="name")
    assert len(rt.globals()._http) == 0  # handler returns before machine-key/HTTP/signing callbacks
    authenticate(rt, to_lua)
    get = rt.globals()._http[3]
    assert get.headers["X-Session-ID"] == "private-session"
    assert (
        get.url
        == "https://se.acstuff.club/setups?carID=car_a&offset=4&limit=2&orderBy=name&trackID=spa&search=race%20%2B%20wet"
    )
    respond(
        rt,
        to_lua,
        3,
        [
            {
                "setupID": 23,
                "name": "Wet",
                "userName": "Alice",
                "statDownloads": 42,
                "sessionID": "secret",
                "userID": "secret",
                "key": "secret",
            }
        ],
        headers={"x-total-count": "19"},
    )
    result = from_lua(rt.globals()._results[1])
    assert result == {
        "request_id": REQUEST_ID,
        "operation": "search",
        "ok": True,
        "response": [{"setupID": 23, "name": "Wet", "userName": "Alice", "statDownloads": 42}],
        "total_count": 19,
    }
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)


def test_download_reuses_session_and_only_returns_public_data():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    authenticate(rt, to_lua)
    respond(rt, to_lua, 3, [])
    start(rt, to_lua, request_id="b" * 32, operation="download", setup_id=23)
    assert rt.globals()._http[4].url.endswith("/setups/23")
    respond(rt, to_lua, 4, {"data": "[CAR]\nMODEL=car_a", "name": "Wet", "sessionID": "secret"})
    assert from_lua(rt.globals()._results[2])["response"] == {
        "data": "[CAR]\nMODEL=car_a",
        "name": "Wet",
    }
    assert len(rt.globals()._http) == 4


@pytest.mark.parametrize("metadata", [{"carID": "other"}, {"trackID": "other"}])
def test_download_rejects_conflicting_car_or_track(metadata):
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua, operation="download", setup_id=1, track_id="spa")
    authenticate(rt, to_lua)
    respond(rt, to_lua, 3, {"data": "[CAR]\nMODEL=car_a", **metadata})
    assert "different car or track" in from_lua(rt.globals()._results[1])["error"]


def test_download_rejects_oversized_metadata_without_dereferencing_missing_row():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua, operation="download", setup_id=1)
    authenticate(rt, to_lua)
    respond(rt, to_lua, 3, {"data": "[CAR]\nMODEL=car_a", "name": "é" * 257})
    assert from_lua(rt.globals()._results[1]) == {
        "request_id": REQUEST_ID,
        "operation": "download",
        "ok": False,
        "error": "Setup Exchange returned invalid setup metadata",
    }
    # The rejected callback completes once and leaves the cached session usable.
    respond(rt, to_lua, 3, {"data": "[CAR]\nMODEL=car_a", "name": "Valid"})
    assert len(rt.globals()._results) == 1
    start(rt, to_lua, operation="download", setup_id=2, request_id="b" * 32)
    respond(rt, to_lua, 4, {"data": "[CAR]\nMODEL=car_a", "name": "Valid"})
    assert from_lua(rt.globals()._results[2])["ok"] is True


def test_async_http_json_parse_exception_is_caught_without_leaking_service_data():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    authenticate(rt, to_lua)
    rt.execute("JSON.parse = function() error('private service parse details') end")
    respond(rt, to_lua, 3, [{"setupID": 1}])
    result = from_lua(rt.globals()._results[1])
    assert result["ok"] is False
    assert result["error"] == "Setup Exchange service request failed"


@pytest.mark.parametrize("stage", ["key", "post", "sign", "patch"])
def test_auth_failures_return_safe_error_and_do_not_use_legacy_auth(stage):
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    if stage == "key":
        rt.globals()._keyCallback("private-machine-key", None)
    else:
        rt.globals()._keyCallback(None, "private-machine-key")
        if stage == "post":
            respond(rt, to_lua, 1, {"error": "private-challenge"}, status=500)
        else:
            respond(rt, to_lua, 1, {"key": "private-challenge"})
            if stage == "sign":
                rt.globals()._signCallback(None, None)
            else:
                rt.globals()._signCallback("private-signature", "private-header")
                respond(rt, to_lua, 2, {"error": "private-session"}, status=401)
    result = from_lua(rt.globals()._results[1])
    assert result["error"] == "Setup Exchange authentication failed"
    assert all(row.method != "GET" for row in rt.globals()._http.values())


def test_timeout_before_machine_key_completion_can_recover_next_request():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    old_callback = rt.globals()._keyCallback
    rt.execute("require('setup_exchange').tick(21)")
    assert "timed out" in from_lua(rt.globals()._results[1])["error"]
    old_callback(None, "private-machine-key")
    assert len(rt.globals()._http) == 0
    start(rt, to_lua, request_id="b" * 32)
    authenticate(rt, to_lua)
    respond(rt, to_lua, 3, [])
    assert from_lua(rt.globals()._results[2])["ok"] is True


def test_invalid_session_refreshes_signed_session_once():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    authenticate(rt, to_lua)
    respond(rt, to_lua, 3, {"error": "Invalid session ID"}, status=401)
    authenticate(rt, to_lua, start_index=4)
    respond(rt, to_lua, 6, {"error": "Invalid session ID"}, status=401)
    assert len(rt.globals()._http) == 6
    assert from_lua(rt.globals()._results[1])["error"] == "Setup Exchange service request failed"


@pytest.mark.parametrize("phase", ["key", "post", "sign", "patch", "get"])
def test_stale_context_drops_every_auth_or_request_callback(phase):
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    if phase != "key":
        rt.globals()._keyCallback(None, "private-machine-key")
    if phase in {"sign", "patch", "get"}:
        respond(rt, to_lua, 1, {"key": "private-challenge"})
    if phase in {"patch", "get"}:
        rt.globals()._signCallback("private-signature", "private-header")
    if phase == "get":
        respond(rt, to_lua, 2, {"sessionID": "private-session"})
    rt.execute("_session = 1; require('setup_exchange').tick(0.1)")
    assert "context changed" in from_lua(rt.globals()._results[1])["error"]
    if phase == "key":
        rt.globals()._keyCallback(None, "private-machine-key")
    elif phase == "post":
        respond(rt, to_lua, 1, {"key": "private-challenge"})
    elif phase == "sign":
        rt.globals()._signCallback("private-signature", "private-header")
    elif phase == "patch":
        respond(rt, to_lua, 2, {"sessionID": "private-session"})
    else:
        respond(rt, to_lua, 3, [{"setupID": 1}])
    assert len(rt.globals()._results) == 1


def test_timeout_completes_once_and_late_http_cannot_resurrect_request():
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua)
    authenticate(rt, to_lua)
    rt.execute("require('setup_exchange').tick(21)")
    assert "timed out" in from_lua(rt.globals()._results[1])["error"]
    respond(rt, to_lua, 3, [{"setupID": 1}])
    assert len(rt.globals()._results) == 1


def test_pending_limit_and_shared_auth_do_not_block_ui():
    rt, to_lua, from_lua = runtime()
    for i in range(9):
        start(rt, to_lua, request_id=f"{i:032x}")
    assert from_lua(rt.globals()._results[1])["error"] == "Setup Exchange is busy"
    authenticate(rt, to_lua)
    assert len(rt.globals()._http) == 10  # one handshake, eight concurrent bounded reads


@pytest.mark.parametrize(
    "change",
    [
        {"car_id": "other"},
        {"limit": 41},
        {"offset": -1},
        {"order_by": "DROP"},
        {"operation": "download", "setup_id": "../1"},
    ],
)
def test_invalid_requests_never_call_service(change):
    rt, to_lua, from_lua = runtime()
    start(rt, to_lua, **change)
    assert from_lua(rt.globals()._results[1])["ok"] is False
    assert len(rt.globals()._http) == 0


@pytest.mark.parametrize("stage", ["transport", "json", "search_size", "data_size", "row_count"])
def test_malformed_service_data_and_errors_are_bounded(stage):
    rt, to_lua, from_lua = runtime()
    start(
        rt, to_lua, operation="download" if stage == "data_size" else "search", setup_id=1, limit=1
    )
    authenticate(rt, to_lua)
    if stage == "transport":
        respond(
            rt, to_lua, 3, {"error": "private-session"}, status=500, error="private-machine-key"
        )
    elif stage == "json":
        rt.globals()._http[3].cb(None, to_lua({"status": 200, "body": "not json"}))
    elif stage == "search_size":
        respond(rt, to_lua, 3, ["x" * 2097152])
    elif stage == "data_size":
        respond(rt, to_lua, 3, {"data": "x" * 524289})
    else:
        respond(rt, to_lua, 3, [{"setupID": 1}, {"setupID": 2}])
    result = from_lua(rt.globals()._results[1])
    assert result["ok"] is False and "private" not in result["error"]
    assert len(result["error"]) <= 240


def test_bridge_async_completion_once_and_sync_handlers_unchanged():
    rt, to_lua, _ = runtime()
    rt.execute("""
      wb = require('ws_bridge'); wb.configure('ws://127.0.0.1:8765'); wb.tick(0)
      wb.registerAsyncRequestHandler('se.csp.request', 'se.csp.result',
        require('setup_exchange').handle)
      wb.registerRequestHandler('setup.list', 'setup.list.result', function()
        return {ok=true, names={'wet'}}
      end)
    """)
    rt.globals()._recv(
        json.dumps(
            {
                "v": 1,
                "type": "se.csp.request",
                "request_id": REQUEST_ID,
                "operation": "search",
                "car_id": "car_a",
            }
        )
    )
    rt.execute("wb.pollInbound(8)")
    assert len(rt.globals()._sent) == 0
    authenticate(rt, to_lua)
    respond(rt, to_lua, 3, [{"setupID": 1, "userName": "Alice"}])
    respond(rt, to_lua, 3, [{"setupID": 1}])
    frames = [json.loads(value) for value in rt.globals()._sent.values()]
    assert len(frames) == 1 and frames[0]["type"] == "se.csp.result"
    assert frames[0]["response"][0]["userName"] == "Alice"
    rt.globals()._recv(json.dumps({"v": 1, "type": "setup.list"}))
    rt.execute("wb.pollInbound(8)")
    assert json.loads(rt.globals()._sent[2]) == {
        "v": 1,
        "type": "setup.list.result",
        "ok": True,
        "names": ["wet"],
    }


@pytest.mark.parametrize("change", ["configure", "reopen"])
def test_bridge_never_sends_late_async_result_to_new_connection(change):
    rt, _, _ = runtime()
    rt.execute("""
      wb = require('ws_bridge'); wb.configure('ws://127.0.0.1:8765'); wb.tick(0)
      wb.registerAsyncRequestHandler('test.async', 'test.result', function(payload, complete)
        _complete = complete
      end)
    """)
    rt.globals()._recv('{"v":1,"type":"test.async"}')
    rt.execute("wb.pollInbound(8)")
    rt.execute(
        "wb.configure('ws://127.0.0.1:8765'); wb.tick(0)" if change == "configure" else "_open()"
    )
    count = len(rt.globals()._sent)
    rt.execute("_complete({ok=true}); _complete({ok=true})")
    assert len(rt.globals()._sent) == count
