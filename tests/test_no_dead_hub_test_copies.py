# ruff: noqa: E501
# fmt: off
# HUB-OWNED. The canonical copy of this file is tests/test_no_dead_hub_test_copies.py in the
# governance hub. Every governed repo carries these exact bytes and the hub's conformance
# check compares them, so do not edit a copy: change the hub file and re-sync it.
# Repos use different line lengths, and one set of bytes has to pass in all of them. That
# is why this file opts out of the formatter and of the line-length rule above.
"""No test here may skip because its hook is a governance-hub shim.

The governed hooks in ``scripts/`` are shims that delegate to the hub, and conformance
requires them to stay shims. A local test that skips "when the hook is a shim" therefore
never runs in this repo. It cannot fail, so it drifts from the hub while still reading
like evidence. In one governed repo a skipped copy asserted the opposite of what the hub
does, and that wrong reading reached a contract document before anyone noticed.

The hub owns that behavior and its tests. Delete a copy, do not skip it.

What is still fine, and is not flagged: a smoke test that runs THROUGH the shim and skips
only when the hub is absent (``_IS_SHIM and not _hub_present()``, ``_shim_without_hub(SCRIPT)``).

How a skip is judged, in order:

1. By its CONDITION. The guard works out what a ``skipif`` condition, or the chain of ``if``
   tests around a ``pytest.skip``, does in the state this repo is normally in: the hook is a
   shim and the hub is installed. If the skip still fires there because of the shim, the test
   never runs here. ``_IS_SHIM or hub_present()`` fires. ``_IS_SHIM and not hub_present()``
   does not. Naming the hub is not enough; the condition has to depend on the hub being absent.
2. By its REASON. Text saying the "coverage lives in the hub" hands the coverage away,
   whatever the condition looks like. A ``pytest.mark.skip`` marker has no condition of its
   own, so beyond the ``if`` tests around it, its reason is what there is: handing coverage to
   the hub, or citing a governance shim.

pytest's and unittest's skips are read the same way, in every file pytest reads under
``tests/``: both test-file patterns, and ``conftest.py``.

These are name and wording checks. They catch the shape these copies were written in and
the obvious ways to write it again; they are a tripwire, not a proof.

Where the guard stops, on purpose. A flag with a neutral name is followed to its definition
only inside the same module, and only when that is a plain assignment or a function that
just returns an expression. A flag imported from another module, built up over several
statements, or a skip decided at runtime (an early ``return``, a collection hook) is not
followed. Catching those would take running the code, not reading it, and the thing this
guards against was never hidden: it was copied in plain sight.
"""

from __future__ import annotations

import ast
import itertools
import re
import warnings
from collections.abc import Iterator
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_SELF = Path(__file__).resolve()

_SHIM = re.compile(r"shim", re.I)
# The marker every governance shim carries, and the text these copies test for.
_GOVERNANCE_SHIM = re.compile(r"governance(?:-hub)?\s+shim", re.I)
_HUB = re.compile(r"hub", re.I)
# A hub name that says the hub is NOT there: ``_shim_without_hub``, ``hub_missing``, ``no_hub``.
_HUB_ABSENT = re.compile(
    r"without|absent|missing|unavailable|no_?hub|hub_?not|not_?installed", re.I
)
# "... coverage lives in the hub." / "coverage in hub." The coverage is somewhere else. A reason
# such as "coverage runs against the hub locally" is NOT this: that test still runs here.
_HANDOFF = re.compile(r"\bcoverage\s+(?:lives\s+)?in\s+(?:the\s+)?hub\b", re.I)

_NEGATING_OPS = (ast.NotIn, ast.NotEq, ast.IsNot)
_KNOWN = ("shim", "not-shim", "hub-present", "hub-absent")
# Unrelated checks in one condition (``os.name``, a platform flag). Each is tried both ways.
_MAX_UNRELATED = 6
# How many definitions a neutrally named flag is followed through before the guard gives up.
_MAX_TRACE = 4
# pytest's default ``python_files``, and conftest.py, where a skip can be applied to a whole
# directory.
_SCANNED = ("test_*.py", "*_test.py", "conftest.py")


