from __future__ import annotations

import argparse
import json
import shutil
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


def _load_optional_receipts(receipts_dir: Path | None) -> list[tuple[Path, dict[str, Any]]]:
    if receipts_dir is None or not receipts_dir.exists():
        return []
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(receipts_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"derived receipt must contain an object: {path}")
        loaded.append((path, payload))
    return loaded


def _output_allowed(output_path: str, expected: list[str]) -> bool:
    return any(
        output_path == item or (item.endswith("/") and output_path.startswith(item))
        for item in expected
    )


def _processed_inventory(root: Path) -> set[str]:
    processed = root / "data" / "staging" / "processed"
    if not processed.exists():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in processed.rglob("*.csv")
        if path.is_file()
    }


def _copy_object(*, artifact: Path, objects_dir: Path, expected_sha: str) -> str:
    object_path = objects_dir / expected_sha[:2] / expected_sha[2:]
    object_path.parent.mkdir(parents=True, exist_ok=True)
    if not object_path.exists():
        shutil.copy2(artifact, object_path)
    elif sha256_file(object_path) != expected_sha:
        raise RuntimeError(f"content-addressed object collision: {expected_sha}")
    return f"objects/sha256/{expected_sha[:2]}/{expected_sha[2:]}"


def _verify_artifact(root: Path, record: dict[str, Any], *, label: str) -> tuple[str, Path]:
    rel = safe_relative_path(str(record.get("path", ""))).as_posix()
    artifact = root / rel
    if not artifact.is_file():
        raise RuntimeError(f"{label} artifact missing: {rel}")
    actual_sha = sha256_file(artifact)
    actual_bytes = artifact.stat().st_size
    actual_rows = csv_rows(artifact, logical_path=rel)
    if Path(rel).suffix.lower() == ".csv" and actual_rows is None:
        raise RuntimeError(f"{label} CSV unreadable: {rel}")
    if record.get("sha256") != actual_sha:
        raise RuntimeError(f"{label} sha256 mismatch: {rel}")
    if record.get("bytes") != actual_bytes:
        raise RuntimeError(f"{label} byte-count mismatch: {rel}")
    if record.get("rows") != actual_rows:
        raise RuntimeError(f"{label} row-count mismatch: {rel}")
    return rel, artifact


