# Financial-Sources Materialization Audit — Contract-Sweeper

**Date:** 2026-06-10 · **Scope:** repo-wide · **Program:** Puerto Rico public-money intelligence
**Question answered:** *exactly how much data is prepared in this repo, out of 100% of the publicly available data relevant to the program.*

> Reproduce: `python3 scripts/audit_materialization_coverage.py --probe`
> Machine-readable outputs: [`reports/materialization_coverage_audit.json`](materialization_coverage_audit.json), [`.csv`](materialization_coverage_audit.csv), [`_files.csv`](materialization_coverage_audit_files.csv)

---

## 1. Headline

There is no single "% prepared" number, because **three different accounting layers disagree** — and the disagreement is itself the most important finding. Measured honestly:

| View | What it counts | Result |
|---|---|---|
| **Committed / CI** (what a fresh `git clone` sees) | `reports/gap_analysis_report.json` | **0%** materialized (0 of 85 sources, 0 rows) |
| **Local source-level** (this working tree, registry-accounted) | declared `expected_outputs` present on disk | **34.1%** of sources "fully materialized" (29/85) — but only **7 sources** hold bulk (≥1k-row) data |
| **Local on-disk reality** (all materialized CSVs) | every file in `data/staging/processed/` | **740,081 lines** (~655K parsed records*) of authentic public data across 94 files |
| **Record-universe** (held ÷ publicly available) | live API probes, PR-scoped | contracts **92.8%**, FEMA PA **99.9%**, assistance ~**49%**, LDA **0.5%** |

\* Line counts overstate one file: `pr_grants_master.csv` is ~462K lines but ~377K actual records (award descriptions contain embedded newlines). The inventory uses line counts as a fast proxy; the universe probes parse records.

**Plain reading:** the repo is *not* data-poor. This machine holds hundreds of thousands of real, verified PR public-money records — and for the sources that have been pulled, coverage of the public universe is high (federal contracts ~93%, FEMA Public Assistance ~100%). But **the program's own committed accounting reports 0%**, and even run locally it recognizes only ~127K of the ~740K lines. The gap between "what we have" and "what the repo says we have" is the real story.

---

## 2. The three accounting gaps

### Gap A — Gitignore (committed 0% vs. local 740K rows)
`.gitignore` uses a `data/**` deny-all, then re-includes subdirectories with `!data/staging/processed/**/` (trailing slash = *directories only*). It never re-includes the **files** directly in `data/staging/processed/`. `git check-ignore` confirms `pr_grants_master.csv`, `pr_contracts_master.csv`, etc. are ignored. Every committed report (`gap_analysis_report.json`, `source_coverage_audit.csv`, `materialization_readiness.json`) was generated in a clean/CI checkout where those files are absent — which is why they all read `0` / `fixture_detected: true` / `missing_source_files`. The data exists; it is simply invisible to anything that runs against committed state.

### Gap B — Registry drift / orphans (local 740K on disk vs. 127K registry-accounted)
Of the **740,081 rows on disk**, only **~127,524 (17%)** are wired to a registry source's `expected_outputs`. **612,557 rows across 39 files are orphans** — real data that *no* registry source claims, so the registry-driven accounting cannot see them even when run locally:

| Orphan file | Rows | Why orphaned |
|---|--:|---|
| `pr_grants_master.csv` | 461,668 | **No source declares it.** `grants_gov` expects `pr_grants.csv`; `usaspending_prime` declares only contracts + `pr_all_awards_master.csv` |
| `normalized_expansion_fpds_*` (6 files) | ~106,700 | Historical FPDS/DoD expansion that feeds `pr_contracts_master.csv` but is not a declared output |
| `pr_ofac_sdn.csv` | 19,050 | **Path mismatch** — registry `ofac_sdn` expects `ofac_sdn.csv` |
| `vendor_targets.csv` | 7,472 | Intermediate artifact, undeclared |
| `pr_research_master.csv`, `pr_fdic_financials.csv`, … | ~9,200 | Undeclared masters |

### Gap C — Seed-level vs. bulk (registry "fully materialized" overstates)
The gap-analysis logic treats `min_rows = 1` as "materialized," so seed/placeholder sources count as **fully materialized**: e.g. `lda` (14 rows), `emma_bonds` (35 rows). The **materiality tiers** correct this — only **7 sources** hold bulk data:

