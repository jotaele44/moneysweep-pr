#!/usr/bin/env python3
"""Acquire original Commonwealth public audit PDF bytes; never certify program identity.

Each HTTPS response is preserved exactly. PDF text is a corroboration aid only.
Network errors are recorded per source. No official program lifecycle is inferred.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SOURCES = {
    "prde_2020": "https://hacienda.pr.gov/sites/default/files/puerto_rico_department_of_education_1.pdf",
    "upr_2023": "https://hacienda.pr.gov/sites/default/files/upr_fs_2023.pdf",
    "upr_2024": "https://hacienda.pr.gov/sites/default/files/university_of_puerto_rico_3.pdf",
}
MAX_BYTES = 95 * 1024 * 1024


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def fetch_pdf(url: str, destination: Path) -> dict:
    expected = urlparse(url)
    if expected.scheme != "https" or expected.hostname != "hacienda.pr.gov":
        raise ValueError("NON_GOVERNMENT_SOURCE_DENIED")
    request = Request(url, headers={"User-Agent": "PR-Registry-Archive-Source-Reader/1.0"})
    handle, tmp = tempfile.mkstemp(prefix=".audit-", dir=destination.parent)
    n = 0
    try:
        with os.fdopen(handle, "wb") as f, urlopen(request, timeout=100) as response:
            actual = urlparse(response.geturl())
            if actual.scheme != "https" or actual.hostname != expected.hostname:
                raise ValueError("SOURCE_DOMAIN_REDIRECT_DENIED")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                n += len(chunk)
                if n > MAX_BYTES:
                    raise ValueError("SOURCE_TOO_LARGE")
                f.write(chunk)
        if n < 1024:
            raise ValueError("SOURCE_TOO_SMALL")
        with open(tmp, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise ValueError("NOT_PDF_BYTES")
        os.replace(tmp, destination)
        return {
            "state": "SOURCE_PDF_BYTES_ACQUIRED",
            "original_url": url,
            "byte_count": n,
            "sha256": sha256(destination),
            "file": destination.name,
        }
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema_version": "pr_program_registry_primary_audit_pdf_v1",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "state": "BLOCKED",
        "pdf_visual_page_inspection": "INDEPENDENT_REVIEW_REQUIRED",
        "historical_84_938_vs_84_938T_equivalence": "UNADJUDICATED",
        "current_program_active_status": "NOT_ESTABLISHED",
        "canonical_program_promotion": False,
        "registry_certification": "WITHHELD",
    }
    for key, url in SOURCES.items():
        try:
            receipt["sources"][key] = fetch_pdf(url, folder / (key + ".pdf"))
        except Exception as error:
            receipt["sources"][key] = {
                "state": "FAILED_SOURCE_FETCH",
                "url": url,
                "error_type": type(error).__name__,
                "error_message": str(error)[:500],
            }
    if all(x["state"] == "SOURCE_PDF_BYTES_ACQUIRED" for x in receipt["sources"].values()):
        receipt["state"] = "THREE_ORIGINAL_PDFS_FROZEN"
    (folder / "source_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["state"] == "THREE_ORIGINAL_PDFS_FROZEN" else 2


if __name__ == "__main__":
    raise SystemExit(
        run(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/pr_education_primary_pdfs"))
    )
