<!--
Rendered from thehub-pr/federation-templates/baseline/AGENTS.md.
Edit the canonical template and re-render; do not hand-edit this copy.
-->

# Repository agent requirements

## End-to-end GUI capability parity

Any production, setup, configuration, monitoring, ingestion, analysis,
visualization, reporting, or export capability intended for a human user must be
wired through the complete shipped path:

`backend logic -> API/IPC -> client state -> GUI component -> discoverable app workflow`

A capability is incomplete if it requires a terminal, script, direct API call,
developer tools, or an undiscoverable URL for normal use. Adding a frontend file
or an API endpoint alone does not satisfy this rule.

The inverse rule is equally strict: every interactive GUI control must be backed
by working production behavior, or be explicitly classified as `client_only`.
Do not ship dead controls, production mocks, placeholder workflows, or analysis
outputs that users cannot inspect in the app.

For user-relevant background and analytical work, the GUI must expose results,
provenance, freshness, progress, success, failure, and safe retry/cancel controls
where applicable. Security-sensitive controls may remain internal, but status and
user-relevant outcomes still require a GUI surface.

## Required change protocol

1. Declare the capability in `.federation/gui-capabilities.json`, or in a
   fragment under `.federation/gui-capabilities.extensions/`, in the same change.
2. Bind backend endpoints/modules and GUI routes/components bidirectionally.
3. Make the workflow reachable from visible navigation or a documented
   contextual GUI path. (This repository has not yet adopted the shared shell
   and its navigation registry; until it does, navigation lives in
   `dashboard/src/pages/Dashboard.jsx`.)
4. Add or update an end-to-end GUI test, name it in `tests.e2e`, and list it in
   `dashboard/gui-parity.playwright.config.mjs`.
5. Run `python3 scripts/check_gui_parity.py` (the CI gate; it merges the
   extension fragments itself) and the frontend package's
   `npm run test:gui-parity`.
6. Never regenerate `.federation/gui-parity-baseline.json` to make a gate
   pass. Baseline changes require an audited inventory explanation.

The full rules are in `thehub-pr/docs/FEDERATION_GUI_STANDARD.md`.

Pure infrastructure may be classified `internal` with a concrete rationale.
Phased work must remain unreachable behind a feature flag and carry a tracking
reference plus an expiry date. Unclassified additions fail CI.
