# ACT-family alias coverage audit

- Input: `tests/fixtures/act_transition/sample_rows.csv`
- Rows scanned: 57
- Distinct canonical clusters: 28
- Alias overrides loaded: 103

## Coverage summary

- Matched (cluster has at least one override hit): **14**
- Unmatched (no override hit; default-normalized canonical): **14**
- Cross-source clusters (appear in ≥2 source_dataset values): **1**

## Per-source-year breakdown

| source_dataset | rows | distinct canonical clusters |
|---|---|---|
| `ACT_2020` | 45 | 22 |
| `ACUDEN_2024` | 12 | 7 |

## Recommended new overrides

Unmatched clusters whose raw forms produce ≥2 distinct normalized values (i.e. default normalization can't collapse them — an explicit alias entry is required). Municipios are excluded (see normalizer-rule follow-up below).

_None — every multi-form cluster is already covered by the default normalizer or by an explicit override._

## All unmatched canonicals (for manual review)

Every cluster where no alias override fired. The reviewer should scan for semantic duplicates that the normalizer can't auto-detect (typos, DBA chains, credential prefixes, bilingual labels, etc.) and add explicit alias entries.

| canonical | rows | distinct raw forms | sources |
|---|---|---|---|
| `ALLIED WASTE OF PUERTO RICO` | 2 | ALLIED WASTE OF PUERTO RICO, INC. | ACT_2020 |
| `BEHAR YBARRA AND ASSOCIATES` | 3 | BEHAR-YBARRA & ASSOCIATES, LLC · BEHAR-YBARRA & ASSOCIATES, LLP · Behar-Ybarra and Associates,LLP | ACT_2020 |
| `DESARROLLADORA JA` | 3 | DESARROLLADORA J.A., INC. · Desarrolladora J.A.. Inc. · Desarrolladora JA, Inc.. | ACT_2020 |
| `FERROVIAL AGROMAN` | 3 | FERROVIAL AGROMAN, LLC · FERROVIAL AGROMAN, S.A. · FERROVIAL- AGROMAN, SA | ACT_2020 |
| `FERROVIAL CONSTRUCCION PR` | 1 | FERROVIAL CONSTRUCCION PR, LLC | ACT_2020 |
| `FUNDACI N EDUCATIVA CONCEPCI N MART N CENTRO DE CUIDO SONIFEL` | 2 | Fundación Educativa Concepción Martín (Centro de Cuido Sonifel) · Fundación Educativa Concepción Martín Inc. (Centro de Cuido Sonifel) | ACUDEN_2024 |
| `KLEIN ENGINEERING` | 2 | KLEIN ENGINEERING, PSC | ACT_2020 |
| `M2A GROUP` | 2 | M2A GROUP, PSC | ACT_2020 |
| `O AND M CONSULTING ENGINEERING` | 2 | O & M CONSULTING ENGINEERING ,P.S.C. | ACT_2020 |
| `OBRATEC CONTRATISTA GENERAL` | 2 | Obratec Contratista General, Inc. | ACT_2020 |
| `PILOTO CONSTRUCTION` | 2 | PILOTO CONSTRUCTION, LLC | ACT_2020 |

## Cross-source clusters (entities in both ACT_2020 and ACUDEN_2024)

_None._

## Bilingual municipio collapse evidence (deferred to normalizer-rule PR)

Pairs of `MUNICIPIO DE X` (Spanish) and `MUNICIPALITY OF X` (English) canonicals that refer to the same PR municipio. These are intentionally NOT in `recommended` above — the right fix is a single normalizer rule, not 78 alias entries.

| town | spanish canonical | raw forms |
|---|---|---|
| SAN JUAN | `MUNICIPIO DE SAN JUAN` | MUNICIPALITY OF SAN JUAN · Municipio de San Juan |

