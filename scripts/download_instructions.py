"""
Generate detailed download instructions for all expansion datasets.
Produces DOWNLOAD_INSTRUCTIONS.md and manifest.json in data/staging/expansion/.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import DOWNLOAD_MANIFEST, EXPANSION_DIR, PROJECT_ROOT, setup_logging
from scripts.setup_directories import main as setup_dirs


def _generate_fpds_instructions(entry: dict, idx: int) -> str:
    """Generate FPDS download instructions for one file."""
    ftype = entry["filter_type"]
    filters = entry["filters"]
    fname = entry["filename"]
    date_range = filters.get("Date Signed", "")

    if ftype == "direct":
        filter_field = "Place of Performance State"
        filter_value = "PR"
    else:
        filter_field = "Vendor Address State"
        filter_value = "PR"

    critical = ""
    if "2005_2008" in fname:
        critical = (
            "\n> **CRITICAL**: After download, verify that records from year 2007 are present.\n"
            "> FPDS migrated platforms around 2007 and data may be spotty.\n"
            "> If 2007 records are missing, download 2007 separately with\n"
            "> Date Signed: 10/01/2006 to 09/30/2007.\n"
        )

    return f"""### File {idx}: `{fname}`

**Source**: FPDS (Federal Procurement Data System)
**URL**: https://www.fpds.gov/ezsearch/search.do

**Steps**:
1. Navigate to https://www.fpds.gov/ezsearch/search.do
2. Click **"Advanced Search"**
3. Set **"Date Signed"** range: `{date_range}`
4. Set **"{filter_field}"** = `{filter_value}`
5. Click **"Search"**
6. Click **"Download"** button (top-right of results)
7. Select format: **CSV**
8. Select fields: **ALL available**
9. Save file as: `{fname}`
10. Move to: `data/staging/expansion/{fname}`
{critical}
**Warning**: FPDS may cap exports at 500,000 rows. If the export hits this
limit, split the time window into smaller ranges and combine the CSVs.

---
"""


def _generate_usaspending_idv_instructions(entry: dict, idx: int) -> str:
    """Generate USASpending IDV download instructions."""
    fname = entry["filename"]
    return f"""### File {idx}: `{fname}`

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
9. Save file as: `{fname}`
10. Move to: `data/staging/expansion/{fname}`

**Note**: Large USASpending downloads are processed asynchronously.
You will receive an email with a download link. This may take several minutes.

---
"""


def _generate_usaspending_dod_instructions(entry: dict, idx: int) -> str:
    """Generate USASpending DoD corridor download instructions."""
    fname = entry["filename"]
    filters = entry["filters"]
    time_period = filters.get("Time Period", "")
    keywords = filters.get("Keywords", [])
    kw_str = ", ".join(f'`{k}`' for k in keywords)

    return f"""### File {idx}: `{fname}`

**Source**: USASpending.gov
**URL**: https://www.usaspending.gov/search

**Steps**:
1. Navigate to https://www.usaspending.gov/search
2. Under **"Agency"**, select: **Department of Defense**
3. In **"Keyword"** search, enter each of these keywords
   (use separate searches if needed, then combine results):
   {kw_str}
4. Set **"Time Period"**: `{time_period}`
5. Click **"Download"**
6. Select format: **CSV**, all columns
7. Wait for email with download link
8. Save file as: `{fname}`
9. Move to: `data/staging/expansion/{fname}`

**Note**: If USASpending does not support multiple keywords simultaneously,
run separate searches for each keyword and combine the resulting CSVs
(remove duplicate rows based on Award ID).

---
"""


def _generate_reconstruction_instructions(entry: dict, idx: int) -> str:
    """Generate reconstruction layer download instructions."""
    fname = entry["filename"]
    filters = entry["filters"]
    agencies = filters.get("Agencies", [])
    keywords = filters.get("Keywords", [])
    ag_str = ", ".join(f"**{a}**" for a in agencies)
    kw_str = ", ".join(f'`{k}`' for k in keywords)

    return f"""### File {idx}: `{fname}`

**Source**: USASpending.gov
**URL**: https://www.usaspending.gov/search

**Steps**:
1. Navigate to https://www.usaspending.gov/search
2. Under **"Agency"**, select each of the following agencies:
   {ag_str}
3. In **"Keyword"** search, enter: {kw_str}
4. Set **"Time Period"**: 2017 to 2025
5. Click **"Download"**
6. Select format: **CSV**, all columns
7. Wait for email with download link
8. Save file as: `{fname}`
9. Move to: `data/staging/expansion/{fname}`

**Context**: This captures post-Hurricane Maria reconstruction and disaster
recovery contracts from 2017 onward.

---
"""


def _generate_fsrs_instructions(entry: dict, idx: int) -> str:
    """Generate FSRS subcontract download instructions."""
    fname = entry["filename"]
    return f"""### File {idx}: `{fname}`

**Source**: FSRS (Federal Subaward Reporting System)
**URL**: https://www.fsrs.gov

**Steps**:
1. Navigate to https://www.fsrs.gov
2. Click **"Search Sub-Awards"** or equivalent search interface
3. Set **"Place of Performance State"** = **Puerto Rico** (or **PR**)
4. Leave date range open (all available years)
5. Click **"Search"**
6. Export results as **CSV**
7. Save file as: `{fname}`
8. Move to: `data/staging/expansion/{fname}`

