# moneysweep-pr developer command surface.
#
# Thin wrappers over the same commands the CI quality gates run, so local and CI
# stay in lock-step (see docs/BUILD_EXECUTION_SEQUENCE.md Waves A-G and the
# workflows under .github/workflows/). Run `make help` for the list.
#
# These targets shell out to the interpreter on PATH; activate your venv first.

PYTHON ?= python
PIP    ?= pip

.DEFAULT_GOAL := help

.PHONY: help install-dev lint format format-check type test test-fast cov \
        lock lock-check precommit check

help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install-dev:  ## Install dev + runtime tooling (ruff, mypy, pytest, …)
	$(PIP) install -r requirements-dev.txt

lint:  ## ruff lint (gating in .github/workflows/lint.yml)
	ruff check .

format:  ## ruff format — rewrite files in place
	ruff format .

format-check:  ## ruff format --check (gating; the CI counterpart)
	ruff format --check .

type:  ## mypy over the configured scope (pinned 1.11.2; gating in mypy.yml)
	$(PYTHON) -m mypy

test:  ## Full pytest suite with the coverage floor from pytest.ini
	$(PYTHON) -m pytest

test-fast:  ## pytest without coverage instrumentation (quick inner loop)
	$(PYTHON) -m pytest -o addopts="" -q

cov:  ## pytest with a terminal coverage report
	$(PYTHON) -m pytest --cov=scripts --cov=moneysweep --cov-report=term-missing

lock:  ## Recompile requirements.lock from requirements.in (deterministic, via uv)
	uv pip compile requirements.in --universal --python-version 3.10 -o requirements.lock

lock-check:  ## Fail if requirements.lock is stale vs requirements.in (CI: lockfile.yml)
	uv pip compile requirements.in --universal --python-version 3.10 -o - \
		| diff -u requirements.lock - \
		&& echo "requirements.lock is up to date"

precommit:  ## Run every pre-commit hook over the whole tree (CI: pre-commit.yml)
	pre-commit run --all-files

check: lint format-check type test  ## Run the full gating quality bar locally
