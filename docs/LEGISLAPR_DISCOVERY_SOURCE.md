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
| Discovery producer | `scripts/probe_legislapr_detail.py` |
| Session producer | `scripts/ingest_legislapr_sessions.py` |
| Canonical producer | `scripts/fetch_legislative_canonical_sources.py` |
| Crosswalk producer | `scripts/build_osl_sutra_crosswalk.py` |
| Registry merge utility | `scripts/merge_legislapr_registry.py` |

## Rationale

LegislaPR remains a T2 discovery/readability layer. MoneySweep promotes only records cross-confirmed against OpenStates and official Puerto Rico Legislative Assembly/SUTRA document links.

OpenStates API v3 is the canonical structured legislative route used here. Its root URL is `https://v3.openstates.org/`, API keys are required, and this repo uses the `X-API-KEY` header route.

## Extraction model

```text
LegislaPR detail page
    -> measure_id normalization
    -> session index extraction
    -> OpenStates link check
    -> SUTRA/OSL official document check
    -> canonical fetch
    -> OSL/SUTRA crosswalk
    -> promoted_candidate or blocked_pending_canonical_confirmation
```

## Local run

```bash
python scripts/merge_legislapr_registry.py
python scripts/merge_legislapr_registry.py --check
python scripts/probe_legislapr_detail.py --url "https://www.legislapr.com/bills/PS%20782"
python scripts/ingest_legislapr_sessions.py
OPENSTATES_API_KEY="$OPENSTATES_API_KEY" python scripts/fetch_legislative_canonical_sources.py
python scripts/build_osl_sutra_crosswalk.py
```

## Validation

Static GitHub inspection confirms registered producer paths exist, expected outputs are repo-relative, authentication modes match the source-registry validator, and the link builders now have non-network tests for measure/session normalization, scalar/list parsing, promotion gating, crosswalk writing, and registry merge dedupe. Local pytest execution must still be run in a checkout or CI runner before merge.

```bash
python -m pytest tests/test_legislapr_discovery.py tests/test_legislapr_discovery_probe.py tests/test_legislative_canonical_sources.py tests/test_legislative_link_builders.py tests/test_source_registry.py -q
python -m moneysweep.runtime.source_registry --validate
```

## Key handling

OpenStates API keys must be supplied through `.env`, shell environment, or GitHub repository secrets. Do not commit keys, captured API responses containing secrets, or debug logs that print environment values.
