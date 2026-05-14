"""Download FSRS (Federal Subaward Reporting System) subcontract data for Puerto Rico.

FSRS data is available through their web interface. This module attempts to:
1. Use the FSRS search form to export PR subcontract data (ideal case)
2. Fall back to manual download instructions if needed
3. Provide structured CSV compatible with contract-sweeper normalization

Note: FSRS doesn't have a public API; web scraping may be fragile.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
import logging

import requests
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "staging" / "expansion"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def fetch_fsrs_pr_subcontracts(output_path: Path, session: requests.Session = None) -> tuple[bool, int]:
    """Attempt to download FSRS PR subcontracts via form submission.
    
    Args:
        output_path: Path to write CSV
        session: Optional requests.Session for connection pooling
    
    Returns:
        Tuple of (success: bool, row_count: int)
    """
    if session is None:
        session = requests.Session()
    
    try:
        logger.info("Attempting FSRS API form submission...")
        
        # FSRS search form endpoint
        fsrs_url = "https://www.fsrs.gov/rss"
        
        # Search parameters: PR state, sub-awards only
        data = {
            "s": "Search",
            "pop_state": "PR",
            "reportType": "sub_award",
            "export": "csv",  # Attempt to trigger CSV export
        }
        
        # Try to fetch CSV
        resp = session.post(fsrs_url, data=data, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        
        content_type = resp.headers.get("Content-Type", "").lower()
        
        # Check if we got CSV content
        if "csv" in content_type or "," in resp.text[:200]:
            output_path.write_text(resp.text, encoding="utf-8")
            
            # Verify it's valid CSV
            try:
                df = pd.read_csv(output_path)
                logger.info(f"Successfully downloaded {len(df)} FSRS subcontracts for PR")
                return True, len(df)
            except Exception as e:
                logger.warning(f"Downloaded content not valid CSV: {e}")
                output_path.unlink(missing_ok=True)
        else:
            logger.debug(f"Unexpected content type: {content_type}")
            
    except Exception as e:
        logger.debug(f"FSRS form submission failed: {e}")
    
    return False, 0


def provide_manual_instructions():
    """Log instructions for manual FSRS download."""
    instructions = """
    
    ========== FSRS Manual Download Instructions ==========
    FSRS does not provide a public API; manual download is required.
    
    Steps to download Puerto Rico subcontract data:
    1. Go to: https://www.fsrs.gov/
    2. Click "Search Subawards" or navigate to the subaward search page
    3. Set "Place of Performance (State)" = PR (Puerto Rico)
    4. Set "Report Type" = Sub-Award
    5. Click "Search"
    6. Click "Export" → "CSV Format"
    7. Save file as: data/staging/expansion/expansion_subcontracts_pr.csv
    8. Re-run the pipeline (run_all.py)
    
    Note: FSRS searches require session persistence; if download fails:
    - Try a different browser
    - Clear browser cache
    - Try again at a different time
    
    ========================================================
    """
    logger.info(instructions)


def download_fsrs_subcontracts() -> dict:
    """Download FSRS data with fallback to manual instructions.
    
    Returns:
        Dict with keys: filename, rows, status, error
    """
    out_file = OUT_DIR / "expansion_subcontracts_pr.csv"
    
    result = {
        "filename": "expansion_subcontracts_pr.csv",
        "rows": 0,
        "status": "PENDING",
        "error": None,
    }
    
    # Try automatic download
    try:
        success, row_count = fetch_fsrs_pr_subcontracts(out_file)
        if success:
            result["status"] = "OK"
            result["rows"] = row_count
            return result
    except Exception as e:
        logger.warning(f"FSRS automatic download error: {e}")
        result["error"] = str(e)
    
    # Fallback: manual instructions
    provide_manual_instructions()
    result["status"] = "MANUAL"
    result["error"] = "No public API; manual download required"
    
    return result


def main():
    """CLI entry point for manual FSRS download."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    result = download_fsrs_subcontracts()
    
    if result["status"] == "OK":
        print(f"✓ Downloaded {result['rows']} FSRS subcontracts to {result['filename']}")
        return 0
    else:
        print(f"✗ FSRS download status: {result['status']}")
        if result["error"]:
            print(f"  Error: {result['error']}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
