# Canonical v1 — Evidence Pipeline

**Status:** foundation (WS-C of the 300-task roadmap)
**Code:** `scripts/build_evidence.py`, `contract_sweeper/runtime/evidence_tiers.py`
**Schema:** `schemas/canonical_v1/evidence.schema.json`

Evidence is **first-class** in the Canonical Entity Relationship Model v1: every
graph edge must resolve to at least one `evidence.csv` row, and evidence is
built *before* any node or edge (build-rule step 4). This enforces the North
Star rule **"no provenance → no edge."**

## Flow

```
raw source surface ──► claim record ──► make_evidence() ──► dedupe ──► evidence.csv (+ manifest)
   (CSV/registry/PDF/web/docket)        derive tier + confidence + deterministic id
```

A *claim record* is a dict describing one sourced claim
(`source_type`, `source_name`, `claim`, `page_or_line_ref`, `extraction_method`,
optional `evidence_tier`, `ocr_confidence`, `review_status`). Loaders
(`from_claim_records`, `from_csv_source`) turn source surfaces into claim
records; network/PDF-binary acquisition is handled by the per-source ingesters
(WS-D…K) and is out of scope for this foundation module.

## Deterministic IDs

`evidence_id = evidence_<source>_<ref>_<hash>` via
`contract_sweeper.runtime.canonical_ids.evidence_id(source, ref, payload)`.
Identical (source, ref, claim) → identical id, so dedup is exact and re-runs are
idempotent. `dedupe_evidence()` keeps the highest-confidence row per id.

## Evidence tiers

| Tier | Criteria |
|------|----------|
| `T1` | Primary official record, directly sourced and verified (registry / filing / court docket). |
| `T2` | Official document or API, machine-parsed without manual verification. |
| `T3` | Secondary or OCR/web-extracted material requiring corroboration. |
| `T4` | Unverified, derived, or inferred material; lowest trust. |

`derive_tier(source_type, extraction_method)` picks a base tier from the source
type and then **caps** it by the extraction method (e.g. anything OCR'd can be
no better than `T3`). Confidence starts at the tier floor
(`T1=0.95, T2=0.85, T3=0.6, T4=0.35`); OCR evidence is multiplied by the
measured OCR confidence so a poor scan is not over-trusted.

## Crosswalk to CLAIM_LANGUAGE_POLICY claim tiers

`claim_tier_for(evidence_tier, review_status)` maps evidence to the claim tiers
in [`CLAIM_LANGUAGE_POLICY.md`](CLAIM_LANGUAGE_POLICY.md). Rejected evidence is
`blocked`; not-yet-accepted (pending) evidence is downgraded one trust level
(worst-tier-wins, mirroring `runtime/maturity_gate.py`).

| evidence_tier | accepted | pending | rejected |
|---------------|----------|---------|----------|
| `T1` | observed | linked | blocked |
| `T2` | observed | linked | blocked |
| `T3` | linked | inferred | blocked |
| `T4` | inferred | blocked | blocked |

Downstream text/reports must phrase claims at or below the resulting claim tier
(use "record shows" / "linked with confidence X"; never conclusive language for
`inferred`/`blocked`).

## Review status lifecycle

New evidence defaults to `pending`. A reviewer promotes it to `accepted` or
`rejected`; the claim tier (and therefore the language allowed for any claim it
backs) follows the crosswalk above.

## Usage

```bash
# from a JSON array of claim records
python scripts/build_evidence.py --claims claims.json --out data/canonical_v1/evidence.csv

# one evidence row per data row of a CSV source
python scripts/build_evidence.py --csv-source data/raw/pr_cabilderos.csv \
    --out data/canonical_v1/evidence.csv --manifest data/manifests/evidence_v1.json
```
