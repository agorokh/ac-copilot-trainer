.PHONY: ci-fast ci-format ci-lint ci-test ci-policy ci-agent-proof format lint test hooks-install

PYTHON ?= python3

ci-fast: ci-format ci-lint ci-test ci-policy ci-agent-proof
	@echo "ci-fast: OK"

ci-format:
	$(PYTHON) -m ruff format --check src tests

ci-lint:
	$(PYTHON) -m ruff check src tests

ci-test:
	$(PYTHON) -m pytest -q

ci-policy:
	bash scripts/check_policy_docs.sh

ci-agent-proof:
	$(PYTHON) scripts/check_agent_forbidden.py

format:
	$(PYTHON) -m ruff format src tests

lint:
	$(PYTHON) -m ruff check --fix src tests

test: ci-test

hooks-install:
	pre-commit install

hooks-run:
	pre-commit run --all-files
