# moneysweep-pr — MoneySweep Producer (PRII federation)

![Tests](https://github.com/jotaele44/moneysweep-pr/actions/workflows/tests.yml/badge.svg)

`moneysweep-pr` is the public-money intelligence producer for the Puerto Rico Integrated Intelligence (PRII) federation. Its federation alias is `moneysweep-pr`.

The pipeline acquires, normalizes, validates, and cross-links public procurement, infrastructure, lobbying, campaign-finance, debt/fiscal-control, contractor-reference, recovery-assistance, and geospatial records. It exports reviewable records for [`thehub-pr`](https://github.com/jotaele44/thehub-pr), where cross-producer aggregation and correlation occur.

> **Diagnostic-only surface (ADR 0001, Phase 2).** This repo's dashboard is a
> development and diagnostic tool for this producer only. The supported product
> surface for the PRII federation is the hub app
> (`thehub-pr/server/frontend`), which renders this producer's data alongside
> the other engines. See `thehub-pr/docs/adr/0001-federated-engines-single-hub.md`.

## Desktop app

Double-click launchers at the repo root start the local desktop app:

- `PRII-MONEYSWEEP.command` (macOS) / `PRII-MONEYSWEEP.app`
- `PRII-MONEYSWEEP.bat` (Windows)
- `PRII-MONEYSWEEP.sh` (Linux)

**Node.js is not required.** A prebuilt dashboard ships in the repository, so the
first run only needs Python 3.11+ and one-time network access for Python
packages. To skip the network too, see
[`docs/DESKTOP_OFFLINE_BOOTSTRAP.md`](docs/DESKTOP_OFFLINE_BOOTSTRAP.md).

### macOS: getting it without the Gatekeeper detour

macOS marks anything a *browser* downloads with a quarantine flag, and this
wrapper is not signed with a paid Apple Developer ID. Fetching the repository
without a browser therefore avoids the prompt entirely:

```bash
git clone https://github.com/jotaele44/moneysweep-pr.git
open moneysweep-pr/PRII-MONEYSWEEP.app
```

If you did download a ZIP through a browser, open
**`PRII-MONEYSWEEP.command`** first rather than the `.app`. Approve it once
(right-click → Open; on macOS 15+ use System Settings → Privacy & Security →
Open Anyway), and setup clears the quarantine flag from the folder as it
finishes — so every later launch, including the `.app`, opens with no prompt.

Opening the `.app` first from a quarantined folder is the case that used to
require moving the folder and running a repair script: macOS runs a quarantined
bundle from a temporary read-only copy where the checkout beside it is missing.
Starting from the `.command` avoids that entirely.

See [`desktop/README.md`](desktop/README.md) for details, and
[`docs/APPLE_NOTARIZATION_RUNBOOK.md`](docs/APPLE_NOTARIZATION_RUNBOOK.md) for
what removes the remaining one-time approval.

## Federation role

| Field | Value |
|---|---|
| Repository | `jotaele44/moneysweep-pr` |
| Federation alias | `moneysweep-pr` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Primary function | Public money, procurement, grants, recovery, influence, fiscal-control, contractor-reference, and disaster-assistance producer |
| Production stance | Not production-certified master dataset until gates pass |

## Current operating state

moneysweep-pr is **not yet a production-certified master dataset**. The current state is a controlled buildout phase:

- **Source registry:** 143 tracked source definitions (includes SBA disaster-loan sources; counts follow `reports/materialization_readiness.json`).
- **Automatable sources:** 98 marked ready by the materialization-readiness gate (13 formerly scraper-queued PR-gov sources promoted after confirming real scraping implementations).
- **Queued / excluded sources:** 38 manual-export sources, 2 scraper-needed stubs (hacienda_sut_ivu, pr_act_154_excise), semantic duplicates, and deferred stubs remain outside the automatable target.
- **Strict preflight:** required before producer execution or promotion.
- **Current active work:** Tranche B manual-source ingestion (7 output files seeded; operator must drop source files to populate).
- **Last recorded full test baseline:** 2018 passed, 6 skipped, 0 failed.

Source-of-truth status files:

```text
reports/current_status.json
reports/current_blockers.md
reports/next_actions.md
reports/materialization_readiness.json
reports/source_registry_status.csv
```

New documentation anchors for the SBA recovery source refresh:

```text
docs/SBA_RECOVERY_SOURCE_REFRESH.md
reports/sba_recovery_source_refresh.txt
```

## Scope

| Domain | Examples |
|---|---|
| Federal procurement | FPDS, USASpending, FSRS, SAM.gov enrichment |
| Federal grants and recovery | FEMA, HUD/CDBG-DR, USACE, DOT, USDA, DOE, DOJ, HHS, ED |
| Disaster recovery assistance | SBA Disaster Loan Data for Puerto Rico: FY22 Home Loans and FY22 Business Loans; FEMA disaster-number correlation; verified-loss versus approved-loan gap analysis |
| Territorial / municipal contracts | Puerto Rico agency contracts, municipality-linked spending, Compras |
| Infrastructure | PRASA, PREPA, ACT, PPP, capital projects, recovery projects |
| Infrastructure income | Aggregate civilian-paid revenue: tolls (AutoExpreso/ACT/Metropistas), transit fares (AMA/Tren Urbano), water/power rates (PRASA/PREPA-LUMA), port/airport fees — modeled as inflow transactions (payer = aggregate public, payee = collecting agency) |
| Lobbying and influence | Puerto Rico cabilderos, federal LDA, campaign-finance crosswalks |
| Debt and fiscal control | EMMA/MSRB, COFINA, AAFAF, PROMESA creditor/fiscal-control references |
| Contractor references | DCAA active contractor listings, OFAC, GLEIF LEI, SEC officers, entity aliases |
| Geospatial analysis | Municipality normalization, infrastructure geography, GIS overlays, recovery-loss distribution |

## Boundary rules

| Rule | Meaning |
|---|---|
| moneysweep-pr owns money-source ingestion | It acquires and validates procurement, grant, recovery, fiscal, assistance, and influence records |
| Hub owns cross-producer correlation | `thehub-pr` aggregates moneysweep-pr outputs with other producer exports |
| Manual sources stay staged | Manual files are not authoritative canonical tables until parser, lineage, validation, and review gates pass |
| Promotion requires evidence trail | Rows must preserve source, lineage, confidence, and review state |

## Manual source intake backlog

The following acquired or known manual-source families require schema mapping, parser validation, and ingestion before they can be promoted into canonical outputs:

```text
Contratos Vigentes ACT.pdf
Informe Contratos Vigentes al Momento de Transición.pdf
completed_projects_AAA.pdf
FY2024 CER_Final.pdf
Registro de cabilderos Abril 18 2026.pdf
Registrants.pdf
subcontractingdirectory.772857981.pdf
FY_2007_Active_Contractor_Listing_Final.pdf
FY_2012_All_Active_Contractor_Listing.pdf
FY_2013_All_Active_Contractor_Listing.pdf
sba_disaster_loans_pr.xlsx
```

SBA Disaster Loan source components:

```text
FY22 Home
FY22 Business
```

Manual files must pass file inventory, provenance capture, parser/schema validation, row-count checks, entity normalization, export validation, and source-to-output lineage registration before promotion.

## Architecture

```text
source registry
   ↓
strict preflight / readiness classification
   ↓
producer execution or manual-file intake
   ↓
raw/staging outputs
   ↓
normalization and schema validation
   ↓
entity resolution / alias review
   ↓
canonical contract, source, influence, debt, recovery, GIS, and graph outputs
   ↓
coverage, lineage, and analyst reports
```

| Layer | Purpose |
|---|---|
| `run_all.py` | Main orchestrator and strict-preflight entry point |
| `scripts/pipeline_preflight.py` | Registry-driven structural gate before execution |
| `scripts/build_source_recovery_matrix.py` | Materialization-readiness and source-recovery classification |
| `scripts/gap_analysis_builder.py` | Source-registry status regeneration |
| `moneysweep.query` | On-demand query adapter entry point |
| `scripts/*download*` / producer modules | Source-specific acquisition modules |
| `scripts/import_sba_disaster_loans.py` | Importer for the SBA Disaster Loan Puerto Rico workbook (registry-wired, tested; awaits operator file drop to `data/manual/sba_disaster_loans/`) |
| `tests/` | Pytest validation suite |
| `docs/` | Architecture, runbooks, data policy, and operating controls |
| `reports/` | Machine-readable status, readiness, blockers, and audit outputs |

## Quick start

```bash
git clone https://github.com/jotaele44/moneysweep-pr.git
cd moneysweep-pr
python3 -m venv .venv
source .venv/bin/activate
# The shared prii-maintenance library resolves via a pinned git+https
# reference in requirements.txt — no thehub-pr sibling checkout needed:
pip install -r requirements.txt
python -m pytest tests/ -q
python3 run_all.py --only-setup --strict-preflight
```

## Running the pipeline

```bash
python3 run_all.py --only-setup --strict-preflight
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
python3 run_all.py --strict-preflight
# Fast rerun: only sources that are due; independent upstreams use four lanes.
python3 run_all.py --profile incremental --workers 4
```

Useful flags:

```text
--only-setup        Run setup and instruction generation only
--skip-download     Skip producer download step
--manual-only       Alias for --skip-download
--force-download    Re-download existing source files
--profile incremental  Run only due registry sources
--workers N         Bound independent incremental execution lanes (default: 4)
--sam-api-residual  Opt into the bounded live SAM residual pass
```

### Source update controller

`run_all.py` remains the full producer orchestrator. Its `incremental` profile uses a registry-driven
**source update controller** that decides *whether a source is due*, isolates per-source
failure, detects operator file-drops by hash, sequences derived sources after their
upstreams, serializes callers that share an API host, and reports freshness. See
[docs/SOURCE_UPDATE_CONTROLLER.md](docs/SOURCE_UPDATE_CONTROLLER.md).

```bash
python3 scripts/update_sources.py validate-policy   # policy coverage + DAG gates (exit 2 on failure)
python3 scripts/update_sources.py plan --due        # read-only: which sources are due (no network)
python3 scripts/update_sources.py run --due --workers 4
python3 scripts/update_sources.py freshness         # per-source freshness report → reports/source_freshness.csv
```

SAM entity resolution is offline-first. Source-provided UEIs, monthly SAM extracts,
prior indexes, and local aliases are exhausted before any network lookup. To use a
small live residual budget explicitly:

```bash
python3 scripts/run_sam_pipeline.py --use-api --max-api 100 --circuit-breaker-failures 3
```

Parent-entity hierarchy construction is also offline by default; its optional
USASpending residual is bounded with `scripts/entity_resolution.py --use-api --max-api 100`.
