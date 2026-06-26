# Uploaded Master Export Recipe

This recipe makes the local production-generation path reproducible inside
moneysweep-pr.

## Inputs

| Input | Role |
|---|---|
| `pr_contracts_master_v2*.csv` | Contract master / vendor-level financial context |
| `pr_all_awards_master*.csv` | Federal award-level funding context |
| `lda_canonical_client_summary_all.csv` | Lobbying/client context enrichment |

## Step 1 — Convert raw uploaded masters to canonical processed files

```bash
python scripts/prepare_uploaded_masters.py \
  --contracts-master /path/to/pr_contracts_master_v2.csv \
  --awards-master /path/to/pr_all_awards_master.csv \
  --lda-summary /path/to/lda_canonical_client_summary_all.csv \
  --output-dir data/staging/processed_uploaded_masters
```

This writes:

```text
entities_resolved.csv
contracts_master.csv
financial_flows_master.csv
entity_edges.csv
uploaded_master_mapping_report.json
```

## Step 2 — Generate moneysweep-pr v1.1 package

```bash
python scripts/run_export.py \
  --processed-dir data/staging/processed_uploaded_masters \
  --output-dir exports/moneysweep_uploaded_masters_v1_1 \
  --mode production
```

## Step 3 — Write shared artifact manifest

```bash
python scripts/write_artifact_manifest.py \
  --package-dir exports/moneysweep_uploaded_masters_v1_1 \
  --source-file /path/to/pr_contracts_master_v2.csv \
  --source-file /path/to/pr_all_awards_master.csv \
  --source-file /path/to/lda_canonical_client_summary_all.csv
```

## Step 4 — Hand off to SpiderWeb

Give SpiderWeb the package directory containing:

```text
manifest.json
artifact_manifest.json
entities.jsonl
sources.jsonl
funding_awards.jsonl
transactions.jsonl
relationships.jsonl
```

SpiderWeb then runs its consumer-boundary package gate, adapter, scoring layer,
calibration report, and optional fusion.

## Current calibration posture

The uploaded masters do not carry point geometry. The reproducible path therefore
supports municipality/entity-density scoring first. Point-confirmed spatial
scoring should wait until upstream geocoding populates `geo_lat` and `geo_lon` in
canonical processed files before export.
