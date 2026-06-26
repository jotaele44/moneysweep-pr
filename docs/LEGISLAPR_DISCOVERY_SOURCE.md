# LegislaPR T2 Discovery Source

## Active vector

`MONEYSWEEP_PR -> LEGISLAPR_T2_DISCOVERY_SOURCE -> CROSS_CONFIRMED_PROMOTION_ONLY`

## Classification

| Field | Value |
|---|---|
| Source ID | `legislapr_discovery` |
| Tier | T2 operational discovery / enrichment |
| Canonical status | Not canonical by itself |
| Canonical confirmation | OpenStates plus official Legislative Assembly/SUTRA document link |
| Promotion rule | `cross_confirmed_only` |
| Producer | `scripts/probe_legislapr_detail.py` |
| Registry extension | `registries/source_registry_extensions/legislapr_discovery.json` |
| Schema extension | `registries/schema_registry_extensions/legislapr_legislative_measure.json` |

## Rationale

LegislaPR is useful for fast legislative discovery because it exposes Puerto Rico measure identifiers, detail pages, readable status language, links, and summary text. For MoneySweep, the operational value is the ability to detect measures that may authorize, appropriate, redirect, reimburse, or otherwise structure public-money flows before those flows appear in procurement, grants, recovery, or agency-contract systems.

LegislaPR remains T2 because it is a discovery/readability layer rather than the canonical government record. MoneySweep promotes only records cross-confirmed against OpenStates and official Puerto Rico Legislative Assembly/SUTRA document links.

## Extraction model

```text
LegislaPR measure detail page
    -> measure_id normalization
    -> outbound link extraction
    -> OpenStates link check
    -> official Legislative Assembly/SUTRA document check
    -> fiscal keyword scan
    -> promotion_status assignment
```

## Promotion statuses

| Status | Meaning | MoneySweep action |
|---|---|---|
| `blocked_pending_canonical_confirmation` | LegislaPR page found but both canonical links were not extracted | Keep in staging only |
| `cross_confirmed_candidate` | OpenStates and official document found | Eligible for canonical promotion after schema validation |
| `promoted` | Reserved for a downstream promotion job after canonical validation | Canonical surface |

## Local run

```bash
python scripts/probe_legislapr_detail.py \
  --url "https://www.legislapr.com/bills/PS%20782" \
  --output data/staging/processed/pr_legislapr_measures_probe.json
```

For a batch run:

```bash
python scripts/probe_legislapr_detail.py \
  --input data/manual/legislapr/measure_urls.txt \
  --output data/staging/processed/pr_legislapr_measures_probe.json
```

## Validation

```bash
python -m pytest tests/test_legislapr_discovery.py tests/test_legislapr_discovery_probe.py -q
python -m moneysweep.runtime.source_registry --validate
```

## Key handling

OpenStates API keys must be supplied through `.env`, shell environment, or GitHub repository secrets if a future canonical OpenStates fetcher is added. Do not commit keys, captured API responses containing secrets, or debug logs that print environment values.
