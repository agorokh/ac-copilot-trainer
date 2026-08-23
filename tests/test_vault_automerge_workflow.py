"""Regression guard for the template vault-automerge caller.

The scope guard and merge logic live in governance-hub's composite action. This
repo is the scaffold children inherit, so the local test pins the caller
contract instead of re-testing vendored shell internals here.

Bootstrap-aware (issue #537): only the template keeps both workflow files.
`scripts/copier_post_copy.py` deletes `vault-automerge-public.yml` in private
children and moves it over `vault-automerge.yml` in public children, and this
test module is copied into every child verbatim — so the assertions resolve
which variant actually exists instead of assuming the template layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/vault-automerge.yml"
PUBLIC_WORKFLOW = REPO_ROOT / ".github/workflows/vault-automerge-public.yml"
HUB_ACTION_REF = "f5d9a873dfe1a0893ecc6d2b77935ca27a2c2d0f"  # pragma: allowlist secret

# Copier renders `.copier-answers.yml` into every child (children pin the template
# via its `_src_path`; `copier.yml` `_exclude` keeps it out of the template tree).
# In the template the bootstrap skips below must never fire: a missing public
# variant or a reshaped thin caller there is corruption, not a child layout.
IS_TEMPLATE = not (REPO_ROOT / ".copier-answers.yml").exists()


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _doc() -> dict:
    return _load(WORKFLOW)


def _is_checkout_variant(doc: dict) -> bool:
    steps = doc["jobs"]["guard-and-automerge"]["steps"]
    return any(str(s.get("uses", "")).startswith("actions/checkout") for s in steps)


def _public_variant_path() -> Path | None:
    """Where the checkout-based public variant lives, if anywhere.

    Template: `vault-automerge-public.yml`. Public child: the copier moved it
    to `vault-automerge.yml`. Private child: deleted — no public variant.
    """
    if PUBLIC_WORKFLOW.exists():
        return PUBLIC_WORKFLOW
    if _is_checkout_variant(_doc()):
        return WORKFLOW
    return None


def _on_block(doc: dict) -> dict:
    # PyYAML follows YAML 1.1 and treats the key `on` as boolean True.
    return doc.get("on") or doc[True]


def _job(doc: dict) -> dict:
    return doc["jobs"]["guard-and-automerge"]


def _present_variants() -> list[Path]:
    # Both files exist in the template; exactly one (of either shape) in a child.
    # The core caller invariants below hold for every variant present on disk.
    return [WORKFLOW] + ([PUBLIC_WORKFLOW] if PUBLIC_WORKFLOW.exists() else [])


_each_variant = pytest.mark.parametrize("workflow_path", _present_variants(), ids=lambda p: p.name)


@_each_variant
def test_workflow_triggers_for_vault_pr_events(workflow_path: Path) -> None:
    pull_request = _on_block(_load(workflow_path))["pull_request"]
    assert pull_request["types"] == ["opened", "synchronize", "reopened", "labeled"]


@_each_variant
def test_workflow_has_per_pr_concurrency_guard(workflow_path: Path) -> None:
    conc = _load(workflow_path).get("concurrency")
    assert conc, f"{workflow_path.name} must declare a concurrency block (issue #238)"
    group = conc["group"] if isinstance(conc, dict) else conc
    assert "pull_request.number" in group, (
        "concurrency group must be keyed on the PR number so concurrent "
        f"opened+labeled events serialize per PR; got: {group!r}"
    )
    assert conc.get("cancel-in-progress") is False


@_each_variant
def test_workflow_gates_to_vault_only_same_repo_prs(workflow_path: Path) -> None:
    condition = _job(_load(workflow_path))["if"]
    assert "vault-only" in condition
    assert "github.event.pull_request.labels.*.name" in condition
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition


@pytest.mark.skipif(
    not IS_TEMPLATE and _is_checkout_variant(_doc()),
    reason="public child: vault-automerge.yml is the checkout-based public variant; "
    "hub-SHA pin coverage comes from the public-variant tests (issue #537)",
)
def test_workflow_is_thin_hub_action_caller() -> None:
    steps = _job(_doc())["steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["uses"] == (
        f"agorokh/governance-hub/.github/actions/vault-automerge@{HUB_ACTION_REF}"
    )
    assert "run" not in step
    assert step["with"] == {
        "github-token": "${{ github.token }}",
        "pr-number": "${{ github.event.pull_request.number }}",
        "repo": "${{ github.repository }}",
    }


@_each_variant
def test_workflow_permissions_are_minimal_for_action(workflow_path: Path) -> None:
    assert _load(workflow_path)["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }


_skip_without_public_variant = pytest.mark.skipif(
    not IS_TEMPLATE and _public_variant_path() is None,
    reason="private child: copier bootstrap deleted vault-automerge-public.yml (issue #537)",
)


def _public_doc() -> dict:
    path = _public_variant_path()
    assert path is not None, (
        "vault-automerge-public.yml is missing: the template must keep both variants "
        "(only bootstrapped children may lack the public one — issue #537)"
    )
    return _load(path)


@_skip_without_public_variant
def test_public_variant_pins_same_hub_action_ref() -> None:
    """The public-spoke variant fetches the action via `actions/checkout` and runs it
    from a local path (private cross-repo `uses:` cannot resolve — issue #329). Its
    checkout `ref:` MUST pin the SAME hub SHA as the private caller so both variants roll
    together; bumping one and forgetting the other is exactly the gov-hub#192 drift."""
    steps = _public_doc()["jobs"]["guard-and-automerge"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == HUB_ACTION_REF
    assert any(
        s.get("uses") == "./.governance-hub/.github/actions/vault-automerge" for s in steps
    ), "public variant must invoke the checked-out action via its local path"


@_skip_without_public_variant
def test_public_variant_timeout_exceeds_merge_wait() -> None:
    """timeout-minutes must exceed the action's synchronous merge-timeout-seconds
    (300s default) so the graceful timeout-comment path runs instead of a hard-kill."""
    assert _public_doc()["jobs"]["guard-and-automerge"]["timeout-minutes"] >= 6


@pytest.mark.skipif(not IS_TEMPLATE, reason="template-only integrity check (issue #537)")
def test_template_keeps_both_workflow_variants() -> None:
    """In the canonical template the bootstrap skips must never mask drift: both
    variant files exist, the private caller stays the thin single-`uses:` shape,
    and the public variant stays the checkout-based shape the copier moves."""
    assert PUBLIC_WORKFLOW.exists()
    assert not _is_checkout_variant(_doc())
    assert _is_checkout_variant(_load(PUBLIC_WORKFLOW))


# --- bootstrap layout resolution (issue #537) -------------------------------
# The copier deletes the public variant in private children and moves it over
# vault-automerge.yml in public children; this module ships into children
# verbatim, so the resolution logic above is itself contract and gets guarded.

_THIN_CALLER_YAML = f"""\
jobs:
  guard-and-automerge:
    steps:
      - uses: agorokh/governance-hub/.github/actions/vault-automerge@{HUB_ACTION_REF}
"""

_CHECKOUT_VARIANT_YAML = f"""\
jobs:
  guard-and-automerge:
    steps:
      - uses: actions/create-github-app-token@v3
      - uses: actions/checkout@v7
        with:
          ref: {HUB_ACTION_REF}
      - uses: ./.governance-hub/.github/actions/vault-automerge
"""


def _layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    main_yaml: str,
    public_yaml: str | None,
) -> tuple[Path, Path]:
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    main = wf_dir / "vault-automerge.yml"
    main.write_text(main_yaml, encoding="utf-8")
    public = wf_dir / "vault-automerge-public.yml"
    if public_yaml is not None:
        public.write_text(public_yaml, encoding="utf-8")
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "WORKFLOW", main)
    monkeypatch.setattr(module, "PUBLIC_WORKFLOW", public)
    return main, public


def test_template_layout_resolves_public_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, public = _layout(tmp_path, monkeypatch, _THIN_CALLER_YAML, _CHECKOUT_VARIANT_YAML)
    assert _public_variant_path() == public


def test_private_child_layout_has_no_public_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _layout(tmp_path, monkeypatch, _THIN_CALLER_YAML, None)
    assert _public_variant_path() is None
    assert not _is_checkout_variant(_doc())


def test_public_child_layout_resolves_moved_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, _ = _layout(tmp_path, monkeypatch, _CHECKOUT_VARIANT_YAML, None)
    assert _public_variant_path() == main
    assert _is_checkout_variant(_doc())
    checkout = next(
        s
        for s in _public_doc()["jobs"]["guard-and-automerge"]["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["ref"] == HUB_ACTION_REF
