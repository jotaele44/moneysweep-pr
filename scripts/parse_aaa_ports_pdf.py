"""
Parse the acquired AAA / Ports Authority completed-projects PDF into structured rows.

The operator has `completed_projects_AAA.pdf` on hand (see README manual-source
backlog) but no parser existed. This feeds `ports_airports_contracts`. The PDF is a
semi-structured table; this parser uses pdfplumber when available and falls back to a
graceful empty result so the pipeline never hard-fails on a missing optional input.

Input:  data/raw/documents/completed_projects_AAA.pdf (operator-delivered)
Output: data/staging/processed/pr_ports_airports_contracts.csv (merged, deduped)

Usage:
  python3 scripts/parse_aaa_ports_pdf.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging
from scripts._contract_dropzone import CONTRACT_COLUMNS, _normalize_name

AGENCY = "AUTORIDAD DE LOS PUERTOS"


def _candidate_pdfs(root):
    docs = root / "data" / "raw" / "documents"
    if not docs.exists():
        return []
    return sorted(p for p in docs.glob("*AAA*.pdf")) + sorted(p for p in docs.glob("*ports*.pdf"))


def _rows_from_pdf(path, logger):
    try:
        import pdfplumber  # type: ignore
    except Exception:
        logger.warning("  pdfplumber not installed — skipping PDF extraction.")
        return []
    rows = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    header = [str(c or "").strip().lower() for c in table[0]]
                    for raw in table[1:]:
                        cells = [str(c or "").strip() for c in raw]
                        record = dict(zip(header, cells))
                        vendor = (
                            record.get("contractor")
                            or record.get("vendor")
                            or record.get("contratista")
                            or ""
                        )
                        if not vendor:
                            continue
                        rows.append(
                            {
                                "contract_id": record.get("project") or record.get("id") or "",
                                "vendor_name": vendor,
                                "vendor_normalized": _normalize_name(vendor),
                                "contract_type": record.get("type") or "completed_project",
                                "contract_value": record.get("amount") or record.get("monto") or "",
                                "award_date": record.get("date") or record.get("fecha") or "",
                                "start_date": "",
                                "end_date": "",
                                "status": "completed",
                                "description": record.get("description")
                                or record.get("descripcion")
                                or "",
                                "municipality": record.get("municipality")
                                or record.get("municipio")
                                or "",
                                "agency": AGENCY,
                                "source_file": path.name,
                            }
                        )
    except Exception as e:
        logger.warning(f"  Failed to parse {path.name}: {e}")
    logger.info(f"  → {len(rows):,} rows from {path.name}")
    return rows


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_ports_airports_contracts.csv"
    logger = setup_logging("parse_aaa_ports_pdf")

    pdfs = _candidate_pdfs(root)
    if not pdfs:
        logger.info("  No AAA/ports PDF found in data/raw/documents/ — nothing to parse.")
        return {"rows": 0, "path": str(out_path), "errors": ["No AAA ports PDF present"]}

    all_rows = []
    for pdf in pdfs:
        all_rows.extend(_rows_from_pdf(pdf, logger))

    if not all_rows:
        return {"rows": 0, "path": str(out_path), "errors": ["No rows extracted from PDF(s)"]}

    new_df = pd.DataFrame(all_rows, columns=CONTRACT_COLUMNS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not force:
        existing = pd.read_csv(out_path, dtype=str, na_filter=False, low_memory=False)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined = combined.drop_duplicates(subset=["vendor_normalized", "contract_id"])
    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  → wrote {len(combined):,} ports/airports contract rows")
    return {"rows": len(combined), "path": str(out_path), "errors": []}


def main():
    parser = argparse.ArgumentParser(description="Parse AAA ports completed-projects PDF")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nAAA ports PDF parse complete: {result['rows']:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
