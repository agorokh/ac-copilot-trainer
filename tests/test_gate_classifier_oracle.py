"""Oracle / consumer-contract test for the gate classifier.

Kimi #180 council: the recurring design→propagate→walk-back loop happens
because a change to the gate's classifier (in scripts/) can silently break a
child repo's declared code_dirs (in ops/memory_manifest.yml). Bot review
catches it AFTER propagation. This oracle catches it BEFORE — at CI/merge.

How it works:
  * Load THIS repo's ops/memory_manifest.yml.
  * Extract declared `repo.code_dirs` / `repo.code_top_level` (or template
    defaults when absent).
  * Synthesize a sample path under each declared entry.
  * Assert the gate's `_classify` returns "code" for every sample.

If a future PR alters _classify in a way that breaks a declared dir, this
test fails with the specific declaration that no longer holds — the operator
sees exactly which contract was broken, immediately, not after bot review.

Cross-repo extension (Wave-2): a CI workflow can fetch each child's
manifest via gh and run the same oracle with the proposed gate code.
That closes the loop fleet-wide; this intra-repo version pins it for
THIS repo on every PR.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# #338 SHIM RECONCILIATION: when hook_memory_gate.py is a governance-hub shim, the classifier
# (`_classify`) lives in the hub, not in the thin delegator — the import below would fail and the
# oracle would exercise nothing local. The hub owns and re-runs this oracle for every spoke; skip.
if "governance shim" in (REPO_ROOT / "scripts" / "hook_memory_gate.py").read_text(encoding="utf-8"):
    pytest.skip(
        "hook_memory_gate.py is a governance-hub shim; classifier oracle lives in the hub.",
        allow_module_level=True,
    )

from hook_memory_gate import _classify  # noqa: E402
from hook_memory_manifest import (  # noqa: E402
    DEFAULT_CODE_PATH_PREFIXES,
    DEFAULT_CODE_PATH_TOP_LEVEL,
    load_manifest,
    oracle_classification_failures,
    repo_code_path_prefixes,
)


def test_oracle_repo_manifest_classifies_declared_dirs_as_code() -> None:
    """THIS repo's gate classifier must honor every dir/file declared in
    ops/memory_manifest.yml. The walk-back loop cure (Kimi #180)."""
    manifest = load_manifest(REPO_ROOT)
    failures = oracle_classification_failures(manifest, _classify, root=REPO_ROOT)
    assert failures == [], (
        "Gate classifier broke the manifest contract — "
        "either fix _classify or update ops/memory_manifest.yml.\n"
        + "\n".join(f"  * {f}" for f in failures)
    )


def test_oracle_failures_reported_when_classifier_drifts(tmp_path: Path) -> None:
    """Sanity-check the oracle itself: synthesize a divergence and confirm
    the oracle reports it (so a real regression actually fires)."""
    manifest = {"repo": {"code_dirs": ["completely_made_up_dir_name"]}}

    def _broken_classify(
        path: str, *, root, code_prefixes, code_top_level, code_dir_top_level
    ) -> str:
        # Deliberately doesn't honor the override → returns "other" always.
        return "other"

    failures = oracle_classification_failures(manifest, _broken_classify, root=tmp_path)
    assert failures, "oracle did not surface a broken classifier"
    assert any("completely_made_up_dir_name" in f for f in failures)


def test_template_defaults_classify_as_code() -> None:
    """Defensive: the gate's hardcoded fallback defaults must themselves all
    classify as code (a divergence here would mean defaults are unreachable
    via the classifier — silent gate-coverage gap)."""
    for prefix in DEFAULT_CODE_PATH_PREFIXES:
        sample = prefix + "x.py"
        assert _classify(sample) == "code", f"default prefix '{prefix}' not code"
    for top in DEFAULT_CODE_PATH_TOP_LEVEL:
        assert _classify(top) == "code", f"default top-level '{top}' not code"


def test_oracle_uses_manifest_overrides_not_module_defaults() -> None:
    """Pass an override manifest with a non-default dir; oracle must use that
    dir (not the module defaults). Ensures the oracle exercises the per-repo
    override path, not the fallback."""
    manifest = {"repo": {"code_dirs": ["my_runtime_pkg"]}}
    failures = oracle_classification_failures(manifest, _classify)
    # When override is honored, _classify('my_runtime_pkg/x.py', code_prefixes=('my_runtime_pkg/',))
    # returns 'code' → no failure.
    assert failures == [], failures
    # Also assert this actually changed the prefix set (not just same as defaults).
    assert repo_code_path_prefixes(manifest) == ("my_runtime_pkg/",)
