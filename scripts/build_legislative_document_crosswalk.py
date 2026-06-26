"""Build a legislative document crosswalk from discovery records."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts.config import PROJECT_ROOT, setup_logging
except Exception:  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def setup_logging(name: str, log_dir: Path | None = None):
        import logging

        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        return logging.getLogger(name)

DEFAULT_INPUT = "data/staging/processed/pr_legislapr_measures_probe.json"
DEFAULT_OUTPUT = "data/staging/processed/pr_legislative_document_crosswalk.csv"
OFFICIAL_HOST_MARKERS = ("oslpr.org", "senado.pr.gov", "camara.pr.gov", "rcm.gov.pr")


def compact_measure_id(value: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    return raw.replace("PDELC", "PC").replace("PDELS", "PS")


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def is_official_document_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and any(marker in host for marker in OFFICIAL_HOST_MARKERS)


def first_document_url(row: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in ["sutra_url", "official_document_url"]:
        if row.get(key):
            candidates.append(str(row[key]))
    for value in row.get("document_urls") or []:
        candidates.append(str(value))
    for url in candidates:
        if is_official_document_url(url):
            return url
    return ""


def build_crosswalk(records: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        measure_id = compact_measure_id(str(row.get("measure_id") or ""))
        document_url = first_document_url(row)
        key = (measure_id, document_url)
        if not measure_id or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "measure_id": measure_id,
                "legislapr_url": str(row.get("source_url") or row.get("detail_url") or ""),
                "openstates_url": str(row.get("openstates_url") or ""),
                "document_url": document_url,
                "document_domain": urlparse(document_url).netloc.lower() if document_url else "",
                "crosswalk_status": "ready" if document_url and row.get("openstates_url") else "needs_review",
            }
        )
    return rows


def run(root: Path | None = None, input_path: str = DEFAULT_INPUT, output_path: str = DEFAULT_OUTPUT) -> dict[str, Any]:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("build_legislative_document_crosswalk", log_dir=root / "data" / "logs")
    rows = build_crosswalk(read_records(root / input_path))
    out = root / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["measure_id", "legislapr_url", "openstates_url", "document_url", "document_domain", "crosswalk_status"])
        writer.writeheader()
        writer.writerows(rows)
    logger.info("legislative document crosswalk: %s rows", len(rows))
    return {"status": "OK" if rows else "EMPTY", "rows": len(rows), "output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(run(input_path=args.input, output_path=args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
