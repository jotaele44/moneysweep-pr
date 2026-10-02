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
- [ ] Touches the federation contract (`schemas/`, `moneysweep/federation/`)? If so, flagged for maintainer + `spiderweb-pr` coordination

## End-to-end GUI capability parity

- [ ] No production, setup, analysis, or operator capability was added or changed,
      **or** `.federation/gui-capabilities.json` was updated in this PR
- [ ] Every human-facing backend/analysis capability is usable through a
      discoverable GUI workflow without a terminal, script, direct API call,
      developer tools, or hidden URL
- [ ] Every interactive GUI control is connected to working production behavior
      or explicitly classified `client_only`; no dead control, production mock,
      or placeholder workflow was introduced
- [ ] Analytical/background results expose applicable progress, freshness,
      provenance, errors, and artifact access in the GUI
- [ ] End-to-end GUI tests were added or updated and
      `python .federation/check_gui_parity_with_extensions.py` passes (the CI
      gate — wraps `scripts/check_gui_parity.py` against the manifest merged
      with `.federation/gui-capabilities.extensions/*.json`)
- [ ] Any `internal` or `staged` exception includes its rationale, owner,
      tracking reference, and expiry

## Verification

<!-- How did you confirm this works? Commands run, output, screenshots. -->
