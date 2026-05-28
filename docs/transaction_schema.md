# Transaction Schema

Stream: `transactions.jsonl` · Schema:
[`schemas/contract_sweeper_transaction.schema.json`](../schemas/contract_sweeper_transaction.schema.json)

A **transaction** is a single movement of money between two entities — a
disbursement, obligation, reimbursement, etc. Where an award is the agreement,
transactions are the cash flows under it.

## Required fields

| Field              | Type    | Notes                                                       |
|--------------------|---------|-------------------------------------------------------------|
| `transaction_id`   | string  | Deterministic `txn_<32-hex>`. See payload below.            |
| `source_id`        | string  | FK into `sources.jsonl`.                                    |
| `payer_entity_id`  | string  | FK into `entities.jsonl` (who paid).                        |
| `payee_entity_id`  | string  | FK into `entities.jsonl` (who received).                    |
| `amount`           | number  | Non-negative.                                              |
| `currency`         | string  | 3-letter uppercase code (e.g. `USD`).                      |
| `transaction_date` | string  | ISO-8601 date (`YYYY-MM-DD`).                              |
| `transaction_type` | string  | e.g. `disbursement`, `obligation`, `reimbursement`.        |
| `confidence`       | number  | `[0.0, 1.0]`.                                              |
| `lineage`          | object  | See [lineage_model.md](lineage_model.md).                  |
| `synthetic`        | boolean | `true` only in `test` mode.                                |
| `created_at`       | string  | ISO-8601, tz-aware.                                        |
| `extracted_at`     | string  | ISO-8601, tz-aware.                                        |

## Identity

`transaction_id` is derived from the canonical payload:

```
{source_id, payer_entity_id, payee_entity_id, transaction_date, amount, currency, transaction_type}
```

## Example (from the fixture)

```json
{"transaction_id":"txn_0624b7f4231a96ef917e56c60e8dfcfd","source_id":"src_633ec79b98705f6ddce6dbd6555d0cee","payer_entity_id":"ent_ee9bafc35b7200bc560f2c7f2e7d7d1d","payee_entity_id":"ent_9f4831646edda3ece7dd1ff3a8b8738c","amount":1000000.0,"currency":"USD","transaction_date":"2023-03-20","transaction_type":"disbursement","confidence":0.9,"lineage":{"producer_script":"scripts/build_export_package.py","producer_phase":"EXPORT_PACKAGE_BUILD","source_inputs":["data/processed/funding_awards.csv"],"extraction_method":"deterministic_canonicalization"},"synthetic":true,"created_at":"2024-01-15T12:00:00Z","extracted_at":"2024-01-15T12:00:00Z"}
```

## Integrity gates

- `payer_entity_id` and `payee_entity_id` must resolve in `entities.jsonl`
  (`dangling_entity_ref`).
- `source_id` must resolve in `sources.jsonl` (`dangling_source_ref`).
- `amount` finite and non-negative; `currency` a 3-letter uppercase code.
- Duplicate `transaction_id` within the file fails (`duplicate_id`).

See [validation_gates.md](validation_gates.md).
