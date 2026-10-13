"""No test here may skip because its hook is a governance-hub shim.

The governed hooks in ``scripts/`` are shims that delegate to the hub, and conformance
requires them to stay shims. A local test that skips "when the hook is a shim" therefore
never runs in this repo. It cannot fail, so it drifts from the hub while still reading
like evidence. In one fleet repo a skipped copy asserted the opposite of what the hub
does, and that wrong reading reached a contract document before anyone noticed
(the fleet governance tracker).

The hub owns that behavior and its tests. Delete a copy, do not skip it.

What is still fine, and is not flagged: a smoke test that runs THROUGH the shim and skips
only when the hub is absent. Its condition asks about the hub as well as the shim
(``_IS_SHIM and not _hub_present()``, ``_shim_without_hub(SCRIPT)``).

How a skip is judged, in order:

1. By its CONDITION. A ``skipif`` condition, or the ``if`` around a ``pytest.skip``, that
   mentions a shim and nothing about the hub is "skip because it is a shim".
2. By its REASON. Text saying the "coverage lives in the hub" hands the coverage away,
   whatever the condition looks like.

Both are name and wording checks. They catch the shape these copies were written in and
the obvious ways to write it again; they are a tripwire, not a proof.
"""

from __future__ import annotations

import ast
import re
import warnings
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_SELF = Path(__file__).resolve()

_SHIM = re.compile(r"shim", re.I)
# The marker every governance shim carries, and the text these copies test for.
_GOVERNANCE_SHIM = re.compile(r"governance(?:-hub)?\s+shim", re.I)
_HUB = re.compile(r"hub", re.I)
# "... coverage lives in the hub." / "coverage in hub." The coverage is somewhere else. A reason
# such as "coverage runs against the hub locally" is NOT this: that test still runs here.
_HANDOFF = re.compile(r"\bcoverage\s+(?:lives\s+)?in\s+(?:the\s+)?hub\b", re.I)


def _is_pytest_call(node: ast.AST, *dotted: str) -> bool:
    """True for ``pytest.skip(...)`` / ``pytest.mark.skipif(...)`` style calls."""
    if not isinstance(node, ast.Call):
        return False
    parts: list[str] = []
    func: ast.AST = node.func
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return tuple(reversed(parts)) == ("pytest", *dotted)


def _strings(node: ast.AST) -> list[str]:
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _identifiers(node: ast.AST) -> list[str]:
    names: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.append(n.id)
        elif isinstance(n, ast.Attribute):
            names.append(n.attr)
    return names


def _is_shim_only_condition(cond: ast.AST) -> bool:
    """A condition about being a shim that asks nothing about the hub.

    ``_GATE_IS_SHIM`` and ``"governance shim" in SCRIPT.read_text()`` are shim-only.
    ``_IS_SHIM and not _hub_present()`` and ``_shim_without_hub()`` are not: they name the
    hub, so the test still runs whenever the hub is installed. Only identifiers count for
    the hub half, so the words "governance-hub" inside a string do not excuse a condition.
    """
    identifiers = _identifiers(cond)
    about_shim = any(_SHIM.search(s) for s in [*identifiers, *_strings(cond)])
    about_hub = any(_HUB.search(s) for s in identifiers)
    return about_shim and not about_hub


