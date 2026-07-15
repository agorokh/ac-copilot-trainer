"""Read-only access to Assetto Corsa car data in unpacked or ``data.acd`` form."""

from __future__ import annotations

import struct
from pathlib import Path

_ACD_DUMMY_LEADING = -1111


def acd_key(folder_name: str) -> str:
    """Derive the ACD obfuscation key string from the car folder name."""
    o = [ord(c) for c in folder_name]
    n = len(o)

    p1 = sum(o) & 0xFF

    p2 = 0
    i = 0
    while i < n - 1:
        p2 = p2 * o[i]
        i += 1
        p2 -= o[i]
        i += 1
    p2 &= 0xFF

    p3 = 0
    i = 1
    while i < n - 3:
        p3 *= o[i]
        i += 1
        p3 = -(abs(p3) // (o[i] + 0x1B)) if p3 < 0 else p3 // (o[i] + 0x1B)
        i -= 2
        p3 += -0x1B - o[i]
        i += 4
    p3 &= 0xFF

    p4 = 0x1683
    for value in o[1:]:
        p4 -= value
    p4 &= 0xFF

    p5 = 0x42
    i = 1
    while i < n - 4:
        p5 = (o[i - 1] + 0xF) * (p5 * (o[i] + 0xF)) + 0x16
        i += 4
    p5 &= 0xFF

    p6 = 0x65
    for value in o[: max(0, n - 2) : 2]:
        p6 -= value
    p6 &= 0xFF

    p7 = 0xAB
    for value in o[: max(0, n - 2) : 2]:
        p7 %= value
    p7 &= 0xFF

    p8 = 0xAB
    i = 0
    while i < n - 1:
        p8 //= o[i]
        i += 1
        p8 += o[i]
    p8 &= 0xFF

    return f"{p1}-{p2}-{p3}-{p4}-{p5}-{p6}-{p7}-{p8}"


def unpack_acd(data: bytes, folder_name: str) -> dict[str, bytes]:
    """De-obfuscate a raw ``data.acd`` blob into ``{filename: content_bytes}``."""
    key_ord = [ord(char) for char in acd_key(folder_name)]
    if not key_ord:
        raise ValueError("empty ACD key")

    files: dict[str, bytes] = {}
    pos = 0
    total = len(data)
    (lead,) = struct.unpack_from("<l", data, pos)
    if lead == _ACD_DUMMY_LEADING:
        pos += 8

    while pos < total:
        (name_len,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if name_len == 0 or pos + name_len > total:
            break
        name = data[pos : pos + name_len].decode("utf-8", "replace")
        pos += name_len

        (content_len,) = struct.unpack_from("<I", data, pos)
        pos += 4
        content_span = content_len * 4
        if pos + content_span > total:
            break

        out = bytearray(content_len)
        for index in range(content_len):
            low = data[pos + index * 4]
            out[index] = (low - key_ord[index % len(key_ord)]) & 0xFF
        pos += content_span
        files[name] = bytes(out)

    return files


class CarDataSource:
    """Lazy flat-member accessor for the data source Assetto Corsa will load.

    ``data.acd`` has precedence when present. Packed members are decoded at most once per accessor;
    unpacked files are read only when explicitly requested. Both forms expose the same root-level,
    case-insensitive contract, so nested packed entries cannot behave differently from ``data/``.
    """

    def __init__(self, car_dir: str | Path) -> None:
        self.car_dir = Path(car_dir)
        self._packed_loaded = False
        self._packed_members: dict[str, bytes] | None = None

    @staticmethod
    def _member_key(member_name: str) -> str | None:
        normalized = member_name.replace("\\", "/")
        if not normalized or "/" in normalized or normalized in (".", ".."):
            return None
        return normalized.lower()

    def read_member(self, member_name: str) -> bytes | None:
        """Read one flat member without falling back to an inactive data source."""
        try:
            wanted = self._member_key(member_name)
            if wanted is None:
                return None

            acd_path = self.car_dir / "data.acd"
            if acd_path.is_file():
                if not self._packed_loaded:
                    self._packed_loaded = True
                    self._packed_members = unpack_acd(acd_path.read_bytes(), self.car_dir.name)
                if self._packed_members is None:
                    return None
                for name, content in self._packed_members.items():
                    normalized = name.replace("\\", "/")
                    if "/" not in normalized and normalized.lower() == wanted:
                        return content
                return None

            data_dir = self.car_dir / "data"
            if data_dir.is_dir():
                for child in data_dir.iterdir():
                    if child.is_file() and child.name.lower() == wanted:
                        return child.read_bytes()
        except (OSError, TypeError, ValueError, struct.error, IndexError):
            return None
        return None


def read_car_data_member(car_dir: str | Path, member_name: str) -> bytes | None:
    """Read one flat member from the car data source Assetto Corsa will use.

    The lookup is case-insensitive, read-only, and returns ``None`` for a missing or malformed
    source/member. Nested archive paths never alias a root-level member.
    """
    try:
        return CarDataSource(car_dir).read_member(member_name)
    except (OSError, TypeError, ValueError, struct.error, IndexError):
        return None
    return None
