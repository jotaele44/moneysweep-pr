# ACT-family data provenance

Tracks the structured extractions backing the ACT alias-coverage audit
(`scripts/audit_act_alias_coverage.py`) and the alias families in
`registries/alias_overrides.yaml` flagged with ACT/ACUDEN evidence.

## Sources

### `act_2020_transition`

| Field             | Value |
|-------------------|-------|
| Agency            | Autoridad de Carreteras y Transportación (ACT) |
| Transition year   | 2020 (Vázquez Garced → Pierluisi) |
| Source PDF        | `Contratos_Vigentes_ACT.pdf` |
| Extraction method | Operator-side structured extraction |
| Operator-paste date | 2026-05-27 |
| Approx. row count | 1,000+ |

### `acuden_2024_transition`

| Field             | Value |
|-------------------|-------|
| Agency            | Administración para el Cuidado y Desarrollo Integral de la Niñez (ACUDEN) |
| Transition year   | 2024 (Pierluisi → next administration) |
| Source PDF        | `Informe_Contratos_Vigentes_al_Momento_de_Transicion.pdf` |
| Extraction method | Operator-side structured extraction |
| Operator-paste date | 2026-05-27 |
| Approx. row count | ~1,147 |

Both extractions share a common 18-column schema (see
`data/raw/act_transition/README.md`).

## Committed artifacts

### Synthetic fixture

| Path | SHA256 | Rows |
|------|--------|------|
| `tests/fixtures/act_transition/sample_rows.csv` | `b71da936873fc690d9cc55fbe468558cf6b6b9d16ed08d7b34bf7200aa0200dd` | 57 data rows + header |

Hand-picked from the operator's full extraction to exercise the highest-collision
alias families (Ferrovial, LPC&D, the 7 deferred families from PR #108's plan,
COSIANI typo, Rajohnyari typo, Carmen Mangual Pérez DBA chain, Maritime Transport
Authority bilingual collapse, plus the municipio bilingual pattern flagged for the
follow-up normalizer PR).

### Full extraction

| Path | Status |
|------|--------|
| `data/raw/act_transition/transition_contracts_extracted.csv` | Pending operator push (see `data/raw/act_transition/README.md`) |

## Downstream

- Audit script: `scripts/audit_act_alias_coverage.py`.
- Audit report: `reports/act_transition_alias_audit.md` (regenerated on each run).
- Alias entries citing these sources: see `registries/alias_overrides.yaml`
  entries whose `evidence:` block references `act_2020_transition` or
  `acuden_2024_transition`.

## Out-of-scope follow-ups flagged during extraction review

1. **Bilingual municipio normalizer rule.** `MUNICIPIO DE X` (Spanish) and
   `Municipality of X` (English) for the same PR municipio currently produce
   different normalized forms. Estimated 78 municipios affected. Right fix is
   a single rule inside `contract_sweeper.runtime.name_normalization`, not 78
   alias entries. Deferred to a separate PR.

2. **Vendor-vs-fund-transfer classification.** ACUDEN rows with
   `service_type = "Transferencia de Fondos"` represent fund transfers to
   municipios/nonprofits rather than vendor contracts. Whether to surface this
   as a distinct entity-role in downstream clustering is a separate design
   decision; flagged here so it isn't lost.
