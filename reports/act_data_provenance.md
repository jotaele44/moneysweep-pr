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

| Path | SHA256 | Rows |
|------|--------|------|
| `data/raw/act_transition/transition_contracts_extracted.csv` | `556fdd569525d5d4f4f24e72dca5b60f601a1fe1ba085f9395e9181a326fa160` | 1,797 data rows + header (ACT_2020=650, ACUDEN_2024=1,147) |

Generated deterministically by `scripts/build_act_transition_extract.py` from the
two operator-supplied source PDFs (uploaded 2026-05-28). The PDFs themselves are
not committed (binary; `data/raw/documents/**/*.pdf` is gitignored) — their
SHA256 is recorded here for traceability:

| Source PDF | SHA256 |
|------------|--------|
| `Contratos_Vigentes_ACT.pdf` (41pp) | `ff9f5a5c726e293943810343249dae4304fd0eb1bc820be90733360046c409bf` |
| `Informe_Contratos_Vigentes_al_Momento_de_Transicion.pdf` (49pp) | `79c160b984aff5fc0ac06aa473f8f77f045e3010bf2a53cd5b3563e4dcb769d9` |

## Downstream

- Audit script: `scripts/audit_act_alias_coverage.py`.
- Audit report: `reports/act_transition_alias_audit.md` (regenerated on each run).
- Alias entries citing these sources: see `registries/alias_overrides.yaml`
  entries whose `evidence:` block references `act_2020_transition` or
  `acuden_2024_transition`.

## Out-of-scope follow-ups flagged during extraction review

1. **Bilingual municipio normalizer rule.** ✅ Resolved. `Municipio de X`,
   `Municipality of X`, and `Municipio Autónomo de X` now collapse to a
   canonical `MUNICIPIO <town>` form in
   `contract_sweeper.runtime.name_normalization`, bridging the Spanish/English
   variants without per-municipio alias entries.

2. **Accent-folding in `normalize_name`.** ✅ Resolved. A NFKD
   `unicodedata` step now folds accented characters to ASCII before all
   other processing: `Comerío`→`COMERIO`, `Juana Díaz`→`JUANA DIAZ`,
   `Rodríguez`→`RODRIGUEZ`, etc. The `Transporte Rodriguez Asfalto` alias
   entry (which only existed to bridge the accent gap) has been removed;
   all remaining entries that contain accented aliases are still retained
   because they also bridge non-accent differences (credential prefixes,
   abbreviations, or typos).

3. **Vendor-vs-fund-transfer classification.** ACUDEN rows with
   `service_type = "Transferencia de Fondos"` represent fund transfers to
   municipios/nonprofits rather than vendor contracts. Whether to surface this
   as a distinct entity-role in downstream clustering is a separate design
   decision; flagged here so it isn't lost.

4. **Broad fuzzy near-duplicate vendor sweep.** A difflib pass over the ~1.5k
   distinct vendors surfaced ~50 candidate merge pairs; the 10 highest-confidence
   non-accent typo clusters were added to `alias_overrides.yaml` (Layer C). A
   systematic rapidfuzz-backed reviewer with operator sign-off is a separate PR.
