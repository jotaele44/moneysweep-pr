#!/usr/bin/env python3
"""Normalize daily PR News intake into router-ready raw JSONL.

This producer does not scrape the web. It consumes already collected public
records from JSONL, JSON, or CSV and writes the canonical intake file consumed
by the shared PR intake router:

    data/intake/pr_news/raw_items_latest.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


DEFAULT_INPUT = Path("data/intake/pr_news/incoming_items_latest.jsonl")
DEFAULT_OUTPUT = Path("data/intake/pr_news/raw_items_latest.jsonl")
DEFAULT_MANIFEST = Path("data/intake/pr_news/raw_items_latest_manifest.json")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize PR News intake into router-ready JSONL."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Input JSONL, JSON, or CSV from PR News capture.",
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT), help="Canonical router-ready JSONL output path."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Run manifest JSON path.")
    parser.add_argument(
        "--strict-missing-input",
        action="store_true",
        help="Return exit code 2 if the input file is missing. Default is to write an empty output and manifest.",
    )
    return parser.parse_args(argv)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_items(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                item = json.loads(stripped)
                if not isinstance(item, dict):
                    raise ValueError(f"JSONL line {line_number} is not an object")
                items.append(item)
        return items

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "items" in data:
            data = data["items"]
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ValueError("JSON input must be an array of objects or {'items': [objects]}")
        return list(data)

    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    raise ValueError(f"Unsupported input format: {path.suffix}. Use .jsonl, .json, or .csv")


def coalesce(item: Mapping[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def stable_hash(*parts: Any) -> str:
    payload = json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def infer_evidence_tier(item: Mapping[str, Any]) -> str:
    source_type = coalesce(item, "source_type", "platform", "document_type").lower()
    source_name = coalesce(item, "source_name", "agency_or_entity", "author_or_entity").lower()
    url = coalesce(item, "source_url", "url", "link").lower()
    if any(
        token in source_type
        for token in ("contract", "dataset", "registry", "procurement", "official record")
    ):
        return "T1"
    if any(token in source_type for token in ("official", "press release", "government", "agency")):
        return "T2"
    if any(token in source_type for token in ("image", "video", "screenshot", "signage")):
        return "T3"
    if any(
        token in source_name
        for token in (
            "gobierno",
            "fortaleza",
            "cor3",
            "fema",
            "hacienda",
            "ogp",
            "dtop",
            "prasa",
            "aaa",
            "prepa",
            "aee",
            "noaa",
            "usgs",
            "epa",
        )
    ):
        return "T2"
    if ".gov" in url or ".pr.gov" in url:
        return "T2"
    return "T4"


def infer_confidence(item: Mapping[str, Any]) -> str:
    has_url = bool(coalesce(item, "source_url", "url", "link"))
    has_title = bool(coalesce(item, "title", "headline"))
    has_entity = bool(coalesce(item, "source_name", "agency_or_entity", "author_or_entity"))
    if has_url and has_title and has_entity:
        return "High"
    if (has_url and has_title) or (has_title and has_entity):
        return "Medium"
    return "Low"


def normalize_item(item: Mapping[str, Any], *, index: int, discovered_at: str) -> Dict[str, Any]:
    source_url = coalesce(item, "source_url", "url", "link")
    source_name = coalesce(
        item, "source_name", "agency_or_entity", "author_or_entity", default="unknown_source"
    )
    title = coalesce(item, "title", "headline", "name", default="untitled")
    summary = coalesce(item, "summary_own_words", "summary", "description", "caption", "excerpt")
    content = coalesce(item, "content", "text", "body")
    published_at = coalesce(item, "published_at", "date_posted", "date", "created_at")
    municipality = coalesce(item, "municipality_name", "municipality", "municipio")
    location_text = coalesce(
        item, "location_text", "location", "ubicacion", "ubicación", default=municipality
    )

    source_item_id = coalesce(item, "source_item_id", "item_id")
    if not source_item_id:
        digest = stable_hash(source_url, source_name, title, published_at)[:12]
        source_item_id = f"PRNEWS-RAW-{digest}"

    normalized = dict(item)
    normalized.update(
        {
            "source_item_id": source_item_id,
            "source_name": source_name,
            "source_url": source_url,
            "published_at": published_at,
            "discovered_at": coalesce(item, "discovered_at", default=discovered_at),
            "title": title,
            "summary_own_words": summary,
            "content": content,
            "municipality_name": municipality,
            "location_text": location_text,
            "evidence_tier": coalesce(item, "evidence_tier", default=infer_evidence_tier(item)),
            "confidence_level": coalesce(item, "confidence_level", default=infer_confidence(item)),
            "source_hash": coalesce(
                item, "source_hash", default=stable_hash(source_url, source_name)
            ),
            "content_hash": coalesce(
                item, "content_hash", default=stable_hash(title, summary, content, source_url)
            ),
            "dedupe_group_id": coalesce(item, "dedupe_group_id", default=""),
            "producer": "pr_news_raw_intake",
            "producer_index": index,
        }
    )
    return normalized


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(manifest), indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def main_with_args(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest)
    discovered_at = utc_now_iso()

    if not input_path.exists():
        manifest = {
            "producer": "pr_news_raw_intake",
            "status": "missing_input",
            "input_path": str(input_path),
            "output_path": str(output_path),
            "manifest_path": str(manifest_path),
            "discovered_at": discovered_at,
            "input_count": 0,
            "output_count": 0,
            "zero_loss_pass": True,
        }
        write_jsonl(output_path, [])
        write_manifest(manifest_path, manifest)
        print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
        return 2 if args.strict_missing_input else 0

    raw_items = load_items(input_path)
    normalized = [
        normalize_item(item, index=i + 1, discovered_at=discovered_at)
        for i, item in enumerate(raw_items)
    ]

    write_jsonl(output_path, normalized)
    manifest = {
        "producer": "pr_news_raw_intake",
        "status": "ok",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
        "discovered_at": discovered_at,
        "input_count": len(raw_items),
        "output_count": len(normalized),
        "zero_loss_pass": len(raw_items) == len(normalized),
    }
    write_manifest(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if manifest["zero_loss_pass"] else 1


def main() -> int:
    return main_with_args()


if __name__ == "__main__":
    raise SystemExit(main())
