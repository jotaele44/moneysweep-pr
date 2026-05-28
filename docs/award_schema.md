# Award Schema

Stream: `funding_awards.jsonl` · Schema:
[`schemas/contract_sweeper_funding_award.schema.json`](../schemas/contract_sweeper_funding_award.schema.json)

A **funding award** is a grant, contract, or other obligation from a funding
agency to a recipient.

## Required fields

| Field                      | Type    | Notes                                                       |
|----------------------------|---------|-------------------------------------------------------------|
| `award_id`                 | string  | Deterministic `awd_<32-hex>`. See payload below.            |
| `source_id`                | string  | FK into `sources.jsonl`.                                    |
| `recipient_entity_id`      | string  | FK into `entities.jsonl` (the awardee).                     |
| `funding_agency_entity_id` | string  | FK into `entities.jsonl` (the funder).                      |
| `amount`                   | number  | Non-negative.                                              |
| `currency`                 | string  | 3-letter uppercase code (e.g. `USD`).                      |
| `fiscal_year`              | integer | Federal fiscal year.                                       |
| `award_type`               | string  | e.g. `grant`, `contract`, `cooperative_agreement`.         |
| `award_date`               | string  | ISO-8601 date (`YYYY-MM-DD`).                              |
| `confidence`               | number  | `[0.0, 1.0]`.                                              |
| `lineage`                  | object  | See [lineage_model.md](lineage_model.md).                  |
| `synthetic`                | boolean | `true` only in `test` mode.                                |
| `created_at`               | string  | ISO-8601, tz-aware.                                        |
| `extracted_at`             | string  | ISO-8601, tz-aware.                                        |

## Identity

`award_id` is derived from the canonical payload:

```
{source_id, recipient_entity_id, funding_agency_entity_id, award_date, amount, currency, fiscal_year}
```

The same award from the same source resolves to the same `award_id` across
deliveries.

## Example (from the fixture)

```json
{"award_id":"awd_b1fcdb9babfc5800d24f68d9072c52bc","source_id":"src_633ec79b98705f6ddce6dbd6555d0cee","recipient_entity_id":"ent_9f4831646edda3ece7dd1ff3a8b8738c","funding_agency_entity_id":"ent_ee9bafc35b7200bc560f2c7f2e7d7d1d","amount":1000000.0,"currency":"USD","fiscal_year":2023,"award_type":"grant","award_date":"2023-03-15","confidence":0.92,"lineage":{"producer_script":"scripts/build_export_package.py","producer_phase":"EXPORT_PACKAGE_BUILD","source_inputs":["data/processed/funding_awards.csv"],"extraction_method":"deterministic_canonicalization"},"synthetic":true,"created_at":"2024-01-15T12:00:00Z","extracted_at":"2024-01-15T12:00:00Z"}
```

## Optional `location` (place of performance)

Since contract v1.1.0, awards may carry an optional inline `location` object so
the `spiderweb-pr` query hub can match awards to its locations. All subfields
are optional; the producer emits the object only when a municipality / municipality
code is known.

| Field | Type | Source column |
|---|---|---|
| `country` | string | (default `US`) |
| `municipality` | string | `municipality` |
| `municipality_code` | string | `geo_municipality_code` (primary match key) |
| `municipality_name` | string | `geo_municipality_name` |
| `county_fips` | string | `geo_county_fips` |
| `postal_code` | string | `geo_zip` |
| `latitude` | number | `geo_lat` (in `[-90, 90]`) |
| `longitude` | number | `geo_lon` (in `[-180, 180]`) |
| `attribution_source` | string | `geo_attribution_source` |
| `attribution_confidence` | number | `geo_attribution_confidence` (`[0,1]`) |

A malformed `location` (bad lat/lon range or `attribution_confidence`) fails the
`location_invalid` gate. See [export_mapping.md](export_mapping.md).

## Integrity gates

- `recipient_entity_id` and `funding_agency_entity_id` must resolve in
  `entities.jsonl` (`dangling_entity_ref`).
- `source_id` must resolve in `sources.jsonl` (`dangling_source_ref`).
- `amount` must be finite and non-negative (`amount_invalid` / `amount_negative`).
- `currency` must match `^[A-Z]{3}$` (`currency_missing` / `currency_invalid`).
- Duplicate `award_id` within the file fails (`duplicate_id`).

See [validation_gates.md](validation_gates.md).
