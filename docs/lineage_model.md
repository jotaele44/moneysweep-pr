# Lineage Model

Every exported row carries provenance so the query hub (and auditors) can trace
a value back to the producer step and the upstream inputs that fed it.

Provenance is split across two places on each row:

- **`extracted_at`** (top-level, ISO-8601 tz-aware) — *when* the row was
  extracted from the upstream source.
- **`lineage`** (object) — *how* and *from what* the row was produced.

## `lineage` object

| Field              | Type        | Required | Notes                                                |
|--------------------|-------------|----------|------------------------------------------------------|
| `producer_script`  | string      | yes      | The script that produced the row, e.g. `scripts/build_export_package.py`. |
| `producer_phase`   | string      | yes      | Logical phase/stage, e.g. `EXPORT_PACKAGE_BUILD`.    |
| `source_inputs`    | string[]    | yes      | Upstream input paths/refs the row was derived from.  |
| `extraction_method`| string      | no       | How the value was derived, e.g. `deterministic_canonicalization`. |

Example:

```json
{
  "producer_script": "scripts/build_export_package.py",
  "producer_phase": "EXPORT_PACKAGE_BUILD",
  "source_inputs": ["data/processed/entity_master.csv", "data/processed/funding_awards.csv"],
  "extraction_method": "deterministic_canonicalization"
}
```

## Alignment with the existing repo

This vocabulary intentionally mirrors the in-repo artifact lineage model in
[`moneysweep/validation/artifact_lineage.py`](../moneysweep/validation/artifact_lineage.py),
which already tracks `producer_script`, `producer_phase`, and `source_inputs`
for internal artifacts. Reusing the same terms keeps producer-internal lineage
and the federation export lineage consistent.

## Validation

The validator fails closed when:

- `lineage` is absent → `lineage_missing`.
- `lineage` is not an object, or `producer_script` / `producer_phase` /
  `source_inputs` are missing or the wrong type → `lineage_invalid`.
- `created_at` or `extracted_at` is not a timezone-aware ISO-8601 timestamp →
  `timestamp_invalid`.

See [validation_gates.md](validation_gates.md).
