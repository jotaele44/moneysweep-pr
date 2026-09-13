from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        CORPUS_SCHEMA_VERSION,
        VERIFICATION_SCHEMA_VERSION,
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
        VERIFICATION_SCHEMA_VERSION,
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


def _expected_claims(output_path: str, expected: list[str]) -> bool:
    for item in expected:
        if item.endswith("/"):
            if output_path.startswith(item):
                return True
        elif output_path == item:
            return True
    return False


def _expected_satisfied(expected_path: str, actual_paths: set[str]) -> bool:
    if expected_path.endswith("/"):
        return any(path.startswith(expected_path) for path in actual_paths)
    return expected_path in actual_paths


def _processed_inventory(root: Path) -> set[str]:
    processed = root / "data" / "staging" / "processed"
    if not processed.exists():
        return set()
    return {
        path.relative_to(root).as_posix() for path in processed.rglob("*.csv") if path.is_file()
    }


def verify(
    *,
    root: Path,
    corpus_root: Path,
    require_operator_snapshot: bool = True,
) -> dict[str, Any]:
    """Verify corpus bytes and, by default, the complete operator snapshot.

    ``require_operator_snapshot=False`` is only for later content revalidation of
    an already-issued full verification receipt. It can prove that the immutable
    corpus still matches its manifest, but it can never independently award
    operator-corpus authority.
    """
    root = root.resolve()
    corpus_root = corpus_root.resolve()
    errors: list[str] = []
    sources, registry_paths = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    current_registry_digest = source_ids_digest(sources)
    current_required = sum(source.get("required") is True for source in sources)

    manifest_path = corpus_root / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"operator corpus manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("operator corpus manifest must contain an object")

    if manifest.get("schema_version") != CORPUS_SCHEMA_VERSION:
        errors.append("unsupported_corpus_schema")
    claimed_corpus_id = manifest.get("corpus_id")
    computed_corpus_id = manifest_digest(manifest)
    if claimed_corpus_id != computed_corpus_id:
        errors.append("corpus_id_mismatch")

    registry = manifest.get("registry")
    if not isinstance(registry, dict):
        registry = {}
        errors.append("manifest_registry_missing")
    if registry.get("total_sources") != len(sources):
        errors.append("registry_total_sources_mismatch")
    if registry.get("required_sources") != current_required:
        errors.append("registry_required_sources_mismatch")
    if registry.get("source_ids_sha256") != current_registry_digest:
        errors.append("registry_source_ids_digest_mismatch")
    if registry.get("registry_paths") != registry_paths:
        errors.append("registry_paths_mismatch")

    snapshot = manifest.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
        errors.append("manifest_snapshot_missing")
    if snapshot.get("processed_inventory_complete") is not True:
        errors.append("processed_inventory_not_complete")
    if snapshot.get("unreceipted_processed_files") not in ([], None):
        errors.append("manifest_records_unreceipted_processed_files")

    manifest_sources = manifest.get("sources")
    if not isinstance(manifest_sources, list):
        manifest_sources = []
        errors.append("manifest_sources_missing")

    seen_source_ids: set[str] = set()
    manifest_output_paths: set[str] = set()
    source_results: list[dict[str, Any]] = []
    for entry in manifest_sources:
        if not isinstance(entry, dict):
            errors.append("invalid_manifest_source_entry")
            continue
        source_id = str(entry.get("source_id", "")).strip()
        source_errors: list[str] = []
        if not source_id:
            errors.append("empty_manifest_source_id")
            continue
        if source_id in seen_source_ids:
            errors.append(f"duplicate_manifest_source:{source_id}")
            continue
        seen_source_ids.add(source_id)
        source = source_by_id.get(source_id)
        if source is None:
            errors.append(f"unknown_manifest_source:{source_id}")
            continue

        definition_digest = source_definition_digest(source)
        if entry.get("source_definition_sha256") != definition_digest:
            source_errors.append("source_definition_digest_mismatch")

        receipt_rel = safe_relative_path(str(entry.get("receipt_path", "")))
        receipt_path = corpus_root / receipt_rel
        receipt_contract_errors: list[str] = []
        if not receipt_path.exists() or not receipt_path.is_file():
            source_errors.append("receipt_missing")
            receipt: dict[str, Any] = {}
            receipt_contract_errors.append("receipt_missing")
        else:
            if sha256_file(receipt_path) != entry.get("receipt_sha256"):
                source_errors.append("receipt_sha256_mismatch")
            try:
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
                source_errors.append("receipt_unreadable")
            receipt = payload if isinstance(payload, dict) else {}
            receipt_contract_errors = validate_receipt(receipt)
            source_errors.extend(f"receipt_contract:{item}" for item in receipt_contract_errors)
            if receipt.get("source_id") != source_id:
                source_errors.append("receipt_source_id_mismatch")
            receipt_registry = receipt.get("registry")
            if not isinstance(receipt_registry, dict):
                source_errors.append("receipt_registry_missing")
            else:
                if receipt_registry.get("source_ids_sha256") != current_registry_digest:
                    source_errors.append("receipt_registry_digest_mismatch")
                if receipt_registry.get("source_definition_sha256") != definition_digest:
                    source_errors.append("receipt_definition_digest_mismatch")

        outputs = entry.get("outputs")
        if not isinstance(outputs, list):
            outputs = []
            source_errors.append("manifest_outputs_missing")
        actual_paths: set[str] = set()
        receipt_outputs = receipt.get("outputs") if isinstance(receipt, dict) else None
        receipt_by_path = {
            str(item.get("path")): item
            for item in receipt_outputs or []
            if isinstance(item, dict) and item.get("path")
        }

        for output in outputs:
            if not isinstance(output, dict):
                source_errors.append("invalid_manifest_output")
                continue
            rel = safe_relative_path(str(output.get("path", ""))).as_posix()
            actual_paths.add(rel)
            manifest_output_paths.add(rel)
            expected = expected_outputs(source)
            if not _expected_claims(rel, expected):
                source_errors.append(f"undeclared_output:{rel}")

            receipt_output = receipt_by_path.get(rel)
            if receipt_output is None:
                source_errors.append(f"receipt_output_missing:{rel}")
            else:
                for key in ("sha256", "bytes", "rows"):
                    if receipt_output.get(key) != output.get(key):
                        source_errors.append(f"receipt_manifest_{key}_mismatch:{rel}")

            object_rel = safe_relative_path(str(output.get("object", "")))
            object_path = corpus_root / object_rel
            mount_path = corpus_root / "mount" / rel
            expected_sha = output.get("sha256")
            expected_bytes = output.get("bytes")
            expected_rows = output.get("rows")
            for label, path in (("object", object_path), ("mount", mount_path)):
                if not path.exists() or not path.is_file():
                    source_errors.append(f"{label}_missing:{rel}")
                    continue
                if sha256_file(path) != expected_sha:
                    source_errors.append(f"{label}_sha256_mismatch:{rel}")
                if path.stat().st_size != expected_bytes:
                    source_errors.append(f"{label}_bytes_mismatch:{rel}")
                actual_rows = csv_rows(path, logical_path=rel)
                if Path(rel).suffix.lower() == ".csv" and actual_rows is None:
                    source_errors.append(f"{label}_csv_unreadable:{rel}")
                if actual_rows != expected_rows:
                    source_errors.append(f"{label}_rows_mismatch:{rel}")

        missing_expected = [
            item for item in expected_outputs(source) if not _expected_satisfied(item, actual_paths)
        ]
        validation = receipt.get("validation") if isinstance(receipt, dict) else None
        source_results.append(
            {
                "source_id": source_id,
                "required": source.get("required") is True,
                "expected_output_count": len(expected_outputs(source)),
                "present_output_count": len(actual_paths),
                "missing_expected_outputs": missing_expected,
                "coverage_contract_pass": (
                    validation.get("coverage_contract_pass")
                    if isinstance(validation, dict)
                    else None
                ),
                "receipt_schema_valid": not receipt_contract_errors,
                "receipt_contract_errors": receipt_contract_errors,
                "errors": sorted(set(source_errors)),
            }
        )
        errors.extend(f"{source_id}:{item}" for item in source_errors)

    mounted_processed = _processed_inventory(corpus_root / "mount")
    manifest_processed = {
        path for path in manifest_output_paths if path.startswith("data/staging/processed/")
    }
    orphan_mounted = sorted(mounted_processed - manifest_processed)
    if orphan_mounted:
        errors.extend(f"orphan_mounted_processed_file:{path}" for path in orphan_mounted)

    operator_processed: set[str] = set()
    unreceipted_operator: list[str] = []
    receipt_missing_operator: list[str] = []
    if require_operator_snapshot:
        operator_processed = _processed_inventory(root)
        unreceipted_operator = sorted(operator_processed - manifest_processed)
        receipt_missing_operator = sorted(manifest_processed - operator_processed)
        if unreceipted_operator:
            errors.extend(
                f"unreceipted_operator_processed_file:{path}" for path in unreceipted_operator
            )
        if receipt_missing_operator:
            errors.extend(
                f"receipt_output_missing_from_operator:{path}" for path in receipt_missing_operator
            )
        if snapshot.get("operator_processed_csv_files") != len(operator_processed):
            errors.append("snapshot_operator_processed_count_mismatch")
        if snapshot.get("receipted_processed_csv_files") != len(manifest_processed):
            errors.append("snapshot_receipted_processed_count_mismatch")
        if snapshot.get("unreceipted_processed_files") != unreceipted_operator:
            errors.append("snapshot_unreceipted_processed_files_mismatch")

    verified = not errors
    report = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verification_scope": {
            "operator_snapshot_required": require_operator_snapshot,
            "mode": "full_operator_snapshot"
            if require_operator_snapshot
            else "content_revalidation",
        },
        "verified": verified,
        "operator_corpus_authoritative": verified and require_operator_snapshot,
        "corpus_id": claimed_corpus_id,
        "computed_corpus_id": computed_corpus_id,
        "registry": {
            "total_sources": len(sources),
            "required_sources": current_required,
            "source_ids_sha256": current_registry_digest,
            "registry_paths": registry_paths,
        },
        "manifest_source_count": len(seen_source_ids),
        "processed_file_inventory": {
            "operator_csv_files": len(operator_processed) if require_operator_snapshot else None,
            "mounted_csv_files": len(mounted_processed),
            "manifest_csv_files": len(manifest_processed),
            "orphan_mounted_files": orphan_mounted,
            "unreceipted_operator_files": (
                unreceipted_operator if require_operator_snapshot else None
            ),
            "receipt_outputs_missing_from_operator": (
                receipt_missing_operator if require_operator_snapshot else None
            ),
        },
        "sources": sorted(source_results, key=lambda item: item["source_id"]),
        "errors": sorted(set(errors)),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an operator corpus fail-closed.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--corpus-root", type=Path, default=Path("build/operator-corpus"))
    parser.add_argument(
        "--output", type=Path, default=Path("reports/operator_corpus_verification.json")
    )
    args = parser.parse_args()

    report = verify(root=args.root, corpus_root=args.corpus_root, require_operator_snapshot=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "verified": report["verified"],
                "operator_corpus_authoritative": report["operator_corpus_authoritative"],
                "corpus_id": report["corpus_id"],
                "errors": len(report["errors"]),
            },
            sort_keys=True,
        )
    )
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
