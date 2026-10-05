.PHONY: all clean ci-fast ci-vault ci-conventional ci-format ci-lint ci-test ci-security ci-secrets ci-policy ci-agent-proof ci-csp-api ci-csp-ui-safety ci-drive doppler-doctor memory-contract memory-contract-check init-knowledge bootstrap-knowledge merge-settings format lint test hooks-install hooks-run

PYTHON ?= python3

all: ci-fast

ci-conventional:
	$(PYTHON) scripts/ci_policy.py

clean:
	@find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true

ci-fast: ci-conventional ci-format ci-lint ci-test ci-security ci-secrets ci-policy ci-agent-proof ci-csp-api ci-csp-ui-safety
	@echo "ci-fast: OK"

# ci-vault — what the CI `build` job runs INSTEAD of ci-fast for a PR whose every changed path is
# under docs/01_Vault/ (governance-hub#701), so a required `build` concludes inside the
# vault-automerge wait. It is every ci-fast check that reads live vault content: the branch/title
# policy (it applies to every PR), the tracked-file secret scan, the canonical-docs check (it
# requires docs/01_Vault/00_Graph_Schema.md to exist), and the tests below.
# Add a test here when it starts reading live vault notes; a missed one is not silent, it turns
# the next code PR's full build red. The test list was derived by tracing the suite's file opens
# under docs/01_Vault/ (2026-10-04), not by grepping for the path. The last entry reads no vault
# note: it pins the vendored scope classifier that selects this path, so it runs on both paths.
VAULT_TESTS = tests/test_no_stale_hook_refs.py tests/test_instruction_coherence.py \
	tests/test_invariants_present.py tests/test_scripts/test_fleet_inventory_refresh.py \
	tests/test_doppler_doctor.py tests/test_merge_memory_contract.py \
	tests/test_memory_vault_paths.py tests/test_public_governance_conformance.py \
	tests/test_vendored_classifier_pin.py

ci-vault: ci-conventional ci-secrets ci-policy
	$(PYTHON) -m pytest -q $(VAULT_TESTS)
	@echo "ci-vault: OK"

ci-format:
	$(PYTHON) -m ruff format --check src tests tools scripts

ci-lint:
	$(PYTHON) -m ruff check src tests tools scripts

ci-test:
	$(PYTHON) -m pytest -q --cov=ac_copilot_trainer --cov=tools --cov-fail-under=80

# Bandit targets application code only. tools/ and scripts/ hold infrastructure
# (subprocess, I/O, network) and produce high false-positive noise if scanned.
ci-security:
	$(PYTHON) -m bandit -r src -ll -ii

# pre_commit_hook exits non-zero when tracked files contain secrets not in the baseline;
# plain `scan --baseline` updates the baseline and does not fail CI.
ci-secrets:
	$(PYTHON) scripts/policy_tracked_files.py  # pragma: allowlist secret

init-knowledge:
	$(PYTHON) scripts/init_knowledge_db.py

bootstrap-knowledge: init-knowledge
	$(PYTHON) scripts/bootstrap_knowledge.py

merge-settings:
	$(PYTHON) scripts/merge_settings.py

doppler-doctor:
	$(PYTHON) scripts/doppler_doctor.py

memory-contract:
	$(PYTHON) scripts/merge_memory_contract.py

memory-contract-check:
	$(PYTHON) scripts/merge_memory_contract.py --check

ci-policy:
	$(PYTHON) scripts/check_policy_docs.py

ci-agent-proof:
	$(PYTHON) scripts/check_agent_forbidden.py

format:
	$(PYTHON) -m ruff format src tests tools scripts

lint:
	$(PYTHON) -m ruff check --fix src tests tools scripts

test: ci-test

# Layer-1 autonomous self-test (issue #154): boot a loopback sidecar and drive it with
# the headless harness client; asserts the deterministic coaching rubric. Integration
# smoke — kept OUT of ci-fast (which stays game-free and millisecond-fast); the same
# logic is gated deterministically by tests/test_harness_client.py inside ci-test.
ci-drive:
	bash scripts/baseline_copilot_check.sh

hooks-install:
	pre-commit install

hooks-run:
	pre-commit run --all-files

ci-csp-api:
	$(PYTHON) scripts/check_csp_api.py src

ci-csp-ui-safety:
	$(PYTHON) scripts/check_csp_ui_safety.py