def _dotted(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def _skip_shape(call: ast.Call) -> str | None:
    """How a call skips, or None when it does not.

    * ``"now"``: skips when reached. ``pytest.skip(...)``, ``self.skipTest(...)``.
    * ``"marker"``: skips whatever it is put on. ``pytest.mark.skip(...)``, ``unittest.skip(...)``.
    * ``"if"`` / ``"unless"``: skips on its first argument. ``pytest.mark.skipif``,
      ``unittest.skipIf``, ``unittest.skipUnless``.

    Matched on the end of the dotted name, so ``from pytest import mark, skip`` reads the same.
    """
    name = _dotted(call.func)
    if not name:
        return None
    if name[-1] in ("skipIf", "skipif") and (
        name[-1] == "skipIf" or name[-2:-1] in ((), ("mark",))
    ):
        return "if"
    if name[-1] == "skipUnless":
        return "unless"
    if name[-1] == "skipTest" or name in (("pytest", "skip"), ("skip",)):
        return "now"
    if name[-2:] == ("mark", "skip") or name == ("unittest", "skip"):
        return "marker"
    return None


def _strings(node: ast.AST) -> list[str]:
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _identifiers(node: ast.AST) -> list[str]:
    names: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.append(n.id)
        elif isinstance(n, ast.Attribute):
            names.append(n.attr)
    return names


def _mentions_shim(node: ast.AST) -> bool:
    return any(_SHIM.search(s) for s in [*_identifiers(node), *_strings(node)])


def _leaves(node: ast.AST) -> Iterator[ast.AST]:
    """The checks a condition is built from, under its ``and`` / ``or`` / ``not``."""
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _leaves(value)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yield from _leaves(node.operand)
    elif not isinstance(node, ast.Constant):
        yield node


def _kind(leaf: ast.AST) -> str:
    """What one check asks: about the shim, about the hub, or something unrelated.

    Only identifiers count for the hub, so the words "governance-hub" inside a string do not
    make a check a hub check. A hub name is read by its polarity: ``hub_present()`` and
    ``HUB.is_dir()`` say the hub is there, ``_shim_without_hub()`` says it is not. A hub check
    in any other shape (``HUB_ROOT is None``) is left as unrelated: the guard cannot tell
    which way it points.
    """
    identifiers = _identifiers(leaf)
    hub_names = [name for name in identifiers if _HUB.search(name)]
    if hub_names:
        if isinstance(leaf, ast.Name | ast.Attribute | ast.Call):
            return (
                "hub-absent"
                if any(_HUB_ABSENT.search(name) for name in hub_names)
                else "hub-present"
            )
        return ast.dump(leaf)
    if any(_SHIM.search(s) for s in [*identifiers, *_strings(leaf)]):
        negated = (
            isinstance(leaf, ast.Compare)
            and len(leaf.ops) == 1
            and isinstance(leaf.ops[0], _NEGATING_OPS)
        )
        return "not-shim" if negated else "shim"
    return ast.dump(leaf)


def _holds(node: ast.AST, *, shim: bool, unrelated: dict[str, bool]) -> bool:
    """The value of a condition WITH THE HUB INSTALLED, for a shim or a vendored hook."""
    if isinstance(node, ast.BoolOp):
        values = [
            _holds(value, shim=shim, unrelated=unrelated) for value in node.values
        ]
        return any(values) if isinstance(node.op, ast.Or) else all(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _holds(node.operand, shim=shim, unrelated=unrelated)
    if isinstance(node, ast.Constant):
        return bool(node.value)
    kind = _kind(node)
    if kind in ("shim", "not-shim"):
        return shim == (kind == "shim")
    if kind in ("hub-present", "hub-absent"):
        return kind == "hub-present"
    return unrelated[kind]


def _definitions(tree: ast.AST) -> dict[str, ast.AST]:
    """Names this module defines exactly once, as a plain expression.

    ``NAME = <expr>``, or a function whose body only returns ``<expr>``. A name defined twice,
    or any other way, is left out: the guard would be guessing which definition applies.
    """
    seen: dict[str, list[ast.AST | None]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            seen.setdefault(node.targets[0].id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            seen.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, ast.FunctionDef):
            body = [
                s
                for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            ]
            returned = (
                body[0].value
                if len(body) == 1 and isinstance(body[0], ast.Return)
                else None
            )
            seen.setdefault(node.name, []).append(returned)
    return {
        name: values[0]
        for name, values in seen.items()
        if len(values) == 1 and values[0] is not None
    }


def _without_bool_comparison(node: ast.AST) -> ast.AST:
    """``X is True`` and ``X != False`` are ``X``. ``X is False`` and ``X != True`` are ``not X``."""
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
        return node
    left, right, op = node.left, node.comparators[0], node.ops[0]
    if isinstance(right, ast.Constant) and isinstance(right.value, bool):
        subject, constant = left, right.value
    elif isinstance(left, ast.Constant) and isinstance(left.value, bool):
        subject, constant = right, left.value
    else:
        return node
    if isinstance(op, ast.Eq | ast.Is):
        agrees = constant
    elif isinstance(op, ast.NotEq | ast.IsNot):
        agrees = not constant
    else:
        return node
    return subject if agrees else ast.UnaryOp(op=ast.Not(), operand=subject)


def _expand(node: ast.AST, definitions: dict[str, ast.AST], depth: int = 0) -> ast.AST:
    """Replace a neutrally named check by what this module defines it as.

    ``SKIP_HOOK = _is_governance_hook()`` says nothing by its name. Followed to its
    definition, and that to the function's ``return "governance shim" in ...``, it is a shim
    check. A check whose own name already says what it asks is kept as it is.
    """
    node = _without_bool_comparison(node)
    if isinstance(node, ast.BoolOp):
        return ast.BoolOp(
            op=node.op,
            values=[_expand(value, definitions, depth) for value in node.values],
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return ast.UnaryOp(
            op=ast.Not(), operand=_expand(node.operand, definitions, depth)
        )
    if isinstance(node, ast.Constant) or depth >= _MAX_TRACE or _kind(node) in _KNOWN:
        return node
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
    else:
        return node
    defined = definitions.get(name)
    return node if defined is None else _expand(defined, definitions, depth + 1)


def _skips_because_of_the_shim(conditions: list[ast.AST]) -> bool:
    """True when a skip under ``conditions`` (all of them must hold) is a dead copy.

    Judged with the hub installed. There are two ways to be dead:

    * the skip fires whatever the unrelated checks say, in a condition that mentions a shim.
      The test never runs here (``_IS_SHIM``, ``_IS_SHIM or hub_present()``);
    * being a shim is what tips it. For some state of the unrelated checks the skip fires for
      a shim and would not for a vendored hook (``os.name == "posix" and _IS_SHIM``).

    ``_IS_SHIM and not hub_present()`` is neither: with the hub installed it never fires.
    """
    kinds = {_kind(leaf) for condition in conditions for leaf in _leaves(condition)}
    names = sorted(kinds.difference(_KNOWN))
    if len(names) > _MAX_UNRELATED:
        states = [dict.fromkeys(names, value) for value in (False, True)]
    else:
        states = [
            dict(zip(names, combo, strict=True))
            for combo in itertools.product((False, True), repeat=len(names))
        ]

    always, tipped = True, False
    for unrelated in states:
        as_shim = all(_holds(c, shim=True, unrelated=unrelated) for c in conditions)
        as_vendored = all(
            _holds(c, shim=False, unrelated=unrelated) for c in conditions
        )
        always = always and as_shim
        tipped = tipped or (as_shim and not as_vendored)
    return tipped or (always and any(_mentions_shim(c) for c in conditions))


def _skipif_condition(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "condition":
            return kw.value
    return None


class _Finder(ast.NodeVisitor):
    def __init__(
        self, *, condition_rules: bool, definitions: dict[str, ast.AST]
    ) -> None:
        self.hits: set[int] = set()
        # The ``if`` tests the visitor is inside. An ``else`` branch holds the test negated.
        self._guards: list[ast.AST] = []
        self._condition_rules = condition_rules
        self._definitions = definitions

    def _dead(self, conditions: list[ast.AST]) -> bool:
        if not (self._condition_rules and conditions):
            return False
        return _skips_because_of_the_shim(
            [_expand(c, self._definitions) for c in conditions]
        )

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self._guards.append(node.test)
        for stmt in node.body:
            self.visit(stmt)
        self._guards[-1] = ast.UnaryOp(op=ast.Not(), operand=node.test)
        for stmt in node.orelse:
            self.visit(stmt)
        self._guards.pop()

    def visit_Call(self, node: ast.Call) -> None:
        shape = _skip_shape(node)
        if shape is not None:
            reasons = _strings(node)
            # Whatever the call is, it only happens if the ``if`` tests around it hold.
            conditions = list(self._guards)
            own = _skipif_condition(node) if shape in ("if", "unless") else None
            if own is not None:
                conditions.append(
                    own if shape == "if" else ast.UnaryOp(op=ast.Not(), operand=own)
                )
            # A skip with no condition of its own and no ``if`` around it is unconditional: its
            # reason is the only account of it. Under an ``if`` the conditions decide, so a
            # marker applied only when the hub is absent may say "governance shim" freely.
            cites_shim = not conditions and any(
                _GOVERNANCE_SHIM.search(s) for s in reasons
            )
            if (
                any(_HANDOFF.search(s) for s in reasons)
                or cites_shim
                or self._dead(conditions)
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
    finder = _Finder(
        condition_rules=bool(_GOVERNANCE_SHIM.search(source)),
        definitions=_definitions(tree),
    )
    finder.visit(tree)
    return sorted(finder.hits)


def scanned_modules(root: Path) -> list[Path]:
    """Every file under ``root`` that pytest reads: both test-file patterns, and conftest.py."""
    return sorted(
        {path.resolve() for pattern in _SCANNED for path in root.rglob(pattern)}
    )


def test_no_test_skips_because_its_hook_is_a_hub_shim() -> None:
    findings: list[str] = []
    for path in scanned_modules(TESTS):
        if path == _SELF:
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


def test_guard_flags_an_unconditional_skip_marker() -> None:
    """``pytest.mark.skip`` has no condition, so it is judged by its reason."""
    source = (
        "import pytest\n"
        "pytestmark = pytest.mark.skip(reason='hook_x.py is a governance-hub shim')\n"
        "@pytest.mark.skip(reason='block/relax coverage lives in the hub')\n"
        "def test_a():\n"
        "    assert True\n"
        "@pytest.mark.parametrize('n', [pytest.param(1, marks=pytest.mark.skip('coverage in hub.'))])\n"
        "def test_b(n):\n"
        "    assert n\n"
        "@pytest.mark.skip(reason='needs a GPU')\n"
        "def test_c():\n"
        "    assert True\n"
    )
    assert dead_copy_findings(source) == [2, 3, 6]


def test_guard_flags_a_skip_marker_applied_under_a_shim_check() -> None:
    """A marker with a neutral reason is still dead when a shim check decides it is applied."""
    source = (
        "import pytest\n"
        "if _IS_SHIM:\n"
        "    pytestmark = pytest.mark.skip(reason='superseded elsewhere')\n"
        "if _IS_SHIM and not hub_present():\n"
        "    pytestmark = pytest.mark.skip(reason='no hub to delegate to')\n"
        "if _shim_without_hub(SCRIPT):\n"
        "    pytestmark = pytest.mark.skip(reason='hook_x.py is a governance-hub shim and the hub is not installed')\n"
    ) + _MARKER
    assert dead_copy_findings(source) == [3]


def test_guard_reads_unittest_skips_and_imported_names_the_same_way() -> None:
    source = (
        "import unittest\n"
        "from pytest import mark, skip\n"
        "class T(unittest.TestCase):\n"
        "    @unittest.skipIf(_IS_SHIM, 'x')\n"
        "    def test_a(self):\n"
        "        pass\n"
        "    @unittest.skipUnless(hub_missing() or not _IS_SHIM, 'x')\n"
        "    def test_b(self):\n"
        "        pass\n"
        "    def test_c(self):\n"
        "        if _IS_SHIM:\n"
        "            self.skipTest('x')\n"
        "@mark.skipif(_IS_SHIM, reason='x')\n"
        "def test_d():\n"
        "    skip('coverage lives in the hub')\n"
        "@unittest.skipUnless(hub_present(), 'needs the hub')\n"
        "def test_e():\n"
        "    if _IS_SHIM:\n"
        "        reader.skip(1)\n"  # not a test skip
    ) + _MARKER
    assert dead_copy_findings(source) == [4, 7, 12, 13, 15]


def test_guard_reads_a_comparison_with_true_or_false_as_the_flag_it_compares() -> None:
    source = (
        "import pytest\n"
        "_a = pytest.mark.skipif(_IS_SHIM != False, reason='x')\n"
        "_b = pytest.mark.skipif(_IS_SHIM is True, reason='x')\n"
        "_c = pytest.mark.skipif(_IS_SHIM is False, reason='vendored only')\n"
        "_d = pytest.mark.skipif(True != _IS_SHIM, reason='vendored only')\n"
        "_e = pytest.mark.skipif('governance shim' not in TEXT, reason='vendored only')\n"
    )
    assert dead_copy_findings(source) == [2, 3]


def test_guard_judges_an_unguarded_skip_by_its_reason_whoever_it_was_imported_from() -> (
    None
):
    source = (
        "from unittest import skip\n"
        "@skip('hook_x.py is a governance-hub shim')\n"
        "def test_a():\n"
        "    assert True\n"
        "def test_b():\n"
        "    skip('hook_x.py is a governance-hub shim')\n"
        "def test_c():\n"
        "    if _shim_without_hub():\n"
        "        skip('hook_x.py is a governance-hub shim and the hub is not installed')\n"
    )
    assert dead_copy_findings(source) == [2, 6]


def test_guard_follows_a_neutrally_named_flag_to_its_definition() -> None:
    source = (
        "import pytest\n"
        "def _is_governance_hook():\n"
        "    return 'governance shim' in SCRIPT.read_text()\n"
        "SKIP_HOOK = _is_governance_hook()\n"
        "QUIET = SKIP_HOOK and not hub_present()\n"
        "@pytest.mark.skipif(SKIP_HOOK, reason='central implementation')\n"
        "def test_a():\n"
        "    assert True\n"
        "@pytest.mark.skipif(QUIET, reason='no hub to delegate to')\n"  # fine: the hub is absent
        "def test_b():\n"
        "    assert True\n"
        "def test_c():\n"
        "    if not QUIET and SKIP_HOOK:\n"
        "        pytest.skip('central implementation')\n"
        "LOOP = LOOP_AGAIN\n"
        "LOOP_AGAIN = LOOP\n"
        "@pytest.mark.skipif(LOOP, reason='defined in a circle; the guard gives up, it does not hang')\n"
        "def test_d():\n"
        "    assert True\n"
    )
    assert dead_copy_findings(source) == [6, 14]


def test_guard_scans_every_file_pytest_reads(tmp_path: Path) -> None:
    for name in (
        "test_a.py",
        "b_test.py",
        "conftest.py",
        "helper.py",
        "unit/c_test.py",
        "unit/conftest.py",
    ):
        target = tmp_path / name
        target.parent.mkdir(exist_ok=True)
        target.write_text("", encoding="utf-8")
    found = [
        str(path.relative_to(tmp_path.resolve())) for path in scanned_modules(tmp_path)
    ]
    assert found == [
        "b_test.py",
        "conftest.py",
        "test_a.py",
        "unit/c_test.py",
        "unit/conftest.py",
    ]


def test_guard_flags_a_condition_that_names_the_hub_but_still_fires_with_it_installed() -> (
    None
):
    """Naming the hub does not excuse a condition. It has to depend on the hub being ABSENT."""
    source = (
        "import pytest\n"
        "_a = pytest.mark.skipif(_IS_SHIM or hub_present(), reason='x')\n"
        "_b = pytest.mark.skipif(_IS_SHIM and hub_present(), reason='x')\n"
        "_c = pytest.mark.skipif(_IS_SHIM and HUB.is_dir(), reason='x')\n"
        "_d = pytest.mark.skipif(not hub_missing() and _IS_SHIM, reason='x')\n"
        "if _IS_SHIM or _hub_present():\n"
        "    pytest.skip('x', allow_module_level=True)\n"
    ) + _MARKER
    assert dead_copy_findings(source) == [2, 3, 4, 5, 7]


def test_guard_reads_nested_and_else_conditions_together() -> None:
    source = (
        (
            "import os\n"
            "import pytest\n"
            "def _need_hub():\n"
            "    if _IS_SHIM:\n"
            "        if not hub_present():\n"
            "            pytest.skip('shim and no hub installed')\n"  # fine: the hub is absent
            "def test_a():\n"
            "    if os.name == 'posix':\n"
            "        if _IS_SHIM:\n"
            "            pytest.skip('x')\n"  # dead: the shim is what tips it
            "def test_b():\n"
            "    if not _IS_SHIM:\n"
            "        assert True\n"
            "    else:\n"
            "        pytest.skip('x')\n"  # dead: the else of "not a shim" is "a shim"
            "def test_c():\n"
            "    if _IS_SHIM and not hub_present():\n"
            "        pytest.skip('shim and no hub installed')\n"
            "    elif os.name != 'posix':\n"
            "        pytest.skip('POSIX only')\n"  # fine: unrelated to the shim
        )
        + _MARKER
    )
    assert dead_copy_findings(source) == [10, 15]


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
        "import os\n"
        "import pytest\n"
        "_skip_no_hub = pytest.mark.skipif(\n"
        "    IS_SHIM and not hub_present(),\n"
        "    reason='hook_x.py is a governance shim and the hub is not installed (fail-open).',\n"
        ")\n"
        "_skip_elsewhere = pytest.mark.skipif(os.name != 'posix' or _shim_without_hub(), reason='x')\n"
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
    """A repo can have other shims: a test for a CLI shim is written this way."""
    source = (
        "import pytest\n"
        "def _load_shim_module():\n"
        "    if not SHIM.exists():\n"
        "        pytest.skip(f'Hermes not installed at {SHIM}')\n"
        "def test_shim_adapts_event():\n"
        "    if USES_CLI_SHIM:\n"
        "        pytest.skip('covered by the CLI shim suite')\n"
    )
    assert dead_copy_findings(source) == []
    # "The shim is not there" is never "because it is a shim". The positive check is a
    # finding only once the module tests for a governance shim.
    assert dead_copy_findings(source + _MARKER) == [7]


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
