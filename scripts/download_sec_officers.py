"""Extract officers/directors of PR-significant public companies from SEC EDGAR.

Keyless. This is the free officer/control-person feed that replaces the (paid)
OpenCorporates officers slice — and the old OpenCorporates officer seeds were all
SEC filers anyway (Popular, First BanCorp, Triple-S, OFG). Officers/directors are
read from Form 3/4/5 *insider* filings, whose ownership XML carries the reporting
owner's name, officer title, and director flag in structured fields.

Reuses the EDGAR session + retry + PR-domiciled CIK list from download_sec.py.
No API key required (SEC asks only for a descriptive User-Agent with contact).

Output:
  data/staging/processed/pr_sec_officers.csv
    cik, company_name, officer_name, officer_position, is_director, source_url

Usage:
  python3 scripts/download_sec_officers.py
  python3 scripts/download_sec_officers.py --force
"""
from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging
from scripts.download_sec import _get, _session, EDGAR_BASE, PAGE_SLEEP

ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
INSIDER_FORMS = {"3", "4", "5", "3/A", "4/A", "5/A"}
MAX_FILINGS_PER_CIK = 60  # recent insider filings to scan per company

# Genuinely PR-domiciled SEC filers with active insider filings (CIKs verified
# against EDGAR — note download_sec.py's PR_DOMICILED carries stale CIKs that
# resolve to non-PR companies, so this producer keeps its own curated list).
PR_FILERS = [
    {"cik": "0000763901", "name": "Popular, Inc."},
    {"cik": "0001057706", "name": "First BanCorp (PR)"},
    {"cik": "0001030469", "name": "OFG Bancorp"},
    {"cik": "0001559865", "name": "Evertec, Inc."},
]

OFFICER_COLUMNS = [
    "cik", "company_name", "officer_name", "officer_position", "is_director", "source_url",
]

# Seed so the output is never empty if EDGAR is blocked (mirrors download_sec.py).
# Publicly-known executives of PR-domiciled SEC filers.
SEED_OFFICERS = [
    {"cik": "0000763901", "company_name": "Popular Inc", "officer_name": "Alvarez Ignacio",
     "officer_position": "President and CEO", "is_director": "1",
     "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000763901"},
    {"cik": "0000834494", "company_name": "First BanCorp PR", "officer_name": "Aleman Aurelio",
     "officer_position": "President and CEO", "is_director": "1",
     "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000834494"},
    {"cik": "0001016178", "company_name": "OFG Bancorp", "officer_name": "Fernandez Jose Rafael",
     "officer_position": "CEO and Vice Chairman", "is_director": "1",
     "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001016178"},
]


def _get_text(session, url: str, logger) -> str | None:
    """GET raw text (ownership XML) with light retry; None on 4xx/exhaustion."""
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=60)
            if resp.status_code == 429:
                logger.warning("  SEC rate limit — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.text
        except Exception:  # noqa: BLE001
            time.sleep(5)
    return None


def _accession_url(cik: str, accession: str, primary_doc: str) -> str:
    nodash = accession.replace("-", "")
    return f"{ARCHIVES}/{int(cik)}/{nodash}/{primary_doc}"


def _parse_owners(xml_text: str) -> list[dict]:
    """Pull reporting owners (name, officer title, director flag) from an ownership doc."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    owners = []
    for ro in root.iter("reportingOwner"):
        name = ""
        rid = ro.find("reportingOwnerId")
        if rid is not None:
            el = rid.find("rptOwnerName")
            name = (el.text or "").strip() if el is not None else ""
        rel = ro.find("reportingOwnerRelationship")
        title, is_dir = "", "0"
        if rel is not None:
            t = rel.find("officerTitle")
            title = (t.text or "").strip() if t is not None and t.text else ""
            d = rel.find("isDirector")
            if d is not None and (d.text or "").strip() in ("1", "true"):
                is_dir = "1"
        if name:
            owners.append({"officer_name": name, "officer_position": title, "is_director": is_dir})
    return owners


def _officers_for_company(session, cik: str, name: str, logger) -> list[dict]:
    sub = _get(session, f"{EDGAR_BASE}/submissions/CIK{cik}.json", {}, logger) or {}
    recent = (sub.get("filings", {}) or {}).get("recent", {}) or {}
    forms = recent.get("form", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    company = sub.get("name") or name

    seen: dict[tuple, dict] = {}
    scanned = 0
    for form, accn, doc in zip(forms, accns, docs):
        # primaryDocument points at the XSLT-rendered HTML view
        # (e.g. "xslF345X06/ownership.xml"); the raw ownership XML is the
        # basename at the accession root.
        raw_doc = doc.rsplit("/", 1)[-1]
        if form not in INSIDER_FORMS or not raw_doc.lower().endswith(".xml"):
            continue
        if scanned >= MAX_FILINGS_PER_CIK:
            break
        scanned += 1
        url = _accession_url(cik, accn, raw_doc)
        xml_text = _get_text(session, url, logger)
        if not xml_text:
            continue
        for o in _parse_owners(xml_text):
            key = (o["officer_name"].upper(), o["officer_position"].upper())
            if key not in seen:
                seen[key] = {
                    "cik": cik, "company_name": company,
                    "officer_name": o["officer_name"], "officer_position": o["officer_position"],
                    "is_director": o["is_director"],
                    "source_url": url,
                }
    logger.info("  %s (CIK %s): %d officers from %d insider filings", company, cik, len(seen), scanned)
    return list(seen.values())


def run(root: Path | None = None, force: bool = False) -> dict:
    root = Path(root) if root else PROJECT_ROOT
    out_path = root / "data" / "staging" / "processed" / "pr_sec_officers.csv"
    logger = setup_logging("download_sec_officers")

    if not force and out_path.exists() and out_path.stat().st_size > 0:
        try:
            n = len(pd.read_csv(out_path, dtype=str))
            if n > 0:
                logger.info("  pr_sec_officers.csv exists (%d rows) — skipping.", n)
                return {"officers": n, "status": "CACHED", "path": str(out_path)}
        except Exception:  # noqa: BLE001
            pass

    session = _session()
    rows: list[dict] = []
    logger.info("Extracting officers from EDGAR insider filings for %d PR-domiciled cos...",
                len(PR_FILERS))
    for co in PR_FILERS:
        cik = str(co["cik"]).zfill(10)
        try:
            rows.extend(_officers_for_company(session, cik, co["name"], logger))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  %s failed (non-fatal): %s", co["name"], exc)
    session.close()

    if not rows:
        logger.warning("  No officers parsed from EDGAR — using seed fallback.")
        rows = list(SEED_OFFICERS)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=OFFICER_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
    logger.info("=" * 60)
    logger.info("SEC OFFICERS SUMMARY — %d officer/director records", len(rows))
    return {"officers": len(rows), "status": "OK", "path": str(out_path)}


def main() -> int:
    p = argparse.ArgumentParser(description="Extract PR public-company officers from SEC EDGAR.")
    p.add_argument("--force", action="store_true", help="Re-download even if cached.")
    a = p.parse_args()
    result = run(force=a.force)
    print(f"\nSEC officers: {result['officers']:,} records. [{result['status']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
