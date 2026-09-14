from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.derived_product_common import (
        derived_registry_digest,
        load_derived_products,
        product_definition_digest,
        validate_derived_receipt,
    )
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
    from derived_product_common import (  # type: ignore[no-redef]
        derived_registry_digest,
        load_derived_products,
        product_definition_digest,
        validate_derived_receipt,
    )
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
    return any(
        output_path == item or (item.endswith("/") and output_path.startswith(item))
        for item in expected
    )


def _expected_satisfied(expected_path: str, actual_paths: set[str]) -> bool:
    if expected_path.endswith("/"):
        return any(path.startswith(expected_path) for path in actual_paths)
    return expected_path in actual_paths


def _processed_inventory(root: Path) -> set[str]:
    processed = root / "data" / "staging" / "processed"
    if not processed.exists():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in processed.rglob("*.csv")
        if path.is_file()
    }


def _verify_corpus_artifact(
    *,
    corpus_root: Path,
    record: dict[str, Any],
    logical_path: str,
    require_mount: bool,
) -> list[str]:
    errors: list[str] = []
    object_rel = safe_relative_path(str(record.get("object", "")))
    object_path = corpus_root / object_rel
    paths = [("object", object_path)]
    if require_mount:
        paths.append(("mount", corpus_root / "mount" / logical_path))
    for label, path in paths:
        if not path.is_file():
            errors.append(f"{label}_missing:{logical_path}")
            continue
        if sha256_file(path) != record.get("sha256"):
            errors.append(f"{label}_sha256_mismatch:{logical_path}")
        if path.stat().st_size != record.get("bytes"):
            errors.append(f"{label}_bytes_mismatch:{logical_path}")
        actual_rows = csv_rows(path, logical_path=logical_path)
        if Path(logical_path).suffix.lower() == ".csv" and actual_rows is None:
            errors.append(f"{label}_csv_unreadable:{logical_path}")
        if actual_rows != record.get("rows"):
            errors.append(f"{label}_rows_mismatch:{logical_path}")
    return errors


