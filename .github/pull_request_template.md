<!--
Keep PRs small and single-purpose. Green CI is required to merge.
-->

## Summary

<!-- What does this change do, and why? Link the relevant task in
docs/BUILD_EXECUTION_SEQUENCE.md or the issue it closes. -->

## Changes

-

## Quality gates

- [ ] `ruff check .` clean
- [ ] `ruff format --check .` clean
- [ ] `python -m mypy` clean (pinned version from `requirements-dev.txt`)
- [ ] `pytest -q` passes (and coverage stays at/above the floor)
- [ ] `requirements.lock` regenerated if `requirements.in` changed

## Scope & risk

- [ ] Single-purpose; no unrelated changes
- [ ] No runtime/behavior change, **or** behavior change is covered by tests
- [ ] Touches the federation contract (`schemas/`, `contract_sweeper/federation/`)? If so, flagged for maintainer + `spiderweb-pr` coordination

## Verification

<!-- How did you confirm this works? Commands run, output, screenshots. -->
