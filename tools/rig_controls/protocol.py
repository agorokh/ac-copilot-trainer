"""Wire contract with the prepared CH55x firmware, never the stock keypad."""

from dataclasses import dataclass

VID, PID, USAGE_PAGE, USAGE = 0x1209, 0xC55D, 0xFF31, 1


def capability(packet: bytes) -> int:
    if len(packet) != 9 or packet[:4] != bytes([7, 65, 67, 1]) or packet[8] not in (0, 1):
        raise ValueError("keypad protocol capability mismatch")
    return packet[4]


def command(epoch: int, rgb: tuple[int, int, int]) -> bytes:
    return bytes([5, 1, epoch, *rgb, 30, 0, 0])


@dataclass(frozen=True)
class Report:
    kind: int
    epoch: int
    sequence: int = 0
    control: int = 0
    pressed: bool = False
    rgb: tuple[int, ...] = ()


def decode(packet: bytes) -> Report:
    if len(packet) != 9 or packet[1] != 1:
        raise ValueError("invalid keypad report size/version")
    if packet[0] == 4 and 1 <= packet[4] <= 6 and packet[5] in (0, 1) and not any(packet[6:]):
        if packet[4] in (4, 5) and packet[5] != 1:
            raise ValueError("rotation must be an impulse")
        return Report(4, packet[2], packet[3], packet[4], bool(packet[5]))
    if packet[0] == 6 and packet[6] == 1 and not any(packet[7:]):
        return Report(6, packet[2], rgb=tuple(packet[3:6]))
    raise ValueError("invalid keypad report contents")


def open_device():
    import hid

    candidates = [
        row
        for row in hid.enumerate(VID, PID)
        if row.get("usage_page") == USAGE_PAGE
        and row.get("usage") == USAGE
        and row.get("vendor_id") == VID
        and row.get("product_id") == PID
    ]
    if len(candidates) != 1:
        raise OSError(f"expected one prepared keypad, found {len(candidates)}")
    device = hid.device()
    try:
        device.open_path(candidates[0]["path"])
        capability(bytes(device.get_feature_report(7, 9)))
        return device
    except Exception:
        device.close()
        raise
