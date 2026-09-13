"""Collect the FOMB /reports/ special-report surface omitted from /fomb-reports/.

This is a narrow companion to scripts/download_fomb.py. It preserves the raw
HTML response and emits one row per downloadable report link so the special
investigative/report collection remains independently auditable.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.base_downloader import build_session
from scripts.config import PROJECT_ROOT, setup_logging
from scripts.download_fomb import (
    HTTP,
    _canonical_url,
    _extract_links,
    _looks_like_document,
    _publication_date,
)

SOURCE_URL = "https://oversightboard.pr.gov/reports/"
OUT_REL = "data/staging/processed/pr_fomb_special_reports.csv"
RAW_HTML_REL = "data/raw/FOMB/discovery/special_reports.html"
RAW_HEADERS_REL = "data/raw/FOMB/discovery/special_reports.headers.json"
COLUMNS = [
    "report_id",
    "title_raw",
    "publication_date",
    "source_url",
    "download_url",
    "retrieved_at",
]


def run(root: Path | str | None = None):
    root = Path(root) if root is not None else PROJECT_ROOT
    logger = setup_logging("download_fomb_special_reports")
    session = build_session(HTTP.user_agent)
    retrieved_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    response = session.get(SOURCE_URL, timeout=HTTP.timeout)
    response.raise_for_status()
    session.close()

    raw_html = root / RAW_HTML_REL
    raw_html.parent.mkdir(parents=True, exist_ok=True)
    raw_html.write_bytes(response.content)
    (root / RAW_HEADERS_REL).write_text(
        json.dumps(
            {
                "source_url": SOURCE_URL,
                "retrieved_at": retrieved_at,
                "status_code": response.status_code,
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "byte_size": len(response.content),
                "headers": {k: v for k, v in response.headers.items() if k.lower() != "set-cookie"},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    rows = []
    for link in _extract_links(response.text, SOURCE_URL):
        if not _looks_like_document(link.href, link.text):
            continue
        stable = f"special_reports|{_canonical_url(link.href)}|{link.text}"
        rows.append(
            {
                "report_id": hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24],
                "title_raw": link.text,
                "publication_date": _publication_date(link.text),
                "source_url": SOURCE_URL,
                "download_url": link.href,
                "retrieved_at": retrieved_at,
            }
        )
    unique = {row["report_id"]: row for row in rows}
    rows = sorted(
        unique.values(), key=lambda r: (r["publication_date"], r["title_raw"], r["download_url"])
    )
    out = root / OUT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Materialized %s FOMB special-report links", len(rows))
    return {"rows": len(rows), "path": str(out), "errors": [], "status": "OK" if rows else "ERROR"}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["rows"] else 1)
