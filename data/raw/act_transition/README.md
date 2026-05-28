# ACT-family transition contract extractions

This directory is the operator drop-zone for structured CSV extractions of the
Autoridad de Carreteras y Transportación (ACT) and ACUDEN administration-transition
contract publications.

## Expected file

```
transition_contracts_extracted.csv
```

Schema (matches operator-pasted format on 2026-05-27):

```
source_dataset, agency_name, transition_year, source_pdf, source_page,
source_table, sec, contract_number, contractor_name, award_date_raw,
start_date_raw, end_date_raw, amount_raw, amount_numeric, service_type,
comments, base_contract_number, contract_suffix
```

`source_dataset` values currently observed:

- `ACUDEN_2024` — Informe_Contratos_Vigentes_al_Momento_de_Transicion.pdf (~1,147 rows).
- `ACT_2020`    — Contratos_Vigentes_ACT.pdf (~1,000+ rows).

## Status

The full operator CSV is not committed here. Subdirectories of `data/raw/` are
not gitignored, so a push will persist; the operator drops the file when ready.

Until the full file lands, `scripts/audit_act_alias_coverage.py` falls back to
the curated synthetic fixture at `tests/fixtures/act_transition/sample_rows.csv`,
which captures the same schema with ~60 hand-picked rows representing every
alias family the audit currently knows about.

See `docs/ACT_DATA_INVENTORY.md` for the full catalog of known ACT-family
publications and their access paths.
