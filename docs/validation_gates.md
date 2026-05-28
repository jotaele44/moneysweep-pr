# Validation Gates

`scripts/validate_export.py` enforces the export contract. It is **fail-closed**:
any defect produces a `ValidationError(code, location, message)` and a non-zero
exit. The validator has no external dependencies — it loads the `required` lists
from [`schemas/`](../schemas) and implements value-shape rules in plain Python.

```bash
python scripts/validate_export.py --package <dir> --mode {test|production}
```

Programmatic use:

```python
from scripts.validate_export import validate_package
errors = validate_package(package_dir, mode="test")   # [] means valid
```

## Gates

| # | Code | What it catches |
|---|------|-----------------|
| 1 | `manifest_missing` | `manifest.json` is not present in the package. |
| 2 | `manifest_unparseable` | `manifest.json` is not valid JSON. |
| 3 | `manifest_files_missing` | Fewer than 5 `files[]` entries, a stream entry missing, or a declared stream file absent on disk. |
| 4 | `manifest_sha256_mismatch` | A stream file's recomputed sha256 ≠ the manifest's declared `sha256`. |
| 5 | `manifest_row_count_mismatch` | A stream file's line count ≠ the manifest's declared `record_count`. |
| 6 | `jsonl_unparseable` | A line in a stream file is not valid JSON. |
| 7 | `required_fields_missing` | A row is missing a field required by its schema (incl. the sources `source_url`/`source_ref` one-of rule). |
| 8 | `confidence_missing` / `confidence_out_of_range` | `confidence` absent, non-numeric, or outside `[0.0, 1.0]`. |
| 9 | `lineage_missing` / `lineage_invalid` | `lineage` absent, not an object, or missing `producer_script` / `producer_phase` / `source_inputs`. |
| 10 | `timestamp_invalid` | A `created_at` / `extracted_at` (row or manifest) is not a timezone-aware ISO-8601 timestamp. |
| 11 | `amount_invalid` / `amount_negative` | Money `amount` is non-numeric/non-finite, or is negative. |
| 12 | `currency_missing` / `currency_invalid` | Money `currency` absent or not `^[A-Z]{3}$`. |
| 13 | `duplicate_id` | A deterministic ID repeats within its stream file. |
| 14 | `dangling_source_ref` | A row's envelope `source_id` is not found in `sources.jsonl`. |
| 15 | `dangling_entity_ref` | An entity/source reference (`recipient_entity_id`, `funding_agency_entity_id`, `payer_entity_id`, `payee_entity_id`, `source_entity_id`, `target_entity_id`, `evidence_source_id`) does not resolve. |
| 16 | `synthetic_in_production` | In `mode=production`, a row has `synthetic: true`. |
| 17 | `federation_invalid` | `manifest.federation` is missing/malformed or does not name the `spiderweb-pr` `query-hub` consumer (`producer_repo`, `consumer_repo`, `consumer_component`, `contract`). |

## Mode differences

- **`test`** — synthetic rows are allowed; gate 16 does not fire.
- **`production`** — synthetic rows fail (gate 16). All other gates apply in
  both modes.

## Notes

- Gates 1–2 short-circuit (a missing or unparseable manifest returns
  immediately). All later gates accumulate, so a single run reports every
  defect it can find.
- The cross-repo `federation_invalid` gate (17) ensures a package can be routed
  to and version-checked by the query hub in `spiderweb-pr`. See
  [federation_readiness.md](federation_readiness.md).
