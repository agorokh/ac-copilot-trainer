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
    assert "Task.Run(() => RunAsync" in SOURCE
    assert "DataUpdate" in SOURCE
    data_update = SOURCE.split("public void DataUpdate", 1)[1].split("public void End", 1)[0]
    assert "ConnectAsync" not in data_update


def test_bridge_never_writes_or_reconfigures_simhub_profiles() -> None:
    assert "File.Write" not in SOURCE
    assert "ShakeITBassShakersSettingsV2" not in SOURCE
    assert "AC_COPILOT_SIDECAR_TOKEN" in SOURCE
