.PHONY: all clean ci-fast ci-format ci-lint ci-test ci-security ci-policy ci-agent-proof ci-csp-api format lint test hooks-install hooks-run

PYTHON ?= python3

all: ci-fast

clean:
	@find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true

ci-fast: ci-format ci-lint ci-test ci-security ci-policy ci-agent-proof ci-csp-api
	@echo "ci-fast: OK"

ci-format:
	$(PYTHON) -m ruff format --check src tests tools scripts

ci-lint:
	$(PYTHON) -m ruff check src tests tools scripts

ci-test:
	$(PYTHON) -m pytest -q --cov=ac_copilot_trainer --cov=tools --cov-fail-under=80

ci-security:
	$(PYTHON) -m bandit -r src tools -ll -ii

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