def verify(
    *,
    root: Path,
    corpus_root: Path,
    require_operator_snapshot: bool = True,
) -> dict[str, Any]:
    """Verify corpus bytes and, by default, the complete operator snapshot."""
    root = root.resolve()
    corpus_root = corpus_root.resolve()
    errors: list[str] = []
    sources, registry_paths = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    current_registry_digest = source_ids_digest(sources)
    current_required = sum(source.get("required") is True for source in sources)
    products, derived_registry_path = load_derived_products(root)
    product_by_id = {str(product["product_id"]): product for product in products}
    current_derived_digest = derived_registry_digest(products)

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

    derived_registry = manifest.get("derived_registry")
    if not isinstance(derived_registry, dict):
        derived_registry = {}
        errors.append("manifest_derived_registry_missing")
    if derived_registry.get("path") != derived_registry_path:
        errors.append("derived_registry_path_mismatch")
    if derived_registry.get("product_count") != len(products):
        errors.append("derived_registry_product_count_mismatch")
    if derived_registry.get("derived_registry_sha256") != current_derived_digest:
        errors.append("derived_registry_digest_mismatch")

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
    source_output_paths: set[str] = set()
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
        receipt: dict[str, Any] = {}
        if not receipt_path.is_file():
            source_errors.append("receipt_missing")
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
            acquisition = receipt.get("acquisition")
            if not isinstance(acquisition, dict) or acquisition.get("producer") != source.get(
                "producer_script"
            ):
                source_errors.append("receipt_producer_mismatch")
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
            if rel in source_output_paths:
                source_errors.append(f"duplicate_source_output:{rel}")
            source_output_paths.add(rel)
            if not _expected_claims(rel, expected_outputs(source)):
                source_errors.append(f"undeclared_output:{rel}")
            receipt_output = receipt_by_path.get(rel)
            if receipt_output is None:
                source_errors.append(f"receipt_output_missing:{rel}")
            else:
                for key in ("sha256", "bytes", "rows"):
                    if receipt_output.get(key) != output.get(key):
                        source_errors.append(f"receipt_manifest_{key}_mismatch:{rel}")
            source_errors.extend(
                _verify_corpus_artifact(
                    corpus_root=corpus_root,
                    record=output,
                    logical_path=rel,
                    require_mount=True,
                )
            )

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

    manifest_products = manifest.get("derived_products")
    if not isinstance(manifest_products, list):
        manifest_products = []
        errors.append("manifest_derived_products_missing")
    seen_product_ids: set[str] = set()
    derived_output_paths: set[str] = set()
    product_results: list[dict[str, Any]] = []
    for entry in manifest_products:
        if not isinstance(entry, dict):
            errors.append("invalid_manifest_derived_product_entry")
            continue
        product_id = str(entry.get("product_id", "")).strip()
        product_errors: list[str] = []
        if not product_id:
            errors.append("empty_manifest_product_id")
            continue
        if product_id in seen_product_ids:
            errors.append(f"duplicate_manifest_product:{product_id}")
            continue
        seen_product_ids.add(product_id)
        product = product_by_id.get(product_id)
        if product is None:
            errors.append(f"unknown_manifest_product:{product_id}")
            continue
        definition_digest = product_definition_digest(product)
        if entry.get("product_definition_sha256") != definition_digest:
            product_errors.append("product_definition_digest_mismatch")
        if entry.get("producer_script") != product.get("producer_script"):
            product_errors.append("product_producer_mismatch")

        receipt_rel = safe_relative_path(str(entry.get("receipt_path", "")))
        receipt_path = corpus_root / receipt_rel
        receipt: dict[str, Any] = {}
        receipt_contract_errors: list[str] = []
        if not receipt_path.is_file():
            product_errors.append("receipt_missing")
            receipt_contract_errors.append("receipt_missing")
        else:
            if sha256_file(receipt_path) != entry.get("receipt_sha256"):
                product_errors.append("receipt_sha256_mismatch")
            try:
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
                product_errors.append("receipt_unreadable")
            receipt = payload if isinstance(payload, dict) else {}
            receipt_contract_errors = validate_derived_receipt(receipt)
            product_errors.extend(
                f"receipt_contract:{item}" for item in receipt_contract_errors
            )
            if receipt.get("product_id") != product_id:
                product_errors.append("receipt_product_id_mismatch")
            production = receipt.get("production")
            if not isinstance(production, dict) or production.get("producer") != product.get(
                "producer_script"
            ):
                product_errors.append("receipt_producer_mismatch")
            definition = receipt.get("definition")
            if not isinstance(definition, dict):
                product_errors.append("receipt_definition_missing")
            else:
                if definition.get("product_definition_sha256") != definition_digest:
                    product_errors.append("receipt_product_definition_mismatch")
                if definition.get("derived_registry_sha256") != current_derived_digest:
                    product_errors.append("receipt_derived_registry_mismatch")

        receipt_inputs = {
            str(item.get("path")): item
            for item in receipt.get("inputs", [])
            if isinstance(item, dict) and item.get("path")
        }
        receipt_outputs = {
            str(item.get("path")): item
            for item in receipt.get("outputs", [])
            if isinstance(item, dict) and item.get("path")
        }
        manifest_input_paths: set[str] = set()
        for item in entry.get("inputs", []) if isinstance(entry.get("inputs"), list) else []:
            if not isinstance(item, dict):
                product_errors.append("invalid_manifest_product_input")
                continue
            rel = safe_relative_path(str(item.get("path", ""))).as_posix()
            manifest_input_paths.add(rel)
            receipt_item = receipt_inputs.get(rel)
            if receipt_item is None:
                product_errors.append(f"receipt_input_missing:{rel}")
            else:
                for key in ("sha256", "bytes", "rows", "required"):
                    if receipt_item.get(key) != item.get(key):
                        product_errors.append(f"receipt_manifest_input_{key}_mismatch:{rel}")
            product_errors.extend(
                _verify_corpus_artifact(
                    corpus_root=corpus_root,
                    record=item,
                    logical_path=rel,
                    require_mount=False,
                )
            )
            if require_operator_snapshot:
                operator_path = root / rel
                if not operator_path.is_file():
                    product_errors.append(f"operator_input_missing:{rel}")
                else:
                    if sha256_file(operator_path) != item.get("sha256"):
                        product_errors.append(f"operator_input_sha256_mismatch:{rel}")
                    if operator_path.stat().st_size != item.get("bytes"):
                        product_errors.append(f"operator_input_bytes_mismatch:{rel}")
                    if csv_rows(operator_path, logical_path=rel) != item.get("rows"):
                        product_errors.append(f"operator_input_rows_mismatch:{rel}")

        required_inputs = set(product["required_inputs"])
        if not required_inputs.issubset(manifest_input_paths):
            for rel in sorted(required_inputs - manifest_input_paths):
                product_errors.append(f"required_input_missing:{rel}")
        if manifest_input_paths - (required_inputs | set(product["optional_inputs"])):
            product_errors.append("undeclared_product_inputs_present")

        manifest_product_outputs = entry.get("outputs")
        if not isinstance(manifest_product_outputs, list):
            manifest_product_outputs = []
            product_errors.append("manifest_product_outputs_missing")
        actual_output_paths: set[str] = set()
        for item in manifest_product_outputs:
            if not isinstance(item, dict):
                product_errors.append("invalid_manifest_product_output")
                continue
            rel = safe_relative_path(str(item.get("path", ""))).as_posix()
            actual_output_paths.add(rel)
            if rel in source_output_paths or rel in derived_output_paths:
                product_errors.append(f"duplicate_output_ownership:{rel}")
            derived_output_paths.add(rel)
            receipt_item = receipt_outputs.get(rel)
            if receipt_item is None:
                product_errors.append(f"receipt_output_missing:{rel}")
            else:
                for key in ("sha256", "bytes", "rows"):
                    if receipt_item.get(key) != item.get(key):
                        product_errors.append(f"receipt_manifest_output_{key}_mismatch:{rel}")
            product_errors.extend(
                _verify_corpus_artifact(
                    corpus_root=corpus_root,
                    record=item,
                    logical_path=rel,
                    require_mount=True,
                )
            )
        if actual_output_paths != set(product["outputs"]):
            product_errors.append("product_output_inventory_mismatch")

        product_results.append(
            {
                "product_id": product_id,
                "producer_script": product.get("producer_script"),
                "input_count": len(manifest_input_paths),
                "output_count": len(actual_output_paths),
                "receipt_schema_valid": not receipt_contract_errors,
                "receipt_contract_errors": receipt_contract_errors,
                "errors": sorted(set(product_errors)),
            }
        )
        errors.extend(f"derived:{product_id}:{item}" for item in product_errors)

    mounted_processed = _processed_inventory(corpus_root / "mount")
    source_processed = {
        path for path in source_output_paths if path.startswith("data/staging/processed/")
    }
    derived_processed = {
        path for path in derived_output_paths if path.startswith("data/staging/processed/")
    }
    accounted_processed = source_processed | derived_processed
    orphan_mounted = sorted(mounted_processed - accounted_processed)
    if orphan_mounted:
        errors.extend(f"orphan_mounted_processed_file:{path}" for path in orphan_mounted)

    operator_processed: set[str] = set()
    unreceipted_operator: list[str] = []
    accounted_missing_operator: list[str] = []
    if require_operator_snapshot:
        operator_processed = _processed_inventory(root)
        unreceipted_operator = sorted(operator_processed - accounted_processed)
        accounted_missing_operator = sorted(accounted_processed - operator_processed)
        if unreceipted_operator:
            errors.extend(
                f"unreceipted_operator_processed_file:{path}" for path in unreceipted_operator
            )
        if accounted_missing_operator:
            errors.extend(
                f"accounted_output_missing_from_operator:{path}"
                for path in accounted_missing_operator
            )
        expected_snapshot_counts = {
            "operator_processed_csv_files": len(operator_processed),
            "source_receipted_processed_csv_files": len(source_processed),
            "derived_receipted_processed_csv_files": len(derived_processed),
            "accounted_processed_csv_files": len(accounted_processed),
        }
        for key, expected in expected_snapshot_counts.items():
            if snapshot.get(key) != expected:
                errors.append(f"snapshot_{key}_mismatch")
        if snapshot.get("unreceipted_processed_files") != unreceipted_operator:
            errors.append("snapshot_unreceipted_processed_files_mismatch")

    verified = not errors
    return {
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
        "derived_registry": {
            "path": derived_registry_path,
            "product_count": len(products),
            "derived_registry_sha256": current_derived_digest,
        },
        "manifest_source_count": len(seen_source_ids),
        "manifest_product_count": len(seen_product_ids),
        "processed_file_inventory": {
            "operator_csv_files": len(operator_processed) if require_operator_snapshot else None,
            "mounted_csv_files": len(mounted_processed),
            "source_manifest_csv_files": len(source_processed),
            "derived_manifest_csv_files": len(derived_processed),
            "accounted_manifest_csv_files": len(accounted_processed),
            "orphan_mounted_files": orphan_mounted,
            "unreceipted_operator_files": (
                unreceipted_operator if require_operator_snapshot else None
            ),
            "accounted_outputs_missing_from_operator": (
                accounted_missing_operator if require_operator_snapshot else None
            ),
        },
        "sources": sorted(source_results, key=lambda item: item["source_id"]),
        "derived_products": sorted(product_results, key=lambda item: item["product_id"]),
        "errors": sorted(set(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an operator corpus fail-closed.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--corpus-root", type=Path, default=Path("build/operator-corpus"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/operator_corpus_verification.json"),
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
