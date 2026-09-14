from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        canonical_json,
        safe_relative_path,
        sha256_bytes,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        canonical_json,
        safe_relative_path,
        sha256_bytes,
    )

DERIVED_REGISTRY_SCHEMA_VERSION = "moneysweep.derived_products/v1"
DERIVED_RECEIPT_SCHEMA_VERSION = "moneysweep.derived_product_evidence/v1"
DERIVED_REGISTRY_PATH = Path("registries/derived_products.json")


def load_derived_products(root: Path) -> tuple[list[dict[str, Any]], str | None]:
    path = root / DERIVED_REGISTRY_PATH
    if not path.exists():
        return [], None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("derived product registry must contain an object")
    if payload.get("schema_version") != DERIVED_REGISTRY_SCHEMA_VERSION:
        raise RuntimeError("unsupported derived product registry schema")
    products = payload.get("products")
    if not isinstance(products, list):
        raise RuntimeError("derived product registry products must be a list")

    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            raise RuntimeError("derived product entry must be an object")
        product_id = str(product.get("product_id") or "").strip()
        if not product_id:
            raise RuntimeError("derived product has empty product_id")
        if product_id in seen_ids:
            raise RuntimeError(f"duplicate derived product_id: {product_id}")
        seen_ids.add(product_id)
        producer = str(product.get("producer_script") or "").strip()
        if not producer:
            raise RuntimeError(f"derived product producer missing: {product_id}")
        producer_path = safe_relative_path(producer)
        if not (root / producer_path).is_file():
            raise RuntimeError(f"derived product producer missing on disk: {product_id}:{producer}")

        for key in ("required_inputs", "optional_inputs", "outputs"):
            values = product.get(key)
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                raise RuntimeError(f"derived product {key} invalid: {product_id}")
            normalized_paths = [safe_relative_path(item).as_posix() for item in values]
            if len(normalized_paths) != len(set(normalized_paths)):
                raise RuntimeError(f"derived product {key} duplicates: {product_id}")
            product[key] = normalized_paths
        if not product["required_inputs"]:
            raise RuntimeError(f"derived product requires at least one required input: {product_id}")
        if not product["outputs"]:
            raise RuntimeError(f"derived product requires at least one output: {product_id}")
        overlap = set(product["required_inputs"]) & set(product["optional_inputs"])
        if overlap:
            raise RuntimeError(
                f"derived product required/optional input overlap: {product_id}:{','.join(sorted(overlap))}"
            )
        for output in product["outputs"]:
            if output in seen_outputs:
                raise RuntimeError(f"duplicate derived output ownership: {output}")
            seen_outputs.add(output)
        normalized.append(product)
    return normalized, DERIVED_REGISTRY_PATH.as_posix()


def product_definition_digest(product: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(product))


def derived_registry_digest(products: list[dict[str, Any]]) -> str:
    return sha256_bytes(canonical_json(products))


def validate_derived_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema_version") != DERIVED_RECEIPT_SCHEMA_VERSION:
        errors.append("derived_receipt_schema_version_mismatch")
    if not isinstance(receipt.get("product_id"), str) or not str(receipt.get("product_id")).strip():
        errors.append("derived_receipt_product_id_missing")

    production = receipt.get("production")
    if not isinstance(production, dict):
        errors.append("derived_receipt_production_missing")
        production = {}
    allowed_production = {"producer", "producer_sha", "started_at", "completed_at"}
    extra = sorted(set(production) - allowed_production)
    if extra:
        errors.append("derived_receipt_unexpected_production_keys:" + ",".join(extra))
    if not isinstance(production.get("producer"), str) or not production.get("producer", "").strip():
        errors.append("derived_receipt_producer_missing")
    producer_sha = production.get("producer_sha")
    if not (
        isinstance(producer_sha, str)
        and len(producer_sha) == 40
        and all(char in "0123456789abcdef" for char in producer_sha)
    ):
        errors.append("derived_receipt_producer_sha_invalid")
    if not isinstance(production.get("completed_at"), str) or not production.get("completed_at", "").strip():
        errors.append("derived_receipt_completed_at_missing")

    definition = receipt.get("definition")
    if not isinstance(definition, dict):
        errors.append("derived_receipt_definition_missing")
        definition = {}
    for key in ("product_definition_sha256", "derived_registry_sha256"):
        value = definition.get(key)
        if not (
            isinstance(value, str)
            and len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
        ):
            errors.append(f"derived_receipt_{key}_invalid")

    def _validate_artifacts(key: str, *, nonempty: bool) -> None:
        values = receipt.get(key)
        if not isinstance(values, list) or (nonempty and not values):
            errors.append(f"derived_receipt_{key}_missing")
            return
        seen: set[str] = set()
        for index, item in enumerate(values):
            prefix = f"derived_receipt_{key}_{index}"
            if not isinstance(item, dict):
                errors.append(f"{prefix}_invalid")
                continue
            extra_item = sorted(set(item) - {"path", "sha256", "bytes", "rows", "required"})
            if extra_item:
                errors.append(f"{prefix}_unexpected_keys:" + ",".join(extra_item))
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                errors.append(f"{prefix}_path_missing")
                continue
            try:
                normalized = safe_relative_path(path).as_posix()
            except ValueError:
                errors.append(f"{prefix}_path_unsafe")
                continue
            if normalized in seen:
                errors.append(f"{prefix}_path_duplicate")
            seen.add(normalized)
            digest = item.get("sha256")
            if not (
                isinstance(digest, str)
                and len(digest) == 64
                and all(char in "0123456789abcdef" for char in digest)
            ):
                errors.append(f"{prefix}_sha256_invalid")
            size = item.get("bytes")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                errors.append(f"{prefix}_bytes_invalid")
            rows = item.get("rows")
            if rows is not None and (not isinstance(rows, int) or isinstance(rows, bool) or rows < 0):
                errors.append(f"{prefix}_rows_invalid")
            if key == "inputs" and not isinstance(item.get("required"), bool):
                errors.append(f"{prefix}_required_invalid")
            if key == "outputs" and "required" in item:
                errors.append(f"{prefix}_required_not_allowed")

    _validate_artifacts("inputs", nonempty=True)
    _validate_artifacts("outputs", nonempty=True)

    validation = receipt.get("validation")
    if not isinstance(validation, dict):
        errors.append("derived_receipt_validation_missing")
        validation = {}
    for key in ("schema_valid", "inputs_complete", "outputs_complete"):
        if validation.get(key) is not True:
            errors.append(f"derived_receipt_validation_{key}_not_true")
    return sorted(set(errors))
