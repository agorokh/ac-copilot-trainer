"""Unit tests for the per-repo ``repo:`` block loaders in hook_memory_manifest.

Covers the council #180 fix: code-dir classification moved out of code into
per-repo manifest data so propagation can't clobber child code dirs.
"""

from __future__ import annotations

from pathlib import Path

from tools.testing.script_imports import load_script_module

REPO_ROOT = Path(__file__).resolve().parents[1]

_manifest = load_script_module(
    "_test_hook_memory_manifest", REPO_ROOT / "scripts" / "hook_memory_manifest.py"
)
DEFAULT_CODE_DIR_TOP_LEVEL = _manifest.DEFAULT_CODE_DIR_TOP_LEVEL
DEFAULT_CODE_PATH_PREFIXES = _manifest.DEFAULT_CODE_PATH_PREFIXES
DEFAULT_CODE_PATH_TOP_LEVEL = _manifest.DEFAULT_CODE_PATH_TOP_LEVEL
load_repo_section = _manifest.load_repo_section
repo_code_dir_top_level = _manifest.repo_code_dir_top_level
repo_code_path_prefixes = _manifest.repo_code_path_prefixes
repo_code_path_top_level = _manifest.repo_code_path_top_level
repo_tier3_workspace_id = _manifest.repo_tier3_workspace_id

# ---------------------------------------------------------------------------
# load_repo_section
# ---------------------------------------------------------------------------


def test_load_repo_section_none_manifest() -> None:
    assert load_repo_section(None) == {}


def test_load_repo_section_non_dict_manifest() -> None:
    assert load_repo_section("hosts: []") == {}  # type: ignore[arg-type]


def test_load_repo_section_missing_block() -> None:
    assert load_repo_section({"hosts": []}) == {}


def test_load_repo_section_block_is_not_dict() -> None:
    assert load_repo_section({"repo": ["x"]}) == {}


def test_load_repo_section_returns_block() -> None:
    block = {"code_dirs": ["src"]}
    assert load_repo_section({"repo": block}) == block


# ---------------------------------------------------------------------------
# repo_code_path_prefixes
# ---------------------------------------------------------------------------


def test_code_path_prefixes_default_when_none() -> None:
    assert repo_code_path_prefixes(None) == DEFAULT_CODE_PATH_PREFIXES


def test_code_path_prefixes_default_when_absent() -> None:
    assert repo_code_path_prefixes({"hosts": []}) == DEFAULT_CODE_PATH_PREFIXES


def test_code_path_prefixes_default_when_empty_list() -> None:
    assert repo_code_path_prefixes({"repo": {"code_dirs": []}}) == DEFAULT_CODE_PATH_PREFIXES


def test_code_path_prefixes_normalizes_to_trailing_slash() -> None:
    out = repo_code_path_prefixes({"repo": {"code_dirs": ["src", "agent/", "core"]}})
    assert out == ("src/", "agent/", "core/")


def test_code_path_prefixes_strips_leading_slash() -> None:
    out = repo_code_path_prefixes({"repo": {"code_dirs": ["/scripts", "tests"]}})
    assert out == ("scripts/", "tests/")


def test_code_path_prefixes_skips_non_strings_and_empties() -> None:
    out = repo_code_path_prefixes({"repo": {"code_dirs": ["src", 42, None, "", "  ", "agent"]}})
    assert out == ("src/", "agent/")


# ---------------------------------------------------------------------------
# repo_code_path_top_level
# ---------------------------------------------------------------------------


def test_code_path_top_level_default_when_none() -> None:
    assert repo_code_path_top_level(None) == DEFAULT_CODE_PATH_TOP_LEVEL


def test_code_path_top_level_default_when_absent() -> None:
    assert repo_code_path_top_level({"repo": {}}) == DEFAULT_CODE_PATH_TOP_LEVEL


def test_code_path_top_level_uses_override() -> None:
    out = repo_code_path_top_level({"repo": {"code_top_level": ["Justfile", "Makefile"]}})
    assert out == frozenset({"Justfile", "Makefile"})


# ---------------------------------------------------------------------------
# repo_code_dir_top_level (derived from code_dirs first segments)
# ---------------------------------------------------------------------------


def test_code_dir_top_level_default_when_no_code_dirs() -> None:
    assert repo_code_dir_top_level(None) == DEFAULT_CODE_DIR_TOP_LEVEL


def test_code_dir_top_level_derives_first_segments() -> None:
    out = repo_code_dir_top_level(
        {"repo": {"code_dirs": ["src/foo", "agent", ".github/workflows"]}}
    )
    assert out == frozenset({"src", "agent", ".github"})


# ---------------------------------------------------------------------------
# repo_tier3_workspace_id
# ---------------------------------------------------------------------------


def test_tier3_workspace_id_none_when_absent() -> None:
    assert repo_tier3_workspace_id(None) is None
    assert repo_tier3_workspace_id({"repo": {}}) is None


def test_tier3_workspace_id_returns_value() -> None:
    out = repo_tier3_workspace_id({"repo": {"tier3_workspace_id": "agent_factory_steward"}})
    assert out == "agent_factory_steward"


def test_tier3_workspace_id_strips_whitespace() -> None:
    out = repo_tier3_workspace_id({"repo": {"tier3_workspace_id": "  ws  "}})
    assert out == "ws"


def test_tier3_workspace_id_ignores_empty_string() -> None:
    assert repo_tier3_workspace_id({"repo": {"tier3_workspace_id": "   "}}) is None
    assert repo_tier3_workspace_id({"repo": {"tier3_workspace_id": ""}}) is None