| Tier | Definition | Sources |
|---|---|--:|
| **bulk** | ≥ 1,000 rows | **7** |
| moderate | 50–999 rows | 6 |
| seed/stub | 1–49 rows | 18 |
| empty | 0 rows | 54 |

---

## 3. Source-level coverage (of ~85 registered sources)

Registry totals (per `materialization_readiness.json`): **85 sources** = 55 automatable + 30 queued (15 scraper-needed, 10 manual-export, 3 semantic-duplicate, 2 deferred NARA stubs). 14 are marked **required**.

**Local materialization status (this tree):**

| Local status | Sources | Note |
|---|--:|---|
| fully_materialized | 29 | incl. seed-level (min_rows=1); only 7 are bulk |
| partially_materialized | 12 | has rows but a declared output is missing/below-threshold |
| not_materialized | 44 | declared outputs absent on disk |

Sources with *any* local data span 8 families: federal (15), territorial (9), political_finance (2), entity_resolution (1), bonds (1), lobbying (1), infrastructure (1), municipal (1).

**Required sources (14) — the critical path:**

| Source | Local status | Rows | Reality |
|---|---|--:|---|
| usaspending_prime | partial | 68,681 | bulk ✓ — missing 2nd output `pr_all_awards_master.csv` |
| fema_pa_openfema_v2 | full | 21,868 | bulk ✓ — ~100% of universe |
| fec | full | 16,637 | bulk ✓ |
| hud_cdbg_dr_public | full | 7,700 | bulk ✓ |
| usaspending_subawards | full | 7,125 | bulk ✓ |
| sam_entities | partial | 50 | seed — key-gated (SAM_API_KEY) |
| emma_bonds | full | 35 | seed-level |
| lda | full | 14 | seed — dry-run fixture, ~0.5% of universe |
| cor3 | partial | 0 | header-only |
| oficina_contralor | partial | 0 | manual export pending |
| pr_cabilderos | partial | 0 | manual export pending |
| fsrs_subawards | not | 0 | not downloaded (semantic dup of subawards) |
| hud_drgr_authorized | not | 0 | credentialed manual export pending |
| prasa | not | 0 | manual export pending |

So of 14 required sources, **5 carry genuine bulk data**, 3 are seed-level, and 6 are empty/pending.

---

## 4. Record-universe coverage ("% of 100%")

Live, read-only probes of keyless public APIs, PR-scoped to match the producers (place-of-performance = PR, FY2008–2026 where the API allows). `coverage = local_rows ÷ public_universe`.

| Source | Local (numerator) | Public universe | Coverage | Method |
|---|--:|--:|--:|---|
| **USAspending prime — contracts (+IDVs)** | 67,256 *(FY2008+)* | 72,500 | **92.8%** | `spending_by_award_count` (live) |
| **FEMA PA project details** | 21,868 | 21,898 | **99.9%** | OpenFEMA `$inlinecount` (live) |
| **USAspending — all assistance** | 376,759 *(records)* | 767,050 | **~49%** *(approx)* | `spending_by_award_count` (live) |
| **LDA federal lobbying (PR clients)** | 14 | 2,670 | **0.5%** | lda.senate.gov filings (live) |
| USAspending subawards | 7,125 | — | n/a | no keyless count endpoint |
| FEC contributions | 16,637 | — | estimate | key-gated (FEC_API_KEY) |
| SAM entities | 50 | — | estimate | key-gated (SAM_API_KEY) |
| OFAC SDN | 19,050 | full feed | reference-complete | global list, not PR-scoped |
| EMMA bonds | 35 | — | estimate | no keyless count API |

**PR public-spending universe (USAspending award-level, FY2008–26, place-of-performance = PR):** contracts 72,500 · grants 23,420 · direct_payments 320,445 · loans 288,740 · other 134,445.

