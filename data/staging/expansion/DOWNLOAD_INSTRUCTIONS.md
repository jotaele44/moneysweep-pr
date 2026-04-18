# Download Instructions — Puerto Rico Federal Contracts Expansion Data

This document provides step-by-step instructions for downloading all 13
expansion datasets from federal procurement data sources.

> **Note**: `auto_download.py` automates 12/13 files via USASpending APIs
> (bulk_download for FY2000-2006, spending_by_award for FY2007+).
> These instructions apply to the 1 remaining manual file (FSRS) or as a
> fallback if automated downloads fail.

**Manual download constraints** (FSRS and fallback only):
- Format: **CSV**
- Fields: **ALL available** (do not filter columns)
- Compression: **NONE**
- Save all files to: `data/staging/expansion/`

---

## FPDS Primary Backbone (8 files)

**Source**: https://www.fpds.gov

Download TWO files per time window:
- **Direct**: Place of Performance = Puerto Rico
- **Vendor**: Vendor State = PR

### File 1: `expansion_fpds_2000_2004_direct.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2000 to 09/30/2004`
4. Set **"Place of Performance State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2000_2004_direct.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2000_2004_direct.csv`

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 2: `expansion_fpds_2000_2004_vendor.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2000 to 09/30/2004`
4. Set **"Vendor Address State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2000_2004_vendor.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2000_2004_vendor.csv`

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 3: `expansion_fpds_2005_2008_direct.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2004 to 09/30/2008`
4. Set **"Place of Performance State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2005_2008_direct.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2005_2008_direct.csv`

> **CRITICAL**: After download, verify that records from year 2007 are present.
> FPDS migrated platforms around 2007 and data may be spotty.
> If 2007 records are missing, download 2007 separately with
> Date Signed: 10/01/2006 to 09/30/2007.

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 4: `expansion_fpds_2005_2008_vendor.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2004 to 09/30/2008`
4. Set **"Vendor Address State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2005_2008_vendor.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2005_2008_vendor.csv`

> **CRITICAL**: After download, verify that records from year 2007 are present.
> FPDS migrated platforms around 2007 and data may be spotty.
> If 2007 records are missing, download 2007 separately with
> Date Signed: 10/01/2006 to 09/30/2007.

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 5: `expansion_fpds_2009_2016_direct.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2008 to 09/30/2016`
4. Set **"Place of Performance State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2009_2016_direct.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2009_2016_direct.csv`

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 6: `expansion_fpds_2009_2016_vendor.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2008 to 09/30/2016`
4. Set **"Vendor Address State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2009_2016_vendor.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2009_2016_vendor.csv`

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 7: `expansion_fpds_2017_2025_direct.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2016 to 09/30/2025`
4. Set **"Place of Performance State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2017_2025_direct.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2017_2025_direct.csv`

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
### File 8: `expansion_fpds_2017_2025_vendor.csv`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `10/01/2016 to 09/30/2025`
4. Set **"Vendor Address State"** = `PR`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `expansion_fpds_2017_2025_vendor.csv`
10. Move to: `data/staging/expansion/expansion_fpds_2017_2025_vendor.csv`

**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
## USASpending — IDV / Indirect PR (1 file)

### File 9: `expansion_idv_indirect_pr.csv`

**Source**: USASpending.gov
**URL**: https://www.usaspending.gov/search

**Steps**:
1. Navigate to https://www.usaspending.gov/search
2. Under **"Award Type"**, select: **IDV** and **Delivery Order**
3. Under **"Recipient Location"**: Do **NOT** set to Puerto Rico
   (we want recipients OUTSIDE PR whose awards relate to PR)
4. In **"Keyword"** search box, enter: `Puerto Rico`
5. Set **"Time Period"**: 2000 to 2025
6. Click **"Download"** (top of results)
7. Select format: **CSV**, all columns
8. USASpending will queue the download and email you a link — wait for the email
9. Save file as: `expansion_idv_indirect_pr.csv`
10. Move to: `data/staging/expansion/expansion_idv_indirect_pr.csv`

**Note**: Large USASpending downloads are processed asynchronously.
You will receive an email with a download link. This may take several minutes.

---
## USASpending — DoD Corridor (2 files)

### File 10: `expansion_dod_upr_2001_2015.csv`

**Source**: USASpending.gov
**URL**: https://www.usaspending.gov/search

**Steps**:
1. Navigate to https://www.usaspending.gov/search
2. Under **"Agency"**, select: **Department of Defense**
3. In **"Keyword"** search, enter each of these keywords
   (use separate searches if needed, then combine results):
   `Puerto Rico`, `University of Puerto Rico`, `Mayaguez`, `Ramey`, `Roosevelt Roads`