# ---------------------------------------------------------------------------
# resolve_workspace + repo.tier3_workspace_id integration
# (Kimi #180 council: workspace resolution is template-relative — must live in
# per-repo manifest data, not in copied gate logic.)
# ---------------------------------------------------------------------------


resolve_workspace = _manifest.resolve_workspace


def _manifest_with_workspaces(*names: str) -> dict:
    return {
        "hosts": [
            {
                "id": "h",
                "workspaces": [
                    {"name": n, "backend": "lightrag", "endpoint": f"http://x:80{i}"}
                    for i, n in enumerate(names)
                ],
            }
        ]
    }


def test_resolve_workspace_uses_tier3_workspace_id_over_basename(tmp_path: Path) -> None:
    """When ``repo.tier3_workspace_id`` is set, the resolver returns THAT
    workspace regardless of the repo basename — this is how template-repo
    routes to ``agent_factory_steward`` even though its directory is
    ``template-repo``."""
    root = tmp_path / "template-repo"
    root.mkdir()
    manifest = _manifest_with_workspaces("agent_factory_steward", "template_repo")
    manifest["repo"] = {"tier3_workspace_id": "agent_factory_steward"}
    out = resolve_workspace(root, manifest)
    assert out is not None
    assert out["name"] == "agent_factory_steward"


def test_resolve_workspace_returns_none_when_tier3_id_unknown(tmp_path: Path) -> None:
    """Declared but not in manifest → return None so SessionStart can surface
    the standard 'no workspace registered' warning. Better than silently
    falling back to a name match on a wrong workspace."""
    root = tmp_path / "anything"
    root.mkdir()
    manifest = _manifest_with_workspaces("only_one_ws")
    manifest["repo"] = {"tier3_workspace_id": "ghost_workspace_not_in_manifest"}
    assert resolve_workspace(root, manifest) is None


def test_resolve_workspace_falls_back_to_basename_when_no_tier3_id(tmp_path: Path) -> None:
    """Absent ``repo.tier3_workspace_id`` → existing basename-match logic fires."""
    root = tmp_path / "my_repo"
    root.mkdir()
    manifest = _manifest_with_workspaces("other_ws", "my_repo")
    assert resolve_workspace(root, manifest) is not None
    assert resolve_workspace(root, manifest)["name"] == "my_repo"


def test_resolve_workspace_tier3_id_hyphen_underscore_tolerant(tmp_path: Path) -> None:
    """``tier3_workspace_id: 'foo-bar'`` matches workspace ``foo_bar``."""
    root = tmp_path / "anything"
    root.mkdir()
    manifest = _manifest_with_workspaces("foo_bar", "other")
    manifest["repo"] = {"tier3_workspace_id": "foo-bar"}
    out = resolve_workspace(root, manifest)
    assert out is not None
    assert out["name"] == "foo_bar"


# ---------------------------------------------------------------------------
# PyYAML-fallback parser preserves the repo: block (Qodo PR #194 HIGH —
# without this, the per-repo override is silently dropped in hook runtimes
# that lack PyYAML, re-introducing the wave-introduced clobber regression).
# ---------------------------------------------------------------------------


_fallback_manifest_from_text = _manifest._fallback_manifest_from_text


def test_fallback_parser_preserves_repo_code_dirs_list() -> None:
    text = """\
repo:
  code_dirs:
    - "src"
    - "scripts"
    - "agent"
hosts: []
"""
    parsed = _fallback_manifest_from_text(text)
    assert parsed.get("repo", {}).get("code_dirs") == ["src", "scripts", "agent"]


def test_fallback_parser_preserves_repo_tier3_workspace_id_scalar() -> None:
    text = """\
repo:
  tier3_workspace_id: "agent_factory_steward"
hosts: []
"""
    parsed = _fallback_manifest_from_text(text)
    assert parsed.get("repo", {}).get("tier3_workspace_id") == "agent_factory_steward"


def test_fallback_parser_preserves_repo_with_mixed_keys() -> None:
    text = """\
repo:
  code_dirs:
    - "src"
    - "core"
  code_top_level:
    - "Justfile"
    - "Makefile"
  tier3_workspace_id: "my_workspace"
hosts:
  - id: h
    workspaces:
      - name: "my_workspace"
        endpoint: "http://x:80"
"""
    parsed = _fallback_manifest_from_text(text)
    assert parsed["repo"]["code_dirs"] == ["src", "core"]
    assert parsed["repo"]["code_top_level"] == ["Justfile", "Makefile"]
    assert parsed["repo"]["tier3_workspace_id"] == "my_workspace"
    # hosts/workspaces still parsed correctly.
    assert parsed["hosts"][0]["workspaces"][0]["name"] == "my_workspace"


def test_fallback_parser_no_repo_block_returns_no_repo_key() -> None:
    """Backward-compat: manifests without a repo: block don't grow one."""
    text = "hosts:\n  - id: h\n    workspaces: []\n"
    parsed = _fallback_manifest_from_text(text)
    assert "repo" not in parsed


def test_fallback_parser_repo_block_after_hosts() -> None:
    """Repo block can come after hosts (YAML key order is free)."""
    text = """\
hosts:
  - id: h
    workspaces:
      - name: "ws"
        endpoint: "http://x:80"
repo:
  tier3_workspace_id: "ws"
"""
    parsed = _fallback_manifest_from_text(text)
    assert parsed["repo"]["tier3_workspace_id"] == "ws"
    assert parsed["hosts"][0]["workspaces"][0]["name"] == "ws"
