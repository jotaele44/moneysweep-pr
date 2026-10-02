# Materialization Runbook — Filling Automatable Sources

## Authority

The materialization target is computed from the live source registry by
`scripts/build_source_recovery_matrix.py` and certified by
`tests/test_materialization_readiness.py`.

**Do not copy source counts from this prose into operational logic.** The sole
authoritative count surface is:

`reports/materialization_readiness.json`

That artifact records `total_sources`, `automatable_total`,
`automatable_ready`, queued/excluded breakdowns, required credential names, and
the SHA-256 of the source-ID denominator. Historical counts in earlier runbook
revisions are superseded.

## Source classes

The generated recovery matrix separates:

- automatable adapters/producers — target for network materialization;
- `manual_export` — operator-supplied files in registered dropzones;
- `scraper_needed` — structurally incomplete source implementation;
- `semantic_duplicate` — covered by a sibling source, never materialize alone;
- `deferred_stub` — intentionally unimplemented;
- any future classifier state emitted by the current matrix.

Do not infer class from a source name.

## CLI/network procedure

### 1. Install the pinned core runtime

```bash
pip install -r requirements.lock
```

For source-development paths that intentionally exercise unpinned minimum
constraints, `requirements.txt` remains available; it is not the preferred
certification input.

### 2. Configure credentials where required

Local source-development runs may use environment variables / `.env`. Never
commit secrets. The desktop application instead stores keyed credentials in the
OS credential vault; see `docs/DESKTOP_DATA_POPULATION.md`.

The current required credential names are generated into
`reports/materialization_readiness.json -> automatable_required_keys`.

### 3. Stage manual exports when applicable

Manual source destinations, filename patterns, expected columns, and validation
rules are defined by `registries/manual_export_registry.yaml`. Required
operator-gated source procedures and staleness rules are documented in
`docs/MANUAL_SOURCE_OPERATIONS.md`.

Manual exports are outside the automatable denominator. Do not treat a missing
manual file as an API zero-row result.

### 4. Preflight

```bash
python3 run_all.py --only-setup --strict-preflight
python3 -m pytest tests/test_materialization_readiness.py -q
```

Expected result: zero structural errors and
`automatable_ready == automatable_total` in the generated readiness artifact.

### 5. Dry-run the exact selection

```bash
python3 scripts/run_automatable_sources.py --dry-run
python3 scripts/run_automatable_sources.py --source <source_id> --dry-run
python3 scripts/run_automatable_sources.py --family <family> --dry-run
```

Dry-run is discovery/selection only. It must execute zero producers.

### 6. Materialize

For a bounded source-first run:

```bash
python3 scripts/run_automatable_sources.py --source <source_id>
```

For the complete current automatable set:

```bash
python3 scripts/run_automatable_sources.py
```

The runner:

- loads source identity from the authoritative registry;
- performs an outbound-egress preflight;
- executes registry-declared producers;
- captures each source result independently so one source failure does not erase
  the rest of the candidate set;
- writes a latest summary to
  `data/staging/materialization_run_summary.json`;
- writes a versioned run receipt under `receipts/materialization_runs/` when
  executed in the desktop/workspace architecture.

When egress is blocked, the runner executes no producers and reports
`egress_blocked`. That state must not be interpreted as source absence.

## Desktop procedure

The self-contained desktop application exposes the same data plane through the
**Data Sources** tab:

- **Offline files** — registered dropzone + SHA-256 staging + explicit producer
  invocation;
- **API materialization** — source-level dry-run/live operation;
- **API credentials** — OS credential-vault management with no secret echo.

The desktop application uses an immutable bundled registry and a writable
per-user workspace. Legacy producer path globals are rebound into that workspace
before producer import so a successful run cannot silently write into the
signed application bundle.

See `docs/DESKTOP_DATA_POPULATION.md`.

## CI live materialization

The manual workflow `.github/workflows/materialize-sources.yml` remains the
remote egress-capable path. `mode=fetch` requires exact confirmation `YES`; a
preflight dispatch does not authorize live fetching. Secrets are passed only to
the live producer step, and materialized outputs are uploaded as workflow
artifacts rather than committed automatically.

## Verification

Regenerate the derived coverage surfaces after materialization:

```bash
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
```

Judge automatable completion against the generated automatable denominator, not
overall registered-source coverage while manual/deferred classes remain queued.
`reports/gap_analysis_report.json` may also expose an overall `coverage_rate`.
That metric spans the entire registered-source denominator, including
manual/deferred classes, so it is contextual only and must not replace
`automatable_ready == automatable_total` or source-specific validation
thresholds for the automatable completion claim.

## Per-source definition of done

A source is `fully_materialized` only when every declared expected output exists,
is non-empty, and satisfies source-specific validation thresholds such as
minimum row counts and required schema.

HTTP 200, process exit 0, `status=OK`, filename match, or equal row count alone
is not source certification and never proves entity identity.
