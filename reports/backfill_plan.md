# Backfill Plan — R5 Gap Closure

**Generated:** 2026-05-12
**Required coverage:** 7/14 sources materialized (50%)

## Required sources — not materialized

| source_id | family | authentication | blocker | effort |
|---|---|---|---|---|
| `fsrs_subawards` | federal | none | USAspending FSRS bulk download not yet run | Low — run `scripts/download_fsrs.py` |
| `cor3` | territorial | manual_export | COR3 portal requires account; data in `Contract-Sweeper-Secrets/` | Medium — run `scripts/ingest_cor3.py` once file confirmed |
| `emma_bonds` | bond_market | none | MSRB EMMA scrape not yet run | Low — run `scripts/download_emma.py` |
| `prasa` | territorial | manual_export | PRASA contract data requires manual CSV export | Medium — confirm source file, run `scripts/ingest_prasa.py` |
| `hud_drgr_authorized` | federal | manual_export | HUD DRGR authorized reports require grantee login | High — coordinate with grantee access |
| `oficina_contralor` | territorial | none | Contralor scraper not yet run | Low — run `scripts/ingest_contralor.py` |
| `pr_cabilderos` | lobbying | none | PR Cabilderos scraper not yet run | Low — run `scripts/ingest_cabilderos.py` |

## Priority order for backfill

1. **fsrs_subawards** — directly feeds `execution_chain_linkage_rate` gate; 382 subawards present now, FSRS will add the sub-tier linkage needed to push linkage_rate from 0.60 → target 0.90
2. **emma_bonds** — bond underwriter layer for influence graph; no credentials needed
3. **oficina_contralor** — territorial contracts; no credentials needed
4. **pr_cabilderos** — lobbying layer; no credentials needed
5. **cor3** — COR3 infrastructure contracts; file presence in drop zone to be confirmed
6. **prasa** — water authority contracts; file presence in drop zone to be confirmed
7. **hud_drgr_authorized** — deferred to PR6 (grantee access required)

## Partially materialized required sources

| source_id | status | notes |
|---|---|---|
| `usaspending_subawards` | partially_materialized | `pr_prime_sub_relationships.csv` present (258 rows) but `pr_fec_crossref.csv` header-only; crossref depends on entity-resolved awards join (PR3 done) |

## Gate impact after full backfill

| Gate | Current | Expected after backfill |
|---|---|---|
| `source_coverage_rate` | 0.50 | ≥ 0.95 (after top-7 backfill) |
| `execution_chain_linkage_rate` | 0.597 | ≥ 0.90 (after FSRS) |
| `corporate_parent_uei_rate` | 0.0004 | ~0.05–0.15 (after USAspending enrichment completes) |

## Stale r4_X artifacts

- `data/review_queue/`: 80 files of r4_X credential/endpoint blockers — catalogued, not deleted
- `data/exports/`: 96 r4_X recovery artifacts — retained as historical reference

No destructive cleanup performed. Stale artifacts will be archived to `data/quarantine/` in a later PR once R5 canonical outputs are fully confirmed.
