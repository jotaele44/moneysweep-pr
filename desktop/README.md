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
prerequisites are different from a frozen release artifact.

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
