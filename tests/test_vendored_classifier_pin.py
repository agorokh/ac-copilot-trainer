"""Vendored PR-scope classifier pin (governance-hub#701).

The CI `build` job runs `make ci-vault` instead of `make ci-fast` for a PR whose every changed path
is under `docs/01_Vault/`. The rule that decides this lives once for the fleet, in governance-hub
`scripts/classify_pr_scope.py`. Private repos reach it through the hub's `classify-pr-scope`
action. This PUBLIC repo cannot resolve a private action, and `build` runs PR code, so it must not
mint a token to check the hub out. So the script is VENDORED into
`.fleet-governance-vendor/scripts/` and pinned byte-identical to the hub here, the same pattern as
the egress client (`tests/test_vendored_egress_pin.py`).

The pin is written twice on purpose: here, and in the `Classify PR scope` step of
`.github/workflows/ci.yml`. The workflow checks the file against its own copy BEFORE it trusts the
verdict, because the step runs the pull request's copy of the script. This test keeps the two
copies equal, and it is in `VAULT_TESTS`, so it runs on both the full path and the vault path.

PIN MAINTENANCE: re-vendor from governance-hub and update BOTH pins only when the hub
`scripts/classify_pr_scope.py` legitimately changes. The value is a public file hash, not a
credential.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / ".fleet-governance-vendor" / "scripts"
CLASSIFIER = VENDOR_DIR / "classify_pr_scope.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# governance-hub scripts/classify_pr_scope.py at abe6d6e0c8f66cd9be2b628cfdb7c16ed610ac62.
CANONICAL_CLASSIFIER_SHA256 = (
    "b6e9180e87d8b8c19670abf7c0cf10b49cfd7cc7b41a2461afceffeb6134ddc8"  # pragma: allowlist secret
)


def _sha256(path: Path) -> str:
    # The pin is against the LF-normalized canonical file in governance-hub.
    # Windows checkouts may materialize text files as CRLF.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _scope_step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    matches = [s for s in steps if s.get("id") == "scope"]
    assert len(matches) == 1, f"expected exactly one `scope` step in ci.yml, found {len(matches)}"
    return matches[0]


def test_vendored_classifier_present_and_pinned() -> None:
    rel = CLASSIFIER.relative_to(REPO_ROOT).as_posix()
    assert CLASSIFIER.is_file(), f"vendored classifier missing at {rel}"
    actual = _sha256(CLASSIFIER)
    assert actual == CANONICAL_CLASSIFIER_SHA256, (
        f"vendored classify_pr_scope.py drifted from the hub canonical script: {actual[:16]} != "
        f"pinned {CANONICAL_CLASSIFIER_SHA256[:16]}. Re-vendor from governance-hub, or update "
        "the pin here AND in .github/workflows/ci.yml if the hub legitimately changed."
    )


def test_workflow_pin_equals_this_pin() -> None:
    """The workflow refuses a classifier that does not match ITS pin. If the two pins drifted, a
    correct file would be refused (every vault PR runs the full build) or a wrong one accepted."""
    env = _scope_step().get("env") or {}
    assert env.get("CLASSIFIER_SHA256") == CANONICAL_CLASSIFIER_SHA256
    assert env.get("CLASSIFIER") == CLASSIFIER.relative_to(REPO_ROOT).as_posix()


def test_no_extra_files_beside_the_classifier() -> None:
    """Nothing else may sit in the vendored scripts directory. A module placed beside a script can
    shadow a standard-library import of that script. The workflow also runs the classifier in
    Python's isolated mode for the same reason; this is the second lock."""
    present = sorted(p.name for p in VENDOR_DIR.iterdir() if p.name != "__pycache__")
    assert present == ["classify_pr_scope.py"], (
        f"unexpected entries in {VENDOR_DIR.relative_to(REPO_ROOT).as_posix()}: {present}"
    )


def test_vendored_classifier_is_public_safe() -> None:
    """This file ships in a PUBLIC repository. It may talk to the GitHub API and nothing else, and
    it carries no address of a private host."""
    text = CLASSIFIER.read_text(encoding="utf-8")
    hosts = set(re.findall(r"https?://([^/\s\"'`]+)", text))
    assert hosts == {"api.github.com"}, f"unexpected hosts in the vendored classifier: {hosts}"
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text), "an IPv4 literal was vendored"
    assert not re.search(r"\.(?:local|lan|internal|ts\.net)\b", text), "a private hostname suffix"
