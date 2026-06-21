"""Vendored inference-egress client pin (governance-hub#75 / #78).

This PUBLIC repo cannot consume the PRIVATE governance-hub composite action the private governed
repos use, and `tools/process_miner/distill.py` HARD-imports `inference_egress` at import time. So
the canonical egress client is VENDORED into `.fleet-governance-vendor/runtime/inference_egress/`
(referenced by CI via `FLEET_GOVERNANCE_ROOT`) instead of checked out with a per-repo `GH_PAT`.

This pins the vendored files byte-identical to the hub canonical client — the pin IS the
reference-not-vendor drift gate (mirroring the hub's `check_egress_conformance.py` byte-check and
this repo's `test_public_governance_conformance.py` shim pin). The hub client was made
hostname-clean in governance-hub#78 specifically so it is safe to vendor into a PUBLIC repo; these
tests also guard that the PRIVATE sidecar (`dial_host.txt`, which carries the internal DIAL
hostname) never leaks here and that no internal hostname token returns.

PIN MAINTENANCE: update the CANONICAL_* hashes only when the hub
`runtime/inference_egress/{client.py,__init__.py}` legitimately changes (re-vendor from
governance-hub @ main, then update the pin). The values are PUBLIC file hashes, not credentials.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / ".fleet-governance-vendor" / "runtime" / "inference_egress"

CANONICAL_CLIENT_SHA256 = (
    "c116eedc744ae2a93334976dfbc7a885fa6e9d64cf46d6405222ddb9a9de5ff2"  # pragma: allowlist secret
)
CANONICAL_INIT_SHA256 = (
    "caef2793afce8f3db96f15115ab87532ed5747cf5f26225159246c18e4df57d1"  # pragma: allowlist secret
)
PINS = {"client.py": CANONICAL_CLIENT_SHA256, "__init__.py": CANONICAL_INIT_SHA256}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vendored_egress_files_present_and_pinned() -> None:
    """Both vendored files exist and are byte-identical to the pinned hub canonical client."""
    drift = []
    for name, pin in PINS.items():
        f = VENDOR_DIR / name
        assert f.is_file(), f"vendored {name} missing at {f.relative_to(REPO_ROOT)}"
        if _sha256(f) != pin:
            drift.append(
                f"{name}: {_sha256(f)[:16]} != pinned {pin[:16]} (drift from hub canonical)"
            )
    assert not drift, (
        "vendored egress client drifted from the hub canonical client — re-vendor from "
        "governance-hub @ main (or update the pin if the hub legitimately changed):\n  - "
        + "\n  - ".join(drift)
    )


def test_no_extra_files_vendored() -> None:
    """Only client.py + __init__.py are vendored. The PRIVATE hub sidecar `dial_host.txt` carries
    the internal DIAL hostname and must NOT reach this PUBLIC repo (governance-hub#78); its absence
    is also what keeps the vendored copy hostname-clean and the pins stable."""
    assert VENDOR_DIR.is_dir(), f"vendor dir missing: {VENDOR_DIR.relative_to(REPO_ROOT)}"
    present = sorted(p.name for p in VENDOR_DIR.iterdir() if p.is_file())
    assert present == ["__init__.py", "client.py"], (
        f"unexpected files in vendored egress dir: {present} — only client.py + __init__.py may be "
        "vendored; dial_host.txt (internal hostname) must stay in the private hub"
    )


def test_vendored_client_is_real_and_hostname_clean() -> None:
    """Load the vendored client.py standalone (no sys.path side effects) to confirm it is the real
    egress client AND that, with no sidecar present, it bakes in no default DIAL host (a public
    deployment configures `$DIAL_PROXY_HOST` if it ever needs DIAL)."""
    spec = importlib.util.spec_from_file_location(
        "_vendored_egress_client", VENDOR_DIR / "client.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for sym in ("resolve_api_key", "auth_headers", "is_dial_host", "request_headers"):
        assert hasattr(mod, sym), f"vendored client.py missing {sym}"
    assert mod.DIAL_PROXY_HOST_MARKER == "", (
        "vendored (public) copy must bake in no default DIAL host"
    )