**Caveats:**
- **Contracts (92.8%) — date-aligned.** The master holds 68,681 records but ~1,425 are pre-2008 FPDS, outside the API's FY2008+ window; the numerator counts only the 67,256 FY2008+ records so it matches the denominator. The pre-2008 rows are genuine "bonus" coverage the modern API can't return. Still approximate (line vs. record edge cases), but the date windows now agree.
- **Assistance (~49%) — granularity-approximate.** `pr_grants_master.csv` is a bulk-download artifact and is overwhelmingly **loans + direct payments**, not grants (composition: guaranteed/insured loans 142,882 · direct payments 76,345 · direct loans 72,074 · actual project/formula/block grants ~12,200). Comparing its 376,759 parsed records to award-level grants-only (23,420) would exceed 100% — confirming it is broad assistance, not grants — so the honest denominator is all-assistance awards (767,050), giving ~49%. Numerator/denominator granularity still differ; treat as indicative.
- **FEMA PA (99.9%) — producer-scoped universe.** The denominator replicates the producer's own query (PA project details for PR disaster numbers drawn from `DisasterDeclarationsSummaries state='PR'`), and the local file was built from that same query — so 99.9% means "the download captured ~all of what that query returns," not necessarily every PA record ever tied to PR. Projects under disasters outside that declaration set fall outside both numerator and denominator. It is the best available keyless denominator.

---

## 5. What this means for "how much is prepared"

- **For the handful of sources that have been pulled, preparation is excellent** — federal contracts ~93% and FEMA Public Assistance ~100% of the public PR universe. That is genuinely high coverage.
- **But coverage is bimodal.** 7 sources hold bulk data; 18 are seed/stubs and 54 are empty. The lobbying (LDA 0.5%), entity-resolution (SAM, key-gated), and most territorial/PR-government sources (PRASA, COR3, Comptroller, cabilderos — all manual-export/scraper-gated) are effectively unmaterialized.
- **The repo cannot currently *report* its own materialization** because (A) staging is gitignored and (B) the largest assets are orphaned from the registry. Both are fixable bookkeeping issues, not data problems.

---

## 6. Gaps & recommended follow-ups

1. **Wire the orphans into the registry (Gap B).** Add `pr_grants_master.csv` as an `expected_output` of the assistance source and fix the `ofac_sdn` path (`ofac_sdn.csv` → `pr_ofac_sdn.csv`); together these two move registry-accounted coverage from ~17% to roughly 80% of on-disk rows. Decide separately whether the `normalized_expansion_fpds_*` files are declarable outputs or intentional intermediates — if declared too, registry-accounted coverage approaches ~100%.
2. **Complete `usaspending_prime`.** Produce the missing `pr_all_awards_master.csv` so the largest required source flips partial → full.
3. **Decide the gitignore policy (Gap A).** Either commit a *manifest* of staging (row counts + sha256, already partly present in `data/manifests/`) so committed reports reflect reality, or document that materialization is intentionally local-only. Today the committed 0% is misleading.
4. **Materialize the key-gated set** (FEC live, SAM, HigherGov, OpenCorporates) — 5 keys unlock the entity-resolution and lobbying coverage that currently reads ~0%.
5. **Capture API universe totals at download time.** The producers already hit endpoints that return totals (`metadata.count`, `spending_by_award_count`); persisting them per source would make "% of universe" a first-class, continuously-tracked metric instead of an after-the-fact probe.

---

## 7. Methodology, provenance & limits

- **Source-level layer is offline & deterministic.** It reuses `scripts/gap_analysis_builder.py` status logic verbatim (`_file_status` / `_source_status`); the only change is running against the local tree instead of a clean checkout.
- **Provenance verified.** Sampled the bulk masters directly — real records: HUD grants to PR municipalities with valid UEIs (`pr_grants_master.csv`), DoD/FPDS contracts incl. Dick Corp $78.5M & Flatiron Dragados $57.6M (`pr_contracts_master.csv`), real FEC contributions (`pr_fec_contributions.csv`). FEMA's 99.9% match to the live API independently confirms authenticity.
- **Universe probes are read-only, count-only**, against public keyless endpoints; failure-tolerant (a failed probe is recorded, never fatal). Key-gated sources are documented estimates by design.
- **Committed CI-view reports were not modified.** This audit writes only its own `reports/materialization_coverage_audit.*` artifacts, preserving the registry-sync/CI guardrail. `gap_analysis_report.json` still reads 0% (generated 2026-06-06) — intentionally, as the contrast.
- **Known imprecision:** the inventory's row counts are **line-based** (a fast proxy) and overstate files with embedded newlines — materially for `pr_grants_master.csv` (~462K lines vs ~377K records); the universe probes use parsed record counts to avoid this. Assistance coverage is granularity-approximate (§4); subaward/FEC/SAM/EMMA universes are estimates pending count endpoints or keys.
