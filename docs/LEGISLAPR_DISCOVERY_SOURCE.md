# LegislaPR T2 Discovery Source

## Active vector

`MONEYSWEEP_PR → LEGISLAPR_T2_DISCOVERY_SOURCE → CROSS_CONFIRMED_PROMOTION_ONLY`

## Classification

| Field | Value |
|---|---|
| Source ID | `legislapr_discovery` |
| Tier | T2 operational discovery / enrichment |
| Canonical status | Not canonical by itself |
| Canonical confirmation | OpenStates + official Legislative Assembly/SUTRA document link |
| Promotion rule | `cross_confirmed_only` |
| Producer | `scripts/probe_legislapr_detail_page.py` |
| Overlay registry | `registries/source_registry_overlays/legislapr_t2_discovery.yaml` |

## Rationale

LegislaPR is useful for fast legislative discovery because it exposes Puerto Rico measure identifiers, measure pages, readable status language, links, and summary text. For MoneySweep, the operational value is not legislative commentary; it is the ability to detect measures that may authorize, appropriate, redirect, reimburse, or otherwise structure public-money flows before those flows appear in procurement, grants, recovery, or agency-contract systems.

LegislaPR must remain T2 because its own public page identifies upstream data routes through OpenStates and the Puerto Rico Legislative Assembly and states that it is not government-affiliated. MoneySweep therefore treats LegislaPR as a discovery surface and promotes only cross-confirmed records.

## Extraction model

```text
LegislaPR measure page
    ↓
measure_id normalization
    ↓
outbound link extraction
    ↓
OpenStates link check
    ↓
official Legislative Assembly/SUTRA document check
    ↓
fiscal keyword scan
    ↓
promotion_state assignment
```

## Promotion states

| State | Meaning | MoneySweep action |
|---|---|---|
| `discovery_only_hold` | LegislaPR page found, no canonical links extracted | Keep in staging only |
| `partially_confirmed_hold` | OpenStates or official document found, but not both | Keep in staging; queue for review |
| `cross_confirmed_ready` | OpenStates and official document found | Eligible for canonical promotion after schema validation |

## Fiscal signal terms

The probe flags public-money relevance when the visible measure text contains terms related to appropriations, funds, reimbursement, incentives, budget, municipalities, OGP, CRIM, Hacienda, AAFAF, COR3, FEMA, CDBG, contracts, or procurement. This is only a triage flag. It does not prove fiscal effect.

## Local run

```bash
python scripts/probe_legislapr_detail_page.py \
  --measure "PS 782" \
  --output data/staging/processed/legislapr_measures_discovery.jsonl \
  --crosswalk-output data/staging/processed/legislapr_measure_crosswalk.csv
```

## Key handling

OpenStates API keys must be supplied through `.env`, shell environment, or GitHub repository secrets. Do not commit keys, captured API responses containing secrets, or debug logs that print environment values.

## Next integration step

Merge the overlay into `registries/source_registry.yaml`, then regenerate `registries/source_registry.json` with:

```bash
python scripts/regenerate_registry_json.py
python -m pytest tests/test_legislapr_discovery_probe.py -q
```
