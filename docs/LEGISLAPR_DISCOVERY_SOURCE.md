# LegislaPR T2 Discovery Source

## Active vector

`MONEYSWEEP_PR -> LEGISLAPR_T2_DISCOVERY_SOURCE -> CROSS_CONFIRMED_PROMOTION_ONLY`

## Classification

| Field | Value |
|---|---|
| Discovery source ID | `legislapr_discovery` |
| Session source ID | `legislapr_sessions` |
| Canonical source ID | `legislative_canonical_sources` |
| Crosswalk source ID | `osl_sutra_crosswalk` |
| Link source ID | `legislative_fiscal_link_candidates` |
| Discovery tier | T2 operational discovery / enrichment |
| Canonical status | Cross-confirmed candidate only |
| Canonical confirmation | OpenStates plus official document link |
| Promotion rule | `cross_confirmed_only` |
| Registry merge utility | `scripts/merge_legislapr_registry.py` |

## Rationale

LegislaPR is useful for fast legislative discovery because it exposes Puerto Rico measure identifiers, detail pages, readable status language, links, and summary text. For MoneySweep, the operational value is the ability to detect measures that may authorize, appropriate, redirect, reimburse, or otherwise structure public-money flows before those flows appear in procurement, grants, recovery, or agency-contract systems.

LegislaPR remains T2 because it is a discovery/readability layer rather than the canonical government record. MoneySweep promotes only records cross-confirmed against OpenStates and official document links.

OpenStates API v3 is the canonical structured legislative route used here. Its root URL is `https://v3.openstates.org/`, API keys are required, and keys may be supplied through the `X-API-KEY` header or `apikey` query parameter. This repo uses the header route only.

## Extraction model

```text
LegislaPR detail page
    -> session index
    -> OpenStates/document crosswalk
    -> canonical confirmation
    -> legislative fiscal link candidates
    -> manual review gate
```

## Local run

```bash
python scripts/merge_legislapr_registry.py
python scripts/merge_legislapr_registry.py --check
python scripts/probe_legislapr_detail.py --url "https://www.legislapr.com/bills/PS%20782"
python scripts/ingest_legislapr_sessions.py
OPENSTATES_API_KEY="$OPENSTATES_API_KEY" python scripts/fetch_legislative_canonical_sources.py
python scripts/build_osl_sutra_crosswalk.py
python scripts/build_legislative_links.py
```

## Validation

Static GitHub inspection confirms registered producer paths exist, expected outputs are repo-relative, authentication modes match the source-registry validator, and tests cover session extraction, registry merge dedupe, document crosswalks, and legislative fiscal link candidates. Local pytest execution must still be run in a checkout or CI runner before merge.

```bash
python -m pytest tests/test_legislapr_discovery.py tests/test_legislapr_discovery_probe.py tests/test_legislative_canonical_sources.py tests/test_legislative_link_builder.py tests/test_legislative_link_builders.py tests/test_source_registry.py -q
python -m moneysweep.runtime.source_registry --validate
```

## Key handling

OpenStates API keys must be supplied through `.env`, shell environment, or GitHub repository secrets. Do not commit keys, captured API responses containing secrets, or debug logs that print environment values.
