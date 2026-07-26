from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sidecar.car_class import (
    CarClassRegistry,
    CarClassRegistryError,
    classify_car,
    classify_metadata,
    load_registry,
    load_ui_metadata,
    resolve_installed_car,
)


def _registry(**overrides: str) -> CarClassRegistry:
    return CarClassRegistry(version=1, default_class="road", overrides=overrides)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"class": "race", "tags": ["singleSeater", "GP"]}, "formula"),
        ({"class": "race", "tags": ["LMP1", "prototype C"]}, "prototype"),
        ({"class": "street", "tags": ["#Hypercars", "road"]}, "hypercar"),
        ({"class": "race", "tags": ["DTM", "touring"]}, "touring"),
        ({"class": "drift", "tags": None}, "drift"),
        ({"class": "race", "tags": ["GT3", "race"]}, "gt"),
        ({"class": "race", "tags": []}, "race"),
        ({"class": "street", "tags": ["GT3 RS", "trackday"]}, "road"),
        ({"class": None, "tags": None, "specs": {"bhp": "500hp"}}, "road"),
        (None, "road"),
    ],
)
def test_classify_metadata_taxonomy(metadata: dict | None, expected: str) -> None:
    assert classify_metadata(metadata) == expected


def test_override_wins_with_differential_proof() -> None:
    metadata = {"class": "race", "tags": ["GT3", "race"]}
    baseline = classify_car("ks_porsche_911_gt3_r_2016", metadata, registry=_registry())
    enriched = classify_car(
        "ks_porsche_911_gt3_r_2016",
        metadata,
        registry=_registry(ks_porsche_911_gt3_r_2016="rear-engine-gt"),
    )

    assert baseline.car_class == "gt"
    assert baseline.source == "metadata"
    assert enriched.car_class == "rear-engine-gt"
    assert enriched.source == "override"


def test_override_ids_are_case_insensitive() -> None:
    resolution = classify_car(
        "KS_PORSCHE_911_GT3_R_2016",
        {"class": "race"},
        registry=_registry(ks_porsche_911_gt3_r_2016="rear-engine-gt"),
    )
    assert resolution.car_class == "rear-engine-gt"


def test_load_ui_metadata_accepts_bom_and_heterogeneous_specs(tmp_path: Path) -> None:
    ui = tmp_path / "content" / "cars" / "car_a" / "ui" / "ui_car.json"
    ui.parent.mkdir(parents=True)
    ui.write_text(
        "\ufeff"
        + json.dumps(
            {
                "class": "race",
                "tags": ["GT3"],
                "specs": {"bhp": "500hp", "range": 180, "optional": None},
            }
        ),
        encoding="utf-8",
    )
    assert load_ui_metadata("car_a", ac_root=tmp_path) == {
        "class": "race",
        "tags": ["GT3"],
        "specs": {"bhp": "500hp", "range": 180, "optional": None},
    }


def test_load_ui_metadata_repairs_ac_multiline_description(tmp_path: Path) -> None:
    ui = tmp_path / "content" / "cars" / "car_a" / "ui" / "ui_car.json"
    ui.parent.mkdir(parents=True)
    ui.write_text(
        '{\n"description":"first line\nsecond\tline",\n'
        '"class":"race","tags":["singleSeater"],"specs":{}}\n',
        encoding="utf-8",
    )
    metadata = load_ui_metadata("car_a", ac_root=tmp_path)
    assert metadata == {"class": "race", "tags": ["singleSeater"], "specs": {}}
    assert classify_metadata(metadata) == "formula"


@pytest.mark.parametrize("car_id", ["../escape", r"..\escape", "a/b", r"C:\cars\x", ".", "..", ""])
def test_unsafe_car_ids_never_read(car_id: str, tmp_path: Path) -> None:
    outside = tmp_path / "escape" / "ui" / "ui_car.json"
    outside.parent.mkdir(parents=True)
    outside.write_text('{"class":"race"}', encoding="utf-8")
    assert load_ui_metadata(car_id, ac_root=tmp_path) is None


@pytest.mark.parametrize("contents", ["not json", "[]", '{"class":'])
def test_missing_or_malformed_ui_defaults_to_road(contents: str, tmp_path: Path) -> None:
    ui = tmp_path / "content" / "cars" / "broken" / "ui" / "ui_car.json"
    ui.parent.mkdir(parents=True)
    ui.write_text(contents, encoding="utf-8")
    assert resolve_installed_car("broken", ac_root=tmp_path).car_class == "road"
    assert resolve_installed_car("broken", ac_root=tmp_path).source == "default"


def test_checked_in_registry_has_expected_authoritative_rows() -> None:
    registry = load_registry()
    assert registry.version == 1
    assert registry.overrides["ks_porsche_911_gt3_r_2016"] == "rear-engine-gt"
    assert registry.overrides["bmw_m3_gt2"] == "front-engine-gt"


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "default_class": "road", "overrides": {}},
        {"version": 1, "default_class": "spaceship", "overrides": {}},
        {"version": 1, "default_class": "road", "overrides": {"car": "spaceship"}},
    ],
)
def test_invalid_registry_rejected(tmp_path: Path, payload: dict) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CarClassRegistryError):
        load_registry(path)


def test_duplicate_registry_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"version":1,"default_class":"road","overrides":{"car":"road","car":"race"}}',
        encoding="utf-8",
    )
    with pytest.raises(CarClassRegistryError, match="duplicate registry key"):
        load_registry(path)
