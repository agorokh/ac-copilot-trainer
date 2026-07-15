"""Hermetic coverage for shared Assetto Corsa car-content access."""

from __future__ import annotations

import struct
from pathlib import Path

from tools.ac_content import CarDataSource, acd_key, read_car_data_member, unpack_acd


def _build_acd(folder_name: str, members: dict[str, bytes]) -> bytes:
    key_ord = [ord(char) for char in acd_key(folder_name)]
    blob = bytearray(struct.pack("<ll", -1111, 42))
    for name, content in members.items():
        name_bytes = name.encode()
        blob.extend(struct.pack("<I", len(name_bytes)))
        blob.extend(name_bytes)
        blob.extend(struct.pack("<I", len(content)))
        for index, value in enumerate(content):
            blob.extend(struct.pack("<I", (value + key_ord[index % len(key_ord)]) & 0xFF))
    return bytes(blob)


def test_acd_key_matches_known_stock_car_value() -> None:
    assert acd_key("bmw_m3_gt2") == "177-166-216-52-166-192-73-51"


def test_unpack_and_member_lookup_support_packed_source(tmp_path: Path) -> None:
    car_dir = tmp_path / "synth_car"
    car_dir.mkdir()
    lods = b"[LOD_0]\nFILE=synth_car.kn5\n"
    packed = _build_acd(car_dir.name, {"LoDs.InI": lods, "other.ini": b"ok"})
    (car_dir / "data.acd").write_bytes(packed)

    assert unpack_acd(packed, car_dir.name)["LoDs.InI"] == lods
    assert read_car_data_member(car_dir, "LODS.INI") == lods


def test_member_lookup_reads_unpacked_source_when_archive_is_absent(tmp_path: Path) -> None:
    car_dir = tmp_path / "unpacked_car"
    (car_dir / "data").mkdir(parents=True)
    expected = b"[LOD_0]\nFILE=unpacked_car.kn5\n"
    (car_dir / "data" / "LoDs.InI").write_bytes(expected)

    assert read_car_data_member(car_dir, "lods.ini") == expected


def test_unpacked_accessor_reads_only_requested_member(tmp_path: Path, monkeypatch) -> None:
    car_dir = tmp_path / "lazy_car"
    (car_dir / "data").mkdir(parents=True)
    (car_dir / "data" / "lods.ini").write_bytes(b"wanted")
    (car_dir / "data" / "large-unrelated.bin").write_bytes(b"unrelated")
    original_read_bytes = Path.read_bytes
    reads: list[str] = []

    def guarded_read_bytes(path: Path) -> bytes:
        reads.append(path.name)
        if path.name == "large-unrelated.bin":
            raise AssertionError("unrequested unpacked member was eagerly loaded")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    assert CarDataSource(car_dir).read_member("lods.ini") == b"wanted"
    assert reads == ["lods.ini"]


def test_member_lookup_prefers_packed_source_when_both_exist(tmp_path: Path) -> None:
    car_dir = tmp_path / "dual_source_car"
    (car_dir / "data").mkdir(parents=True)
    (car_dir / "data" / "lods.ini").write_bytes(b"unpacked")
    packed = _build_acd(car_dir.name, {"lods.ini": b"packed"})
    (car_dir / "data.acd").write_bytes(packed)

    assert read_car_data_member(car_dir, "lods.ini") == b"packed"


def test_nested_packed_member_does_not_alias_root_member(tmp_path: Path) -> None:
    car_dir = tmp_path / "nested_car"
    car_dir.mkdir()
    (car_dir / "data.acd").write_bytes(_build_acd(car_dir.name, {"nested/lods.ini": b"nested"}))

    assert read_car_data_member(car_dir, "lods.ini") is None


def test_member_lookup_rejects_paths_and_malformed_archives(tmp_path: Path) -> None:
    car_dir = tmp_path / "broken_car"
    car_dir.mkdir()
    (car_dir / "data.acd").write_bytes(b"bad")

    assert read_car_data_member(car_dir, "../lods.ini") is None
    assert read_car_data_member(car_dir, "nested/lods.ini") is None
    assert read_car_data_member(car_dir, "lods.ini") is None
