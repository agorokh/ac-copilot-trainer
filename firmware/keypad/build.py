"""Compile both provisional keypad variants and check HEX; never upload."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def verify_hex(path):
    addresses = set()
    base = 0
    eof = False
    for line in path.read_text().splitlines():
        if eof:
            raise ValueError("data after Intel HEX EOF")
        if not line.startswith(":"):
            raise ValueError("invalid Intel HEX prefix")
        record = bytes.fromhex(line[1:])
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise ValueError("invalid Intel HEX record/checksum")
        size, kind = record[0], record[3]
        offset = int.from_bytes(record[1:3], "big")
        data = record[4:-1]
        if kind == 0:
            for address in range(base + offset, base + offset + size):
                if address >= 0x3800:
                    raise ValueError("HEX crosses CH552 application/ROM boundary")
                if address in addresses:
                    raise ValueError("overlapping Intel HEX data")
                addresses.add(address)
        elif kind == 1 and not size and not offset:
            eof = True
        elif kind in (2, 4) and size == 2 and not offset:
            base = int.from_bytes(data, "big") << (4 if kind == 2 else 16)
        else:
            raise ValueError("unsupported Intel HEX record")
    if not eof or not addresses or 0 not in addresses:
        raise ValueError("incomplete Intel HEX application")
    return {
        "bytes": len(addresses),
        "maximum_address": f"0x{max(addresses):04x}",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arduino-cli", default="arduino-cli")
    parser.add_argument("--output", type=Path, default=Path(".scratch/keypad-build"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "Keypad.Firmware"
    command = [args.arduino_cli, "--config-file", str(source / "arduino-cli.yaml")]
    installed = json.loads(
        subprocess.check_output(command + ["core", "list", "--format", "json"], text=True)
    )
    platforms = installed.get("platforms", []) if isinstance(installed, dict) else installed
    if not any(
        p.get("id") == "CH55xDuino:mcs51" and p.get("installed_version") == "0.0.26"
        for p in platforms
    ):
        raise SystemExit("Install pinned CH55xDuino:mcs51@0.0.26 first (see README)")
    outputs = {}
    for name, managed in (("managed", 1), ("baseline", 0)):
        folder = args.output.resolve() / name
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            command
            + [
                "compile",
                "--fqbn",
                "CH55xDuino:mcs51:ch552:clock=16internal,usb_settings=user148",
                "--build-property",
                f"compiler.c.extra_flags=-DKEYPAD_MANAGED={managed}",
                "--build-property",
                f"compiler.cpp.extra_flags=-DKEYPAD_MANAGED={managed}",
                "--build-path",
                str(folder),
                str(source),
            ],
            check=True,
        )
        hex_file = folder / "Keypad.Firmware.ino.hex"
        details = verify_hex(hex_file)
        warning = folder / "DO-NOT-FLASH.txt"
        warning.write_text(
            "Provisional GPIO and silicon identity. Hardware acceptance and ROM recovery "
            "must be established before flash.\n"
        )
        outputs[name] = {"path": str(hex_file), **details}
    receipt = args.output / "build-receipt.json"
    receipt.write_text(
        json.dumps({"status": "DO-NOT-FLASH", "core": "0.0.26", "outputs": outputs}, indent=2)
        + "\n"
    )
    print(receipt.read_text())


if __name__ == "__main__":
    main()
