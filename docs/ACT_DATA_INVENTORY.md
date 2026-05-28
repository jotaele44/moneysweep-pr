# ACT-family data inventory

Catalog of known Autoridad de Carreteras y Transportación (ACT) and ACUDEN
publications. Tracks what the operator has on hand vs what's known to exist
upstream but hasn't been retrieved yet. Intentionally documentation-only — no
new fetch scripts ship from this doc; downloads remain operator-driven.

**Last updated:** 2026-05-27 · **Maintainer:** see `docs/SOURCE_RECOVERY_RUNBOOK.md`

## Status legend

- ✅ Operator has structured extraction on hand (see provenance row).
- 🟡 Document is known to exist publicly; not yet retrieved by operator.
- ⬜ Theoretical / TODO — agency claim to publish exists but no concrete URL or schema confirmed.

## Catalog

### §9(a)(12) transition contracts

The Puerto Rico Government Ethics Office, Act 8 of 2017, and Ley 9 require
outgoing agency heads to publish the contracts in force at the moment of an
administration transition. ACT and ACUDEN both produce such reports.

| Source | Year | Status | File | Approx rows | Notes |
|---|---|---|---|---|---|
| ACT (Autoridad de Carreteras) | 2008 (Fortuño) | ⬜ | unknown | unknown | Predates structured publication; likely archived only at the OCPR or PR State Archives. |
| ACT | 2012 (García Padilla) | ⬜ | unknown | unknown | TODO — check ACT/DTOP transparency page archive. |
| ACT | 2016 (Rosselló) | 🟡 | unknown | unknown | Should exist on ACT/DTOP transparency page; operator hasn't retrieved. |
| ACT | 2020 (Vázquez Garced → Pierluisi) | ✅ | `Contratos_Vigentes_ACT.pdf` | ~1,000+ | Extracted into `data/raw/act_transition/transition_contracts_extracted.csv` (`source_dataset=ACT_2020`). See `reports/act_data_provenance.md`. |
| ACT | 2024-25 (Pierluisi → next) | 🟡 | unknown | unknown | Should now be published; check ACT/DTOP transparency page and OCPR. |
| ACUDEN | 2024 (Pierluisi → next) | ✅ | `Informe_Contratos_Vigentes_al_Momento_de_Transicion.pdf` | ~1,147 | Extracted into the same CSV (`source_dataset=ACUDEN_2024`). Same provenance entry. |

### Rolling / ongoing publications

| Source | Cadence | Status | Notes |
|---|---|---|---|
| ACT Contratos Otorgados (rolling) | Quarterly / ad-hoc | ⬜ | Published on the ACT/DTOP transparency page when ACT awards new contracts. No stable URL yet — operator retrieves manually. |
| OCPR Registro de Contratos filtered to ACT | Continuous | 🟡 | `https://consultacontratos.ocpr.gov.pr/` — comptroller-level registry; agency code `032`. Public search portal; bulk extract requires either scraping or the operator's negotiated extract path. |
| OCPR Registro filtered to ACUDEN | Continuous | 🟡 | Same OCPR portal; ACUDEN's agency code is separate from 032 — verify on retrieval. |

### Sister datasets (related, not strictly ACT/ACUDEN)

| Source | Status | Notes |
|---|---|---|
| DCAA active contractors (FY2007/FY2012/FY2013) | ⬜ | Already in `source_registry.yaml` as `dcaa_active_contractors`. Manual-export. Useful for crosswalking older ACT vendors. |
| AMA (Autoridad Metropolitana de Autobuses) | ⬜ | Appears as a counterparty in many ACT 2020 interagency rows. Has its own contract publishing; not yet cataloged here. |
| AFI (Autoridad para el Financiamiento de la Infraestructura) | ⬜ | Same pattern — counterparty on ACT 2020 rows; separate registry. |
| ATM (Maritime Transport Authority) | ⬜ | Bilingual aliasing now landed (`Maritime Transport Authority for Puerto Rico` canonical in `alias_overrides.yaml`). Independent publication TBD. |

## Provenance & retrieval flow

1. Operator retrieves a PDF from the upstream source (ACT/DTOP transparency
   page, OCPR portal, or direct request to the agency).
2. Operator extracts structured rows locally (Adobe Acrobat extract, pdfplumber,
   or manual cleanup) into the 18-column schema documented in
   `data/raw/act_transition/README.md`.
3. Operator pushes the extracted CSV to
   `data/raw/act_transition/transition_contracts_extracted.csv` on the active
   feature branch. Subdirectories under `data/raw/` are not gitignored
   (only root-level `data/raw/*.csv` is), so the push will persist.
4. CI / downstream consumers read either the full CSV (when present) or the
   curated synthetic fixture at `tests/fixtures/act_transition/sample_rows.csv`.
5. The audit script (`scripts/audit_act_alias_coverage.py`) reads whichever
   exists and writes `reports/act_transition_alias_audit.md` plus the
   machine-readable `.csv` companion.
6. New alias clusters surfaced by the audit are added to
   `registries/alias_overrides.yaml` with `evidence:` citing both the CSV and
   the audit report.

## Resolved follow-ups

- **Bilingual municipio normalizer rule.** ✅ Implemented in
  `contract_sweeper.runtime.name_normalization`: `Municipio de X`,
  `Municipality of X`, and `Municipio Autónomo de X` now collapse to a canonical
  `MUNICIPIO <town>` form, bridging the Spanish/English variants across both
  source datasets without needing per-municipio alias entries. The audit
  report's former "Bilingual municipio collapse evidence" section is now a
  regression check (should stay empty).

## Deferred follow-ups

- **Vendor-vs-fund-transfer classification.** ACUDEN's `Transferencia de Fondos`
  rows (where the counterparty is a municipio or nonprofit recipient) aren't
  "contractor" relationships in the typical vendor sense. Whether to surface
  this as a distinct entity-role downstream is a separate design decision.
- **`extract_act_acuden_pdfs.py` hardening + layout-profile registration.** PR
  #108 shipped the extractor harness. Hardening for wrapped continuation cells
  and a `--sha256` helper remain in the prior plan's Step D, deferred until a
  new ACT-family PDF lands that exposes a layout the current extractor can't
  handle (the operator's own extraction tooling has covered the two known PDFs
  so far without invoking the harness).

## Related artifacts

- `data/raw/act_transition/README.md` — drop-zone README.
- `reports/act_data_provenance.md` — per-source SHA256 + row count.
- `reports/act_transition_alias_audit.md` — generated audit report.
- `registries/source_registry.yaml` — sister entries
  `act_transition_contracts`, `acuden_2024_transition`, `dcaa_active_contractors`.
- `registries/manual_export_registry.yaml` — schema and validation rules for
  the same sources.
- `scripts/extract_act_acuden_pdfs.py` — PR #108's PDF-extractor harness
  (currently dormant, no inputs).
- `scripts/audit_act_alias_coverage.py` — this round's audit reporter.
