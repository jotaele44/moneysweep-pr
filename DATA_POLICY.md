# Data Policy

## What Is and Is Not Committed

### Committed to git (safe, small, public)

| Path | What it contains |
|---|---|
| `data/ci/seeds/*.csv` | 12 minimal seed CSVs (3–4 rows each) for CI gate satisfaction |
| `data/staging/processed/execution/execution_chain_master.csv` | Synthetic execution chain seed (committed) |
| `data/staging/processed/hud_drgr/*.csv` | Public-record HUD CDBG-DR seed data (5 rows, from published Action Plans) |
| `data/staging/processed/risk/*.csv` | R7 signal seed outputs (synthetic, derived from seed data) |
| `data/manifests/` | Per-source manifest JSON files (metadata only, no PII) |
| `registries/*.yaml` and `registries/*.json` | Source + schema registry declarations |

### Not committed (gitignored)

| Pattern | Reason |
|---|---|
| `data/staging/processed/*.csv` | Live pipeline outputs — can be large, contain vendor data |
| `data/staging/expansion/*.csv` | Expansion-source CSVs — not in core registry |
| `data/normalized/` | Parquet outputs — binary, large |
| `data/raw/*.csv` | Raw downloads — not normalised, potentially large |
| `data/staging/raw/**/*.csv` | Raw staged inputs |
| `data/staging/processed/enrichment/` | May contain entity PII from SAM enrichment |
| `data/logs/*.log` | Pipeline run logs |
| `.env` | API keys — NEVER committed |
| `*.key` | Any key file |

---

## Seed Data Provenance

CI seed files contain only public-record data drawn from official government sources:

| Seed file | Source |
|---|---|
| `data/ci/seeds/usaspending_prime.csv` | USASpending.gov public award records |
| `data/ci/seeds/fsrs_subawards.csv` | FSRS public subaward records |
| `data/ci/seeds/sam_entities.csv` | SAM.gov public entity records |
| `data/ci/seeds/fema_pa_openfema_v2.csv` | OpenFEMA public PA project data |
| `data/ci/seeds/cor3.csv` | COR3 public project registry |
| `data/ci/seeds/hud_cdbg_dr_public.csv` | HUD CPD public CDBG-DR allocations |
| `data/ci/seeds/prasa.csv` | PRASA public contract registry |
| `data/ci/seeds/oficina_contralor.csv` | PR Contralor public audit records |
| `data/ci/seeds/emma_bonds.csv` | MSRB EMMA public bond disclosure |
| `data/ci/seeds/lda.csv` | Senate LDA public lobbying filings |
| `data/ci/seeds/pr_cabilderos.csv` | PR OECE public lobbyist registry |
| `data/ci/seeds/fec.csv` | FEC public contribution records |
| `data/staging/processed/hud_drgr/*.csv` | HUD-published CDBG-DR Puerto Rico Action Plans |

Seed data is representative (3–5 rows) and is used solely to satisfy CI gates.
It is not a substitute for real pipeline data and should be replaced by live
ingestion outputs before production analysis.

---

## Sensitive Data Handling

### API Keys
All API keys are stored in `.env` (gitignored).  Keys are referenced by environment
variable name in `registries/source_registry.yaml` under `authentication: api_key:<VAR>`.
Running `python scripts/scan_for_secrets.py --root .` (run in CI) will fail the
build if any pattern matching a secret is detected in committed files.

### Vendor / Entity Data
- `data/staging/processed/enrichment/` is gitignored because SAM enrichment
  outputs may contain registered agent names and addresses.
- Live `pr_all_awards_master.csv` is gitignored.  The committed seed has synthetic rows.
- Political-finance outputs (FEC, LDA cross-references) contain public-record data
  only — no private contributions below the FEC reporting threshold.

### Portal-Export Data
Some sources (`hud_drgr_authorized`) require grantee-portal login credentials to
download the full dataset.  These exports are dropped manually into `data/manual/`
(gitignored).  The ingest script reads from there; outputs land in
`data/staging/processed/{source_id}/` (also gitignored at top level).

---

## Data Licensing

All committed seed data is drawn from public-domain government sources:

| Source | License |
|---|---|
| USASpending / FPDS | USAFacts Open Data (public domain) |
| FSRS | Public domain (federal reporting system) |
| SAM.gov | Public domain (GSA) |
| OpenFEMA | Open Government License |
| MSRB EMMA | MSRB public disclosure data |
| FEC | Public domain (federal agency) |
| Senate LDA | Public domain (federal disclosure) |
| HUD CPD public data | Public domain (HUD) |
| COR3 | Puerto Rico public agency data |
| PRASA | Puerto Rico public agency data |
| PR Oficina del Contralor | Puerto Rico public records |
| PR OECE Cabilderos | Puerto Rico public records |

No proprietary, licensed, or subscription data is committed to this repository.

---

## Gitignore Patterns — Key Exceptions

The `.gitignore` blocks `data/staging/processed/*.csv` (top-level files only).
**Subdirectory contents are not blocked** — this is intentional and allows committing
seed outputs in named subdirectories.  Do not rely on gitignore to protect PII in
subdirectories; review before committing any new subdirectory under `data/`.

---

## Gate-Seed Contract

When the CI gate checks `required_source_nonempty` for a source, it evaluates
**any** of the source's `expected_outputs` paths.  The committed seed path is
listed last in `expected_outputs`, so a live pipeline output (if present) takes
precedence.  If no live output is present, the seed satisfies the gate.

This means:
- A developer with no live data can still pass CI.
- A production run with live data naturally replaces the gate-satisfying path.
- The seed is never authoritative for analysis — it is a CI fixture only.
