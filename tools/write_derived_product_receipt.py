from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.derived_product_common import (
        DERIVED_RECEIPT_SCHEMA_VERSION,
        derived_registry_digest,
        load_derived_products,
        product_definition_digest,
    )
    from tools.operator_corpus_common import csv_rows, sha256_file
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from derived_product_common import (  # type: ignore[no-redef]
        DERIVED_RECEIPT_SCHEMA_VERSION,
        derived_registry_digest,
        load_derived_products,
        product_definition_digest,
    )
    from operator_corpus_common import csv_rows, sha256_file  # type: ignore[no-redef]


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _artifact(root: Path, rel: str, *, required: bool | None = None) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        raise RuntimeError(f"derived product artifact missing: {rel}")
    row_count = csv_rows(path, logical_path=rel)
    if Path(rel).suffix.lower() == ".csv" and row_count is None:
        raise RuntimeError(f"derived product CSV unreadable: {rel}")
    result: dict[str, Any] = {
        "path": rel,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": row_count,
    }
    if required is not None:
        result["required"] = required
    return result


def build_receipt(
    *,
    root: Path,
    product_id: str,
    producer_sha: str,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    products, _ = load_derived_products(root)
    product_by_id = {str(item["product_id"]): item for item in products}
    product = product_by_id.get(product_id)
    if product is None:
        raise RuntimeError(f"unknown derived product_id: {product_id}")
    if not (
        len(producer_sha) == 40
        and all(char in "0123456789abcdef" for char in producer_sha)
    ):
        raise RuntimeError("producer_sha must be a lowercase 40-character Git SHA")

    inputs: list[dict[str, Any]] = []
    for rel in product["required_inputs"]:
        inputs.append(_artifact(root, rel, required=True))
    for rel in product["optional_inputs"]:
        if (root / rel).is_file():
            inputs.append(_artifact(root, rel, required=False))

    outputs = [_artifact(root, rel) for rel in product["outputs"]]
    completed_at = completed_at or datetime.now(timezone.utc).isoformat()
    production: dict[str, Any] = {
        "producer": product["producer_script"],
        "producer_sha": producer_sha,
        "completed_at": completed_at,
    }
    if started_at:
        production["started_at"] = started_at

    return {
        "schema_version": DERIVED_RECEIPT_SCHEMA_VERSION,
        "product_id": product_id,
        "production": production,
        "definition": {
            "product_definition_sha256": product_definition_digest(product),
            "derived_registry_sha256": derived_registry_digest(products),
        },
        "inputs": sorted(inputs, key=lambda item: item["path"]),
        "outputs": sorted(outputs, key=lambda item: item["path"]),
        "validation": {
            "schema_valid": True,
            "inputs_complete": True,
            "outputs_complete": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a content-bound receipt for a registered derived product."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--producer-sha")
    parser.add_argument("--started-at")
    parser.add_argument("--completed-at")
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=Path("data/manifests/derived_product_evidence"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    receipt = build_receipt(
        root=root,
        product_id=args.product_id,
        producer_sha=args.producer_sha or _head(root),
        started_at=args.started_at,
        completed_at=args.completed_at,
    )
    receipt_dir = args.receipt_dir
    if not receipt_dir.is_absolute():
        receipt_dir = root / receipt_dir
    receipt_dir.mkdir(parents=True, exist_ok=True)
    output = receipt_dir / f"{args.product_id}.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"product_id": args.product_id, "receipt": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