4. Set **"Time Period"**: `2001-2015`
5. Click **"Download"**
6. Select format: **CSV**, all columns
7. Wait for email with download link
8. Save file as: `expansion_dod_upr_2001_2015.csv`
9. Move to: `data/staging/expansion/expansion_dod_upr_2001_2015.csv`

**Note**: If USASpending does not support multiple keywords simultaneously,
run separate searches for each keyword and combine the resulting CSVs
(remove duplicate rows based on Award ID).

---
### File 11: `expansion_dod_upr_2016_2025.csv`

**Source**: USASpending.gov
**URL**: https://www.usaspending.gov/search

**Steps**:
1. Navigate to https://www.usaspending.gov/search
2. Under **"Agency"**, select: **Department of Defense**
3. In **"Keyword"** search, enter each of these keywords
   (use separate searches if needed, then combine results):
   `Puerto Rico`, `University of Puerto Rico`, `Mayaguez`, `Ramey`, `Roosevelt Roads`
4. Set **"Time Period"**: `2016-2025`
5. Click **"Download"**
6. Select format: **CSV**, all columns
7. Wait for email with download link
8. Save file as: `expansion_dod_upr_2016_2025.csv`
9. Move to: `data/staging/expansion/expansion_dod_upr_2016_2025.csv`

**Note**: If USASpending does not support multiple keywords simultaneously,
run separate searches for each keyword and combine the resulting CSVs
(remove duplicate rows based on Award ID).

---
## Reconstruction Layer (1 file)

### File 12: `expansion_reconstruction_2017_2025.csv`

**Source**: USASpending.gov
**URL**: https://www.usaspending.gov/search

**Steps**:
1. Navigate to https://www.usaspending.gov/search
2. Under **"Agency"**, select each of the following agencies:
   **FEMA**, **HUD**, **DOT**, **USACE**, **VA**
3. In **"Keyword"** search, enter: `Puerto Rico`, `Maria`, `reconstruction`
4. Set **"Time Period"**: 2017 to 2025
5. Click **"Download"**
6. Select format: **CSV**, all columns
7. Wait for email with download link
8. Save file as: `expansion_reconstruction_2017_2025.csv`
9. Move to: `data/staging/expansion/expansion_reconstruction_2017_2025.csv`

**Context**: This captures post-Hurricane Maria reconstruction and disaster
recovery contracts from 2017 onward.

---
## FSRS — Subcontracts (1 file, optional)

### File 13: `expansion_subcontracts_pr.csv`

**Source**: FSRS (Federal Subaward Reporting System)
**URL**: https://www.fsrs.gov

**Steps**:
1. Navigate to https://www.fsrs.gov
2. Click **"Search Sub-Awards"** or equivalent search interface
3. Set **"Place of Performance State"** = **Puerto Rico** (or **PR**)
4. Leave date range open (all available years)
5. Click **"Search"**
6. Export results as **CSV**
7. Save file as: `expansion_subcontracts_pr.csv`
8. Move to: `data/staging/expansion/expansion_subcontracts_pr.csv`

**Note**: FSRS has limited historical data. Some years may have no
subcontract results. This is expected — the file should still contain
whatever records are available.

---
## Download Checklist

| # | Filename | Source | Downloaded? |
|---|----------|--------|-------------|
| 1 | `expansion_fpds_2000_2004_direct.csv` | FPDS | [ ] |
| 2 | `expansion_fpds_2000_2004_vendor.csv` | FPDS | [ ] |
| 3 | `expansion_fpds_2005_2008_direct.csv` | FPDS | [ ] |
| 4 | `expansion_fpds_2005_2008_vendor.csv` | FPDS | [ ] |
| 5 | `expansion_fpds_2009_2016_direct.csv` | FPDS | [ ] |
| 6 | `expansion_fpds_2009_2016_vendor.csv` | FPDS | [ ] |
| 7 | `expansion_fpds_2017_2025_direct.csv` | FPDS | [ ] |
| 8 | `expansion_fpds_2017_2025_vendor.csv` | FPDS | [ ] |
| 9 | `expansion_idv_indirect_pr.csv` | USASpending | [ ] |
| 10 | `expansion_dod_upr_2001_2015.csv` | USASpending | [ ] |
| 11 | `expansion_dod_upr_2016_2025.csv` | USASpending | [ ] |
| 12 | `expansion_reconstruction_2017_2025.csv` | USASpending | [ ] |
| 13 | `expansion_subcontracts_pr.csv` | FSRS | [ ] |

## After Downloading

Run the validation script to check all files:

```bash
python3 scripts/validate_downloads.py
```

Then run the full pipeline:

```bash
python3 run_all.py
```
