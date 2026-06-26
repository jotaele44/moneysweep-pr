# Entity Schema

Stream: `entities.jsonl` · Schema:
[`schemas/moneysweep_entity.schema.json`](../schemas/moneysweep_entity.schema.json)

An **entity** is a named party in the funding graph: a funding agency, a prime
recipient, a sub-recipient, a contractor, etc. Entities are the nodes that
awards, transactions, and relationships reference.

## Required fields

| Field             | Type    | Notes                                                         |
|-------------------|---------|--------------------------------------------------------------|
| `entity_id`       | string  | Deterministic `ent_<32-hex>`. Payload: `{normalized_name, entity_type, jurisdiction}`. |
| `source_id`       | string  | FK into `sources.jsonl` (`src_<32-hex>`).                    |
| `name`            | string  | Display name as observed upstream.                          |
| `normalized_name` | string  | Canonicalized name used for matching/dedup.                 |
| `entity_type`     | string  | e.g. `funding_agency`, `recipient`, `sub_recipient`.        |
| `jurisdiction`    | string  | e.g. `US`, `PR`.                                            |
| `confidence`      | number  | `[0.0, 1.0]` — see [confidence_model.md](confidence_model.md). |
| `lineage`         | object  | See [lineage_model.md](lineage_model.md).                   |
| `synthetic`       | boolean | `true` only in `test` mode.                                 |
| `created_at`      | string  | ISO-8601, tz-aware.                                         |
| `extracted_at`    | string  | ISO-8601, tz-aware.                                         |

## Identity / dedup

`entity_id` is derived from `{normalized_name, entity_type, jurisdiction}`, so
the same real-world party normalizes to the same ID across deliveries. Use
`normalized_name` (not `name`) for joins. The repo's existing normalization
conventions live in `moneysweep/runtime/name_normalization.py`.

## Example (from the fixture)

```json
{"entity_id":"ent_ee9bafc35b7200bc560f2c7f2e7d7d1d","source_id":"src_633ec79b98705f6ddce6dbd6555d0cee","name":"Federal Emergency Management Agency","normalized_name":"FEDERAL EMERGENCY MANAGEMENT AGENCY","entity_type":"funding_agency","jurisdiction":"US","confidence":0.98,"lineage":{"producer_script":"scripts/build_export_package.py","producer_phase":"EXPORT_PACKAGE_BUILD","source_inputs":["data/processed/entity_master.csv"],"extraction_method":"deterministic_canonicalization"},"synthetic":true,"created_at":"2024-01-15T12:00:00Z","extracted_at":"2024-01-15T12:00:00Z"}
```

## Optional `external_ids` (cross-repo matching)

Since contract v1.1.0, entities may carry an optional `external_ids` object so
the `spiderweb-pr` query hub can match on a strong identifier rather than only
`normalized_name`:

| Field | Type | Source column |
|---|---|---|
| `uei` | string | `entity_uei` |
| `parent_uei` | string | `parent_uei` |

Populated subfields only; synthesized funding-agency entities (which have no
UEI) omit the object. A non-object `external_ids` (or non-string value) fails
the `external_ids_invalid` gate.

## Referential integrity

Every `entity_id` referenced by awards (`recipient_entity_id`,
`funding_agency_entity_id`), transactions (`payer_entity_id`,
`payee_entity_id`), and relationships (`source_entity_id`, `target_entity_id`)
must appear in `entities.jsonl`. Dangling references fail the
`dangling_entity_ref` gate — see [validation_gates.md](validation_gates.md).
