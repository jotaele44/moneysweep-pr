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

## Inflow / revenue transactions (infrastructure income)

Transactions are not limited to government outflows. The same stream represents
**money the public pays to use infrastructure** — aggregate toll, transit fare,
utility rate, and port/airport fee revenue. No schema change is needed: direction is
encoded by `payer_entity_id → payee_entity_id`, and `transaction_type` is an open
string, so an inflow is simply `{payer = aggregate public, payee = collecting agency}`
with a revenue `transaction_type`. `amount` stays non-negative.

### Inflow `transaction_type` vocabulary

| `transaction_type`     | Meaning                                   | Service domain |
|------------------------|-------------------------------------------|----------------|
| `toll_collection`      | Highway/expressway toll revenue           | toll           |
| `fare_collection`      | Transit farebox revenue                   | transit        |
| `utility_rate_revenue` | Water/power rate revenue                  | utility        |
| `port_fee_revenue`     | Port/airport wharfage, landing, fees      | port           |

### Aggregate public / ratepayer payer

Individual payers are private and unobtainable, so revenue is attributed to a
deterministic **aggregate public entity per service domain** (the only legal and
available granularity):

- `PUBLIC RATEPAYERS TOLL`, `PUBLIC RATEPAYERS TRANSIT`,
  `PUBLIC RATEPAYERS UTILITY`, `PUBLIC RATEPAYERS PORT`.

These resolve to normal `ent_<32hex>` ids through the entity crosswalk (so the
`dangling_entity_ref` gate passes) and are seeded as real aggregate-figure entities —
`synthetic` stays `false` (that flag is reserved for `test` mode). They must never be
treated as individuals. Figures are sourced from audited financial statements, MSRB
EMMA continuing-disclosure filings, and agency budgets; finer breakdowns are pursued
via FOIA. The producers populate these via `scripts/build_financial_flows_master.py`
(`_ingest_infrastructure_revenue`); `scripts/build_export_streams.py` derives the
revenue `transaction_type` from the flow's `flow_type`.

## Optional `location` (place of performance)

Since contract v1.1.0, transactions may carry the same optional inline
`location` object as awards (see [award_schema.md](award_schema.md#optional-location-place-of-performance)),
sourced from the `financial_flows_master` geo columns (`municipality`,
`geo_municipality_code`, `geo_municipality_name`, `geo_attribution_confidence`;
no lat/lon in this table). It lets the `spiderweb-pr` query hub match
transactions by location. A malformed `location` fails the `location_invalid`
gate.

## Integrity gates

- `payer_entity_id` and `payee_entity_id` must resolve in `entities.jsonl`
  (`dangling_entity_ref`).
- `source_id` must resolve in `sources.jsonl` (`dangling_source_ref`).
- `amount` finite and non-negative; `currency` a 3-letter uppercase code.
- Duplicate `transaction_id` within the file fails (`duplicate_id`).

See [validation_gates.md](validation_gates.md).
