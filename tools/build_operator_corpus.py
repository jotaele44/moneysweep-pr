from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        CORPUS_SCHEMA_VERSION,
        csv_rows,
        expected_outputs,
        load_sources,
        manifest_digest,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        CORPUS_SCHEMA_VERSION,
        csv_rows,
        expected_outputs,
        load_sources,
        manifest_digest,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )


def _load_receipts(receipts_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not receipts_dir.exists():
        raise RuntimeError(f"receipt directory does not exist: {receipts_dir}")
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(receipts_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"receipt must contain an object: {path}")
        loaded.append((path, payload))
    if not loaded:
        raise RuntimeError(f"no operator evidence receipts found in {receipts_dir}")
    return loaded


def _validate_receipt_shape(receipt: dict[str, Any], path: Path) -> None:
    errors = validate_receipt(receipt)
    if errors:
        raise RuntimeError(f"invalid operator evidence receipt {path}: " + "; ".join(errors))


def _output_allowed(output_path: str, expected: list[str]) -> bool:
    for item in expected:
        if item.endswith("/"):
            if output_path.startswith(item):
                return True
        elif output_path == item:
            return True
    return False


def _processed_inventory(root: Path) -> set[str]:
    processed = root / "data" / "staging" / "processed"
    if not processed.exists():
        return set()
    return {
        path.relative_to(root).as_posix() for path in processed.rglob("*.csv") if path.is_file()
    }


def build(*, root: Path, receipts_dir: Path, corpus_root: Path) -> dict[str, Any]:
    root = root.resolve()
    receipts_dir = receipts_dir.resolve()
    corpus_root = corpus_root.resolve()
    sources, registry_paths = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    registry_digest = source_ids_digest(sources)

    receipts = _load_receipts(receipts_dir)
    seen_sources: set[str] = set()
    manifest_sources: list[dict[str, Any]] = []
    receipt_output_paths: set[str] = set()

    if corpus_root.exists():
        shutil.rmtree(corpus_root)
    objects_dir = corpus_root / "objects" / "sha256"
    mount_dir = corpus_root / "mount"
    receipt_copy_dir = corpus_root / "receipts"
    objects_dir.mkdir(parents=True, exist_ok=True)
    mount_dir.mkdir(parents=True, exist_ok=True)
    receipt_copy_dir.mkdir(parents=True, exist_ok=True)

    for receipt_path, receipt in receipts:
        _validate_receipt_shape(receipt, receipt_path)
        source_id = str(receipt["source_id"]).strip()
        if source_id in seen_sources:
            raise RuntimeError(f"duplicate receipt for source_id: {source_id}")
        seen_sources.add(source_id)
        source = source_by_id.get(source_id)
        if source is None:
            raise RuntimeError(f"receipt references unknown source_id: {source_id}")

        expected = expected_outputs(source)
        receipt_registry = receipt["registry"]
        if receipt_registry.get("source_ids_sha256") != registry_digest:
            raise RuntimeError(f"registry digest mismatch for receipt: {source_id}")
        definition_digest = source_definition_digest(source)
        if receipt_registry.get("source_definition_sha256") != definition_digest:
            raise RuntimeError(f"source definition digest mismatch for receipt: {source_id}")

        output_records: list[dict[str, Any]] = []
        seen_output_paths: set[str] = set()
        for output in receipt["outputs"]:
            rel = safe_relative_path(str(output.get("path", ""))).as_posix()
            if rel in seen_output_paths:
                raise RuntimeError(f"duplicate output path in receipt {source_id}: {rel}")
            seen_output_paths.add(rel)
            if not _output_allowed(rel, expected):
                raise RuntimeError(f"undeclared promotion output for {source_id}: {rel}")

            artifact = root / rel
            if not artifact.exists() or not artifact.is_file():
                raise RuntimeError(f"receipt artifact missing for {source_id}: {rel}")
            actual_sha = sha256_file(artifact)
            actual_bytes = artifact.stat().st_size
            actual_rows = csv_rows(artifact)
            if artifact.suffix.lower() == ".csv" and actual_rows is None:
                raise RuntimeError(f"unreadable CSV for {source_id}: {rel}")
            if output.get("sha256") != actual_sha:
                raise RuntimeError(f"sha256 mismatch for {source_id}: {rel}")
            if output.get("bytes") != actual_bytes:
                raise RuntimeError(f"byte-count mismatch for {source_id}: {rel}")
            if output.get("rows") != actual_rows:
                raise RuntimeError(f"row-count mismatch for {source_id}: {rel}")

            object_path = objects_dir / actual_sha[:2] / actual_sha[2:]
            object_path.parent.mkdir(parents=True, exist_ok=True)
            if not object_path.exists():
                shutil.copy2(artifact, object_path)
            elif sha256_file(object_path) != actual_sha:
                raise RuntimeError(f"content-addressed object collision: {actual_sha}")

            mounted = mount_dir / rel
            mounted.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(object_path, mounted)
            receipt_output_paths.add(rel)
            output_records.append(
                {
                    "path": rel,
                    "sha256": actual_sha,
                    "bytes": actual_bytes,
                    "rows": actual_rows,
                    "object": f"objects/sha256/{actual_sha[:2]}/{actual_sha[2:]}",
                }
            )

        receipt_copy = receipt_copy_dir / f"{source_id}.json"
        receipt_copy.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_sources.append(
            {
                "source_id": source_id,
                "required": source.get("required") is True,
                "source_definition_sha256": definition_digest,
                "receipt_sha256": sha256_file(receipt_copy),
                "receipt_path": f"receipts/{source_id}.json",
                "outputs": sorted(output_records, key=lambda item: item["path"]),
            }
        )

    operator_processed = _processed_inventory(root)
    receipted_processed = {
        path for path in receipt_output_paths if path.startswith("data/staging/processed/")
    }
    unreceipted_processed = sorted(operator_processed - receipted_processed)
    manifest: dict[str, Any] = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "registry": {
            "total_sources": len(sources),
            "required_sources": sum(source.get("required") is True for source in sources),
            "source_ids_sha256": registry_digest,
            "registry_paths": registry_paths,
        },
        "snapshot": {
            "processed_inventory_complete": not unreceipted_processed,
            "operator_processed_csv_files": len(operator_processed),
            "receipted_processed_csv_files": len(receipted_processed),
            "unreceipted_processed_files": unreceipted_processed,
        },
        "sources": sorted(manifest_sources, key=lambda item: item["source_id"]),
    }
    manifest["corpus_id"] = manifest_digest(manifest)
    manifest_path = corpus_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a content-addressed operator corpus.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, default=Path("build/operator-corpus"))
    args = parser.parse_args()

    manifest = build(root=args.root, receipts_dir=args.receipts, corpus_root=args.corpus_root)
    print(
        json.dumps(
            {
                "corpus_id": manifest["corpus_id"],
                "receipt_sources": len(manifest["sources"]),
                "registry_total_sources": manifest["registry"]["total_sources"],
                "processed_inventory_complete": manifest["snapshot"][
                    "processed_inventory_complete"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
