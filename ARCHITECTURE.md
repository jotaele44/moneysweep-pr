# Architecture

## System Purpose

Contract-Sweeper is a governed analytical pipeline for Puerto Rico federal
contracting, disaster-recovery spending, and political-finance data.

It answers: **Who received public funds, through what chain, with what political
connections, and at what risk level?**

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SOURCE LAYER (14 required)                    │
│                                                                       │
│  Federal               Territorial          Political-Finance         │
│  ─────────────         ───────────────      ──────────────────        │
│  USASpending prime     Oficina Contralor     LDA (lobbying)           │
│  USASpending subs      COR3                  PR Cabilderos            │
│  FSRS subawards        PRASA                 FEC contributions        │
│  FEMA PA v2            HUD CDBG-DR public                             │
│  SAM entities          HUD DRGR authorized*  EMMA bonds               │
└─────────────────────────────────────────────────────────────────────┘
                               │
                  download_*.py / ingest_*.py
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    NORMALIZATION LAYER                                │
│                                                                       │
│  scripts/build_unified_master.py   → pr_all_awards_master.csv        │
│  scripts/execution_chain_builder.py → execution_chain_master.csv     │
│  scripts/parent_collapse.py        → entities_resolved.csv           │
│  scripts/sam_enrichment.py         → (entity enrichment in-place)    │
│  scripts/lda_enrich.py             → (lobbying linkage in-place)     │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      VALIDATION LAYER (R5)                            │
│                                                                       │
│  contract_sweeper/runtime/validation_gates.py                         │
│                                                                       │
│  Gates (all enforced in CI):                                          │
│    source_coverage_rate           ≥ 0.93   (14/14 = 1.000)           │
│    required_source_nonempty       all 14 sources have ≥1 data row    │
│    manifest_present_per_required  all 14 sources have a manifest dir │
│    execution_chain_linkage_rate   ≥ 0.90                             │
│    subaward_linkage_rate          ≥ 0.90                             │
│    entity_type_assignment_rate    ≥ 0.80                             │
│    corporate_parent_uei_rate      ≥ 0.002 (PR SME-dominated dataset) │
│    duplicate_rate_per_source      ≤ 0.05                             │
│    secret_leakage_zero            == 0                               │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SIGNAL LAYER (R7)                                │
│                                                                       │
│  contract_sweeper/runtime/risk_signals.py                             │
│  scripts/build_risk_signals.py                                        │
│                                                                       │
│  Signal families:                                                     │
│    concentration        entity dominates award share (> 15%)         │
│    repeat_awards        entity receives ≥ 3 separate awards          │
│    subaward_opacity     chain has missing UEI or low link_confidence │
│    parent_sub_mismatch  prime and sub share corporate parent UEI     │
│    political_overlap    awardee in LDA / PR Cabilderos / FEC         │
│    bond_contract_overlap bond issuer is also contract recipient      │
│    geographic_clustering single municipality > 30% of award count   │
│    stale_lineage        award missing source_lineage_path / dataset  │
│                                                                       │
│  Outputs:                                                             │
│    data/staging/processed/risk/risk_signals_master.csv               │
│    data/staging/processed/risk/entity_risk_scores.csv                │
│    data/staging/processed/risk/project_risk_scores.csv               │
│    data/staging/processed/risk/municipality_risk_scores.csv          │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       OUTPUT LAYER                                    │
│                                                                       │
│  scripts/generate_report.py        → investigative report            │
│  scripts/influence_graph_builder.py → influence graph JSON           │
│  scripts/analyze_*.py              → cross-reference analyses        │
└─────────────────────────────────────────────────────────────────────┘

