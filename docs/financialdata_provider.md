# FinancialData.net Provider — Optional Commercial Enrichment

**Status:** Optional. Disabled by default. Never required for pipeline coverage gates.

**Use case:** public-market entity resolution only — CUSIP / ISIN / FIGI / LEI / CIK / ticker
crosswalks for the small subset of contractor entities that are US-listed publics.

This adapter exists as gated scaffolding so a future operator decision to license
FinancialData.net can be activated without re-architecting. The strategic decision
to subscribe has **not** been made; the scaffolding is mock-first.

## How it stays off by default

Live calls require **both** of the following to be true:

| Setting                          | Required value           | Where                |
|----------------------------------|--------------------------|----------------------|
| `FINANCIALDATA_API_KEY`          | non-empty                | env or `.env`        |
| `FINANCIALDATA_LICENSE_APPROVED` | `true` / `1` / `yes`     | env or `.env`        |

If either is missing the provider:
- emits a structured `ProviderReadiness` payload with `status` in
  `{"missing_key", "missing_license", "missing_both"}`,
- runs the CLI in dry-run/mock mode using synthetic fixtures,
- writes outputs (possibly empty) and a `readiness.json` report,
- exits successfully — the pipeline does **not** treat absence as failure.

## Supported endpoints (stubs)

All paths are placeholders pending vendor doc confirmation at first live call:

| Method                              | Path (placeholder)                 |
|-------------------------------------|------------------------------------|
| `company_information(identifier)`   | `/company`                         |
| `securities_information(identifier)`| `/securities`                      |
| `institutional_holdings(identifier)`| `/institutional-holdings`          |
| `investment_adviser_information(identifier)` | `/investment-advisers`     |

Every endpoint goes through a single `_request(...)` chokepoint that:
- builds the URL from the centralized `ENDPOINTS` table,
- attaches auth header + standard timeout,
- delegates to the injected transport (default refuses to run),
- retries transient failures with backoff.

The default transport raises if invoked without configuration — so a forgotten
`patch` in a test will fail loudly rather than reach the network.

## Evidence-tier treatment

| Match kind                                              | `evidence_tier` | `review_required` |
|---------------------------------------------------------|-----------------|-------------------|
| Deterministic identifier match (CUSIP/ISIN/FIGI/LEI/CIK/ticker) | T1       | false             |
| Exact normalized name + identifier carried              | T2              | false             |
| Exact normalized name, no identifier                    | T3              | false             |
| Fuzzy name match (with identifier)                      | T2              | true              |
| Fuzzy name match (no identifier)                        | T4              | true              |
| Ambiguous multi-candidate                               | T3              | true              |
| No public-market candidate                              | T4              | false             |

Vendor-description-only rows are always T4 — they describe the entity but don't
prove identity.

## No raw payload persistence

Every output row carries `raw_payload_stored=false`. Vendor responses are
consumed in memory, normalized into the schema, and discarded. If a future
licensing review changes this policy, the schema field must be flipped
explicitly per row.

## Outputs

| Path                                                    | Purpose                              |
|---------------------------------------------------------|--------------------------------------|
| `outputs/enrichment/financialdata_identifier_crosswalk.csv` | Matched rows carrying ≥1 identifier |
| `outputs/enrichment/financialdata_entity_matches.csv`   | All non-review matched rows          |
| `outputs/review/financialdata_match_review_queue.csv`   | Rows requiring manual review         |
| `reports/financialdata_enrichment_readiness.json`       | Gate status + run metadata           |

## Files

| Layer        | Path                                                            |
|--------------|-----------------------------------------------------------------|
| Schema       | `schemas/canonical_v1/financialdata_enrichment.schema.json`     |
| Provider     | `scripts/providers/financialdata_net.py`                        |
| Base / iface | `scripts/providers/__init__.py`                                 |
| CLI / runner | `scripts/enrichment/enrich_financialdata_entities.py`           |
| Config       | `get_financialdata_api_key()`, `is_financialdata_license_approved()` in `scripts/config.py` |
| Tests        | `tests/test_financialdata_provider.py`                          |
| Fixture      | `tests/fixtures/financialdata_synthetic_entities.csv`           |
| Registry     | `financialdata_net` source in `registries/source_registry.yaml` |
