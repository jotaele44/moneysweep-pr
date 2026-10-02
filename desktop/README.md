# MoneySweep desktop application

MoneySweep has two desktop launch surfaces. They are intentionally classified
differently.

## 1. Source-checkout developer wrapper — not the distribution

The repository-root launchers (`PRII-MONEYSWEEP.command`, `.bat`, `.sh`, and the
committed lightweight `PRII-MONEYSWEEP.app`) are developer conveniences around
the source checkout. They may create a private `.venv`, install dependencies,
and build the dashboard. First setup can therefore require externally installed
Python 3.11+, Node.js, and network access.

**Do not certify the committed wrapper as the downloadable self-contained app.**

It remains useful for source development and repair, but its identity and
prerequisites are different from a frozen release artifact. The committed
prebuilt dashboard described below does **not** change that classification: the
wrapper still requires an externally installed Python 3.11+, still installs
Python packages (from the network or an operator-supplied wheelhouse), and is
still unsigned, so it still costs one macOS Gatekeeper approval per machine.

### Prebuilt dashboard bundle

`desktop/prebuilt-dashboard/` holds a committed `vite build` output plus
`PREBUILT_MANIFEST.json`. `desktop/setup.py` copies it into `dashboard/dist`
instead of running `npm ci` + `npm run build`, which is what removes Node.js from
the wrapper's first-run prerequisites.

Regenerate it whenever `dashboard/` sources change:

```bash
make prebuilt-dashboard        # or: python3 scripts/build_prebuilt_dashboard.py --build
python3 scripts/build_prebuilt_dashboard.py --check
```

`tests/test_desktop_prebuilt_dashboard.py` recomputes the manifest's
`source_fingerprint` from the working tree and fails when the two diverge, so a
dashboard change that forgets the regeneration is caught in CI without needing
Node on the runner.

