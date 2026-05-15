# Contract-Sweeper

Puerto Rico federal-contracting data pipeline — governed analytical platform.  
14 registered sources · R5 validation gates enforced · R7 risk signals active.

## What This Is

Contract-Sweeper acquires, normalises, and cross-references federal procurement,
disaster-recovery, bond, and political-finance data related to Puerto Rico to produce
risk-ranked, investigative-ready outputs.

It is not a scraper collection. Every output is traceable to a source row, every gate
is enforced by CI, and every risk signal carries a deterministic `explanation` field.

## Quick Start

```bash
pip install -r requirements.txt

python scripts/pipeline.py all      # full pipeline: validate → build → signals → report
python scripts/pipeline.py status   # check gate status without failing
pytest -q                           # run tests (~640 passing)
```

See [SETUP.md](SETUP.md) for full environment setup, API key handling, and troubleshooting.

## Pipeline Steps

The canonical entry point is `scripts/pipeline.py`:

| Subcommand | What it does |
|---|---|
| `validate` | Run R5 validation gates (14-source coverage check) |
| `build` | Build unified master, execution chains, parent collapse |
| `signals` | Compute R7 risk signals (8 families) |
| `report` | Generate investigative output report |
| `all` | Chain validate → build → signals → report |
| `status` | Print gate status; always exits 0 |

## Data Sources (14 Registered)

All sources are declared in `registries/source_registry.yaml`. The 14 required sources
span federal procurement (FPDS, USASpending, FSRS), disaster recovery (HUD DRGR),
municipal bonds (EMMA), vendor identity (SAM.gov), and political-finance crossrefs
(LDA lobbying, OpenSecrets, FEC, OGPe, NGO beneficiaries).

## Architecture

```
Sources ──► Normalisation ──► Validation (R5) ──► Signal (R7) ──► Output
              pipeline/           runtime/          runtime/        output/
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full layer diagram and module tables.

## CI Gates

Every push runs three gate layers:

| Gate | Check | Enforced since |
|---|---|---|
| R5 validation | 14/14 sources present, coverage ≥ 0.93 | CI hardening commit |
| R7 risk | Schema valid, lineage complete, deterministic scores | R7 ship commit |
| Import graph | Zero imports of `contract_sweeper.pipeline` outside pipeline/ | PR-4 commit |

No `--allow-failed` bypass is permitted. CI exits 1 on any gate failure.

## Key Files

| File | Purpose |
|---|---|
| `scripts/pipeline.py` | Canonical entry point |
| `contract_sweeper/runtime/risk_signals.py` | R7 signal engine (8 families) |
| `contract_sweeper/runtime/validation_gates.py` | R5 gate enforcer |
| `registries/source_registry.yaml` | 14-source registry (source of truth) |
| `data/ci/seeds/` | Committed CI seed data (gate-satisfying) |
| `SETUP.md` | Environment setup, variables, troubleshooting |
| `ARCHITECTURE.md` | Layer diagram and module tables |
| `HANDOFF.md` | Current state, branch audit, next steps |
| `DATA_POLICY.md` | What is committed vs gitignored, seed provenance |

## Testing

```bash
pytest -q                   # all tests
pytest -m unit -q           # fast unit tests only
pytest -m pipeline_gate -q  # gate-enforcement tests only
```

## What Not To Do

- Do not commit `.env`, `*.key`, or any file containing API credentials
- Do not bypass CI gates with `--allow-failed`
- Do not import from `contract_sweeper.pipeline` in new code (CI enforces zero violations)
- Do not push directly to `main` — open a PR
- Do not add sources without updating `registries/source_registry.yaml`
- Do not commit files from `data/staging/processed/enrichment/` (gitignored — may contain vendor PII)

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow and [DATA_POLICY.md](DATA_POLICY.md)
for a complete breakdown of what is and is not committed.
