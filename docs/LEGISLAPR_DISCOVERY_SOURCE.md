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
| Discovery tier | T2 operational discovery / enrichment |
| Canonical status | Cross-confirmed candidate only |
| Canonical confirmation | OpenStates plus official Legislative Assembly/SUTRA document link |
| Promotion rule | `cross_confirmed_only` |
| Discovery producer | `scripts/probe_legislapr_detail.py` |
| Session producer | `scripts/ingest_legislapr_sessions.py` |
| Canonical producer | `scripts/fetch_legislative_canonical_sources.py` |
| Crosswalk producer | `scripts/build_osl_sutra_crosswalk.py` |
| Registry merge utility | `scripts/merge_legislapr_registry.py` |
| Registry extension | `registries/source_registry_extensions/legislapr_discovery.json` |
| Schema extension | `registries/schema_registry_extensions/legislapr_legislative_measure.json` |

## Rationale

LegislaPR is useful for fast legislative discovery because it exposes Puerto Rico measure identifiers, detail pages, readable status language, links, and summary text. For MoneySweep, the operational value is the ability to detect measures that may authorize, appropriate, redirect, reimburse, or otherwise structure public-money flows before those flows appear in procurement, grants, recovery, or agency-contract systems.

LegislaPR remains T2 because it is a discovery/readability layer rather than the canonical government record. MoneySweep promotes only records cross-confirmed against OpenStates and official Puerto Rico Legislative Assembly/SUTRA document links.

OpenStates API v3 is the canonical structured legislative route used here. Its root URL is `https://v3.openstates.org/`, API keys are required, and keys may be supplied through the `X-API-KEY` header or `apikey` query parameter. This repo uses the header route only.

## Extraction model

```text
LegislaPR measure detail page
    -> measure_id normalization
    -> outbound link extraction
    -> session index extraction
    -> OpenStates link check
    -> official Legislative Assembly/SUTRA document check
    -> fiscal keyword scan
    -> promotion_status assignment
    -> OpenStates API confirmation
    -> official document URL confirmation
    -> OSL/SUTRA crosswalk build
    -> promoted_candidate or blocked_pending_canonical_confirmation
```

## Promotion statuses

| Status | Meaning | MoneySweep action |
|---|---|---|
| `blocked_pending_canonical_confirmation` | Both canonical paths were not confirmed | Keep in staging only |
| `cross_confirmed_candidate` | Discovery-stage page exposed OpenStates and official document links | Eligible for canonical fetch |
| `promoted_candidate` | Canonical fetcher confirmed OpenStates and official document evidence | Eligible for downstream canonical promotion review |

## Local run

Registry merge pre-step:

```bash
python scripts/merge_legislapr_registry.py
python scripts/merge_legislapr_registry.py --check
```

Discovery probe:

```bash
python scripts/probe_legislapr_detail.py \
  --url "https://www.legislapr.com/bills/PS%20782" \
  --output data/staging/processed/pr_legislapr_measures_probe.json
```

Session index:

```bash
python scripts/ingest_legislapr_sessions.py \
  --input data/staging/processed/pr_legislapr_measures_probe.json \
  --output data/staging/processed/pr_legislapr_sessions.json
```

Canonical confirmation:

```bash
OPENSTATES_API_KEY="$OPENSTATES_API_KEY" \
python scripts/fetch_legislative_canonical_sources.py \
  --input data/staging/processed/pr_legislapr_measures_probe.json \
  --output data/staging/processed/pr_legislative_measures_canonical.json
```

Offline/SUTRA-only audit mode:

```bash
python scripts/fetch_legislative_canonical_sources.py --allow-missing-key
```

OSL/SUTRA crosswalk:

```bash
python scripts/build_osl_sutra_crosswalk.py \
  --discovery data/staging/processed/pr_legislapr_measures_probe.json \
  --canonical data/staging/processed/pr_legislative_measures_canonical.json \
  --output data/staging/processed/pr_osl_sutra_crosswalk.json
```

## Validation

Static GitHub inspection confirms registered producer paths exist, expected outputs are repo-relative, authentication modes match the source-registry validator, and the link builders now have non-network tests for measure/session normalization, scalar/list parsing, promotion gating, crosswalk writing, and registry merge dedupe. GitHub metadata reports the branch as mergeable. Local pytest execution must still be run in a checkout or CI runner before merge.

```bash
python -m pytest tests/test_legislapr_discovery.py tests/test_legislapr_discovery_probe.py tests/test_legislative_canonical_sources.py tests/test_legislative_link_builders.py tests/test_source_registry.py -q
python -m moneysweep.runtime.source_registry --validate
```

## Key handling

OpenStates API keys must be supplied through `.env`, shell environment, or GitHub repository secrets. Do not commit keys, captured API responses containing secrets, or debug logs that print environment values.
