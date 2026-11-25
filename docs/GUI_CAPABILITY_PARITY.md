<!-- Rendered from thehub-pr/federation-templates/gui/GUI_CAPABILITY_PARITY.md.
     Do not hand-edit - template-drift.yml fails the build if you do. Change the
     template and re-render. -->

# End-to-end GUI capability parity

moneysweep-pr follows the federation rule that a human-facing capability is not
complete until it is usable through this repository's own GUI. The full rule set
is `thehub-pr/docs/FEDERATION_GUI_STANDARD.md`; this page is the working summary.

## Completion boundary

The required chain is:

`backend logic -> API/IPC -> client state -> GUI component -> discoverable workflow`

The GUI covers the configuration, validation, permission, loading, empty, stale,
offline, progress, success, failure and recovery states that apply. Analytical
output is inspectable through a map, table, chart, report or record view, with
provenance and freshness, and with download or export when the output is an
artifact.

The normal path for a person never needs a terminal command, a script, a direct
API request, developer tools or a hidden URL.

## Classifications

Answer in order and stop at the first "yes".

| # | Question | Classification |
|---|---|---|
| 1 | Infrastructure no person operates directly? | `internal` |
| 2 | Lives entirely in the browser, with no backend call of its own? | `client_only` |
| 3 | Changes state, runs a job, manages configuration, approves something? | `operator` |
| 4 | Main output is a computed result a person inspects? | `analysis` |
| 5 | Otherwise: a person browses, searches or reads records. | `user` |

| Classification | Required contract when `active` |
|---|---|
| `user`, `operator`, `analysis` | Backend or analysis binding, discoverable GUI, end-to-end GUI test |
| `client_only` | Discoverable GUI and end-to-end test; no backend claim |
| `internal` | No GUI required; a concrete rationale naming what consumes it |

`internal` is for code with no human operator, not for a GUI that has not been
built yet. `staged` capabilities are unreachable behind a feature flag and carry
a tracking reference and an expiry. `legacy` entries record known one-sided
behaviour and do not erase its debt.

## Adding a page or capability

1. Add the backend endpoint or module (skip for `client_only`).
2. Add the API call in the API client module.
3. Add the page component.
4. Register the route.
5. Add one navigation entry.
6. Declare the capability in `.federation/gui-capabilities.json`, or in a
   fragment for a self-contained feature, and bind both sides.
7. Add or extend an end-to-end spec and name it in `tests.e2e`.
8. Run:
   ```
   python3 scripts/check_gui_parity.py
   npm --prefix dashboard run test:gui-parity
   ```
9. Update the documents the change made untrue.

## Repository files

- `.federation/gui-capabilities.json` — the reviewed capability manifest.
- `.federation/gui-capabilities.extensions/<extension_id>.json` — optional
  fragments for self-contained features. A fragment appends capabilities and
  exceptions; it cannot redefine a base entry, change discovery, or affect the
  baseline. The filename stem equals its `extension_id`.
- `.federation/gui-parity-baseline.json` — the inventory of debt that existed
  when the gate was introduced, used by the no-new-debt ratchet.
- `scripts/check_gui_parity.py` — the detector and contract validator. It merges
  the fragments itself; it is the one entry point for CI and for local runs.
- `tests/test_gui_parity.py` — regression tests for the detector.
- `.github/workflows/gui-capability-parity.yml` — the pull-request gate and
  nightly audit.

## Signals

- `BACKEND_NOT_GUI_SURFACED`
- `GUI_NOT_BACKEND_WIRED`
- `GUI_WORKFLOW_UNREACHABLE`
- `DEAD_CONTROL`
- `TERMINAL_REQUIRED`
- `ANALYSIS_NOT_GUI_RENDERED`
- `PRODUCTION_PLACEHOLDER_OR_MOCK`
- `GUI_PATH_NOT_E2E_TESTED`
- `E2E_SPEC_NOT_COLLECTED`
- `EXPIRED_PARITY_EXCEPTION`
- `INVALID_EXTENSION_FRAGMENT`, `EXTENSION_REDEFINES_BASE`
- `CORE_CAPABILITY_MISMATCH`

The detector inventories HTTP endpoints, production and analysis modules and
public symbols, CLI surfaces, GUI routes, pages and controls, API-client
functions, dead buttons, mock or placeholder markers, and unreachable routes.

## Ratchet and audit behaviour

Pull requests run in ratchet mode. Current candidates are compared with the
committed baseline and the manifest:

- a newly unpaired or unclassified candidate fails;
- an invalid or expired capability contract fails;
- existing debt is reported but does not block unrelated work;
- deleting debt, or converting it into a complete mapping, is allowed.

The nightly run publishes the full machine-readable report. A manually
dispatched strict audit fails on all remaining legacy debt.

## Baseline and exceptions

The baseline is rewritten only when the gate is first adopted, or by a change
whose only effect on it is to remove candidates. It is never rewritten to make a
failing gate pass: map the new candidate or remove the code.

An exception needs an owner, a tracking reference, a reason and an expiry at
most 90 days out. The checker warns from 14 days before expiry. After expiry the
gate fails for every change in the repository, so act on the warning: deliver
the missing side, or renew with a reviewed reason that says what moved.
