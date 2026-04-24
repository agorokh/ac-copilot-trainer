.PHONY: all clean ci-fast ci-conventional ci-format ci-lint ci-test ci-security ci-secrets ci-policy ci-agent-proof ci-csp-api ci-csp-ui-safety init-knowledge bootstrap-knowledge merge-settings format lint test hooks-install hooks-run

PYTHON ?= python3

all: ci-fast

ci-conventional:
	$(PYTHON) scripts/ci_policy.py

clean:
	@find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true

ci-fast: ci-conventional ci-format ci-lint ci-test ci-security ci-secrets ci-policy ci-agent-proof ci-csp-api ci-csp-ui-safety
	@echo "ci-fast: OK"

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
	PYTHON=$(PYTHON) bash scripts/policy_tracked_files.sh  # pragma: allowlist secret

init-knowledge:
	$(PYTHON) scripts/init_knowledge_db.py

bootstrap-knowledge: init-knowledge
	$(PYTHON) scripts/bootstrap_knowledge.py

merge-settings:
	$(PYTHON) scripts/merge_settings.py

ci-policy:
	bash scripts/check_policy_docs.sh

ci-agent-proof:
	$(PYTHON) scripts/check_agent_forbidden.py

format:
	$(PYTHON) -m ruff format src tests tools scripts

lint:
	$(PYTHON) -m ruff check --fix src tests tools scripts

test: ci-test

hooks-install:
	pre-commit install

hooks-run:
	pre-commit run --all-files

ci-csp-api:
	$(PYTHON) scripts/check_csp_api.py src

ci-csp-ui-safety:
	$(PYTHON) scripts/check_csp_ui_safety.py
