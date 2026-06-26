# Funding Schema Overview

This is the umbrella view of the **funding data model** the export contract
publishes. It ties together the five streams; each has its own detail doc.

The model is a directed funding graph:

```
        funding_agency (entity)
               │  award (funding_awards.jsonl)
               ▼
          recipient (entity)
               ▲
               │  transaction (transactions.jsonl)  payer -> payee
               │
        relationships.jsonl  (entity -> entity, with evidence source)
```

## Streams

| Stream           | Grain                                   | Detail doc                              |
|------------------|-----------------------------------------|-----------------------------------------|
| `entities`       | One party (agency, recipient, …)        | [entity_schema.md](entity_schema.md)    |
| `sources`        | One upstream provenance record          | (this doc, below)                       |
| `funding_awards` | One award (grant/contract)              | [award_schema.md](award_schema.md)      |
| `transactions`   | One money movement                      | [transaction_schema.md](transaction_schema.md) |
| `relationships`  | One directed entity→entity edge         | (this doc, below)                       |

## Sources stream

Stream: `sources.jsonl` · Schema:
[`schemas/moneysweep_source.schema.json`](../schemas/moneysweep_source.schema.json)

A **source** records where rows came from. It is self-referential: a source
row's `source_id` is both its identity and its own provenance.

| Field          | Type    | Notes                                                       |
|----------------|---------|-------------------------------------------------------------|
| `source_id`    | string  | Deterministic `src_<32-hex>`. Payload: `{source_type, source_name, source_ref or source_url}`. |
| `source_type`  | string  | e.g. `federal_grants`, `federal_contracts`.                |
| `source_name`  | string  | Human-readable name.                                       |
| `source_url`   | string  | Optional. At least one of `source_url` / `source_ref` is required. |
| `source_ref`   | string  | Optional. Stable semantic ref, e.g. a `registries/source_registry.json` id (`usaspending_prime`). |
| `confidence`, `lineage`, `synthetic`, `created_at`, `extracted_at` | | Common envelope. |

The `source_ref` values align with the existing
[`registries/source_registry.json`](../registries/source_registry.json) so the
hub can map an export source back to a known upstream feed.

## Relationships stream

Stream: `relationships.jsonl` · Schema:
[`schemas/moneysweep_relationship.schema.json`](../schemas/moneysweep_relationship.schema.json)

A **relationship** is a directed edge between two entities, backed by a source
of evidence.

| Field                | Type    | Notes                                                  |
|----------------------|---------|--------------------------------------------------------|
| `relationship_id`    | string  | Deterministic `rel_<32-hex>`. Payload: `{source_entity_id, target_entity_id, relationship_type, evidence_source_id}`. |
| `source_id`          | string  | FK into `sources.jsonl`.                               |
| `source_entity_id`   | string  | FK into `entities.jsonl`.                              |
| `target_entity_id`   | string  | FK into `entities.jsonl`.                              |
| `relationship_type`  | string  | e.g. `received_award_from`, `subcontracts_to`.        |
| `evidence_source_id` | string  | FK into `sources.jsonl` — the evidence for the edge.  |
| `confidence`, `lineage`, `synthetic`, `created_at`, `extracted_at` | | Common envelope. |

## Money fields

Award and transaction `amount` values are numeric and **non-negative**;
`currency` is a 3-letter uppercase ISO-4217-shaped code (e.g. `USD`). These are
enforced by the `amount_*` and `currency_*` validation gates.

See [validation_gates.md](validation_gates.md) for the full fail-closed rule
set and [export_contract.md](export_contract.md) for the common envelope and
manifest.
