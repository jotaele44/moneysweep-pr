# Export Mapping — canonical masters → export streams

`scripts/build_export_streams.py` maps the pipeline's canonical master tables
into the five federation export streams. It **reads** already-produced masters
and writes pre-shaped JSONL; it does not run or modify any pipeline stage. The
streams it emits are designed to pass
`validate_export.validate_package(..., mode="production")`.

See [`export_contract.md`](export_contract.md) for the package/manifest shape
and [`validation_gates.md`](validation_gates.md) for the fail-closed rules.

## Inputs

Canonical tables (column names per `registries/schema_registry.json`), read
from `--processed-dir` (default `data/staging/processed/`):

| File | Canonical table |
|------|-----------------|
| `entities_resolved.csv` | `entities_resolved` |
| `contracts_master.csv` | `contracts_master` |
| `financial_flows_master.csv` | `financial_flows_master` |
| `entity_edges.csv` | `entity_edges` |

Sources are derived from `registries/source_registry.json` plus the source
identifiers actually referenced by the data. Missing input files yield an empty
stream rather than an error.

## Field mapping

### entities ← `entities_resolved.csv`
| Export field | Source |
|---|---|
| `entity_id` | `ent_<sha256[:32]>` of `{normalized_name, entity_type, jurisdiction}` |
| `source_id` | the derived source `moneysweep_resolution` |
| `name` | `entity_name` |
| `normalized_name` | `normalized_name` (else `normalize_name(entity_name)`) |
| `entity_type` | `entity_type` (default `recipient`) |
| `jurisdiction` | `US` (default — see decisions) |
| `external_ids` (optional) | `{uei: entity_uei, parent_uei: parent_uei}` (populated subfields only; synthesized agencies omit it) |
| `confidence` | `match_confidence` (clamped to `[0,1]`) |
| `lineage` | `producer_script=scripts/entity_resolution.py`, `source_inputs=source_files`, `extraction_method=resolution_method` |

### sources ← `source_registry.json` ∪ referenced source ids
| Export field | Source |
|---|---|
| `source_id` | `src_<sha256[:32]>` of `{source_type, source_name, source_ref}` |
| `source_type` | registry `family` (else `derived`/`external`) |
| `source_name` | first line of registry `notes` (else titleized ref) |
| `source_ref` | the source identifier string (e.g. `usaspending_prime`) |
| `source_url` | registry `endpoint_url` (when known) |

### funding_awards ← `contracts_master.csv`
| Export field | Source |
|---|---|
| `award_id` | `awd_<sha256[:32]>` of `{source_id, recipient_entity_id, funding_agency_entity_id, award_date, amount, currency, fiscal_year}` |
| `source_id` | `source_system` → src id |
| `recipient_entity_id` | crosswalk(`recipient_uei` → `normalized_name` → `recipient_name`) |
| `funding_agency_entity_id` | synthesized agency from `awarding_agency` |
| `amount` | `obligation_amount` |
| `currency` | `USD` |
| `fiscal_year` | `fiscal_year` |
| `award_type` | `funding_source` (default `contract`) |
| `award_date` | `award_date` |
| `confidence` | `link_confidence` |
| `location` (optional) | from geo_* columns (see below) |

### transactions ← `financial_flows_master.csv`
| Export field | Source |
|---|---|
| `transaction_id` | `txn_<sha256[:32]>` of `{source_id, payer_entity_id, payee_entity_id, transaction_date, amount, currency, transaction_type}` |
| `source_id` | `source_system` → src id |
| `payer_entity_id` | synthesized agency from `funding_source` |
| `payee_entity_id` | crosswalk(`recipient_entity_id`) |
| `amount` | `amount` |
| `currency` | `USD` |
| `transaction_date` | `flow_date` |
| `transaction_type` | `disbursement` |
| `confidence` | `link_confidence` |
| `location` (optional) | from geo_* columns (see below) |

### relationships ← `entity_edges.csv`
| Export field | Source |
|---|---|
| `relationship_id` | `rel_<sha256[:32]>` of `{source_entity_id, target_entity_id, relationship_type, evidence_source_id}` |
| `source_id` / `evidence_source_id` | `source_dataset` → src id |
| `source_entity_id` | crosswalk(`source`) |
| `target_entity_id` | crosswalk(`target`) |
| `relationship_type` | `edge_type` |
| `confidence` | `confidence` |

### location (inline, v1.1.0) ← geo_* columns

Emitted on awards & transactions only when `geo_municipality_code` or
`municipality` is present; populated subfields only.

| Export `location.*` | Source column |
|---|---|
| `country` | (default `US`) |
| `municipality` | `municipality` |
| `municipality_code` | `geo_municipality_code` (primary match key) |
| `municipality_name` | `geo_municipality_name` |
| `county_fips` | `geo_county_fips` (awards only) |
| `postal_code` | `geo_zip` (awards only) |
| `latitude` / `longitude` | `geo_lat` / `geo_lon` (awards only) |
| `attribution_source` | `geo_attribution_source` |
| `attribution_confidence` | `geo_attribution_confidence` |

## Reused helpers

- `moneysweep/runtime/name_normalization.py:normalize_name`
- `moneysweep/runtime/linkage_confidence.py` (confidence is `[0,1]`;
  `MANUAL_REVIEW_THRESHOLD = 0.90`)
- `scripts/build_export_package.py` (`_deterministic_id`, `build_package`)
- `scripts/validate_export.py` (`validate_package`)

## Crosswalk and agency synthesis

Repo entities use UEI / internal IDs; the export uses `ent_<hash>`. A crosswalk
keyed by `(uei, internal entity_id, normalized_name, name)` maps to export
`entity_id`. Funding agencies referenced by `awarding_agency` /
`funding_source` are not always in `entities_resolved`, so the mapper
synthesizes `entity_type=funding_agency` entities (own deterministic IDs) and
registers them in the crosswalk.

## Decisions

- **`jurisdiction` defaults to `US`** — the masters don't carry a jurisdiction
  column. (A geo/municipality-driven `PR` refinement is left for future work.)
- **`currency` is `USD`.**
- **Missing input confidence defaults to `0.5`**; present values are clamped to
  `[0,1]`. Low-confidence rows are exported as-is (the hub filters downstream) —
  there is no `0.90` cutoff at the producer.
- **All rows are `synthetic: false`** (production data).

## Fail-closed skip rules

A row is **excluded and tallied** (never emitted) when it would produce:

| Reason (report key) | Stream(s) |
|---|---|
| `sentinel_or_aggregate` (e.g. `MULTIPLE RECIPIENTS`, `entity_type=aggregate`) | entities |
| `invalid_or_negative_amount` | awards, transactions |
| `bad_date` / `bad_fiscal_year` | awards, transactions |
| `unresolved_recipient` / `unresolved_agency` | awards |
| `unresolved_payer` / `unresolved_payee` | transactions |
| `unresolved_endpoint` | relationships |

Rows are de-duped by deterministic ID and **sorted by ID before writing** for
byte-stable output (stable sha256 / `package_id`).

## Run

```bash
# Map only:
python scripts/build_export_streams.py \
    --processed-dir data/staging/processed --staging-dir /tmp/streams

# Map -> package -> validate (production) in one command:
python scripts/run_export.py --processed-dir data/staging/processed

# CI-safe demo against committed sample inputs:
python scripts/run_export.py --processed-dir tests/fixtures/sample_master_inputs
```
