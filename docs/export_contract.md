# Export Contract

The **export contract** defines how Contract-Sweeper publishes data for the
federation. Contract-Sweeper is a *producer*: it emits portable, validated
**export packages** that the **query hub** (the `query-hub` component inside the
[`spiderweb-pr`](#cross-repo-federation-handshake) repo) ingests.

- **Contract name:** `contract-sweeper-export`
- **Contract version:** `1.0.0` (field `export_contract_version`)

This document is the index for the contract. Per-stream field details live in
[`funding_schema.md`](funding_schema.md), [`entity_schema.md`](entity_schema.md),
[`award_schema.md`](award_schema.md), [`transaction_schema.md`](transaction_schema.md);
cross-cutting concerns in [`lineage_model.md`](lineage_model.md),
[`confidence_model.md`](confidence_model.md), [`validation_gates.md`](validation_gates.md),
and [`federation_readiness.md`](federation_readiness.md).

## Package layout

A package is a directory containing a manifest plus five JSONL stream files:

```
<package>/
  manifest.json
  entities.jsonl
  sources.jsonl
  funding_awards.jsonl
  transactions.jsonl
  relationships.jsonl
```

Each line of a `.jsonl` file is one JSON object (one row). The JSON Schema for
each stream lives in [`schemas/`](../schemas):

| Stream             | File                    | Schema                                            |
|--------------------|-------------------------|---------------------------------------------------|
| entities           | `entities.jsonl`        | `contract_sweeper_entity.schema.json`             |
| sources            | `sources.jsonl`         | `contract_sweeper_source.schema.json`             |
| funding_awards     | `funding_awards.jsonl`  | `contract_sweeper_funding_award.schema.json`      |
| transactions       | `transactions.jsonl`    | `contract_sweeper_transaction.schema.json`        |
| relationships      | `relationships.jsonl`   | `contract_sweeper_relationship.schema.json`       |
| (manifest)         | `manifest.json`         | `contract_sweeper_export_manifest.schema.json`    |

## Common row envelope

Every row in every stream carries this envelope:

| Field          | Type    | Notes                                                       |
|----------------|---------|-------------------------------------------------------------|
| `source_id`    | string  | FK into `sources.jsonl` (`src_<32-hex>`). A source row's own `source_id` is its provenance. |
| `lineage`      | object  | Provenance metadata — see [`lineage_model.md`](lineage_model.md). |
| `confidence`   | number  | `[0.0, 1.0]` — see [`confidence_model.md`](confidence_model.md). |
| `synthetic`    | boolean | `true` rows are allowed in `test` mode, rejected in `production`. |
| `created_at`   | string  | ISO-8601, timezone-aware. When the export row was created.   |
| `extracted_at` | string  | ISO-8601, timezone-aware. When the row was extracted upstream.|

Each stream additionally has its own identity field and payload — see the
per-stream docs.

## Deterministic IDs

Every ID is deterministic: `<prefix>_<sha256(canonical_payload)[:32]>` (lowercase
hex over canonical JSON with sorted keys and no whitespace). Prefixes: `src`,
`ent`, `awd`, `txn`, `rel`, and `pkg` (package). Re-running the producer over
the same upstream facts yields identical IDs, so the hub can dedupe and
reconcile across deliveries. The canonical helper is
`scripts/build_export_package.py:_deterministic_id`.

## Modes

- **`test`** — synthetic rows (`synthetic: true`) are permitted. Used for
  fixtures, samples, and CI.
- **`production`** — synthetic rows are rejected (fail-closed). Only real,
  sourced data may ship.

## Manifest

`manifest.json` is the package's table of contents and handshake:

```json
{
  "package_id": "pkg_<32-hex>",
  "producer": "contract-sweeper",
  "producer_version": "0.1.0",
  "export_contract_version": "1.0.0",
  "mode": "test",
  "created_at": "2024-01-15T12:00:00Z",
  "extracted_at": "2024-01-15T12:00:00Z",
  "federation": {
    "producer_repo": "contract-sweeper",
    "consumer_repo": "spiderweb-pr",
    "consumer_component": "query-hub",
    "contract": "contract-sweeper-export"
  },
  "coverage_window": { "fiscal_year_min": 2023, "fiscal_year_max": 2023 },
  "files": [
    {
      "filename": "funding_awards.jsonl",
      "stream": "funding_awards",
      "record_count": 1,
      "sha256": "<64-hex>",
      "schema_id": "contract_sweeper_funding_award.schema.json"
    }
  ]
}
```

`files[]` has exactly five entries (one per stream), each with a `sha256` and
`record_count` the validator recomputes and compares.

## Cross-repo federation handshake

The `federation` block makes the package routable to its consumer. The query
hub is **not** an independent repo — it is the `query-hub` component within the
`spiderweb-pr` repo. On ingest the hub:

1. Reads `federation.contract` (`contract-sweeper-export`) to route the package.
2. Checks `export_contract_version` against its supported set — this is the
   **single compatibility key**; no version is duplicated inside the federation
   block, to avoid drift.
3. Validates the package against the same fail-closed gates documented in
   [`validation_gates.md`](validation_gates.md).

See [`federation_readiness.md`](federation_readiness.md) for the full topology
and the producer/consumer boundary.

## Producing and validating

```bash
python scripts/build_export_package.py --output-dir exports/build_demo
python scripts/validate_export.py --package exports/build_demo --mode test
python scripts/smoke_export.py        # build to tempdir + validate, no network
```