Selection order in `setup_frontend()`: an existing `dashboard/dist` wins (a
developer's own build is never clobbered), then the prebuilt bundle, then npm.
Force a real build with `--build-frontend`, `--force`, or
`PRII_FORCE_FRONTEND_BUILD=1`.

The bundle lives outside `dashboard/` on purpose: `.gitignore` eats any directory
named `dist`/`build` at any depth, and `dashboard/eslint.config.js` is a rendered
federation template that cannot gain a local `ignores` entry. It is deliberately
**not** added to `desktop/pyinstaller.spec` — the frozen build compiles the
dashboard with npm in CI, and bundling both would double its frontend payload.

### Offline first run

Setup installs from `desktop/wheelhouse/` (or `$PRII_WHEELHOUSE`) when that
directory contains wheels, making the whole first run work with no network. See
`docs/DESKTOP_OFFLINE_BOOTSTRAP.md`.

`python3 desktop/preflight.py` reports which prerequisite is blocking setup —
checkout integrity, writability, Python version, `venv`, dashboard availability,
`git`, host reachability, free disk — instead of the single catch-all message the
launcher used to show. Network hosts are probed only when installation work
actually remains.

### macOS Gatekeeper

An unsigned bundle always costs **one** approval per machine; nothing in this
repository can remove it, and nothing here weakens system assessment policy
(`spctl` is never invoked). What the wrapper does do is make that approval the
only step: after a successful run, `setup.py` clears `com.apple.quarantine` from
the launchers, so subsequent launches — including the `.app` — open cleanly.

Start from `PRII-MONEYSWEEP.command` rather than the `.app` when the folder came
from a browser download. Terminal runs `.command` files in place, whereas macOS
runs a quarantined `.app` from a temporary read-only copy where the checkout
beside it is missing.

`docs/APPLE_NOTARIZATION_RUNBOOK.md` covers the only route to zero approvals: a
Developer ID certificate and notarization, which apply to the frozen build below.

Note that the repo-root launchers (`Fix-Gatekeeper.command`, the `.command`,
`.sh`, `.bat`, and the `.app` executable) are rendered federation templates
shared with five sibling repositories. Improving them is a coordinated change in
`thehub-pr/federation-templates/`, not a local edit — see
`tests/test_federation_template_boundary.py`.

## 2. Self-contained standalone build — canonical distribution target

`.github/workflows/desktop-build.yml` builds the standalone application with
PyInstaller on macOS, Windows, and Linux. The macOS output is
`PRII-MONEYSWEEP.app`, also packaged as ZIP and DMG.

The frozen build contains:

- Python runtime and complete MoneySweep Python dependency set;
- real DuckDB and PyArrow runtime;
- FastAPI/uvicorn desktop backend;
- pywebview native-window runtime;
- operating-system credential-vault integration;
- compiled dashboard;
- source registries and schemas;
- registry-declared producer modules;
- materialization readiness + production-status metadata;
- seed `data/canonical_v1`.

It must not download or install runtime dependencies on first launch.

## First boot

The application bundle is immutable. On startup MoneySweep creates a writable
per-user workspace and copies only missing seed canonical files.

Default macOS workspace:

`~/Library/Application Support/PRII-MONEYSWEEP/`

The bootstrap is idempotent and never overwrites existing workspace data. A
receipt is written to:

`receipts/desktop_bootstrap_latest.json`

The app then starts one local same-origin FastAPI server on a free loopback port
and opens the dashboard in a native window. The browser fallback remains
available through the shared `prii_desktop` launcher.

## Data Sources tab

The standalone desktop composition adds a **Data Sources** dashboard tab.

### Offline files

Select a registered manual source, choose a local export, then **Stage + hash**.
MoneySweep stores it only under that source's registered workspace dropzone,
computes SHA-256, preserves same-name/different-byte collisions, and writes an
offline-ingest receipt. The state remains `STAGED_NOT_PROMOTED`.

**Materialize staged source** invokes the registered producer against the local
workspace. Producer success is not automatic canonical promotion.

### API materialization

Select one source and perform **Dry run** before **Fetch + materialize**. Live
runs retain the existing egress gate and source-level failure reporting.
Versioned receipts are stored under `receipts/materialization_runs/`.

The GUI intentionally does not expose a one-click run-all operation.

### Credentials

Keyed API credentials are saved through the OS credential vault (macOS
Keychain on Mac). The GUI and API expose only configured/not-configured status;
secret values are never returned or written into workspace receipts.

See `docs/DESKTOP_DATA_POPULATION.md` for the complete ingestion contract.

## Frozen runtime certification

The CI matrix first builds a console form of the exact PyInstaller runtime and
runs both:

```bash
PRII-MONEYSWEEP --smoke
PRII-MONEYSWEEP --selftest
```

`--selftest` verifies real DuckDB/PyArrow imports, bundle/workspace separation,
source-denominator closure, automatable-selection closure, a zero-execution
dry-run, and secret non-disclosure.

The final package receives `DESKTOP_RELEASE_MANIFEST.json` with exact byte sizes
and SHA-256 digests. See `docs/DESKTOP_RELEASE_CERTIFICATION.md`.

## macOS signing and notarization

An unsigned CI artifact may be retained for testing, but it is **not** the final
`download -> double-click -> READY` release.

A public `desktop-v*` macOS release must pass all three on the exact app:

```bash
codesign --verify --deep --strict --verbose=2 PRII-MONEYSWEEP.app
xcrun stapler validate PRII-MONEYSWEEP.app
spctl --assess --type execute --verbose=4 PRII-MONEYSWEEP.app
```

The workflow intentionally fails closed at this gate until Developer-ID signing
and notarization are configured. No Gatekeeper-bypass helper is part of the
release contract.

## Production-data release gate

Desktop buildability and production-data validity are independent.

CI can build diagnostic candidates, but a `desktop-v*` public release remains
blocked unless:

`data/exports/production_status.json -> production_status == PRODUCTION_VALIDATED`

This prevents a technically self-contained application from being published as
a production MoneySweep release while the bundled data remains diagnostic.
