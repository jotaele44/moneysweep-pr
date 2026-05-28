# Federation Readiness

This document describes how Contract-Sweeper participates in the federation as a
**producer**, and the state of the producer side after this change.

## Cross-repo topology

```
  ┌─────────────────────────┐        export package (manifest + 5 JSONL)
  │   Contract-Sweeper       │  ───────────────────────────────────────────►
  │   (producer)             │        exports/<package>/                      │
  └─────────────────────────┘                                                 ▼
                                                       ┌──────────────────────────────┐
                                                       │  spiderweb-pr  repo            │
                                                       │  └── query-hub  (consumer)     │
                                                       │       ingests + validates      │
                                                       └──────────────────────────────┘
```

Key fact: the **query hub is not an independent repo**. It is the `query-hub`
component that lives inside the **`spiderweb-pr`** repo. Contract-Sweeper and
`spiderweb-pr` communicate through the export package on disk/artifact — there is
no shared runtime, database, or network service between them.

## Producer / consumer boundary

| Concern | Owner |
|---------|-------|
| Producing canonical rows (entities, sources, awards, transactions, relationships) | Contract-Sweeper |
| Deterministic IDs, lineage, confidence, synthetic flags | Contract-Sweeper |
| Packaging (`manifest.json` + JSONL) and `federation` handshake | Contract-Sweeper |
| Fail-closed self-validation before hand-off | Contract-Sweeper |
| Discovering, ingesting, indexing, and querying packages | `spiderweb-pr` `query-hub` |
| Hub-side adapters / storage / query API | `spiderweb-pr` (out of scope here) |

## The handshake

Each package's `manifest.json` carries a `federation` block:

```json
"federation": {
  "producer_repo": "contract-sweeper",
  "consumer_repo": "spiderweb-pr",
  "consumer_component": "query-hub",
  "contract": "contract-sweeper-export"
}
```

On ingest the hub routes on `federation.contract` and confirms compatibility
against the top-level `export_contract_version` (`1.0.0`) — the **single**
compatibility key. The validator's `federation_invalid` gate makes a package
that does not name the `spiderweb-pr` `query-hub` consumer fail closed on the
producer side, before it is ever handed off.

## What is in place after this change (producer end)

- Versioned export contract (`contract-sweeper-export` v`1.0.0`) with JSON
  Schemas for all five streams plus the manifest.
- Deterministic IDs, common row envelope (`source_id`, `lineage`, `confidence`,
  `synthetic`, `created_at`, `extracted_at`).
- A builder (`scripts/build_export_package.py`) that packages pre-shaped JSONL
  and writes the manifest + federation handshake.
- A fail-closed validator (`scripts/validate_export.py`) with 17 gates.
- A no-network smoke runner (`scripts/smoke_export.py`).
- A committed sample package (`exports/samples/`) and a test fixture
  (`tests/fixtures/valid_funding_entity_export/`).

## Explicitly out of scope

The following are **not** part of this producer-side change:

- The query hub itself and any hub-side ingest adapter (these live in
  `spiderweb-pr`).
- Frontend, backend API, Spatial-RAG runtime, pgvector, PostGIS runtime, canvas
  UI, or a citation answer engine.
- Wiring the existing ETL / scrapers / analytics to emit canonical export rows.
  The builder consumes *pre-shaped* JSONL; mapping the live pipeline outputs into
  that shape is a separate, later step.

## Next steps (future work)

1. Map `data/processed/` master outputs into the five canonical streams.
2. Emit production-mode packages (`synthetic: false`) on a schedule.
3. Coordinate the `spiderweb-pr` `query-hub` ingest adapter against this
   contract version.
