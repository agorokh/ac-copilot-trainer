from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).parents[1] / "tools" / "simhub_car_enrichment" / "AcCopilot.CarEnrichment"
SOURCE = (ROOT / "AcCopilotDataPlugin.cs").read_text(encoding="utf-8")


def test_simhub_project_targets_supported_sdk_without_copying_operator_files() -> None:
    project = ElementTree.parse(ROOT / "AcCopilot.CarEnrichment.csproj")
    values = {element.tag.rsplit("}", 1)[-1]: element.text for element in project.iter()}
    assert values["TargetFrameworkVersion"] == "v4.8"
    assert "SimHub.Plugins.dll" in values["HintPath"]
    assert "PostBuildEvent" not in values


def test_bridge_exposes_stable_property_contract() -> None:
    for name in (
        "CarClass",
        "CarId",
        "ClassSource",
        "RegistryVersion",
        "SidecarConnected",
        "TrainerConnected",
    ):
        assert f'AttachDelegate("{name}"' in SOURCE


def test_bridge_subscribes_to_authoritative_identity_and_fails_closed() -> None:
    assert r'"topics\":[\"connection\",\"session\"]' in SOURCE
    assert 'String.Equals(topic, "session"' in SOURCE
    assert 'String.Equals(topic, "connection"' in SOURCE
    assert "TrainerFreshMilliseconds = 3500" in SOURCE
    assert 'UnknownClass = "unknown"' in SOURCE
    assert "Stopwatch.GetTimestamp()" in SOURCE
    assert "DateTime.UtcNow" not in SOURCE
    assert 'Value(frame, "snapshot_age_ms")' in SOURCE
    assert "Task.Run(() => RunAsync" in SOURCE
    assert "DataUpdate" in SOURCE
    data_update = SOURCE.split("public void DataUpdate", 1)[1].split("public void End", 1)[0]
    assert "ConnectAsync" not in data_update


def test_connection_heartbeat_preserves_identity_only_within_fresh_epoch() -> None:
    connection_branch = SOURCE.split('if (String.Equals(topic, "connection"', 1)[1].split(
        'if (!String.Equals(topic, "session"', 1
    )[0]
    assert "lastConnectionTimestamp" in connection_branch
    assert "bool wasFresh = TrainerIsFresh();" in connection_branch
    assert "bool isFresh = TrainerIsFresh();" in connection_branch
    assert "if (!wasFresh || !isFresh)" in connection_branch
    assert "ClearIdentity();" in connection_branch
    assert "if (!wasFresh && isFresh)" in connection_branch
    assert "awaitingFreshSessionReplay" in connection_branch
    assert "return true;" in connection_branch


def test_fresh_epoch_requests_and_waits_for_lua_session_replay() -> None:
    receive_loop = SOURCE.split("while (!token.IsCancellationRequested", 1)[1].split(
        "private Uri SidecarUri()", 1
    )[0]
    assert "bool requestSessionReplay = ApplySnapshot(message, generation);" in receive_loop
    assert "if (requestSessionReplay)" in receive_loop
    assert r'"topics\":[\"session\"]' in receive_loop
    session_branch = SOURCE.split('if (!String.Equals(topic, "session"', 1)[1].split(
        "string resolvedClass", 1
    )[0]
    assert "awaitingFreshSessionReplay" in session_branch
    assert 'ToDouble(Value(frame, "snapshot_age_ms")) > TrainerFreshMilliseconds' in session_branch
    assert "return false;" in session_branch
    assert "Interlocked.Exchange(ref awaitingFreshSessionReplay, 0);" in SOURCE


def test_bridge_shutdown_invalidates_worker_before_deferred_disposal() -> None:
    init_branch = SOURCE.split("public void Init", 1)[1].split("public void DataUpdate", 1)[0]
    end_branch = SOURCE.split("public void End", 1)[1].split("private async Task RunAsync", 1)[0]
    assert "CancellationTokenSource source = new CancellationTokenSource();" in init_branch
    assert "RunAsync(source.Token, generation)" in init_branch
    assert "RunAsync(cancellation.Token, generation)" not in init_branch
    assert "Interlocked.Increment(ref lifecycleGeneration);" in end_branch
    assert "runningWorker.Wait(TimeSpan.FromSeconds(2))" in end_branch
    assert "runningWorker.ContinueWith(" in end_branch
    assert end_branch.index("Interlocked.Increment(ref lifecycleGeneration);") < end_branch.index(
        "source.Cancel();"
    )
    assert "IsCurrentGeneration(generation)" in SOURCE
    assert "ApplySnapshot(message, generation)" in SOURCE


def test_bridge_uses_launcher_resolved_endpoint_and_resets_backoff_on_handshake() -> None:
    assert "AC_COPILOT_SIDECAR_PORT" in SOURCE
    assert "AC_COPILOT_SIDECAR_EXTERNAL_BIND" in SOURCE
    assert 'new UriBuilder("ws", host, port, "/")' in SOURCE
    settings_reader = SOURCE.split("private Dictionary<string, object> ReadLauncherSettings()", 1)[
        1
    ].split("private async Task SendAsync", 1)[0]
    assert "AC_COPILOT_GAME_POINT_DIR" in settings_reader
    assert settings_reader.index("AC_COPILOT_GAME_POINT_DIR") < settings_reader.index(
        '"LOCALAPPDATA"'
    )
    assert '"AC Copilot Trainer"' in SOURCE
    assert '"GamePoint"' in SOURCE
    assert '"settings.json"' in SOURCE
    assert 'Value(settings, "sidecar_port")' in SOURCE
    assert 'Value(settings, "port")' not in SOURCE
    assert "File.ReadAllText(path)" in SOURCE
    hello_branch = SOURCE.split("if (!IsHelloAck(hello))", 1)[1].split(
        "sidecarConnected = true", 1
    )[0]
    assert "onConnected();" in hello_branch


def test_bridge_never_writes_or_reconfigures_simhub_profiles() -> None:
    assert "File.Write" not in SOURCE
    assert "X-AC-Copilot-Client" not in SOURCE
    assert "ShakeITBassShakersSettingsV2" not in SOURCE
    assert "AC_COPILOT_SIDECAR_TOKEN" in SOURCE
