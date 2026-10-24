#!/usr/bin/env python3
"""Bounded, credential-free SAM PUBLIC_CURRENT artifact probe.

Never makes a certification claim. Preserves exact original bytes *before* parsing.
The PUBLIC_CURRENT extract is NOT proof of full Active+Inactive membership,
or of Puerto Rico award activity. No file is promoted to a canonical identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SAM_URL = (
    "https://s3.amazonaws.com/falextracts/Assistance%20Listings/datagov/"
    "AssistanceListings_DataGov_PUBLIC_CURRENT.csv"
)
MAX_BYTES = 250 * 1024 * 1024
REQUIRED = ("Program Number", "Program Title", "Types of Assistance (060)")
FINANCIAL_TOKENS = (
    "GRANT", "COOPERATIVE AGREEMENT", "DIRECT PAYMENT", "LOAN", "INSURANCE",
    "FINANCIAL ASSISTANCE", "SALE, EXCHANGE, OR DONATION",
)


def sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_snapshot(path: Path) -> dict:
    """Parse the frozen source file; no cleanup or identifier coercion."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("SOURCE_BYTES_MISSING")
    count = financial = 0
    seen = set()
    with path.open("r", encoding="cp1252", errors="strict", newline="") as f:
        # Permit a bounded vendor preamble, but require unambiguous header.
        for lineno in range(1, 12):
            pos = f.tell()
            line = f.readline()
            if not line:
                raise ValueError("SAM_HEADER_MISSING")
            if all(h in line for h in REQUIRED):
                f.seek(pos)
                break
        else:
            raise ValueError("SAM_HEADER_NOT_FOUND_WITHIN_11_LINES")
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(REQUIRED).issubset(fields):
            raise ValueError("SAM_HEADER_INVALID_OR_DUPLICATE")
        for record in reader:
            count += 1
            if None in record:
                raise ValueError(f"CSV_COLUMN_OVERFLOW_AT_ROW_{count}")
            code = (record.get("Program Number") or "").strip()
            if not code:
                raise ValueError(f"BLANK_PROGRAM_NUMBER_AT_ROW_{count}")
            if code in seen:
                raise ValueError(f"DUPLICATE_PROGRAM_NUMBER_{code}")
            seen.add(code)
            if not (record.get("Program Title") or "").strip():
                raise ValueError(f"BLANK_PROGRAM_TITLE_AT_ROW_{count}")
            kind = (record.get("Types of Assistance (060)") or "").upper()
            financial += int(any(token in kind for token in FINANCIAL_TOKENS))
    if not count:
        raise ValueError("EMPTY_PROGRAM_SOURCE")
    return {"rows": count, "unique_program_numbers": len(seen),
            "financial_listing_rows": financial,
            "nonfinancial_listing_rows": count-financial,
            "program_number_matching": "EXACT_STRING_NOT_NAME_ONLY",
            "no_canonical_identity_promotion": True}


def fetch_preserve_raw(destination: Path):
    """Retrieve only the hardcoded public GSA extract with streaming byte limit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(SAM_URL, headers={"User-Agent": "PR-Program-Registry-Source-Probe/1.0"})
    fd, tmp = tempfile.mkstemp(prefix=".sam-source-", dir=destination.parent)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out, urlopen(request, timeout=90) as response:
            final_url = response.geturl()
            if not final_url.startswith("https://"):
                raise RuntimeError("INSECURE_REDIRECT_REJECTED")
            while True:
                buf = response.read(1024 * 1024)
                if not buf:
                    break
                size += len(buf)
                if size > MAX_BYTES:
                    raise RuntimeError("SOURCE_SIZE_LIMIT_EXCEEDED")
                out.write(buf)
        if size == 0:
            raise RuntimeError("EMPTY_RESPONSE")
        os.replace(tmp, destination)
        return final_url
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    source_path = outdir / "AssistanceListings_DataGov_PUBLIC_CURRENT.csv"
    receipt_path = outdir / "source_receipt.json"
    receipt = {
        "schema_version": "pr_registry_sam_raw_source_probe_v1",
        "retrieval_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_url": SAM_URL,
        "authority": "GSA_SAM_PUBLIC_CURRENT_FILE_EXTRACT",
        "query_status_scope": "PUBLIC_CURRENT_NOT_PROVEN_ALL_ACTIVE_INACTIVE",
        "pr_activity_confirmed": False,
        "source_universe_complete": False,
        "award_level_pr_binding_complete": False,
        "canonical_program_count": None,
        "certification": "WITHHELD",
        "state": "BLOCKED",
    }
    try:
        receipt["retrieved_url"] = fetch_preserve_raw(source_path)
        receipt["source_sha256"] = sha256_bytes(source_path)
        receipt["source_size_bytes"] = source_path.stat().st_size
        receipt["parse"] = parse_snapshot(source_path)
        receipt["state"] = "SOURCE_BYTES_ACQUIRED_BOUNDED_PARSE_PASS"
    except Exception as exc:
        receipt["error_class"] = type(exc).__name__
        receipt["error_message"] = str(exc)[:500]
        receipt["state"] = "BLOCKED_SOURCE_FETCH_OR_PARSE"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["state"] == "SOURCE_BYTES_ACQUIRED_BOUNDED_PARSE_PASS" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", type=Path, default=Path("outputs/sam_source_probe"))
    args = parser.parse_args()
    sys.exit(run(args.outdir))
