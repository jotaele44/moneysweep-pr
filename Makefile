# moneysweep-pr developer command surface.
#
# Thin wrappers over the same commands the CI quality gates run, so local and CI
# stay in lock-step (see docs/BUILD_EXECUTION_SEQUENCE.md Waves A-G and the
# workflows under .github/workflows/). Run `make help` for the list.
#
# These targets shell out to the interpreter on PATH; activate your venv first.

PYTHON ?= python
PIP    ?= python -m pip
PYTHON_BASELINE ?= 3.11

.DEFAULT_GOAL := help

.PHONY: help install-dev dependency-plane compileall lint format format-check type test test-fast cov \
        lock lock-check precommit check

help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install-dev:  ## Install dev + runtime tooling (ruff, mypy, pytest, …)
	$(PIP) install -r requirements-dev.txt

dependency-plane:  ## Validate runtime/dev manifests and Hub setup profiles
	$(PYTHON) scripts/validate_dependency_planes.py

compileall:  ## Byte-compile moneysweep/scripts/tests (matches ci.yml's compile step)
	$(PYTHON) -m compileall moneysweep scripts tests

lint:  ## ruff lint (gating in .github/workflows/lint.yml)
	ruff check .

format:  ## ruff format — rewrite files in place
	ruff format .

format-check:  ## ruff format --check (gating; the CI counterpart)
	ruff format --check .

type:  ## mypy over the configured scope (gating in mypy.yml)
	$(PYTHON) -m mypy

test:  ## Full pytest suite with the coverage floor from pytest.ini
	$(PYTHON) -m pytest

test-fast:  ## pytest without coverage instrumentation (quick inner loop)
	$(PYTHON) -m pytest -o addopts="" -q

cov:  ## pytest with a terminal coverage report
	$(PYTHON) -m pytest --cov=scripts --cov=moneysweep --cov-report=term-missing

lock:  ## Recompile requirements.lock from requirements.in and validate profiles
	uv pip compile requirements.in --universal --python-version $(PYTHON_BASELINE) -o requirements.lock
	$(PYTHON) scripts/validate_dependency_planes.py

lock-check:  ## Fail if requirements.lock is stale vs requirements.in (CI: lockfile.yml)
	uv pip compile requirements.in --universal --python-version $(PYTHON_BASELINE) -o - \
		| diff -u requirements.lock - \
		&& $(PYTHON) scripts/validate_dependency_planes.py \
		&& echo "requirements.lock is up to date"

precommit:  ## Run every pre-commit hook over the whole tree (CI: pre-commit.yml)
	pre-commit run --all-files

check: dependency-plane compileall lint format-check type test  ## Run the full gating quality bar locally
