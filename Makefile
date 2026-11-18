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

.PHONY: help install-dev compileall lint format format-check type test test-fast cov \
        lock lock-check precommit check prebuilt-dashboard prebuilt-dashboard-check

help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install-dev:  ## Install dev + runtime tooling (ruff, mypy, pytest, …)
	$(PIP) install -r requirements-dev.txt

compileall:  ## Byte-compile moneysweep/scripts/tests (matches ci.yml's compile step)
	$(PYTHON) -m compileall moneysweep scripts tests

lint:  ## ruff lint (gating in .github/workflows/lint.yml)
	ruff check .

# The CI format gate skips every tracked .py file that FROZEN_RE in
# .github/workflows/lint.yml matches: the certified leaderboard runtime and the
# Grid V2 Cell_Profile files rendered from thehub-pr. Both format targets read
# that pattern from lint.yml, so they cannot drift from CI, and stop if it is gone.
FORMAT_FILES = re="$$(sed -n "s/^ *FROZEN_RE='\(.*\)'$$/\1/p" .github/workflows/lint.yml)"; \
	test -n "$$re" || { echo "FROZEN_RE not found in .github/workflows/lint.yml" >&2; exit 1; }; \
	git ls-files '*.py' | grep -Ev "$$re" | tr '\n' '\0'

format:  ## ruff format — rewrite in place every file the CI format gate checks
	@$(FORMAT_FILES) | xargs -0 ruff format

format-check:  ## ruff format --check over the same files (gating; the CI counterpart)
	@$(FORMAT_FILES) | xargs -0 ruff format --check

type:  ## mypy over the configured scope (gating in mypy.yml)
	$(PYTHON) -m mypy

test:  ## Full pytest suite with the coverage floor from pytest.ini
	$(PYTHON) -m pytest

test-fast:  ## pytest without coverage instrumentation (quick inner loop)
	$(PYTHON) -m pytest -o addopts="" -q

cov:  ## pytest with a terminal coverage report
	$(PYTHON) -m pytest --cov=scripts --cov=moneysweep --cov-report=term-missing

lock:  ## Recompile requirements.lock from requirements.in for the local baseline
	uv pip compile requirements.in --universal --python-version $(PYTHON_BASELINE) -o requirements.lock

prebuilt-dashboard:  ## Rebuild the committed desktop dashboard bundle (needs Node.js)
	python3 scripts/build_prebuilt_dashboard.py --build

prebuilt-dashboard-check:  ## Fail if the committed dashboard bundle is stale or corrupt
	python3 scripts/build_prebuilt_dashboard.py --check

lock-check:  ## Fail if requirements.lock is stale vs requirements.in (CI: lockfile.yml)
	@set -eu; \
	tmp_dir=$$(mktemp -d); \
	trap 'rm -rf "$$tmp_dir"' EXIT HUP INT TERM; \
	cp requirements.lock "$$tmp_dir/requirements.lock"; \
	uv pip compile requirements.in --universal --python-version $(PYTHON_BASELINE) \
		-o "$$tmp_dir/requirements.lock"; \
	sed '1,2d' requirements.lock > "$$tmp_dir/expected"; \
	sed '1,2d' "$$tmp_dir/requirements.lock" > "$$tmp_dir/actual"; \
	diff -u "$$tmp_dir/expected" "$$tmp_dir/actual"; \
	echo "requirements.lock is up to date"

precommit:  ## Run every pre-commit hook over the whole tree (CI: pre-commit.yml)
	pre-commit run --all-files

check: compileall lint format-check type test  ## Run the full gating quality bar locally
