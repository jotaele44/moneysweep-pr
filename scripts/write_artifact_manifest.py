"""Write a deterministic artifact manifest for export packages and source files.

The manifest is intended to be shared with SpiderWeb consumers. It records file
hashes, byte sizes, row/record counts, generated timestamp, export version, and
source fingerprints without reading any secrets or using network access.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STREAMS = (
    "entities.jsonl",
    "sources.jsonl",
    "funding_awards.jsonl",
    "transactions.jsonl",
    "relationships.jsonl",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _csv_rows(path: Path) -> int | None:
    if path.suffix.lower() != ".csv":
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        count = sum(1 for _ in reader)
    return max(0, count - 1)


def _jsonl_rows(path: Path) -> int | None:
    if path.suffix.lower() != ".jsonl":
        return None
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    csv_count = _csv_rows(path)
    jsonl_count = _jsonl_rows(path)
    record_count = jsonl_count if jsonl_count is not None else csv_count
    return {
        "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "record_count": record_count,
    }


def write_artifact_manifest(
    package_dir: str | Path,
    output_path: str | Path | None = None,
    *,
    source_files: list[str | Path] | None = None,
    export_version: str | None = None,
    producer: str = "moneysweep-pr",
) -> dict[str, Any]:
    """Create an artifact manifest for a package directory plus optional inputs."""

    package = Path(package_dir)
    if output_path is None:
        output_path = package / "artifact_manifest.json"
    output = Path(output_path)

    package_manifest_path = package / "manifest.json"
    package_manifest: dict[str, Any] = {}
    if package_manifest_path.exists():
        package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))

    version = (
        export_version
        or package_manifest.get("export_contract_version")
        or package_manifest.get("export_version")
    )

    artifact_files: list[dict[str, Any]] = []
    for name in DEFAULT_STREAMS:
        path = package / name
        if path.exists():
            artifact_files.append(_file_record(path, package))
    for extra in sorted(package.glob("*.json")):
        if extra.name == output.name or extra.name in {"artifact_manifest.json"}:
            continue
        if extra.name == "manifest.json" or extra.name.endswith("report.json"):
            artifact_files.append(_file_record(extra, package))

    source_records: list[dict[str, Any]] = []
    for raw in source_files or []:
        path = Path(raw)
        if path.exists():
            source_records.append(_file_record(path, path.parent))

    manifest = {
        "schema_version": "artifact_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer,
        "export_contract_version": version,
        "package_dir": str(package),
        "artifact_count": len(artifact_files),
        "source_count": len(source_records),
        "artifacts": artifact_files,
        "sources": source_records,
    }
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write artifact manifest for moneysweep-pr export outputs."
    )
    parser.add_argument("--package-dir", required=True, help="Export package directory")
    parser.add_argument(
        "--out", default=None, help="Manifest output path; default: package/artifact_manifest.json"
    )
    parser.add_argument(
        "--source-file",
        action="append",
        default=[],
        help="Optional source CSV/file to fingerprint; repeatable",
    )
    parser.add_argument("--export-version", default=None)
    args = parser.parse_args(argv)
    manifest = write_artifact_manifest(
        args.package_dir,
        args.out,
        source_files=args.source_file,
        export_version=args.export_version,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
