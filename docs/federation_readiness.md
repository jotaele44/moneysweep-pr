# Federation Readiness

This document describes how moneysweep-pr participates in the federation as a
**producer**, and the state of the producer side after this change.

## Cross-repo topology

```
  ┌─────────────────────────┐        export package (manifest + 5 JSONL)
  │   moneysweep-pr       │  ───────────────────────────────────────────►
  │   (producer)             │        exports/<package>/                      │
  └─────────────────────────┘                                                 ▼
                                                       ┌──────────────────────────────┐
                                                       │  spiderweb-pr  repo            │
                                                       │  └── query-hub  (consumer)     │
                                                       │       ingests + validates      │
                                                       └──────────────────────────────┘
```

Key fact: the **query hub is not an independent repo**. It is the `query-hub`
component that lives inside the **`spiderweb-pr`** repo. moneysweep-pr and
`spiderweb-pr` communicate through the export package on disk/artifact — there is
no shared runtime, database, or network service between them.

## Producer / consumer boundary

| Concern | Owner |
|---------|-------|
| Producing canonical rows (entities, sources, awards, transactions, relationships) | moneysweep-pr |
| Deterministic IDs, lineage, confidence, synthetic flags | moneysweep-pr |
| Packaging (`manifest.json` + JSONL) and `federation` handshake | moneysweep-pr |
| Fail-closed self-validation before hand-off | moneysweep-pr |
| Discovering, ingesting, indexing, and querying packages | `spiderweb-pr` `query-hub` |
| Hub-side adapters / storage / query API | `spiderweb-pr` (out of scope here) |

## The handshake

Each package's `manifest.json` carries a `federation` block:

```json
"federation": {
  "producer_repo": "moneysweep-pr",
  "consumer_repo": "spiderweb-pr",
  "consumer_component": "query-hub",
  "contract": "moneysweep-pr-export"
}
```

On ingest the hub routes on `federation.contract` and confirms compatibility
against the top-level `export_contract_version` (`1.0.0`) — the **single**
compatibility key. The validator's `federation_invalid` gate makes a package
that does not name the `spiderweb-pr` `query-hub` consumer fail closed on the
producer side, before it is ever handed off.

## What is in place after this change (producer end)

- Versioned export contract (`moneysweep-pr-export` v`1.0.0`) with JSON
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

## v1.1.0 — matching fields

Contract v1.1.0 (additive, backward compatible) adds the join keys the
`spiderweb-pr` `query-hub` needs to match moneysweep-pr data:

- **`location`** (inline, optional) on awards & transactions — place of
  performance (`municipality_code`, lat/lon, …) for spatial matching.
- **`external_ids`** (optional) on entities — `uei` / `parent_uei` for strong
  cross-repo entity matching.

A 1.0.0 consumer ignores these fields; `export_contract_version` remains the
single compatibility key.

## Cross-repo release & handshake procedure

The federation export contract is versioned **independently** of any
moneysweep-pr software release. Its single source of truth is
`scripts/build_export_package.py:EXPORT_CONTRACT_VERSION` (currently `1.2.0`).
Three on-disk places mirror that literal and are pinned to it by
`tests/test_conformance_fixture_freshness.py`:

- `exports/conformance/v1_2/manifest.json` (the golden conformance package),
- `exports/samples/manifest.sample.json`,
- `schemas/moneysweep_export_manifest.schema.json` (`const`).

> The finance-lane **report** contract (`readiness/moneysweep_finance_lane.py`,
> `1.0.0`) is a *separate* contract on its own version track. Do not couple the two.

### When you bump the federation contract version

Compatibility is matched on `export_contract_version` alone, so versioning policy is:

| Change to the export shape | Version bump |
|----------------------------|--------------|
| New **optional** field a 1.x consumer can ignore (e.g. the v1.1.0 `location`/`external_ids` adds) | **minor** |
| Field removed/renamed, type narrowed, or a new **required** field | **major** |
| Doc/comment-only, no wire change | none |

Producer-side steps for a bump (all in one PR against `main`):

1. Edit `EXPORT_CONTRACT_VERSION` in `scripts/build_export_package.py`.
2. Update the schema `const` and regenerate the sample + conformance manifests
   (`python scripts/run_export.py … --mode test` into the fixture dir, or hand-edit
   the literal) so `tests/test_conformance_fixture_freshness.py` passes.
3. Add a `CHANGELOG.md` entry under **Unreleased** describing the contract change.
4. Bump the schema/fixture directory name if it is a **major** version
   (`exports/conformance/v1_2/` → `v2_0/`).

### What happens on merge

When the PR lands on `main`, `.github/workflows/release-tag.yml` resolves the new
`EXPORT_CONTRACT_VERSION`, and — only if no `export-v<version>` tag exists yet —
creates that annotated tag and a matching GitHub release. The workflow is
idempotent and non-gating: it reacts to the bump, it never blocks the merge.

### Coordinating with `spiderweb-pr`

1. Producer cuts the `export-v<version>` tag (above).
2. Notify the `spiderweb-pr` maintainers with the tag and the CHANGELOG entry.
   The `query-hub` ingest adapter reads `export_contract_version` from each
   package's `manifest.json` and gates ingestion on a compatible range.
3. For a **minor** bump, existing hub consumers keep working (additive only);
   for a **major** bump, the hub adapter must be updated to the new shape
   **before** production packages at that version are emitted.
4. The committed `exports/conformance/v<version>/` package is the contract test
   both sides validate against — it is the shared source of truth for the wire shape.

## Next steps (future work)

1. Map `data/processed/` master outputs into the five canonical streams.
2. Emit production-mode packages (`synthetic: false`) on a schedule.
3. Coordinate the `spiderweb-pr` `query-hub` ingest adapter against this
   contract version.
