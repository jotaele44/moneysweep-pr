# LegislaPR Legislative Context Integration

## Active vector

`MONEYSWEEP_PR → LEGISLAPR_SOURCE_REGISTRY → SESSION_SCHEMA_INSPECTION → LEGISLATIVE_CONTEXT_MODEL → OSL_SUTRA_CROSSWALK → FUNDING_VENDOR_LINKAGE`

## Source role

LegislaPR is a legislative-intelligence enrichment source for MoneySweep-PR. It should not be treated as the canonical legal authority. It provides structured session records that can explain why public-money movement occurred: program creation, statutory authority, appropriation language, committee oversight, sponsor signals, agency mentions, amendments, and enacted-law status.

Canonical validation remains with official Puerto Rico legislative publication sources, especially OSL/SUTRA and official law-publication surfaces.

## Evidence posture

| Source | Evidence tier | Role |
|---|---:|---|
| LegislaPR exported session records | T2 | Operational/session export enrichment |
| OSL/SUTRA | T1 | Canonical legislative identifier and status validation |
| MoneySweep spending records | T1/T2 depending source | Funding, contract, grant, recovery, and vendor linkage |

## Required raw intake layout

```text
data/manual/legislapr/
  README.md
  exports/
    <operator_export_files>.csv|json|xlsx
  manifests/
    export_manifest.csv
```

Minimum manifest columns:

```csv
file_name,exported_at,session_label,source_system,record_count,sha256,operator_notes
```

## Legislative context schema

Canonical staging output:

```text
data/staging/processed/legislative/pr_legislapr_measures.csv
```

Required columns:

| Column | Purpose |
|---|---|
| `source_id` | Always `legislapr_sessions_export` |
| `source_record_id` | Stable LegislaPR record identifier when present |
| `session_label` | Puerto Rico legislative session label |
| `measure_type` | Bill, resolution, law, amendment, committee item, or equivalent |
| `measure_number` | Human-readable measure number |
| `measure_title` | Official or exported title |
| `measure_summary` | Exported summary or normalized abstract |
| `status` | Latest exported status |
| `introduced_date` | Filing/introduction date when available |
| `latest_action_date` | Latest action date when available |
| `enacted_law_number` | Law number when enacted |
| `sponsors` | Delimited sponsor list |
| `committees` | Delimited committee list |
| `agency_mentions` | Normalized agencies mentioned in title/summary/body |
| `appropriation_signal` | Boolean/score for appropriation or budget language |
| `oversight_signal` | Boolean/score for audit, investigation, hearing, compliance language |
| `infrastructure_signal` | Boolean/score for project/assets/utilities/transport/water/power language |
| `recovery_signal` | Boolean/score for FEMA, COR3, CDBG-DR, disaster, reconstruction language |
| `vendor_signal` | Boolean/score for named vendors, contractors, concessionaires, operators |
| `source_url` | LegislaPR public URL when present |
| `retrieved_at` | Export/import timestamp |
| `provenance_hash` | Hash of normalized raw row |
| `review_state` | `staged`, `needs_crosswalk`, `crosswalk_confirmed`, or `rejected` |

## Crosswalk schema

Canonical staging output:

```text
data/staging/processed/legislative/pr_legislative_osl_sutra_crosswalk.csv
```

Required columns:

| Column | Purpose |
|---|---|
| `legislapr_source_record_id` | LegislaPR row identifier |
| `legislapr_measure_key` | Normalized session/type/number key |
| `osl_sutra_measure_key` | Matching official measure key |
| `official_law_number` | Official law number when enacted |
| `official_status` | Official status from canonical source |
| `official_url` | OSL/SUTRA or official law-publication URL |
| `match_method` | `exact_id`, `session_type_number`, `law_number`, `title_date_fuzzy`, or `manual_review` |
| `match_confidence` | 0.00–1.00 confidence score |
| `review_state` | `confirmed`, `needs_review`, or `rejected` |

## Linkage model

Canonical staging output:

```text
data/staging/processed/legislative/pr_legislative_context_links.csv
```

Required columns:

| Column | Purpose |
|---|---|
| `link_id` | Stable hash of measure + target record |
| `legislative_record_id` | LegislaPR or canonical crosswalk record key |
| `target_source_id` | MoneySweep source linked to the legislative record |
| `target_record_id` | Contract, grant, recovery, debt, or vendor record key |
| `target_entity_name` | Agency/vendor/recipient name |
| `link_type` | `authority`, `appropriation`, `oversight`, `program_creation`, `agency_mention`, `vendor_mention`, `infrastructure_context`, `recovery_context` |
| `link_method` | `exact_identifier`, `agency_name`, `program_name`, `law_number`, `keyword_temporal`, `manual_review` |
| `confidence` | 0.00–1.00 confidence score |
| `evidence_tier` | T1/T2/T3/T4 |
| `review_state` | `candidate`, `confirmed`, `rejected` |

## Promotion gates

A LegislaPR-derived row can promote from staged intelligence into canonical MoneySweep authority chains only when:

1. The raw export file is listed in the manual manifest with hash and row count.
2. The row has session, measure type, measure number or source record ID, status, and provenance hash.
3. Any enacted-law claim is confirmed against OSL/SUTRA or another official source.
4. Funding/vendor links preserve source IDs, target IDs, match method, confidence, and review state.
5. API key material is absent from committed files.

## Blind spots

- Export schema may vary by session or endpoint.
- LegislaPR identifiers may not be stable enough for canonical use without official crosswalk.
- Older sessions may require manual review for OCR/title/date mismatches.
- Legislative text can create authority without directly naming the eventual spending record.
