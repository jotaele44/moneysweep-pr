from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        RECEIPT_SCHEMA_VERSION,
        csv_rows,
        expected_outputs,
        load_sources,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        RECEIPT_SCHEMA_VERSION,
        csv_rows,
        expected_outputs,
        load_sources,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
    )


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _declared(rel: str, expected: list[str]) -> bool:
    return any(rel == item or (item.endswith("/") and rel.startswith(item)) for item in expected)


def _expected_satisfied(expected_path: str, actual_paths: set[str]) -> bool:
    if expected_path.endswith("/"):
        return any(path.startswith(expected_path) for path in actual_paths)
    return expected_path in actual_paths


def _bool_text(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def build_receipt(
    *,
    root: Path,
    source_id: str,
    outputs: list[str],
    producer_sha: str,
    producer: str | None = None,
    source_url: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    http_status: int | None = None,
    coverage_contract_pass: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    sources, _ = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    source = source_by_id.get(source_id)
    if source is None:
        raise RuntimeError(f"unknown source_id: {source_id}")
    if len(producer_sha) != 40 or any(char not in "0123456789abcdef" for char in producer_sha):
        raise RuntimeError("producer_sha must be a lowercase 40-character Git SHA")

    registered_producer = str(source.get("producer_script") or "").strip()
    resolved_producer = (producer or registered_producer).strip()
    if not resolved_producer:
        raise RuntimeError(f"acquisition producer is not available for {source_id}")
    expected = expected_outputs(source)
    if not outputs:
        raise RuntimeError("at least one output is required")

    output_records: list[dict[str, Any]] = []
    actual_paths: set[str] = set()
    positive_checks: list[bool] = []
    for value in outputs:
        rel = safe_relative_path(value).as_posix()
        if rel in actual_paths:
            raise RuntimeError(f"duplicate output path: {rel}")
        actual_paths.add(rel)
        if not _declared(rel, expected):
            raise RuntimeError(f"output is not declared for {source_id}: {rel}")
        path = root / rel
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"output is missing for {source_id}: {rel}")
        rows = csv_rows(path)
        positive_checks.append(rows > 0 if rows is not None else path.stat().st_size > 0)
        output_records.append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "rows": rows,
                "content_type": ("text/csv" if path.suffix.lower() == ".csv" else None),
            }
        )

    expected_complete = all(_expected_satisfied(item, actual_paths) for item in expected)
    resolved_url = (
        source_url or str(source.get("endpoint_url") or source.get("source_url") or "").strip()
    )
    if not resolved_url:
        raise RuntimeError(f"source URL is not available for {source_id}")
    completed_at = completed_at or datetime.now(timezone.utc).isoformat()
    acquisition: dict[str, Any] = {
        "producer": resolved_producer,
        "producer_sha": producer_sha,
        "completed_at": completed_at,
        "source_url": resolved_url,
        "http_status": http_status,
    }
    if started_at is not None:
        acquisition["started_at"] = started_at

    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source_id": source_id,
        "acquisition": acquisition,
        "registry": {
            "source_ids_sha256": source_ids_digest(sources),
            "source_definition_sha256": source_definition_digest(source),
        },
        "outputs": sorted(output_records, key=lambda item: item["path"]),
        "validation": {
            "schema_valid": True,
            "positive_rows": all(positive_checks),
            "coverage_contract_pass": coverage_contract_pass,
            "expected_outputs_complete": expected_complete,
            "expected_output_count": len(expected),
            "receipted_output_count": len(actual_paths),
            "registered_producer": registered_producer,
            "producer_matches_registry": (resolved_producer == registered_producer),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a registry-bound operator evidence receipt."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", action="append", required=True, dest="outputs")
    parser.add_argument("--producer-sha")
    parser.add_argument("--producer")
    parser.add_argument("--source-url")
    parser.add_argument("--started-at")
    parser.add_argument("--completed-at")
    parser.add_argument("--http-status", type=int)
    parser.add_argument(
        "--coverage-contract-pass",
        type=_bool_text,
        default=False,
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=Path("data/manifests/operator_evidence"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    producer_sha = args.producer_sha or _head(root)
    receipt = build_receipt(
        root=root,
        source_id=args.source_id,
        outputs=args.outputs,
        producer_sha=producer_sha,
        producer=args.producer,
        source_url=args.source_url,
        started_at=args.started_at,
        completed_at=args.completed_at,
        http_status=args.http_status,
        coverage_contract_pass=args.coverage_contract_pass,
    )
    receipt_dir = args.receipt_dir
    if not receipt_dir.is_absolute():
        receipt_dir = root / receipt_dir
    receipt_dir.mkdir(parents=True, exist_ok=True)
    output_path = receipt_dir / f"{args.source_id}.json"
    output_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"receipt": str(output_path), "source_id": args.source_id},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
