#!/usr/bin/env python3
"""Parse PREPA Title III service-matrix text into structured CSV.

Input options:
- plain text extracted from the PDF
- OCR/text dump containing service-list pages

The parser is conservative. It emits candidate rows with raw text, parsed entity
name, address/email metadata, parser confidence, and evidence tier. It is built
for reviewable extraction, not silent attribution.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
HEADER_RE = re.compile(
    r"^(Service List|Puerto Rico - PREPA|Claim Name Address Information|EPIQ BANKRUPTCY|Case:)",
    re.I,
)
PAGE_RE = re.compile(r"Document Page\s+(\d+)\s+of\s+410", re.I)


def clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def is_noise(line: str) -> bool:
    line = clean_line(line)
    return not line or bool(HEADER_RE.search(line))


def likely_entity_start(line: str) -> bool:
    if is_noise(line):
        return False
    if EMAIL_RE.search(line):
        return True
    # Service matrix rows usually begin with all-caps entity/person names.
    head = line[:80]
    letters = re.findall(r"[A-Za-z]", head)
    uppers = re.findall(r"[A-Z]", head)
    return bool(letters) and len(uppers) / max(len(letters), 1) > 0.72


def parse_entry(raw: str, page: str | None) -> dict[str, str]:
    emails = ";".join(EMAIL_RE.findall(raw))
    no_emails = EMAIL_RE.sub(" ", raw)
    tokens = clean_line(no_emails)

    # Split entity name from address by common address cues.
    split_match = re.search(
        r"\b(ATTN:|C/O|PO BOX|P\.O\. BOX|PMB|HC |RR |\d{1,5}\s+[A-Z0-9])\b",
        tokens,
        flags=re.I,
    )
    if split_match:
        entity_name = clean_line(tokens[: split_match.start()])
        address = clean_line(tokens[split_match.start() :])
    else:
        parts = tokens.split(" ")
        entity_name = clean_line(" ".join(parts[: min(len(parts), 8)]))
        address = clean_line(" ".join(parts[min(len(parts), 8) :]))

    confidence = "0.80" if entity_name and (emails or address) else "0.55"
    return {
        "entity_name": entity_name,
        "address_or_service_metadata": address,
        "emails": emails,
        "source_page": page or "",
        "evidence_tier": "T1_technical_primary",
        "parser_confidence": confidence,
        "raw_entry": raw,
    }


def parse_text(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    buffer: list[str] = []
    page: str | None = None

    for raw_line in text.splitlines():
        line = clean_line(raw_line)
        page_match = PAGE_RE.search(line)
        if page_match:
            page = page_match.group(1)
        if is_noise(line):
            continue
        if likely_entity_start(line) and buffer:
            rows.append(parse_entry(" ".join(buffer), page))
            buffer = [line]
        else:
            buffer.append(line)
    if buffer:
        rows.append(parse_entry(" ".join(buffer), page))
    return rows


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entity_name",
        "address_or_service_metadata",
        "emails",
        "source_page",
        "evidence_tier",
        "parser_confidence",
        "raw_entry",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse PREPA Title III service matrix text into CSV"
    )
    parser.add_argument(
        "input_text", type=Path, help="Text dump extracted from PREPA Title III service matrix PDF"
    )
    parser.add_argument("output_csv", type=Path, help="Structured CSV output path")
    args = parser.parse_args()

    text = args.input_text.read_text(encoding="utf-8", errors="replace")
    rows = parse_text(text)
    write_csv(rows, args.output_csv)
    print(f"parsed_rows={len(rows)} output={args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