**Note**: FSRS has limited historical data. Some years may have no
subcontract results. This is expected — the file should still contain
whatever records are available.

---
"""


def generate_instructions(root: Path = None) -> Path:
    """Generate DOWNLOAD_INSTRUCTIONS.md and manifest.json. Returns path to MD file."""
    if root is None:
        root = PROJECT_ROOT

    expansion_dir = root / "data" / "staging" / "expansion"
    expansion_dir.mkdir(parents=True, exist_ok=True)

    md_path = expansion_dir / "DOWNLOAD_INSTRUCTIONS.md"
    manifest_path = expansion_dir / "manifest.json"

    lines = [
        "# Download Instructions — Puerto Rico Federal Contracts Expansion Data\n\n",
        "This document provides step-by-step instructions for downloading all 13\n",
        "expansion datasets from federal procurement data sources.\n\n",
        "> **Note**: `auto_download.py` automates 12/13 files via USASpending APIs\n",
        "> (bulk_download for FY2000-2006, spending_by_award for FY2007+).\n",
        "> These instructions apply to the 1 remaining manual file (FSRS) or as a\n",
        "> fallback if automated downloads fail.\n\n",
        "**Manual download constraints** (FSRS and fallback only):\n",
        "- Format: **CSV**\n",
        "- Fields: **ALL available** (do not filter columns)\n",
        "- Compression: **NONE**\n",
        "- Save all files to: `data/staging/expansion/`\n\n",
        "---\n\n",
        "## FPDS Primary Backbone (8 files)\n\n",
        "**Source**: https://www.fpds.gov\n\n",
        "Download TWO files per time window:\n",
        "- **Direct**: Place of Performance = Puerto Rico\n",
        "- **Vendor**: Vendor State = PR\n\n",
    ]

    generators = {
        "FPDS": _generate_fpds_instructions,
        "USASpending": {
            "idv": _generate_usaspending_idv_instructions,
            "dod": _generate_usaspending_dod_instructions,
            "reconstruction": _generate_reconstruction_instructions,
        },
        "FSRS": _generate_fsrs_instructions,
    }

    idx = 1
    current_section = None

    for entry in DOWNLOAD_MANIFEST:
        source = entry["source"]
        ftype = entry["filter_type"]

        # Section headers
        if source == "USASpending" and ftype == "idv" and current_section != "usaspending_idv":
            lines.append("## USASpending — IDV / Indirect PR (1 file)\n\n")
            current_section = "usaspending_idv"
        elif source == "USASpending" and ftype == "dod" and current_section != "usaspending_dod":
            lines.append("## USASpending — DoD Corridor (2 files)\n\n")
            current_section = "usaspending_dod"
        elif source == "USASpending" and ftype == "reconstruction" and current_section != "reconstruction":
            lines.append("## Reconstruction Layer (1 file)\n\n")
            current_section = "reconstruction"
        elif source == "FSRS" and current_section != "fsrs":
            lines.append("## FSRS — Subcontracts (1 file, optional)\n\n")
            current_section = "fsrs"

        # Generate instructions
        if source == "FPDS":
            lines.append(generators["FPDS"](entry, idx))
        elif source == "USASpending":
            lines.append(generators["USASpending"][ftype](entry, idx))
        elif source == "FSRS":
            lines.append(generators["FSRS"](entry, idx))

        idx += 1

    # Checklist
    lines.append("## Download Checklist\n\n")
    lines.append("| # | Filename | Source | Downloaded? |\n")
    lines.append("|---|----------|--------|-------------|\n")
    for i, entry in enumerate(DOWNLOAD_MANIFEST, 1):
        lines.append(f"| {i} | `{entry['filename']}` | {entry['source']} | [ ] |\n")
    lines.append("\n")
    lines.append("## After Downloading\n\n")
    lines.append("Run the validation script to check all files:\n\n")
    lines.append("```bash\n")
    lines.append("python3 scripts/validate_downloads.py\n")
    lines.append("```\n\n")
    lines.append("Then run the full pipeline:\n\n")
    lines.append("```bash\n")
    lines.append("python3 run_all.py\n")
    lines.append("```\n")

    md_path.write_text("".join(lines), encoding="utf-8")

    # Write manifest.json (machine-readable)
    # Convert any non-serializable types
    manifest_serializable = []
    for entry in DOWNLOAD_MANIFEST:
        clean = {}
        for k, v in entry.items():
            if isinstance(v, Path):
                clean[k] = str(v)
            else:
                clean[k] = v
        manifest_serializable.append(clean)

    manifest_path.write_text(
        json.dumps(manifest_serializable, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return md_path


def main(root: Path = None) -> int:
    """Generate download instructions. Returns 0 on success."""
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("download_instructions")
    logger.info("Generating download instructions...")

    setup_dirs(root)  # Ensure directories exist

    md_path = generate_instructions(root)
    manifest_path = md_path.parent / "manifest.json"

    logger.info(f"  Instructions: {md_path.relative_to(root)}")
    logger.info(f"  Manifest:     {manifest_path.relative_to(root)}")
    logger.info(f"  Total files to download: {len(DOWNLOAD_MANIFEST)}")
    logger.info("Download instructions generated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
