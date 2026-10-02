# Local Corpus Federation Contract

## Status

`PROVISIONAL_CONTROL_CONTRACT`

This contract generalizes MoneySweep's existing offline-baseline and manual-dropzone controls so an explicitly allowlisted local directory can be frozen and classified before source-specific materialization. It does **not** create a second source registry and does **not** award canonical source credit.

## Control Plane

```text
EXPLICIT_LOCAL_ROOT
  -> READ_ONLY_DISCOVERY
  -> BYTE_FREEZE_SHA256
  -> CONTENT_FORMAT_DETECTION
  -> SOURCE_FAMILY_BINDING_WHERE_AUTHORITATIVE
  -> SEMANTIC_CLASSIFICATION
  -> SOURCE_SPECIFIC_PARSER
  -> RECORD_CONSERVATION_RECEIPT
  -> RECORD_PROVENANCE_RECEIPT
  -> QUERYABILITY_GATE
```

The implementation extends `moneysweep.orchestrator.offline_baseline`, reusing the existing hashing, immutable-receipt, network-blocking, source-registry, and manual-dropzone architecture. It does not introduce a parallel registry.

## Identity Layers

The following are distinct and must never be collapsed:

- BYTE identity: exact SHA256 of the source file.
- LOGICAL identity: operator/source interpretation of the dataset.
- SCHEMA identity: parsed field structure and parser contract.
- SOURCE MANIFESTATION identity: one frozen publication/export/file instance.
- ENTITY identity: separately adjudicated legal/person/project identity.

A shared filename, normalized filename, row count, category, source absence, or proximity is never sufficient to prove entity or source identity.

## Discovery Rules

1. Only an explicit root is traversed.
2. Absolute operator paths are never persisted in receipts.
3. Symlinks are rejected; a root cannot escape through filesystem indirection.
4. Sensitive/internal path components (`.git`, `.env`, `secrets`, `credentials`) are excluded.
5. Supported extensions are allowlisted.
6. Content magic is checked independently of extension.
7. Discovery does not make a file queryable.
8. Unknown source-family bindings remain `UNRESOLVED` rather than being assigned heuristically.

## Archive Rule

ZIP-container inputs (including XLSX containers) record each non-directory member as:

```text
PATH + UNCOMPRESSED_SIZE + SHA256
```

Outer-hash equality proves byte equality only. Distinct outer hashes require payload-level comparison before classifying `PURE_RECOMPRESSION`, `SAME_PAYLOADS_DIFFERENT_PATHS`, or `DISTINCT_PAYLOADS`.

## Record Conservation Gate

A materialized source can become queryable only when all of the following hold:

```text
source_records = retained_records + excluded_records
unresolved_records = 0
provenance_complete_records = source_records
```

The receipt state is `PASS` only when all three conditions close. Otherwise it is `FAIL`, and `queryable=false`.

Excluded rows remain part of conservation arithmetic. Deduplication is not an exclusion justification unless exact row/source duplication has been demonstrated and the displaced row remains auditable.

## Provenance Minimum

Each materialized record must retain enough information to return to the source manifestation. Depending on source type this includes:

- `source_id` where a canonical registry binding exists
- source-file SHA256
- exact raw filename
- source-relative path or safe manifestation ID
- page, sheet, source row, record locator, or equivalent
- raw string/value before normalization
- parser/schema version
- extraction/materialization timestamp or deterministic snapshot identifier

`RAW`, `NORMALIZED`, and `CANONICAL` values are separate fields/layers. Mojibake, spelling defects, accents, spacing, and OCR defects in RAW are preserved exactly.

## Source-Specific Binding

Local files bind to existing source IDs only through an explicit binding map or an independently authoritative source manifest. The local inventory does not mutate `registries/source_registry.*`.

One file may support more than one existing analytical source family (for example a PRASA CER can support CIP facts and PPP-reference facts). That is a 1:N source-family relationship, not duplicate evidence.

## Queryability State Machine

```text
DISCOVERED
  -> FILE_FROZEN
  -> CLASSIFIED
  -> MATERIALIZED
  -> RECORD_CONSERVATION_PASS
  -> PROVENANCE_PASS
  -> QUERYABLE
```

No earlier state implies a later one. The inventory command therefore emits `queryable=false` by default.

## CLI

```bash
python scripts/run_offline_baseline.py \
  --input-dir /explicit/local/root \
  --output-root reports/local_corpus_run \
  --inventory-local-corpus \
  --local-bindings bindings.json \
  --generated-at 2026-08-24T12:00:00Z
```

`bindings.json` shape:

```json
{
  "bindings": {
    "Contratos Vigentes ACT.pdf": {
      "source_ids": ["act_transition_contracts"],
      "semantic_class": "CONTRACT_REGISTER",
      "evidence_class": "financial"
    }
  }
}
```

## Federation Rule

This pattern is jurisdiction-neutral. Federation consumers may reuse the manifest and conservation semantics without importing Puerto Rico-specific source names. Puerto Rico-specific bindings remain configuration/data, not generalized core logic.

## Promotion / Certification

The inventory itself may certify only bounded file conservation. It cannot certify row conservation for an unparsed PDF, workbook, database, or other source merely because hashing succeeded.

Canonical promotion remains fail-closed until source-specific parser tests, schema checks, provenance checks, record arithmetic, and applicable GUI/federation gates pass.
