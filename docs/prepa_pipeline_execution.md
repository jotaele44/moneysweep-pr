# PREPA Title III Pipeline Execution

## Objective

Build a canonical PREPA Title III stakeholder graph and correlate it against normalized procurement datasets.

Outputs:
- canonical stakeholder CSV
- overlap graph JSON
- sector heatmap CSV
- Markdown intelligence report
- pipeline summary JSON

## Input Requirements

### PREPA Service Matrix Text

Convert the PREPA PDF into OCR/text first.

Recommended:

```bash
pdftotext Legal_Case.pdf prepa_service_matrix.txt
```

Alternative:
- OCR pipeline
- Adobe export
- Tesseract

### Procurement Datasets

Normalized CSVs from:
- FPDS
- USASpending
- FSRS

Expected fields include one or more of:
- recipient_name
- vendor_name
- contractor
- awardee
- entity_name

## End-to-End Execution

```bash
python3 scripts/prepa_run_full_pipeline.py \
  --prepa-text prepa_service_matrix.txt \
  --datasets \
    data/fpds_master.csv \
    data/usaspending_master.csv \
    data/fsrs_master.csv \
  --outdir outputs/prepa_titleiii
```

## Outputs

| File | Description |
|---|---|
| prepa_titleiii_stakeholders.csv | canonical stakeholder extraction |
| prepa_titleiii_overlap_graph.json | graph + correlation flags |
| prepa_titleiii_sector_heatmap.csv | sector heatmap |
| prepa_titleiii_overlap_report.md | operational report |
| prepa_titleiii_pipeline_summary.json | summary metrics |

## Correlation Logic

The system matches PREPA stakeholders against procurement entities using normalized token overlap.

Flags emitted:
- PREPA_STAKEHOLDER_OVERLAP
- COUNSEL_COUNTERPARTY_OVERLAP
- FUEL_RESTRUCTURING_OVERLAP
- GRID_PRIVATIZATION_OVERLAP
- FINANCIAL_CLAIMANT_OVERLAP
- PUBLIC_AUTHORITY_INTERLOCK

## Important Analytic Constraint

Stakeholder overlap is not evidence of misconduct.

The PREPA service matrix is a procedural legal notice artifact. Correlation flags indicate network persistence or operational overlap only.

Investigative escalation requires:
- corroborated procurement records
- contract modifications
- fiscal-plan linkage
- litigation evidence
- timeline consistency
- payment/award continuity

## Recommended Expansion

- Neo4j export
- temporal graphing
- award-value weighting
- contract-chain traversal
- LNG/fuel procurement clustering
- LUMA/Genera transition overlays
- FOMB/AAFAF timeline correlation