* hud_drgr_authorized requires grantee-portal login; uses seed data in CI.
```

---

## Package Structure

### `contract_sweeper/runtime/` — Production runtime (KEEP)

| Module | Role |
|---|---|
| `validation_gates.py` | CI gate definitions and report writer |
| `risk_signals.py` | R7 signal engine — `compute_signals()` |
| `risk_signal_gates.py` | R7 completion gates |
| `manifest_runtime.py` | Per-source manifest writer |
| `source_registry.py` | Loads `registries/source_registry.yaml` |
| `schema_registry.py` | Loads `registries/schema_registry.yaml` |
| `name_normalization.py` | Entity-name normaliser (used cross-codebase) |
| `linkage_confidence.py` | Sub-award link confidence scoring |
| `retry_runtime.py` | Jittered exponential backoff |

### `contract_sweeper/validation/` — Audit layers (KEEP)

Covers: source coverage audit, entity universe audit, production status gate,
master input recovery, artifact lineage.

### `contract_sweeper/pipeline/` — R4 backfill orchestration (ARCHIVE)

44 modules implementing the R4 source-acquisition backfill phase.  This phase is
**complete**.  No module in this layer is on any active execution path.  These are
preserved in git history but should be moved to `archive/pipeline_r4/`.

---

## Registries (Single Sources of Truth)

### `registries/source_registry.yaml`

Declares all data sources.  Every source has:
- `source_id` — unique key
- `required` — whether the CI gate enforces non-empty output
- `authentication` — `none` | `api_key:<ENV_VAR>` | `manual_export`
- `expected_outputs` — paths the gate checks for ≥1 data row
- `producer_script` — the script that generates the output
- `update_cadence` — how often the source should be refreshed

**This file governs CI.** Adding a source here without a committed seed in
`data/ci/seeds/` will break the CI gate.

### `registries/schema_registry.yaml`

Canonical column names per source.  Used by mapper scripts (`cms_mapper.py`, etc.)
to ensure consistent column names across heterogeneous source formats.

---

## CI Gate Enforcement

```
.github/workflows/ci.yml
└── Run R5 validation gates (enforced)
    └── python -m contract_sweeper.runtime.validation_gates --root .
        └── exits 1 if any gate fails
```

The `--allow-failed` flag was permanently removed.  Gates are not advisory.

### Adding a new required source without breaking CI

1. Add the source to `registries/source_registry.yaml` with `required: true`.
2. Create `data/ci/seeds/{source_id}.csv` with at least one data row.
3. Add the seed path to the source's `expected_outputs` list.
4. Create `data/manifests/{source_id}/` with at least one manifest JSON.
5. Confirm `pytest -q` and gates both pass before pushing.

---

## Key Design Decisions

### OR semantics on `expected_outputs`
A source's gate passes if **any** of its `expected_outputs` has ≥1 data row.
This allows the CI seed to satisfy the gate when live data is not committed.

### Subdirectory exception to gitignore
`.gitignore` blocks `data/staging/processed/*.csv` (top-level) but not subdirectories.
Committed outputs live in subdirectories:
- `data/staging/processed/execution/` — execution chain master
- `data/staging/processed/hud_drgr/` — HUD DRGR seed
- `data/staging/processed/risk/` — R7 signal outputs
- `data/ci/seeds/` — CI seed CSVs (separate from processed/)

### Signal doctrine (R7)
Every risk signal must: cite `evidence_row_ids`, carry a human-readable `explanation`,
and use a `confidence` value that decreases with data quality.  No silent inference.
Missing data produces no signal rather than a low-confidence fabricated one.

---

## Roadmap

| Phase | Status |
|---|---|
| R0–R4: Source acquisition + backfill | Complete |
| R5: Validation gates + entity resolution | Complete — locked on `main` |
| R6: CI enforcement + coverage threshold | Complete — locked on `main` |
| R7: Risk signal engine | Active — `claude/r7-risk-signal-engine` |
| R8: Module reduction (archival) | Planned — see `MODULE_REDUCTION_PLAN.md` |
| R9: Canonical orchestration entry point | Planned |
| R10: Multi-operator / handoff hardening | Planned |