def _skipif_condition(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "condition":
            return kw.value
    return None


class _Finder(ast.NodeVisitor):
    def __init__(self, *, condition_rules: bool) -> None:
        self.hits: set[int] = set()
        self._shim_ifs = 0
        self._condition_rules = condition_rules

    def _shim_only(self, cond: ast.AST) -> bool:
        return self._condition_rules and _is_shim_only_condition(cond)

    def visit_If(self, node: ast.If) -> None:
        shim_only = self._shim_only(node.test)
        self.visit(node.test)
        self._shim_ifs += shim_only
        for stmt in node.body:
            self.visit(stmt)
        self._shim_ifs -= shim_only
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_pytest_call(node, "skip"):
            if self._shim_ifs or any(_HANDOFF.search(s) for s in _strings(node)):
                self.hits.add(node.lineno)
        elif _is_pytest_call(node, "mark", "skipif"):
            cond = _skipif_condition(node)
            if (cond is not None and self._shim_only(cond)) or any(
                _HANDOFF.search(s) for s in _strings(node)
            ):
                self.hits.add(node.lineno)
        self.generic_visit(node)


def dead_copy_findings(source: str) -> list[int]:
    with warnings.catch_warnings():
        # Parsing another test's source can surface ITS SyntaxWarning (an invalid escape in a
        # regex literal, say). That is not this guard's finding.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    # Condition rules apply only where the module tests for a GOVERNANCE shim. Other things
    # are called shims too (a CLI shim, say); a condition naming one is not our case.
    finder = _Finder(condition_rules=bool(_GOVERNANCE_SHIM.search(source)))
    finder.visit(tree)
    return sorted(finder.hits)


def test_no_test_skips_because_its_hook_is_a_hub_shim() -> None:
    findings: list[str] = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if path.resolve() == _SELF:
            continue
        for line in dead_copy_findings(path.read_text(encoding="utf-8")):
            findings.append(f"{path.relative_to(TESTS.parent)}:{line}")
    assert not findings, (
        "these tests skip because the hook under test is a governance-hub shim, so they never "
        "run here and will drift from the hub. Delete the copy; the hub owns that coverage "
        f"{findings}"
    )


# Appended to a sample module so the condition rules are in force: it is the line a real
# copy uses to find out whether its hook is a governance shim.
_MARKER = "_IS_SHIM = 'governance shim' in SCRIPT.read_text()\n"


def test_guard_flags_a_module_level_shim_skip() -> None:
    source = (
        "import pytest\n"
        "SCRIPT = 'scripts/hook_x.py'\n"
        "if 'governance shim' in open(SCRIPT).read():\n"
        "    pytest.skip('whatever the reason says', allow_module_level=True)\n"
    )
    assert dead_copy_findings(source) == [4]


def test_guard_flags_a_skipif_on_a_shim_flag_whatever_the_reason_says() -> None:
    source = (
        "import pytest\n"
        "@pytest.mark.skipif(\n"
        "    _PREFETCH_IS_SHIM,\n"
        "    reason='superseded by a stricter check elsewhere',\n"
        ")\n"
        "def test_a():\n"
        "    assert True\n"
    ) + _MARKER
    assert dead_copy_findings(source) == [2]


def test_guard_flags_a_skipif_on_several_shim_flags() -> None:
    source = (
        "import pytest\n"
        "_skip = pytest.mark.skipif(\n"
        "    _GATE_IS_SHIM or _START_IS_SHIM,\n"
        "    reason='stale-gate/steward are governance-hub shims; A-D behavior coverage "
        "lives in the hub.',\n"
        ")\n"
    )
    assert dead_copy_findings(source) == [2]


def test_guard_flags_a_skip_inside_a_helper_guarded_by_a_shim_flag() -> None:
    source = (
        "import pytest\n"
        "def _load():\n"
        "    if _STEWARD_IS_SHIM:\n"
        "        pytest.skip('nothing to import here')\n"
        "    return 1\n"
    ) + _MARKER
    assert dead_copy_findings(source) == [4]


def test_guard_flags_a_skip_whose_reason_hands_coverage_to_the_hub() -> None:
    source = (
        "import pytest\n"
        "def test_a():\n"
        "    pytest.skip('protect-main behavior coverage lives in the hub (revised policy)')\n"
        "def test_b():\n"
        "    pytest.skip('#246 block/relax coverage in hub.')\n"
    )
    assert dead_copy_findings(source) == [3, 5]


def test_guard_leaves_alone_a_reason_that_says_the_test_runs_against_the_hub() -> None:
    """Wording close to the handoff, opposite meaning: this test runs when the hub is there."""
    source = (
        "import pytest\n"
        "pytestmark = pytest.mark.skipif(\n"
        "    _shim_without_hub(SCRIPT),\n"
        "    reason='hook_x.py is a governance shim and the hub is not installed; '\n"
        "    'behavior coverage runs against the hub locally / via make governance-proof.',\n"
        ")\n"
    )
    assert dead_copy_findings(source) == []


def test_guard_leaves_a_hub_absent_smoke_test_alone() -> None:
    """Runs through the shim; skips only when there is no hub to delegate to."""
    source = (
        "import pytest\n"
        "_skip_no_hub = pytest.mark.skipif(\n"
        "    IS_SHIM and not hub_present(),\n"
        "    reason='hook_x.py is a governance shim and the hub is not installed (fail-open).',\n"
        ")\n"
        "if _shim_without_hub():\n"
        "    pytest.skip('shim and no hub installed', allow_module_level=True)\n"
        "@_skip_no_hub\n"
        "def test_smoke():\n"
        "    assert True\n"
    ) + _MARKER
    assert dead_copy_findings(source) == []


def test_guard_does_not_flag_the_else_branch_of_a_shim_check() -> None:
    source = (
        "import pytest\n"
        "def test_a():\n"
        "    if IS_SHIM:\n"
        "        assert True\n"
        "    else:\n"
        "        pytest.skip('vendored copy; nothing to check')\n"
    ) + _MARKER
    assert dead_copy_findings(source) == []


def test_guard_ignores_a_shim_that_is_not_a_governance_shim() -> None:
    """A repo can have other shims. hermescraft tests a Gemini CLI shim this way."""
    source = (
        "import pytest\n"
        "def _load_shim_module():\n"
        "    if not SHIM.exists():\n"
        "        pytest.skip(f'Hermes not installed at {SHIM}')\n"
        "def test_shim_adapts_event():\n"
        "    if not LIVE_SHIM_TEST:\n"
        "        pytest.skip('set HERMES_GEMINI_SHIM_LIVE_TEST=1 to run')\n"
    )
    assert dead_copy_findings(source) == []
    # The same conditions ARE findings once the module tests for a governance shim.
    assert dead_copy_findings(source + _MARKER) == [4, 7]


def test_guard_leaves_unrelated_skips_alone() -> None:
    source = (
        "import os\n"
        "import pytest\n"
        "if os.name != 'posix':\n"
        "    pytest.skip('POSIX only', allow_module_level=True)\n"
        "def test_a():\n"
        "    pytest.skip('FLEET_GOVERNANCE_ROOT unset; equality is enforced on the hub')\n"
    )
    assert dead_copy_findings(source) == []
