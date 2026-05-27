# ACT-family alias coverage audit

- Input: `tests/fixtures/act_transition/sample_rows.csv`
- Rows scanned: 57
- Distinct canonical clusters: 34
- Alias overrides loaded: 72

## Coverage summary

- Matched (cluster has at least one override hit): **8**
- Unmatched (no override hit; default-normalized canonical): **26**
- Cross-source clusters (appear in ≥2 source_dataset values): **1**

## Per-source-year breakdown

| source_dataset | rows | distinct canonical clusters |
|---|---|---|
| `ACT_2020` | 45 | 24 |
| `ACUDEN_2024` | 12 | 11 |

## Recommended new overrides

Unmatched clusters whose raw forms produce ≥2 distinct normalized values (i.e. default normalization can't collapse them — an explicit alias entry is required). Municipios are excluded (see normalizer-rule follow-up below).

_None — every multi-form cluster is already covered by the default normalizer or by an explicit override._

## All unmatched canonicals (for manual review)

Every cluster where no alias override fired. The reviewer should scan for semantic duplicates that the normalizer can't auto-detect (typos, DBA chains, credential prefixes, bilingual labels, etc.) and add explicit alias entries.

| canonical | rows | distinct raw forms | sources |
|---|---|---|---|
| `ALLIED WASTE OF PUERTO RICO` | 2 | ALLIED WASTE OF PUERTO RICO, INC. | ACT_2020 |
| `AUTORIDAD DE TRANSPORTE MARITIMO Y LAS ISLAS MUNIC` | 1 | AUTORIDAD DE TRANSPORTE MARITIMO Y LAS ISLAS MUNIC | ACT_2020 |
| `BEHAR YBARRA AND ASSOCIATES` | 3 | BEHAR-YBARRA & ASSOCIATES, LLC · BEHAR-YBARRA & ASSOCIATES, LLP · Behar-Ybarra and Associates,LLP | ACT_2020 |
| `CARMEN MANGUAL P REZ` | 1 | Carmen Mangual Pérez | ACUDEN_2024 |
| `CENTRO INFANTIL ESQUIL N MANGUAL DBA CARMEN MANGUAL P REZ` | 1 | Centro Infantil Esquilín Mangual DBA Carmen Mangual Pérez | ACUDEN_2024 |
| `COOPERATIVA DE SERVICIOS INTEGRADOS A LA NI EZ COSIANI` | 1 | Cooperativa de Servicios Integrados a la Niñez (COSIANI) | ACUDEN_2024 |
| `COOPERATIVA DE SERVICIOS INTEGRAOD A LA NI EZ COSIANI` | 1 | Cooperativa de Servicios Integraod a la Niñez (COSIANI) | ACUDEN_2024 |
| `DESARROLLADORA JA` | 3 | DESARROLLADORA J.A., INC. · Desarrolladora J.A.. Inc. · Desarrolladora JA, Inc.. | ACT_2020 |
| `FERROVIAL AGROMAN` | 3 | FERROVIAL AGROMAN, LLC · FERROVIAL AGROMAN, S.A. · FERROVIAL- AGROMAN, SA | ACT_2020 |
| `FERROVIAL CONSTRUCCION PR` | 1 | FERROVIAL CONSTRUCCION PR, LLC | ACT_2020 |
| `FUNDACI N EDUCATIVA CONCEPCI N MART N CENTRO DE CUIDO SONIFEL` | 2 | Fundación Educativa Concepción Martín (Centro de Cuido Sonifel) · Fundación Educativa Concepción Martín Inc. (Centro de Cuido Sonifel) | ACUDEN_2024 |
| `ING JUAN O VIRELLA S NCHEZ` | 1 | Ing. Juan O. Virella Sánchez | ACT_2020 |
| `JENNIFER SOTO SANTIAGO` | 1 | Jennifer Soto Santiago | ACUDEN_2024 |
| `JENNIFER SOTO SANTIAGO D B A CENTRO EDUCATIVO ABC` | 1 | Jennifer Soto Santiago d/b/a Centro Educativo ABC | ACUDEN_2024 |
| `JUAN O VIRELLA S NCHEZ` | 1 | Juan O. Virella Sánchez | ACT_2020 |
| `KLEIN ENGINEERING` | 2 | KLEIN ENGINEERING, PSC | ACT_2020 |
| `M2A GROUP` | 2 | M2A GROUP, PSC | ACT_2020 |
| `MARITIME TRANSPORT AUTHORITY FOR PUERTO RICO AND T` | 1 | Maritime Transport Authority for Puerto Rico and t | ACT_2020 |
| `O AND M CONSULTING ENGINEERING` | 2 | O & M CONSULTING ENGINEERING ,P.S.C. | ACT_2020 |
| `OBRATEC CONTRATISTA GENERAL` | 2 | Obratec Contratista General, Inc. | ACT_2020 |
| `PILOTO CONSTRUCTION` | 2 | PILOTO CONSTRUCTION, LLC | ACT_2020 |
| `RAJOHNYARI DAY CARE AND ACADEMY BILINGUAL SCHOOL` | 1 | Rajohnyari Day Care & Academy Bilingual School Inc. | ACUDEN_2024 |
| `RAJONYARI DAY CARE AND ACADEMY BILINGUAL SCHOOL` | 1 | Rajonyari Day Care & Academy Bilingual School Inc. | ACUDEN_2024 |

## Cross-source clusters (entities in both ACT_2020 and ACUDEN_2024)

_None._

## Bilingual municipio collapse evidence (deferred to normalizer-rule PR)

Pairs of `MUNICIPIO DE X` (Spanish) and `MUNICIPALITY OF X` (English) canonicals that refer to the same PR municipio. These are intentionally NOT in `recommended` above — the right fix is a single normalizer rule, not 78 alias entries.

| town | spanish canonical | raw forms |
|---|---|---|
| SAN JUAN | `MUNICIPIO DE SAN JUAN` | MUNICIPALITY OF SAN JUAN · Municipio de San Juan |

