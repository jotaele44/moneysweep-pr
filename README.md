# Contract-Sweeper

![Tests](https://github.com/jotaele44/contract-sweeper/actions/workflows/tests.yml/badge.svg)

Contract-Sweeper is a Puerto Rico public-money intelligence pipeline for acquiring,
normalizing, validating, and cross-linking public procurement, infrastructure,
lobbying, campaign-finance, debt/fiscal-control, contractor-reference, and geospatial
records.

The project began as a 13-dataset federal procurement pipeline. It has expanded into
an 84-source registry with source-readiness gates, strict preflight controls,
manual-source ingestion, entity-resolution staging, and graph/influence outputs.

## Current Operating State

Contract-Sweeper is **not yet a production-certified master dataset**. The current
state is a controlled buildout phase:

- **Source registry:** 84 tracked source definitions.
- **Automatable sources:** 54 marked ready by the materialization-readiness gate.
- **Queued / excluded sources:** manual exports, scraper-needed Puerto Rico sources,
  semantic duplicates, and deferred stubs remain outside the automatable target.
- **Strict preflight:** required before producer execution or promotion.
- **Current active work:** Tranche B manual-source ingestion and reconciliation.
- **Last recorded full test baseline:** 1229 passed, 5 skipped, 0 failed.

Source-of-truth status files:

```text
reports/current_status.json
reports/current_blockers.md
reports/next_actions.md
reports/materialization_readiness.json
reports/source_registry_status.csv
```

## Scope

Contract-Sweeper currently tracks source families across the following domains:

| Domain | Examples |
|---|---|
| Federal procurement | FPDS, USASpending, FSRS, SAM.gov enrichment |
| Federal grants and recovery | FEMA, HUD/CDBG-DR, USACE, DOT, USDA, DOE, DOJ, HHS, ED |
| Territorial / municipal contracts | Puerto Rico agency contracts, municipality-linked spending, Compras |
| Infrastructure | PRASA, PREPA, ACT, PPP, capital projects, recovery projects |
| Lobbying and influence | Puerto Rico cabilderos, federal LDA, campaign-finance crosswalks |
| Debt and fiscal control | EMMA/MSRB, COFINA, AAFAF, PROMESA creditor/fiscal-control references |
| Contractor references | DCAA active contractor listings, OFAC, OpenCorporates, entity aliases |
| Geospatial analysis | Municipality normalization, infrastructure geography, GIS overlays |

## Manual Source Intake Backlog

The following acquired or known manual-source families require schema mapping,
parser validation, and ingestion before they can be promoted into canonical outputs:

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
```

Manual files should not be treated as authoritative canonical tables until they pass:

1. file inventory and provenance capture;
2. parser/schema validation;
3. row-count and column-coverage checks;
4. entity normalization and alias review;
5. export validation;
6. source-to-output lineage registration.

## Architecture

The repository is organized around a registry-first pipeline:

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
canonical contract, source, influence, debt, GIS, and graph outputs
   ↓
coverage, lineage, and analyst reports
```

Core execution layers:

| Layer | Purpose |
|---|---|
| `run_all.py` | Main orchestrator and strict-preflight entry point |
| `scripts/pipeline_preflight.py` | Registry-driven structural gate before execution |
| `scripts/build_source_recovery_matrix.py` | Materialization-readiness and source-recovery classification |
| `scripts/gap_analysis_builder.py` | Source-registry status regeneration |
| `contract_sweeper.query` | On-demand query adapter entry point |
| `scripts/*download*` / producer modules | Source-specific acquisition modules |
| `tests/` | Pytest validation suite |
| `docs/` | Architecture, runbooks, data policy, and operating controls |
| `reports/` | Machine-readable status, readiness, blockers, and audit outputs |

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/jotaele44/Contract-Sweeper.git
cd Contract-Sweeper

# 2. Create an isolated Python environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run tests
python -m pytest tests/ -q

# 5. Run setup and strict preflight without executing producers
python3 run_all.py --only-setup --strict-preflight
```

## Running the Pipeline

### Safe setup / validation mode

Use this mode before any source materialization work:

```bash
python3 run_all.py --only-setup --strict-preflight
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
```

### Full orchestrator

```bash
python3 run_all.py --strict-preflight
```

Useful flags:

```text
--only-setup        Run setup and instruction generation only
--skip-download     Skip producer download step
--manual-only       Alias for --skip-download
--force-download    Re-download existing source files
--skip-validation   Skip download validation
--skip-normalize    Skip normalization
--skip-dedup        Skip cross-file deduplication
--skip-coverage     Skip coverage validation
--skip-enrichment   Skip SAM.gov UEI enrichment
--strict-preflight  Abort on structural readiness errors before execution
```

### On-demand adapter execution

Some source families are available through query adapters:

```bash
python -m contract_sweeper.query --source <source_id>
```

After adapter or producer work, regenerate status artifacts:

```bash
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
python -m pytest tests/ -q
```

## API Keys and Secrets

Some producers require credentials at runtime. Keep all keys outside git.

```bash
cp .env.example .env
# edit .env locally; never commit real credentials
```

Common runtime keys include:

```text
SAM_API_KEY
LDA_API_KEY
FEC_API_KEY
OPENCORPORATES_API_TOKEN
HIGHERGOV_API_KEY
```

The repository should never contain live credentials, downloaded PII-heavy outputs,
or private raw files unless they are explicitly approved and policy-compliant.

## Data Directories

```text
data/
├── raw/                         # manually acquired or raw producer inputs
├── staging/                     # staging and expansion work products
│   ├── expansion/               # original federal procurement staging area
│   └── processed/               # normalized/generated outputs; often gitignored
└── logs/                        # local run logs
```

Generated data products are generally excluded from git unless they are small,
policy-safe, and intentionally promoted as fixtures, manifests, or audit reports.

## Canonical Outputs

Canonical outputs vary by active vector. Common target families include:

```text
contracts master tables
source registry status reports
materialization-readiness reports
entity master / alias review queues
lobbying and influence edge tables
debt/fiscal-control relationship tables
municipality and GIS normalization layers
graph exports and analyst audit tables
```

Before treating any output as authoritative, verify:

```bash
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
python -m pytest tests/ -q
```

Then inspect the relevant `reports/` status artifact for gate status and blockers.

## Testing

```bash
# Full suite
python -m pytest tests/ -q

# Verbose mode
python -m pytest tests/ -v

# Run a focused test file
python -m pytest tests/test_pipeline_preflight.py -q
```

For coverage-enabled environments:

```bash
python -m pytest tests/ --cov=scripts --cov=contract_sweeper --cov-report=term-missing
```

## Development

A `Makefile` wraps the same commands the CI quality gates run, so local and CI
stay in lock-step. After cloning, install the dev tooling and run the full bar:

```bash
make install-dev   # ruff, mypy (pinned 1.11.2), pytest, pytest-cov, type stubs
make check         # lint + format-check + type + test  (the gating quality bar)
```

Individual targets (`make help` lists them all):

| Target | Wraps | Gating CI counterpart |
|--------|-------|-----------------------|
| `make lint` | `ruff check .` | `.github/workflows/lint.yml` |
| `make format` / `make format-check` | `ruff format [--check] .` | `.github/workflows/lint.yml` |
| `make type` | `python -m mypy` | `.github/workflows/mypy.yml` |
| `make test` | `pytest` with the `--cov-fail-under` floor | `.github/workflows/tests.yml`, `ci.yml` |
| `make lock` / `make lock-check` | `uv pip compile requirements.in …` | `.github/workflows/lockfile.yml` |
| `make precommit` | `pre-commit run --all-files` | `.github/workflows/pre-commit.yml` |

All of these gates are **blocking** on pull requests. To run the git hooks
locally on every commit, install them once with `pre-commit install`
(config: `.pre-commit-config.yaml`). Contributor conventions — the fresh-`main`
staged-PR flow and the full gate list — live in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Operating Controls

Current repo-control conventions:

- Use status files as the source of truth.
- Prefer delta-only reporting during long execution threads.
- Do not perform broad audits unless explicitly requested.
- Run strict preflight before producer execution.
- Keep manual-source ingestion separate from automatable producer materialization.
- Do not promote a production master until source coverage, lineage, and tests pass.
- Use failure packets for execution failures:

```text
command:
exit_code:
last_40_lines:
files_recently_changed:
suspected_area:
```

## Documentation

Primary documentation files include:

```text
docs/ARCHITECTURE.md
docs/DATA_POLICY.md
docs/MATERIALIZATION_RUNBOOK.md
docs/MODULE_REDUCTION_PLAN.md
docs/NGO_INTEGRATION.md
HANDOFF.md
STATUS.md
SETUP.md
```

Some handoff files are historical audit artifacts. Current execution state should be
checked in `reports/current_status.json` before starting a new repo vector.

## Production Promotion Gate

A Contract-Sweeper output should be considered production-ready only after:

1. strict preflight reports zero structural errors;
2. all targeted sources are materialized or explicitly excluded with reason codes;
3. manual-source parsers pass schema and row-count validation;
4. entity and alias review queues are resolved or bounded;
5. lineage manifests connect every output row to a source artifact;
6. tests pass;
7. status reports and blockers are regenerated;
8. the active vector is closed in the repo state files.

Until those gates pass, outputs are diagnostic or staging artifacts, not definitive
public-money intelligence products.
