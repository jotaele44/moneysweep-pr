# System Architecture — Contract-Sweeper

**Version:** R5 (post PR64)  
**Status:** Pipeline complete; production rebuild paused pending source delivery

---

## Overview

Contract-Sweeper is a multi-stage data pipeline that ingests 80+ public and semi-public data sources, normalizes entities, resolves vendor identities, links cross-program funding flows, and produces compliance analysis and influence graphs for Puerto Rico government procurement.

```
[Data Sources] → INGEST → NORMALIZE → RESOLVE → LINK → GRAPH/VALIDATE → EXPORT
```

---

## Target Architecture (Post Module Reduction)

Issue #69 proposes migrating to this directory structure:

```
contract_sweeper/
├── sources/          # Source definitions and registries
├── ingest/           # Per-source downloaders and ingesters
├── normalize/        # Column mapping, deduplication, standardization
├── resolve/          # Entity resolution, SAM enrichment, parent collapse
├── link/             # Cross-program linkage (FEMA↔contracts, HUD↔assets)
├── geo/              # Geographic enrichment (future)
├── graph/            # Network/influence graph builders
├── validate/         # Coverage gates, production status, schema checks
├── export/           # Report generation, parquet output, manifests
└── orchestration/    # run_all.py, pipeline runners, backfill logic
```

Current state: all code lives in `scripts/` and `contract_sweeper/pipeline|runtime|validation/`. Migration is **not started** (awaiting Architect approval via Issue #69).

---

## Current Directory Layout

### `contract_sweeper/` — Core Package

| Subpackage | Files | Role |
|-----------|-------|------|
| `pipeline/` | 43 | Orchestration: backfill, controlled/partial rebuild, source delivery gates |
| `runtime/` | 9 | Shared utilities: manifest I/O, schema registry, validation gates, hashing |
| `validation/` | 8 | Validation gate logic: source coverage, entity audit, production status |

### `scripts/` — Executable Scripts (165 files)

| Group | Count | Role |
|-------|-------|------|
| `download_*.py` | 74 | Per-source HTTP/API downloaders |
| `ingest_*.py` | 11 | Staging transformers (CSV → normalized parquet) |
| `run_*.py` | 29 | Thin CLI wrappers (MERGE candidate → `run_pipeline.py`) |
| `validate_*.py` | 5 | Coverage integrity validators |
| `analyze_*.py` | 8 | Analysis and graph builders |
| `normalize_*.py` | 2 | Input normalization |
| `link_*.py` | 3 | Cross-program asset linkers |
| `*_mapper.py` | 4 | Column mapping definitions (MERGE candidate → `source_mappers.py`) |
| Core scripts | 29 | config, build, entity resolution, SAM enrichment, etc. |

---

## Data Flow

```
1. INGEST
   scripts/download_*.py + scripts/ingest_*.py
   → data/staging/raw/**/*.csv
   → data/staging/processed/pr_*.csv

2. NORMALIZE
   scripts/normalize_*.py + scripts/*_mapper.py
   scripts/deduplicate_master.py + scripts/parent_collapse.py
   → data/staging/processed/pr_normalized_*.csv

3. RESOLVE
   scripts/entity_resolution.py
   scripts/sam_enrichment.py + scripts/sam_uei_parent_lookup.py
   scripts/alias_registry_builder.py + scripts/lda_enrich.py
   → data/staging/processed/entity_master.csv

4. BUILD MASTER
   scripts/build_unified_master.py
   → data/staging/processed/pr_contracts_master.csv
   → data/staging/processed/pr_all_awards_master.csv

5. LINK
   scripts/link_*.py
   → data/linked/fema_178_pw_linkage.csv
   → data/linked/hud_drgr_*.csv

6. GRAPH / ANALYZE
   scripts/influence_graph_builder.py
   scripts/network_graph.py + scripts/analyze_*.py
   → data/exports/influence_graph.graphml
   → reports/*.md

7. VALIDATE
   contract_sweeper/validation/*.py
   contract_sweeper/runtime/validation_gates.py
   → data/exports/rebuild_status.json
   → reports/gap_analysis_report.csv

8. EXPORT
   scripts/generate_report.py + scripts/ingest_report_builder.py
   scripts/write_source_manifests.py
   → reports/*.md + reports/*.csv
```

---

## Key Registries

| File | Contents |
|------|---------|
| `registries/source_registry.json` | 82 registered data sources with endpoints, expected outputs, and validation thresholds |
| `registries/schema_registry.json` | Column schemas for each normalized output |
| `registries/endpoint_candidates.json` | Candidate endpoints for credentialed/manual sources |
| `registries/manual_export_registry.json` | Sources requiring manual export (credentialed portals) |

---

## Validation Gate System

Gates live in `contract_sweeper/runtime/validation_gates.py`. Each gate is a named check that must return `PASS` before downstream phases can run.

Active gates (R5):
- `source_coverage_rate` — ≥85% of required sources materialized
- `duplicate_rate` — deduplication within threshold
- `entity_resolution` — minimum entity match rate
- `subaward_linkage` — subaward join coverage
- `execution_chain` — execution chain seed present

Current gate status: all pass in test suite; production inputs missing.

---

## Production Pause State

The pipeline is intentionally paused at `NON_PRODUCTION_DIAGNOSTIC` after R4.9Z.  
Phase 7/8 (downstream enrichment and graph builds) are blocked until:
1. All 21 missing source inputs are delivered.
2. `unfreeze_candidates > 0` (run: `scripts/run_source_recovery_pause_lock_r49z.py`).
3. Production gates pass on real data.

See `docs/OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md` and `docs/SOURCE_RECOVERY_RUNBOOK.md`.

---

## Configuration

`scripts/config.py` is the central configuration module (121 inbound imports). It defines:
- Data directory paths
- Source family groupings
- Validation thresholds
- Output file naming conventions

**Do not** restructure `scripts/config.py` without updating all 121 consumers.
