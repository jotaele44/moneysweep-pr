# End-to-end GUI capability parity

This repository follows the federation rule that human-facing production and
analysis capability is not complete until it is usable through the shipped app
interface.

## Completion boundary

The required chain is:

`backend logic -> API/IPC -> client state -> GUI component -> discoverable workflow`

The GUI must cover configuration, validation, permission handling, loading,
empty, stale, offline, progress, success, failure, and recovery states that
apply to the capability. Analytical outputs must be inspectable through an
appropriate map, table, chart, report, or record view, with provenance,
freshness, and download/export access when the output is an artifact.

The normal user path may not require a terminal command, script, direct API
request, developer tools, or a hidden URL.

## Classifications

| Classification | Required contract |
|---|---|
| `user` | Working backend/analysis binding, discoverable GUI, and E2E GUI test |
| `operator` | Same as `user`, including operational state and safe controls |
| `analysis` | Executable or observable analysis plus rendered results and provenance |
| `client_only` | Discoverable GUI and E2E test; no backend claim |
| `internal` | No GUI required, but a concrete rationale is mandatory |

`active` capabilities satisfy the full contract. `staged` capabilities must be
unreachable behind a feature flag and include a tracking reference and expiry.
`legacy` entries document known one-sided behavior but do not erase its debt.

## Repository files

- `.federation/gui-capabilities.json` — reviewed capability mappings.
- `.federation/gui-capabilities.extensions/*.json` — reviewed capability/exception
  fragments merged on top of the base manifest before validation; only appends,
  never suppresses or edits the base.
- `.federation/gui-parity-baseline.json` — immutable inventory of pre-existing
  candidates used by the no-new-debt ratchet.
- `scripts/check_gui_parity.py` — shared static detector and contract validator;
  owns discovery/validation semantics but only ever sees the base manifest when
  run directly.
- `.federation/check_gui_parity_with_extensions.py` — the actual CI entry point
  (see `.github/workflows/gui-capability-parity.yml` below). Merges the base
  manifest with every extension fragment, then delegates to
  `scripts/check_gui_parity.py`. Run this locally, not the bare script, to get
  a faithful preview of the gate.
- `tests/test_gui_parity.py` — regression tests for the detector.
- The frontend `tests/gui-parity.spec.mjs` — manifest-driven browser reachability.
- `.github/workflows/gui-capability-parity.yml` — PR gate and nightly audit;
  invokes `.federation/check_gui_parity_with_extensions.py`.

## Signals

The report distinguishes:

- `BACKEND_NOT_GUI_SURFACED`
- `GUI_NOT_BACKEND_WIRED`
- `GUI_WORKFLOW_UNREACHABLE`
- `DEAD_CONTROL`
- `TERMINAL_REQUIRED`
- `ANALYSIS_NOT_GUI_RENDERED`
- `PRODUCTION_PLACEHOLDER_OR_MOCK`
- `GUI_PATH_NOT_E2E_TESTED`
- `EXPIRED_PARITY_EXCEPTION`

The detector inventories HTTP endpoints, production and analysis modules/public
symbols, CLI surfaces, GUI routes/pages/controls, API-client functions,
dead buttons, mock/placeholder markers, and unreachable routes.

## Ratchet and audit behavior

Pull requests run ratchet mode. Current candidates are compared with the
committed baseline and manifest:

- newly unpaired or unclassified candidates fail;
- invalid or expired capability contracts fail;
- existing debt is reported but does not prevent unrelated repairs;
- deleting debt or converting it into a complete mapping is allowed.

The nightly run publishes the complete machine-readable report. A manually
dispatched strict audit fails on all remaining legacy debt.

Do not rewrite the baseline after adding an unpaired feature. Update the
capability manifest and implement the missing side of the chain instead.
