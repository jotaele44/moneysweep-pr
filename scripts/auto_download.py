"""
Automated download of expansion datasets (12/13 automated, 1 manual fallback).

Sources:
- FPDS (8 files): Atom/XML feed at fpds.gov; when the feed returns HTML (defunct),
  falls back to USASpending bulk_download (FY2000-2006) or spending_by_award (FY2007+)
- USASpending (4 files): REST API at api.usaspending.gov (no auth)
- FSRS (1 file): Manual download required (no public API)

Usage:
  python3 scripts/auto_download.py                  # Download all
  python3 scripts/auto_download.py --force           # Re-download existing files
  python3 scripts/auto_download.py --only=fpds       # FPDS only
  python3 scripts/auto_download.py --only=usaspending # USASpending only
"""

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests
from lxml import etree

from scripts.config import (
    DOWNLOAD_MANIFEST,
    EXPANSION_DIR,
    PROJECT_ROOT,
    read_csv_safe,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USASPENDING_BASE = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
USASPENDING_BULK_BASE   = "https://api.usaspending.gov/api/v2/bulk_download/awards/"
USASPENDING_BULK_STATUS = "https://api.usaspending.gov/api/v2/bulk_download/status/"
FPDS_BASE = "https://www.fpds.gov/ezsearch/fpdsportal"

# USASpending API: earliest supported start_date for spending_by_award
USASPENDING_MIN_YEAR = 2007

BULK_POLL_INTERVAL = 15   # seconds between status polls
BULK_TIMEOUT_SECS  = 600  # 10-minute ceiling for async job completion

USASPENDING_FIELDS = [
    "Award ID", "Recipient Name", "Recipient State Code",
    "Awarding Agency", "Awarding Sub Agency", "Award Amount",
    "Total Obligation", "Start Date", "End Date", "Award Type",
    "Place of Performance State Code", "Place of Performance City",
    "Description", "Contract Award Type", "NAICS Code",
    "generated_internal_id",
]

# Contract award type codes accepted by USASpending (A=BPA, B=Purchase Order, C=Delivery Order, D=Definitive Contract)
_CONTRACT_TYPE_CODES = ["A", "B", "C", "D"]

_IDV_TYPE_CODES = [
    "IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E",
]

FPDS_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "ns1": "https://www.fpds.gov/FPDS",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    """Create a requests session with proper headers."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (Federal Contract Research)",
        "Accept": "application/json",
    })
    return s


def _retry_request(session, method, url, retries=MAX_RETRIES, **kwargs):
    """Execute a request with retry logic and exponential backoff."""
    last_err = None
    for attempt in range(retries):
        try:
            if method == "GET":
                resp = session.get(url, **kwargs)
            else:
                resp = session.post(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            # Don't retry client errors (4xx) — they won't improve on retry
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise
            last_err = e
            if attempt < retries - 1:
                wait = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 8
                time.sleep(wait)
        except requests.RequestException as e:
            last_err = e
            if attempt < retries - 1:
                wait = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else 8
                time.sleep(wait)
    raise last_err


def _file_exists_with_data(filepath: Path) -> int:
    """Check if file exists and has rows. Returns row count or 0."""
    if not filepath.exists():
        return 0
    try:
        df = read_csv_safe(filepath, nrows=5)
        if len(df) > 0:
            # Count actual rows without loading full file
            with open(filepath, "r", encoding="utf-8-sig") as f:
                return sum(1 for _ in f) - 1  # subtract header
        return 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# USASpending Downloads
# ---------------------------------------------------------------------------

def _build_usaspending_payload(entry: dict) -> tuple:
    """Build USASpending API payload from manifest entry.

    Returns (payload, effective_start_year) where effective_start_year may be
    clamped to USASPENDING_MIN_YEAR if the manifest year_start is earlier.
    """
    filters = entry["filters"]
    ftype = entry["filter_type"]
    year_start = entry["year_start"]
    year_end = entry["year_end"]

    # spending_by_award only supports data from 2007-10-01 onward
    effective_start = max(year_start, USASPENDING_MIN_YEAR)

    payload_filters = {
        "time_period": [
            {"start_date": f"{effective_start}-10-01", "end_date": f"{year_end}-09-30"}
        ],
    }

    if ftype == "idv":
        payload_filters["award_type_codes"] = _IDV_TYPE_CODES
        payload_filters["keywords"] = ["Puerto Rico"]

    elif ftype == "dod":
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["agencies"] = [
            {"type": "awarding", "tier": "toptier", "name": "Department of Defense"},
        ]
        keywords = filters.get("Keywords", ["Puerto Rico"])
        payload_filters["keywords"] = keywords

    elif ftype == "reconstruction":
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        # FEMA and USACE are subtier agencies; HUD, DOT, VA are toptier
        _agency_map = {
            "FEMA":  {"tier": "subtier",  "name": "Federal Emergency Management Agency"},
            "HUD":   {"tier": "toptier",  "name": "Department of Housing and Urban Development"},
            "DOT":   {"tier": "toptier",  "name": "Department of Transportation"},
            "USACE": {"tier": "subtier",  "name": "U.S. Army Corps of Engineers"},
            "VA":    {"tier": "toptier",  "name": "Department of Veterans Affairs"},
        }
        raw_agencies = filters.get("Agencies", [])
        payload_filters["agencies"] = [
            {"type": "awarding", "tier": _agency_map[a]["tier"], "name": _agency_map[a]["name"]}
            for a in raw_agencies if a in _agency_map
        ]
        keywords = filters.get("Keywords", ["Puerto Rico"])
        payload_filters["keywords"] = keywords

    elif ftype == "direct":
        # FPDS direct fallback: place of performance = Puerto Rico
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["place_of_performance_locations"] = [{"state": "PR", "country": "USA"}]

    elif ftype == "vendor":
        # FPDS vendor fallback: recipient/vendor state = Puerto Rico
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["recipient_locations"] = [{"state": "PR", "country": "USA"}]

    payload = {
        "filters": payload_filters,
        "fields": USASPENDING_FIELDS,
        "page": 1,
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    return payload, effective_start


def _build_bulk_payload(entry: dict, fy_start: int, fy_end: int) -> dict:
    """Build a bulk_download/awards/ payload for the given fiscal-year range.

    Fiscal year N runs from (N-1)-10-01 to N-09-30.
    Supports filter_types: direct, vendor, idv, dod, reconstruction.
    """
    ftype = entry["filter_type"]
    filters = entry["filters"]

    payload_filters: dict = {
        "date_type": "action_date",
        "date_range": {
            "start_date": f"{fy_start - 1}-10-01",
            "end_date":   f"{fy_end}-09-30",
        },
    }

    if ftype == "direct":
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["agencies"] = []  # empty = all agencies (required field)
        payload_filters["place_of_performance_locations"] = [{"country": "USA", "state": "PR"}]

    elif ftype == "vendor":
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["agencies"] = []  # empty = all agencies (required field)
        payload_filters["recipient_locations"] = [{"country": "USA", "state": "PR"}]

    elif ftype == "idv":
        payload_filters["award_type_codes"] = _IDV_TYPE_CODES
        payload_filters["keywords"] = ["Puerto Rico"]

    elif ftype == "dod":
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["agencies"] = [
            {"type": "awarding", "tier": "toptier", "name": "Department of Defense"},
        ]
        payload_filters["keywords"] = filters.get("Keywords", ["Puerto Rico"])

    elif ftype == "reconstruction":
        _agency_map = {
            "FEMA":  {"tier": "subtier", "name": "Federal Emergency Management Agency"},
            "HUD":   {"tier": "toptier", "name": "Department of Housing and Urban Development"},
            "DOT":   {"tier": "toptier", "name": "Department of Transportation"},
            "USACE": {"tier": "subtier", "name": "U.S. Army Corps of Engineers"},
            "VA":    {"tier": "toptier", "name": "Department of Veterans Affairs"},
        }
        raw_agencies = filters.get("Agencies", [])
        payload_filters["award_type_codes"] = _CONTRACT_TYPE_CODES
        payload_filters["agencies"] = [
            {"type": "awarding", "tier": _agency_map[a]["tier"], "name": _agency_map[a]["name"]}
            for a in raw_agencies if a in _agency_map
        ]
        payload_filters["keywords"] = filters.get("Keywords", ["Puerto Rico"])

    return {
        "filters": payload_filters,
        "award_levels": ["prime_awards"],
        "file_format": "csv",
    }


def download_usaspending(entry: dict, output_dir: Path, logger, session: requests.Session) -> dict:
    """Download a single USASpending dataset via API."""
    fname = entry["filename"]
    result = {"filename": fname, "rows": 0, "status": "OK", "error": None}

    payload, effective_start = _build_usaspending_payload(entry)
    if effective_start > entry["year_start"]:
        logger.warning(
            f"  USASpending API supports data from {USASPENDING_MIN_YEAR}-10-01 only. "
            f"Clamping start year {entry['year_start']} → {effective_start}. "
            f"Pre-{USASPENDING_MIN_YEAR} data requires Custom Award Download from usaspending.gov."
        )

    all_results = []
    page = 1
    total_pages = None

    logger.info(f"  Querying USASpending API...")

    while True:
        payload["page"] = page

        try:
            resp = _retry_request(session, "POST", USASPENDING_BASE, json=payload, timeout=30)
            data = resp.json()
        except requests.HTTPError as e:
            body = e.response.text[:600] if e.response is not None else ""
            result["status"] = "FAILED"
            result["error"] = f"HTTP {e.response.status_code if e.response else '?'}: {body}"
            logger.error(f"  USASpending API HTTP error on page {page}: {e}")
            if body:
                logger.error(f"  Response body: {body}")
            break
        except Exception as e:
            result["status"] = "FAILED"
            result["error"] = str(e)
            logger.error(f"  API request failed on page {page}: {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        all_results.extend(results)

        # Estimate total pages
        page_meta = data.get("page_metadata", {})
        total = page_meta.get("total", 0)
        if total_pages is None and total > 0:
            total_pages = (total + 99) // 100
            logger.info(f"  Total records: ~{total}, pages: ~{total_pages}")

        if page % 10 == 0:
            logger.info(f"  Page {page}/{total_pages or '?'} ({len(all_results)} records)")

        if len(results) < 100:
            break

        page += 1
        time.sleep(1)  # Rate limiting

    if not all_results:
        if result["status"] == "OK":
            result["status"] = "EMPTY"
            logger.warning(f"  No results returned from USASpending API")
        return result

    # Convert to DataFrame
    df = pd.json_normalize(all_results)

    # Post-filter for IDV: exclude PR recipients
    if entry["filter_type"] == "idv" and "Recipient State Code" in df.columns:
        before = len(df)
        df = df[df["Recipient State Code"] != "PR"]
        logger.info(f"  Filtered out {before - len(df)} PR-recipient rows (IDV indirect)")

    # Save CSV
    output_path = output_dir / fname
    df.to_csv(output_path, index=False, encoding="utf-8")
    result["rows"] = len(df)
    logger.info(f"  Saved {len(df)} rows to {fname}")

    return result


# ---------------------------------------------------------------------------
# USASpending Bulk Download (async, supports FY2000+)
# ---------------------------------------------------------------------------

def download_usaspending_bulk(
    entry: dict,
    output_dir: Path,
    logger,
    session: requests.Session,
    fy_start: int = None,
    fy_end: int = None,
) -> dict:
    """Download via the USASpending bulk_download/awards/ async API.

    Unlike spending_by_award, this endpoint supports data back to FY2000 and
    works asynchronously: submit a job, poll until finished, download ZIP, extract CSV.
    """
    fname = entry["filename"]
    result = {"filename": fname, "rows": 0, "status": "OK", "error": None}

    fy_s = fy_start if fy_start is not None else entry["year_start"]
    fy_e = fy_end   if fy_end   is not None else entry["year_end"]

    payload = _build_bulk_payload(entry, fy_s, fy_e)
    logger.info(
        f"  Submitting bulk_download for FY{fy_s}-{fy_e} "
        f"(filter_type={entry['filter_type']})..."
    )

    # --- Step 1: Submit job ---
    import json as _json
    logger.debug(f"  bulk_download payload: {_json.dumps(payload, indent=2)}")
    try:
        resp = _retry_request(session, "POST", USASPENDING_BULK_BASE, json=payload, timeout=30)
        job = resp.json()
    except requests.HTTPError as e:
        body = e.response.text[:800] if e.response is not None else ""
        result["status"] = "FAILED"
        result["error"] = f"bulk_download POST HTTP {getattr(e.response,'status_code','?')}: {body}"
        logger.error(f"  bulk_download POST failed: {e}")
        logger.error(f"  Response body: {body!r}")
        return result
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        logger.error(f"  bulk_download POST failed: {e}")
        return result

    file_name = job.get("file_name") or job.get("file_url", "")
    if not file_name:
        result["status"] = "FAILED"
        result["error"] = f"bulk_download response missing file_name: {job}"
        logger.error(result["error"])
        return result

    logger.info(f"  Job submitted — token: {file_name}")

    # --- Step 2: Poll for completion ---
    deadline = time.time() + BULK_TIMEOUT_SECS
    download_url = None

    while time.time() < deadline:
        time.sleep(BULK_POLL_INTERVAL)
        try:
            status_resp = _retry_request(
                session, "GET", USASPENDING_BULK_STATUS,
                params={"file_name": file_name}, timeout=15,
            )
            status_data = status_resp.json()
        except Exception as e:
            logger.warning(f"  Status poll error (will retry): {e}")
            continue

        state = status_data.get("status", "").lower()
        logger.info(f"  Job status: {state}")

        if state == "finished":
            download_url = status_data.get("url") or status_data.get("file_url")
            break
        elif state in ("failed", "error"):
            result["status"] = "FAILED"
            result["error"] = f"bulk_download job failed: {status_data}"
            logger.error(result["error"])
            return result

    if download_url is None:
        result["status"] = "FAILED"
        result["error"] = f"bulk_download timed out after {BULK_TIMEOUT_SECS}s"
        logger.error(result["error"])
        return result

    logger.info("  Downloading ZIP from presigned URL...")

    # --- Step 3: Download ZIP ---
    try:
        zip_resp = session.get(download_url, timeout=120, stream=True)
        zip_resp.raise_for_status()
        zip_bytes = zip_resp.content
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = f"ZIP download failed: {e}"
        logger.error(result["error"])
        return result

    # --- Step 4: Extract primary awards CSV from ZIP ---
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            members = zf.namelist()
            logger.info(f"  ZIP members: {members}")
            csv_members = [m for m in members if m.lower().endswith(".csv")]
            if not csv_members:
                result["status"] = "FAILED"
                result["error"] = f"No CSV in ZIP. Members: {members}"
                logger.error(result["error"])
                return result
            # Prefer files that mention "prime" or "award" in the name
            preferred = next(
                (m for m in csv_members if "prime" in m.lower() or "award" in m.lower()),
                None,
            )
            if preferred is None:
                preferred = max(csv_members, key=lambda m: zf.getinfo(m).file_size)
            logger.info(f"  Extracting: {preferred}")
            csv_bytes = zf.read(preferred)
    except zipfile.BadZipFile as e:
        result["status"] = "FAILED"
        result["error"] = f"Invalid ZIP: {e}"
        logger.error(result["error"])
        return result
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = f"ZIP extraction failed: {e}"
        logger.error(result["error"])
        return result

    # --- Step 5: Save and verify ---
    output_path = output_dir / fname
    output_path.write_bytes(csv_bytes)

    try:
        df_check = read_csv_safe(output_path, nrows=5)
        if len(df_check) == 0:
            result["status"] = "EMPTY"
            logger.warning("  bulk_download CSV is empty after extraction")
            return result
        with open(output_path, "r", encoding="utf-8-sig", errors="replace") as f:
            row_count = max(sum(1 for _ in f) - 1, 0)
        result["rows"] = row_count
    except Exception as e:
        logger.warning(f"  Could not verify row count: {e}")
        result["rows"] = -1

    logger.info(f"  Saved {result['rows']} rows to {fname}")
    return result


# ---------------------------------------------------------------------------
# FPDS Downloads
# ---------------------------------------------------------------------------

def _build_fpds_query(entry: dict) -> str:
    """Build FPDS Atom feed query string from manifest entry."""
    ftype = entry["filter_type"]
    year_start = entry["year_start"]
    year_end = entry["year_end"]

    # Date range uses fiscal year boundaries
    date_range = f"SIGNED_DATE:[{year_start - 1}/10/01,{year_end}/09/30]"

    if ftype == "direct":
        state_filter = 'PRINCIPAL_PLACE_OF_PERFORMANCE_STATE_CODE:"PR"'
    else:
        state_filter = 'VENDOR_ADDRESS_STATE_CODE:"PR"'

    return f"{state_filter} {date_range}"


def _parse_fpds_entry(entry_elem) -> dict:
    """Extract all fields from a single FPDS Atom entry element."""
    row = {}

    # Walk all descendant elements and collect text values
    for elem in entry_elem.iter():
        tag = elem.tag
        # Strip namespace
        if "}" in tag:
            tag = tag.split("}")[-1]

        # Collect text content
        if elem.text and elem.text.strip():
            # Handle duplicate tags by preferring the first value
            if tag not in row:
                row[tag] = elem.text.strip()

        # Also collect attributes (some FPDS fields are in attributes)
        for attr_name, attr_val in elem.attrib.items():
            key = f"{tag}_{attr_name}"
            if key not in row and attr_val.strip():
                row[key] = attr_val.strip()

    # Remove Atom boilerplate keys
    for skip in ["entry", "content", "title", "link", "id", "updated", "author", "name"]:
        row.pop(skip, None)

    return row


def download_fpds(entry: dict, output_dir: Path, logger, session: requests.Session) -> dict:
    """Download a single FPDS dataset via Atom feed."""
    fname = entry["filename"]
    result = {"filename": fname, "rows": 0, "status": "OK", "error": None}

    query = _build_fpds_query(entry)
    logger.info(f"  FPDS query: {query}")

    all_records = []
    offset = 0
    page_size = 500
    total_results = None

    # Set Accept header for XML
    xml_session = requests.Session()
    xml_session.headers.update({
        "User-Agent": "ContractSweeper/1.0 (Federal Contract Research)",
        "Accept": "application/atom+xml",
    })

    while True:
        url = (
            f"{FPDS_BASE}?s=FPDS&indexName=awardfull&templateName=1.5.3"
            f"&q={requests.utils.quote(query)}&start={offset}&length={page_size}"
        )

        try:
            resp = _retry_request(xml_session, "GET", url, timeout=60)
        except Exception as e:
            result["status"] = "FAILED"
            result["error"] = str(e)
            logger.error(f"  FPDS request failed at offset {offset}: {e}")
            break

        # Detect HTML response — FPDS Atom/XML feed endpoint is defunct
        content_start = resp.content[:500].lower()
        if b"<!doctype" in content_start or b"<html" in content_start:
            result["status"] = "MANUAL"
            result["error"] = "FPDS Atom API is defunct — manual browser download required"
            logger.warning(f"  FPDS returned HTML (Atom feed defunct); USASpending fallback will be attempted for post-{USASPENDING_MIN_YEAR} windows")
            break

        # Parse XML — recover=True tolerates minor malformations (e.g. unescaped &)
        try:
            root = etree.fromstring(resp.content, etree.XMLParser(recover=True))
        except etree.XMLSyntaxError as e:
            result["status"] = "FAILED"
            result["error"] = f"XML parse error: {e}"
            logger.error(f"  FPDS XML parse error: {e}")
            logger.info(f"  Response snippet: {resp.content[:300]!r}")
            break

        # Get total results count on first page
        if total_results is None:
            total_elem = root.find(".//opensearch:totalResults", FPDS_NS)
            if total_elem is not None and total_elem.text:
                total_results = int(total_elem.text)
                logger.info(f"  Total FPDS results: {total_results}")
            else:
                total_results = 0

        # Extract entries
        entries = root.findall(".//atom:entry", FPDS_NS)
        if not entries:
            break

        for entry_elem in entries:
            row = _parse_fpds_entry(entry_elem)
            if row:
                all_records.append(row)

        page_num = (offset // page_size) + 1
        if page_num % 5 == 0:
            logger.info(f"  Page {page_num} ({len(all_records)}/{total_results or '?'} records)")

        offset += page_size

        if total_results is not None and offset >= total_results:
            break

        time.sleep(0.5)  # Rate limiting

    xml_session.close()

    if not all_records:
        if result["status"] == "OK":
            result["status"] = "EMPTY"
            logger.warning(f"  No FPDS records found")
        return result

    # Convert to DataFrame and save
    df = pd.DataFrame(all_records)
    output_path = output_dir / fname
    df.to_csv(output_path, index=False, encoding="utf-8")
    result["rows"] = len(df)
    logger.info(f"  Saved {len(df)} rows to {fname}")

    return result


# ---------------------------------------------------------------------------
# FSRS Downloads
# ---------------------------------------------------------------------------

def download_fsrs(entry: dict, output_dir: Path, logger, session: requests.Session) -> dict:
    """Attempt FSRS download. Falls back to manual instructions."""
    fname = entry["filename"]
    result = {"filename": fname, "rows": 0, "status": "MANUAL", "error": None}

    logger.info(f"  Attempting FSRS download...")

    # Try form POST
    try:
        resp = session.post(
            "https://www.fsrs.gov/rss",
            data={"s": "Search", "pop_state": "PR", "reportType": "sub_award"},
            timeout=15,
            allow_redirects=False,
        )

        # Check if we got actual data (not an HTML page)
        content_type = resp.headers.get("Content-Type", "")
        if "text/csv" in content_type or "application/csv" in content_type:
            output_path = output_dir / fname
            output_path.write_bytes(resp.content)
            # Verify it's valid CSV
            df = read_csv_safe(output_path)
            result["rows"] = len(df)
            result["status"] = "OK"
            logger.info(f"  Saved {len(df)} rows to {fname}")
            return result
        elif resp.status_code == 200 and "," in resp.text[:500]:
            # Might be CSV with wrong content type
            output_path = output_dir / fname
            output_path.write_text(resp.text, encoding="utf-8")
            try:
                df = read_csv_safe(output_path)
                if len(df) > 0:
                    result["rows"] = len(df)
                    result["status"] = "OK"
                    logger.info(f"  Saved {len(df)} rows to {fname}")
                    return result
            except Exception:
                output_path.unlink(missing_ok=True)

    except Exception as e:
        logger.debug(f"  FSRS auto-download failed: {e}")

    # Fallback: manual instructions
    logger.info(f"  FSRS requires manual download:")
    logger.info(f"    1. Go to https://www.fsrs.gov")
    logger.info(f"    2. Search Sub-Awards → Place of Performance State = PR")
    logger.info(f"    3. Export as CSV → save as data/staging/expansion/{fname}")
    result["status"] = "MANUAL"
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def download_single(entry: dict, output_dir: Path, logger, session: requests.Session, force: bool = False) -> dict:
    """Download a single file, dispatching by source type."""
    fname = entry["filename"]
    filepath = output_dir / fname
    source = entry["source"]

    # Resume logic: skip if already exists with data
    if not force:
        existing_rows = _file_exists_with_data(filepath)
        if existing_rows > 0:
            logger.info(f"  Skipping: already exists ({existing_rows} rows)")
            return {"filename": fname, "rows": existing_rows, "status": "SKIPPED", "error": None}

    if source == "FPDS":
        result = download_fpds(entry, output_dir, logger, session)
        if result["status"] in ("FAILED", "MANUAL"):
            if entry["year_end"] < USASPENDING_MIN_YEAR:
                # Entire window is pre-2007 (e.g. FY2000-2004): spending_by_award
                # won't go back this far, so use the async bulk_download API instead.
                logger.info(
                    f"  Pre-{USASPENDING_MIN_YEAR} window — "
                    f"using USASpending bulk_download for FY{entry['year_start']}-{entry['year_end']}..."
                )
                result = download_usaspending_bulk(entry, output_dir, logger, session)
            elif entry["year_start"] < USASPENDING_MIN_YEAR:
                # Window straddles the 2007 boundary (e.g. FY2005-2008): use
                # bulk_download for the full range so FY2005-2006 is not silently lost.
                logger.info(
                    f"  Window spans pre-{USASPENDING_MIN_YEAR} boundary — "
                    f"using bulk_download for full FY{entry['year_start']}-{entry['year_end']}..."
                )
                result = download_usaspending_bulk(entry, output_dir, logger, session)
            else:
                # Fully post-2007 (e.g. FY2009-2016): use the fast paginated API.
                logger.info(
                    f"  Falling back to USASpending spending_by_award "
                    f"for FY{entry['year_start']}-{entry['year_end']}..."
                )
                result = download_usaspending(entry, output_dir, logger, session)
        return result
    elif source == "USASpending":
        return download_usaspending(entry, output_dir, logger, session)
    elif source == "FSRS":
        return download_fsrs(entry, output_dir, logger, session)
    else:
        logger.warning(f"  Unknown source: {source}")
        return {"filename": fname, "rows": 0, "status": "FAILED", "error": f"Unknown source: {source}"}


def download_all(root: Path = None, force: bool = False, only: str = None) -> list:
    """Download all expansion datasets. Returns list of result dicts."""
    if root is None:
        root = PROJECT_ROOT

    output_dir = root / "data" / "staging" / "expansion"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("auto_download")
    session = _session()
    results = []

    # Filter manifest by source if --only specified
    manifest = DOWNLOAD_MANIFEST
    if only:
        only_lower = only.lower()
        manifest = [m for m in manifest if m["source"].lower() == only_lower]
        if not manifest:
            logger.warning(f"No entries match --only={only}. Available: FPDS, USASpending, FSRS")
            return []

    total = len(manifest)
    for i, entry in enumerate(manifest, 1):
        fname = entry["filename"]
        logger.info(f"[{i}/{total}] {fname} ({entry['source']})")

        try:
            result = download_single(entry, output_dir, logger, session, force=force)
        except Exception as e:
            logger.error(f"  Unexpected error: {e}")
            result = {"filename": fname, "rows": 0, "status": "FAILED", "error": str(e)}

        results.append(result)
        logger.info(f"  → {result['status']} ({result['rows']} rows)")
        logger.info("")

    session.close()
    return results


def print_download_summary(results: list, logger) -> None:
    """Print download summary table."""
    logger.info("=" * 70)
    logger.info("DOWNLOAD SUMMARY")
    logger.info("=" * 70)
    logger.info(f"{'Filename':<50} {'Rows':>8} {'Status':>8}")
    logger.info("-" * 70)

    for r in results:
        logger.info(f"{r['filename']:<50} {r['rows']:>8} {r['status']:>8}")

    ok = sum(1 for r in results if r["status"] == "OK")
    skipped = sum(1 for r in results if r["status"] == "SKIPPED")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    empty = sum(1 for r in results if r["status"] == "EMPTY")
    manual = sum(1 for r in results if r["status"] == "MANUAL")
    total_rows = sum(r["rows"] for r in results)

    logger.info("-" * 70)
    logger.info(
        f"Total: {len(results)} files | OK: {ok} | Skipped: {skipped} | "
        f"Failed: {failed} | Empty: {empty} | Manual: {manual}"
    )
    logger.info(f"Total rows: {total_rows:,}")

    if failed > 0:
        logger.info("")
        logger.info("Failed downloads:")
        for r in results:
            if r["status"] == "FAILED":
                logger.info(f"  {r['filename']}: {r.get('error', 'unknown')}")

    if manual > 0:
        logger.info("")
        logger.info("Manual downloads required:")
        for r in results:
            if r["status"] == "MANUAL":
                logger.info(f"  {r['filename']}: see DOWNLOAD_INSTRUCTIONS.md")


def main(root: Path = None, force: bool = False, only: str = None) -> int:
    """Run auto-download. Returns count of successfully downloaded files."""
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("auto_download")
    logger.info("Starting automated downloads...")
    logger.info("")

    results = download_all(root, force=force, only=only)
    print_download_summary(results, logger)

    ok_count = sum(1 for r in results if r["status"] in ("OK", "SKIPPED"))
    return ok_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-download expansion datasets")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    parser.add_argument("--only", type=str, help="Download only: fpds, usaspending, or fsrs")
    args = parser.parse_args()

    count = main(force=args.force, only=args.only)
    print(f"\nDownloaded/verified {count} files.")
    sys.exit(0)
