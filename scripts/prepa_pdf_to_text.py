#!/usr/bin/env python3
"""Extract text from a PREPA Title III PDF for stakeholder analysis."""

from __future__ import annotations

import argparse
from pathlib import Path


def extract_pdf_text(pdf_path: Path) -> tuple[str, list[int]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SystemExit("Install dependency first: pip install pypdf") from exc

    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    empty_pages: list[int] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            empty_pages.append(idx)
        chunks.append(f"\n\n--- PAGE {idx} ---\n{text}")
    return "\n".join(chunks), empty_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract PDF text for PREPA pipeline")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_text", type=Path)
    parser.add_argument("--empty-page-report", type=Path)
    args = parser.parse_args()

    text, empty_pages = extract_pdf_text(args.pdf)
    args.output_text.parent.mkdir(parents=True, exist_ok=True)
    args.output_text.write_text(text, encoding="utf-8")

    if args.empty_page_report:
        args.empty_page_report.parent.mkdir(parents=True, exist_ok=True)
        args.empty_page_report.write_text("\n".join(str(p) for p in empty_pages), encoding="utf-8")

    print(f"empty_pages={len(empty_pages)} output={args.output_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
