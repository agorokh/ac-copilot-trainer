"""The CI vault fast path stays fail-closed (governance-hub#701).

A PR whose every changed path is under ``docs/01_Vault/`` runs ``make ci-vault`` instead of
``make ci-fast``. The scope rule is the fleet's (governance-hub ``scripts/classify_pr_scope.py``,
tested there, vendored and pinned here by ``tests/test_vendored_classifier_pin.py``). This repo
owns the wiring, and the wiring has two dangerous shapes:

* neither branch runs, so a ``build`` goes green having checked nothing. The structural tests pin
  that every step gated on the scope output uses one of two exact conditions that are
  complementary by construction, and that a missing output selects the full build.
* the scope step runs the pull request's copy of the classifier (a vendored script lives in the
  workspace, so the step comes after checkout). The behaviour tests run the step's real shell
  script against a planted classifier, a planted shadow module, a missing interpreter and a dying
  classifier, and require ``full-build=true`` every time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
MAKEFILE = REPO_ROOT / "Makefile"
CLASSIFIER_REL = ".fleet-governance-vendor/scripts/classify_pr_scope.py"

FULL_BUILD = "steps.scope.outputs.full-build != 'false'"
VAULT_ONLY = "steps.scope.outputs.full-build == 'false'"
HEAD_SHA = "a" * 40

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or BASH is None,
    reason="runs the workflow step's bash script; CI (ubuntu) always runs it",
)


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job() -> dict:
    return _doc()["jobs"]["build"]


def _steps() -> list[dict]:
    return _job()["steps"]


def _index(steps: list[dict], name: str) -> int:
    matches = [i for i, s in enumerate(steps) if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}, found {len(matches)}"
    return matches[0]


def _scope() -> dict:
    steps = _steps()
    return steps[_index(steps, "Classify PR scope")]


def _make_targets(steps: list[dict]) -> dict[str, dict]:
    """``make <target>`` -> the step that runs it."""
    out: dict[str, dict] = {}
    for step in steps:
        for target in re.findall(r"\bmake\s+(ci-[a-z-]+)", str(step.get("run", ""))):
            assert target not in out, f"`make {target}` runs in more than one step"
            out[target] = step
    return out


# --- structure -------------------------------------------------------------------------------


def test_scope_step_runs_the_vendored_classifier_ungated() -> None:
    scope = _scope()
    assert scope["id"] == "scope"
    assert "if" not in scope, "the scope step must run on every event; it decides, it is not gated"
    assert "uses" not in scope, "a public repo cannot resolve the private hub action"
    assert scope.get("shell") == "bash"
    assert scope["env"]["CLASSIFIER"] == CLASSIFIER_REL
    assert re.fullmatch(r"[0-9a-f]{64}", scope["env"]["CLASSIFIER_SHA256"])
    run = scope["run"]
    # Isolated mode keeps the script's directory and the workspace off sys.path.
    assert '"$py" -I "$CLASSIFIER"' in run
    assert '"$candidate" -I -c' in run
    # Every interpreter call in the step runs isolated.
    calls = re.findall(r'(?:^\s*|\$\(|!\s+)"\$py"\s+(\S+)', run, flags=re.MULTILINE)
    assert len(calls) >= 2 and set(calls) == {"-I"}, calls


def test_no_pr_controlled_code_runs_before_the_scope_step() -> None:
    """The classifier is trusted because nothing from the pull request has executed yet. So the
    only steps ahead of it are the head-branch guard (an inline script that touches no file) and
    the checkout itself."""
    steps = _steps()
    scope_at = _index(steps, "Classify PR scope")
    before = steps[:scope_at]
    assert [s.get("name") or s.get("uses", "").split("@")[0] for s in before] == [
        "Reject PRs whose head branch is main",
        "actions/checkout",
    ], "a step was inserted ahead of the scope step; it must not run or install PR code"
    for step in before:
        assert not re.search(r"\b(make|pip|python3?|bash|sh)\b", str(step.get("run", "")))


def test_job_can_read_the_pr_file_list_and_nothing_more() -> None:
    assert _job()["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_token_reaches_the_scope_step_only() -> None:
    assert _scope()["env"]["GH_TOKEN"] == "${{ github.token }}"
    job = _job()
    others = [s for s in job["steps"] if s.get("id") != "scope"]
    blob = json.dumps([others, job.get("env", {}), _doc().get("env", {})])
    for needle in ("github.token", "secrets.", "GH_TOKEN", "GITHUB_TOKEN"):
        assert needle not in blob, f"{needle!r} is exposed outside the scope step"


def test_every_scope_gate_is_one_of_the_two_exact_conditions() -> None:
    steps = _steps()
    scope_at = _index(steps, "Classify PR scope")
    gated = 0
    for i, step in enumerate(steps):
        cond = str(step.get("if", ""))
        if "steps.scope" not in cond:
            continue
        gated += 1
        assert i > scope_at, f"{step.get('name')!r} reads the scope output before the scope step"
        assert cond in (FULL_BUILD, VAULT_ONLY), (
            f"{step.get('name')!r} gates on {cond!r}; only {FULL_BUILD!r} and {VAULT_ONLY!r} are "
            "allowed, so a missing or unexpected output always selects the full build"
        )
    assert gated >= 2


def test_exactly_one_of_ci_fast_and_ci_vault_runs() -> None:
    targets = _make_targets(_steps())
    assert targets["ci-fast"].get("if") == FULL_BUILD
    assert targets["ci-vault"].get("if") == VAULT_ONLY


def test_both_paths_install_before_their_make() -> None:
    """A vault test that cannot import a dependency SKIPS, it does not fail. So each path must have
    an install ahead of its make step: one ungated install, or one per exact condition."""
    steps = _steps()
    targets = _make_targets(steps)
    installs = [(i, s) for i, s in enumerate(steps) if "pip install" in str(s.get("run", ""))]
    assert installs, "no install step"
    for target, cond in (("ci-fast", FULL_BUILD), ("ci-vault", VAULT_ONLY)):
        make_at = steps.index(targets[target])
        covering = [i for i, s in installs if s.get("if") in (None, cond) and i < make_at]
        assert covering, f"no install step runs before `make {target}` on its path"


def test_vault_tests_exist_and_ci_vault_keeps_its_prerequisites() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    block = re.search(r"^VAULT_TESTS\s*=\s*((?:.*\\\n)*.*)$", text, flags=re.MULTILINE)
    assert block, "Makefile has no VAULT_TESTS list"
    paths = block.group(1).replace("\\\n", " ").split()
    assert paths, "VAULT_TESTS is empty"
    missing = [p for p in paths if not (REPO_ROOT / p).is_file()]
    assert not missing, f"VAULT_TESTS names files that do not exist: {missing}"
    # A PR that edits the vendored classifier must fail the pin on whichever path it takes.
    assert "tests/test_vendored_classifier_pin.py" in paths
    rule = re.search(r"^ci-vault:(.*)\n((?:\t.*\n)+)", text, flags=re.MULTILINE)
    assert rule, "Makefile has no ci-vault target with a recipe"
    # The recipe must actually run the list: prerequisites alone would leave the vault tests out.
    assert re.search(r"-m pytest\b.*\$\(VAULT_TESTS\)", rule.group(2)), (
        f"the ci-vault recipe does not run pytest on $(VAULT_TESTS): {rule.group(2)!r}"
    )
    prereqs = set(rule.group(1).split())
    # The branch/title policy applies to every PR; the secret scan reads every tracked vault note;
    # the canonical-docs check requires docs/01_Vault/00_Graph_Schema.md to exist.
    assert {"ci-conventional", "ci-secrets", "ci-policy"} <= prereqs
    fast = re.search(r"^ci-fast:(.*)$", text, flags=re.MULTILINE)
    assert fast, "Makefile has no ci-fast target"
    assert prereqs <= set(fast.group(1).split()), "ci-vault runs a check that ci-fast does not"


# --- behaviour of the scope step's own script ---------------------------------------------------


class _Api(BaseHTTPRequestHandler):
    files: list[dict] = []

    def do_GET(self) -> None:
        if self.path == "/repos/o/r/pulls/7":
            body: object = {"head": {"sha": HEAD_SHA}}
        elif self.path.startswith("/repos/o/r/pulls/7/files?"):
            body = type(self).files if "page=1" in self.path.split("&") else []
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def api() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        _Api.files = []


def _workspace(tmp_path: Path, classifier: str | None) -> Path:
    ws = tmp_path / "ws"
    target = ws / CLASSIFIER_REL
    target.parent.mkdir(parents=True)
    if classifier is not None:
        target.write_text(classifier, encoding="utf-8", newline="\n")
    return ws


def _real_classifier() -> str:
    return (REPO_ROOT / CLASSIFIER_REL).read_text(encoding="utf-8")


def _planted(marker: Path, *, exit_code: int = 0) -> str:
    """A classifier a hostile PR would ship: it claims vault-only and leaves a marker if it ran."""
    return (
        "import os, sys\n"
        f"open({str(marker)!r}, 'w').close()\n"
        "with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:\n"
        "    fh.write('reason=planted\\nfull-build=false\\n')\n"
        f"sys.exit({exit_code})\n"
    )


def _run_step(
    tmp_path: Path,
    ws: Path,
    *,
    event_name: str = "pull_request",
    api_url: str = "http://127.0.0.1:9",
    pin: str | None = None,
    interpreter: bool = True,
) -> dict[str, str]:
    """Run the scope step's script the way the runner does. Returns the step's final outputs."""
    scope = _scope()
    script = tmp_path / "step.sh"
    script.write_text(scope["run"], encoding="utf-8", newline="\n")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if interpreter:
        shim = bindir / "python3"
        shim.write_text(f'#!{BASH}\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {"number": 7, "head": {"sha": HEAD_SHA}},
                "repository": {"full_name": "o/r"},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    env = {
        "PATH": str(bindir),
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_API_URL": api_url,
        "GITHUB_REPOSITORY": "o/r",
        "GH_TOKEN": "not-a-real-token",  # pragma: allowlist secret
        "CLASSIFIER": scope["env"]["CLASSIFIER"],
        "CLASSIFIER_SHA256": pin or scope["env"]["CLASSIFIER_SHA256"],
        "no_proxy": "*",
        # A hostile job environment must not be able to redirect the interpreter's imports.
        "PYTHONPATH": str(ws / ".fleet-governance-vendor" / "scripts"),
    }
    assert BASH is not None
    done = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, f"the scope step must never fail the job: {done.stderr}"
    outputs: dict[str, str] = {}
    for line in output.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            outputs[key] = value  # the runner keeps the LAST assignment
    return outputs


@needs_bash
def test_step_reports_vault_only_for_a_proven_vault_pr(tmp_path: Path, api: str) -> None:
    _Api.files = [
        {"filename": "docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md"},
        {"filename": "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-04-x.md"},
    ]
    out = _run_step(tmp_path, _workspace(tmp_path, _real_classifier()), api_url=api)
    assert out == {"reason": "every changed path is under docs/01_Vault/", "full-build": "false"}


@needs_bash
def test_step_reports_full_build_for_a_code_pr(tmp_path: Path, api: str) -> None:
    _Api.files = [
        {"filename": "docs/01_Vault/AcCopilotTrainer/x.md"},
        {"filename": "Makefile"},
    ]
    out = _run_step(tmp_path, _workspace(tmp_path, _real_classifier()), api_url=api)
    assert out["full-build"] == "true"


@needs_bash
def test_step_reports_full_build_when_code_is_renamed_into_the_vault(
    tmp_path: Path, api: str
) -> None:
    _Api.files = [
        {"filename": "docs/01_Vault/AcCopilotTrainer/x.md", "previous_filename": "src/x.py"}
    ]
    out = _run_step(tmp_path, _workspace(tmp_path, _real_classifier()), api_url=api)
    assert out["full-build"] == "true"


@needs_bash
def test_step_reports_full_build_when_the_file_list_is_unreadable(tmp_path: Path) -> None:
    out = _run_step(tmp_path, _workspace(tmp_path, _real_classifier()))  # nothing listens on :9
    assert out["full-build"] == "true"


@needs_bash
def test_step_reports_full_build_on_push(tmp_path: Path, api: str) -> None:
    _Api.files = [{"filename": "docs/01_Vault/AcCopilotTrainer/x.md"}]
    ws = _workspace(tmp_path, _real_classifier())
    out = _run_step(tmp_path, ws, event_name="push", api_url=api)
    assert out == {"reason": "not a pull_request event", "full-build": "true"}


@needs_bash
def test_step_refuses_a_classifier_that_does_not_match_the_pin(tmp_path: Path) -> None:
    marker = tmp_path / "planted-ran"
    out = _run_step(tmp_path, _workspace(tmp_path, _planted(marker)))
    assert out == {"reason": "vendored classifier does not match its pin", "full-build": "true"}
    assert not marker.exists(), "the step executed a classifier that failed its pin"


@needs_bash
def test_step_ignores_a_module_planted_beside_the_classifier(tmp_path: Path, api: str) -> None:
    """The pinned file is untouched, but `argparse.py` next to it would be imported in its place
    by a plain `python script.py` (the script's directory leads sys.path)."""
    _Api.files = [{"filename": "src/x.py"}]
    ws = _workspace(tmp_path, _real_classifier())
    marker = tmp_path / "shadow-ran"
    # The step's environment in this test also carries a PYTHONPATH that names that directory.
    for module in ("argparse", "json", "re", "urllib", "dataclasses", "typing", "sitecustomize"):
        for directory in ((ws / CLASSIFIER_REL).parent, ws):
            (directory / f"{module}.py").write_text(_planted(marker), encoding="utf-8")
    out = _run_step(tmp_path, ws, api_url=api)
    assert out["full-build"] == "true"
    assert out["reason"] == "1 changed path(s) outside docs/01_Vault/"
    assert not marker.exists(), "a module planted in the workspace was imported"


@needs_bash
def test_step_overrides_a_classifier_that_dies_after_claiming_vault_only(tmp_path: Path) -> None:
    """The last assignment wins. A classifier that wrote `full-build=false` and then exited
    non-zero must still end as a full build (the pin is moved to the planted file to get past the
    hash check and reach this branch)."""
    marker = tmp_path / "planted-ran"
    body = _planted(marker, exit_code=1)
    pin = hashlib.sha256(body.encode()).hexdigest()
    out = _run_step(tmp_path, _workspace(tmp_path, body), pin=pin)
    assert marker.exists()
    assert out == {"reason": "classifier could not run", "full-build": "true"}


@needs_bash
def test_step_reports_full_build_when_the_classifier_is_missing(tmp_path: Path) -> None:
    out = _run_step(tmp_path, _workspace(tmp_path, None))
    assert out == {"reason": "classifier could not run", "full-build": "true"}


@needs_bash
def test_step_reports_full_build_without_an_interpreter(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, _real_classifier())
    out = _run_step(tmp_path, ws, interpreter=False)
    assert out == {"reason": "classifier could not run", "full-build": "true"}


def test_ci_runs_the_behaviour_tests() -> None:
    """A skip of the tests above would hollow this file out. On the CI runner they must run."""
    if os.environ.get("GITHUB_ACTIONS") == "true" and sys.platform != "win32":
        assert BASH is not None, "bash is missing on the CI runner"