def build(
    *,
    root: Path,
    receipts_dir: Path,
    corpus_root: Path,
    derived_receipts_dir: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    receipts_dir = receipts_dir.resolve()
    corpus_root = corpus_root.resolve()
    derived_receipts_dir = (
        derived_receipts_dir.resolve() if derived_receipts_dir is not None else None
    )

    sources, registry_paths = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    registry_digest = source_ids_digest(sources)
    products, derived_registry_path = load_derived_products(root)
    product_by_id = {str(product["product_id"]): product for product in products}
    product_registry_digest = derived_registry_digest(products)

    derived_declared_outputs = {
        output: product["product_id"]
        for product in products
        for output in product["outputs"]
    }
    for source in sources:
        for derived_output, product_id in derived_declared_outputs.items():
            if _output_allowed(derived_output, expected_outputs(source)):
                raise RuntimeError(
                    "source/derived ownership collision: "
                    f"{derived_output}:{source['source_id']}:{product_id}"
                )

    receipts = _load_receipts(receipts_dir)
    derived_receipts = _load_optional_receipts(derived_receipts_dir)
    seen_sources: set[str] = set()
    seen_products: set[str] = set()
    manifest_sources: list[dict[str, Any]] = []
    manifest_products: list[dict[str, Any]] = []
    source_output_paths: set[str] = set()
    derived_output_paths: set[str] = set()

    if corpus_root.exists():
        shutil.rmtree(corpus_root)
    objects_dir = corpus_root / "objects" / "sha256"
    mount_dir = corpus_root / "mount"
    receipt_copy_dir = corpus_root / "receipts"
    derived_receipt_copy_dir = corpus_root / "derived_receipts"
    objects_dir.mkdir(parents=True, exist_ok=True)
    mount_dir.mkdir(parents=True, exist_ok=True)
    receipt_copy_dir.mkdir(parents=True, exist_ok=True)
    derived_receipt_copy_dir.mkdir(parents=True, exist_ok=True)

    for receipt_path, receipt in receipts:
        errors = validate_receipt(receipt)
        if errors:
            raise RuntimeError(
                f"invalid operator evidence receipt {receipt_path}: " + "; ".join(errors)
            )
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
        if receipt.get("acquisition", {}).get("producer") != source.get("producer_script"):
            raise RuntimeError(f"source producer mismatch for receipt: {source_id}")

        output_records: list[dict[str, Any]] = []
        seen_output_paths: set[str] = set()
        for output in receipt["outputs"]:
            rel, artifact = _verify_artifact(root, output, label=f"source:{source_id}")
            if rel in seen_output_paths:
                raise RuntimeError(f"duplicate output path in receipt {source_id}: {rel}")
            seen_output_paths.add(rel)
            if not _output_allowed(rel, expected):
                raise RuntimeError(f"undeclared promotion output for {source_id}: {rel}")
            if rel in derived_declared_outputs:
                raise RuntimeError(f"source receipt claims derived output: {source_id}:{rel}")
            object_rel = _copy_object(
                artifact=artifact,
                objects_dir=objects_dir,
                expected_sha=output["sha256"],
            )
            mounted = mount_dir / rel
            mounted.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(corpus_root / object_rel, mounted)
            source_output_paths.add(rel)
            output_records.append({**output, "object": object_rel})

        receipt_copy = receipt_copy_dir / f"{source_id}.json"
        receipt_copy.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
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

    for receipt_path, receipt in derived_receipts:
        errors = validate_derived_receipt(receipt)
        if errors:
            raise RuntimeError(
                f"invalid derived product receipt {receipt_path}: " + "; ".join(errors)
            )
        product_id = str(receipt["product_id"]).strip()
        if product_id in seen_products:
            raise RuntimeError(f"duplicate derived receipt for product_id: {product_id}")
        seen_products.add(product_id)
        product = product_by_id.get(product_id)
        if product is None:
            raise RuntimeError(f"derived receipt references unknown product_id: {product_id}")
        if receipt["production"].get("producer") != product["producer_script"]:
            raise RuntimeError(f"derived producer mismatch: {product_id}")
        definition = receipt["definition"]
        if definition.get("product_definition_sha256") != product_definition_digest(product):
            raise RuntimeError(f"derived product definition mismatch: {product_id}")
        if definition.get("derived_registry_sha256") != product_registry_digest:
            raise RuntimeError(f"derived registry digest mismatch: {product_id}")

        required_inputs = set(product["required_inputs"])
        optional_inputs = set(product["optional_inputs"])
        allowed_inputs = required_inputs | optional_inputs
        input_records: list[dict[str, Any]] = []
        input_paths: set[str] = set()
        for item in receipt["inputs"]:
            rel, artifact = _verify_artifact(root, item, label=f"derived_input:{product_id}")
            if rel in input_paths:
                raise RuntimeError(f"duplicate derived input: {product_id}:{rel}")
            input_paths.add(rel)
            if rel not in allowed_inputs:
                raise RuntimeError(f"undeclared derived input: {product_id}:{rel}")
            if bool(item.get("required")) != (rel in required_inputs):
                raise RuntimeError(f"derived input required-flag mismatch: {product_id}:{rel}")
            object_rel = _copy_object(
                artifact=artifact,
                objects_dir=objects_dir,
                expected_sha=item["sha256"],
            )
            input_records.append({**item, "object": object_rel})
        missing_required = sorted(required_inputs - input_paths)
        if missing_required:
            raise RuntimeError(
                f"derived required inputs missing for {product_id}: " + ", ".join(missing_required)
            )

        receipt_output_paths = {str(item.get("path")) for item in receipt["outputs"]}
        if receipt_output_paths != set(product["outputs"]):
            raise RuntimeError(f"derived output inventory mismatch: {product_id}")
        output_records = []
        for item in receipt["outputs"]:
            rel, artifact = _verify_artifact(root, item, label=f"derived_output:{product_id}")
            if rel in source_output_paths or rel in derived_output_paths:
                raise RuntimeError(f"duplicate corpus output ownership: {rel}")
            object_rel = _copy_object(
                artifact=artifact,
                objects_dir=objects_dir,
                expected_sha=item["sha256"],
            )
            mounted = mount_dir / rel
            mounted.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(corpus_root / object_rel, mounted)
            derived_output_paths.add(rel)
            output_records.append({**item, "object": object_rel})

        receipt_copy = derived_receipt_copy_dir / f"{product_id}.json"
        receipt_copy.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_products.append(
            {
                "product_id": product_id,
                "producer_script": product["producer_script"],
                "product_definition_sha256": product_definition_digest(product),
                "receipt_sha256": sha256_file(receipt_copy),
                "receipt_path": f"derived_receipts/{product_id}.json",
                "inputs": sorted(input_records, key=lambda item: item["path"]),
                "outputs": sorted(output_records, key=lambda item: item["path"]),
            }
        )

    operator_processed = _processed_inventory(root)
    source_processed = {
        path for path in source_output_paths if path.startswith("data/staging/processed/")
    }
    derived_processed = {
        path for path in derived_output_paths if path.startswith("data/staging/processed/")
    }
    accounted_processed = source_processed | derived_processed
    unreceipted_processed = sorted(operator_processed - accounted_processed)
    manifest: dict[str, Any] = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "registry": {
            "total_sources": len(sources),
            "required_sources": sum(source.get("required") is True for source in sources),
            "source_ids_sha256": registry_digest,
            "registry_paths": registry_paths,
        },
        "derived_registry": {
            "path": derived_registry_path,
            "product_count": len(products),
            "derived_registry_sha256": product_registry_digest,
        },
        "snapshot": {
            "processed_inventory_complete": not unreceipted_processed,
            "operator_processed_csv_files": len(operator_processed),
            "source_receipted_processed_csv_files": len(source_processed),
            "derived_receipted_processed_csv_files": len(derived_processed),
            "accounted_processed_csv_files": len(accounted_processed),
            "unreceipted_processed_files": unreceipted_processed,
        },
        "sources": sorted(manifest_sources, key=lambda item: item["source_id"]),
        "derived_products": sorted(manifest_products, key=lambda item: item["product_id"]),
    }
    manifest["corpus_id"] = manifest_digest(manifest)
    manifest_path = corpus_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a content-addressed operator corpus.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--derived-receipts", type=Path)
    parser.add_argument("--corpus-root", type=Path, default=Path("build/operator-corpus"))
    args = parser.parse_args()

    manifest = build(
        root=args.root,
        receipts_dir=args.receipts,
        derived_receipts_dir=args.derived_receipts,
        corpus_root=args.corpus_root,
    )
    print(
        json.dumps(
            {
                "corpus_id": manifest["corpus_id"],
                "receipt_sources": len(manifest["sources"]),
                "derived_products": len(manifest["derived_products"]),
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
