# MoneySweep Desktop Data Population

## Scope

This document defines the two supported paths for growing a desktop MoneySweep
workspace without mutating the signed application bundle:

1. **offline/operator files** — browser/portal exports already obtained by the
   operator;
2. **API materialization** — registry-declared producers executed against public
   or credentialed network sources.

Neither path promotes records to canonical identity merely because a file or API
request succeeded.

## Workspace model

The standalone application ships immutable code, registries, schemas, reports,
and a seed `canonical_v1`. At first boot it creates a writable per-user
workspace. On macOS the default is:

`~/Library/Application Support/PRII-MONEYSWEEP/`

The app copies missing seed canonical files once and never overwrites existing
workspace data on later boots.

Important workspace surfaces:

- `data/raw/` — registered raw/operator dropzones;
- `data/manual/` — registered manual-export dropzones;
- `data/staging/` — materialized/intermediate outputs;
- `receipts/offline_ingest/` — byte-level offline-file receipts;
- `receipts/materialization_runs/` — versioned API/producer run receipts.

## Offline file population

Use **Data Sources -> Offline files** in the desktop GUI.

### Stage

1. Select the exact registered source ID.
2. Choose the export file.
3. Click **Stage + hash**.

The backend resolves the source through
`registries/manual_export_registry.yaml`; arbitrary destination paths are not
accepted. It strips directory components from the supplied filename, constrains
the destination to the MoneySweep workspace, streams the bytes, and calculates
SHA-256 before finalizing the staged file.

Collision behavior is explicit:

| Condition | Classification | Action |
|---|---|---|
| path absent | `NEW_PAYLOAD` | preserve bytes under registered filename |
| same filename + same SHA-256 | `BYTE_IDENTICAL_EXISTING` | do not duplicate payload |
| same filename + different SHA-256 | `DISTINCT_PAYLOADS_SAME_FILENAME` | preserve both; suffix new manifestation with hash prefix |

Every staged payload receives a receipt containing source ID, exact raw
filename, stored relative path, byte size, SHA-256, reception UTC, expected
filename pattern, and `promotion_state=STAGED_NOT_PROMOTED`.

Filename normalization, proximity, row-count equality, or source absence never
establishes record identity.

### Materialize

After staging, click **Materialize staged source**. MoneySweep invokes the
producer declared for that exact source ID with network preflight disabled: the
payload is already local. Legacy producer path globals are rebound to the
workspace before the producer module is imported.

A producer result of `OK` means the producer executed. It does **not** mean that
all records are canonical, that entities were resolved, or that the overall
pipeline is production-valid.

## API materialization

Use **Data Sources -> API materialization**.

The desktop GUI intentionally runs one source at a time. It does not expose a
one-click `run all` operation because a 109-source live run can consume quotas,
trigger rate limits, or generate a large partially successful state.

### First operation: dry-run

Select a source and click **Dry run**. This performs registry selection only:
no producer is invoked and no network source is fetched. The selected source ID
is recorded in a versioned materialization receipt.

### First live tranche

Begin with required/keyless sources whose current recovery-matrix entries are
structurally ready, one at a time. A practical starting sequence is:

1. `fema_pa_openfema_v2`
2. `usaspending_subawards`
3. `usaspending_prime`
4. `sam_entities`
5. `lda`
6. `emma_bonds`

Run a dry-run immediately before each live execution. Preserve any producer
error as a source-level result; do not retry a different source under the same
identity or silently substitute a similar dataset.

### Egress

A live API operation runs the existing egress gate before producer execution.
If the gate fails, the run returns `egress_blocked` and no producer is invoked.
This is a blocked network state, not an empty-data observation.

## API credentials

Keyed sources do not require `.env`, shell exports, or Terminal in the desktop
application.

Use **Data Sources -> API credentials**. Supported credential names are
allowlisted by the application. On macOS, values are stored in the user's
Keychain through the OS keyring backend. The GUI and status API expose only a
configured/not-configured Boolean; the value is never read back to the GUI,
written to receipts, or stored in the MoneySweep workspace.

At live-run time a stored credential is temporarily exposed to the legacy
producer through its historical environment-variable name and removed from the
process environment when the run ends. An already-defined process environment
value takes precedence over the vault and is left untouched.

The current generated readiness artifact identifies these credential names in
the automatable universe:

`CENSUS_API_KEY`, `EIA_API_KEY`, `FAC_API_KEY`, `FEC_API_KEY`,
`FINANCIALDATA_API_KEY`, `FRED_API_KEY`, `HIGHERGOV_API_KEY`,
`OPENSTATES_API_KEY`, `SAM_API_KEY`.

## Source denominator

Do not copy source counts from prose into operational logic. The generated
`reports/materialization_readiness.json` is authoritative for the current
source denominator. At the pre-hardening freeze it reports:

- total registered = 158;
- automatable = 109;
- automatable structurally ready = 109;
- queued/excluded = 49;
- manual-export = 42;
- source-ID-set SHA-256 =
  `673659d9c53e8428e21052d95819ff35023e90142756686e73a9c9f1b326bbf2`.

Any future count change requires a new generated readiness artifact and new
source-ID-set hash; it must not silently inherit these numbers.

## Materialization invariants

A source is not considered fully materialized solely because the HTTP request
returned 200 or the producer process exited zero. Existing source-level
validation remains authoritative: declared expected outputs must exist, be
non-empty, and satisfy source-specific row/schema thresholds.

For every live operation preserve:

- selected source candidate set;
- immutable registry root;
- writable workspace root;
- egress result;
- per-source status, row count, error, and elapsed time;
- versioned run receipt;
- source-specific raw/output provenance created by the producer;
- any contradictory observations rather than overwriting them.

## Promotion boundary

The Data Sources tab is an **ingestion/materialization plane**, not an identity
or production-certification plane. Data remains RAW/STAGED/PROCESSED according
to the producer and downstream validation state. The application must not
promote a source or entity merely because it has been downloaded.
