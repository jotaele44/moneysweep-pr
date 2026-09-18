from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

RECEIPT_SCHEMA_VERSION = "moneysweep.operator_evidence/v1"
CORPUS_SCHEMA_VERSION = "moneysweep.operator_corpus/v1"
VERIFICATION_SCHEMA_VERSION = "moneysweep.operator_corpus_verification/v1"


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows(path: Path, *, logical_path: str | Path | None = None) -> int | None:
    content_path = Path(logical_path) if logical_path is not None else path
    if content_path.suffix.lower() != ".csv":
        return None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return max(sum(1 for _ in csv.reader(fh, strict=True)) - 1, 0)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    normalized = Path(*[part for part in path.parts if part not in {"", "."}])
    if not normalized.parts:
        raise ValueError(f"empty relative path: {value!r}")
    return normalized


def load_sources(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    registry_path = root / "registries" / "source_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    sources = list(registry.get("sources") or [])
    registry_paths = ["registries/source_registry.yaml"]

    extension_dir = root / "registries" / "source_registry_extensions"
    if extension_dir.exists():
        for path in sorted(extension_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            extension_sources = payload.get("sources")
            if extension_sources is None:
                continue
            if not isinstance(extension_sources, list):
                raise RuntimeError(f"source registry extension must contain sources list: {path}")
            sources.extend(extension_sources)
            registry_paths.append(path.relative_to(root).as_posix())

    source_ids = [str(source.get("source_id", "")).strip() for source in sources]
    if any(not source_id for source_id in source_ids):
        raise RuntimeError("source registry contains an empty source_id")
    counts = {source_id: source_ids.count(source_id) for source_id in source_ids}
    duplicates = sorted(source_id for source_id, count in counts.items() if count > 1)
    if duplicates:
        raise RuntimeError("duplicate source IDs: " + ", ".join(duplicates))
    return sources, registry_paths


def source_ids_digest(sources: list[dict[str, Any]]) -> str:
    """Return the repository-canonical source-ID digest.

    Keep this byte-for-byte compatible with
    moneysweep.update_controller.policy.registry_snapshot(): sort IDs, join with
    newlines, and include the final newline before hashing.
    """
    source_ids = sorted(str(source["source_id"]).strip() for source in sources)
    return sha256_bytes(("\n".join(source_ids) + "\n").encode("utf-8"))


def source_definition_digest(source: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(source))


def expected_outputs(source: dict[str, Any]) -> list[str]:
    value = source.get("expected_outputs")
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def manifest_digest(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("corpus_id", None)
    return sha256_bytes(canonical_json(payload))


def _is_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _is_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_receipt(receipt: dict[str, Any]) -> list[str]:
    """Validate the receipt contract without trusting ``schema_valid`` itself."""
    errors: list[str] = []
    allowed_top = {
        "schema_version",
        "source_id",
        "acquisition",
        "registry",
        "outputs",
        "validation",
    }
    extra_top = sorted(set(receipt) - allowed_top)
    if extra_top:
        errors.append("unexpected_top_level_keys:" + ",".join(extra_top))
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        errors.append("receipt_schema_version_mismatch")
    if not isinstance(receipt.get("source_id"), str) or not str(receipt.get("source_id")).strip():
        errors.append("receipt_source_id_missing")

    acquisition = receipt.get("acquisition")
    if not isinstance(acquisition, dict):
        errors.append("receipt_acquisition_missing")
        acquisition = {}
    allowed_acquisition = {
        "producer",
        "producer_sha",
        "started_at",
        "completed_at",
        "source_url",
        "http_status",
    }
    extra_acquisition = sorted(set(acquisition) - allowed_acquisition)
    if extra_acquisition:
        errors.append("unexpected_acquisition_keys:" + ",".join(extra_acquisition))
    if (
        not isinstance(acquisition.get("producer"), str)
        or not acquisition.get("producer", "").strip()
    ):
        errors.append("receipt_producer_missing")
    if not _is_hex(acquisition.get("producer_sha"), 40):
        errors.append("receipt_producer_sha_invalid")
    if not _is_datetime(acquisition.get("completed_at")):
        errors.append("receipt_completed_at_invalid")
    if "started_at" in acquisition and not _is_datetime(acquisition.get("started_at")):
        errors.append("receipt_started_at_invalid")
    if (
        not isinstance(acquisition.get("source_url"), str)
        or not acquisition.get("source_url", "").strip()
    ):
        errors.append("receipt_source_url_missing")
    http_status = acquisition.get("http_status")
    if http_status is not None and (
        not isinstance(http_status, int)
        or isinstance(http_status, bool)
        or not 100 <= http_status <= 599
    ):
        errors.append("receipt_http_status_invalid")

    registry = receipt.get("registry")
    if not isinstance(registry, dict):
        errors.append("receipt_registry_missing")
        registry = {}
    extra_registry = sorted(set(registry) - {"source_ids_sha256", "source_definition_sha256"})
    if extra_registry:
        errors.append("unexpected_registry_keys:" + ",".join(extra_registry))
    if not _is_hex(registry.get("source_ids_sha256"), 64):
        errors.append("receipt_registry_digest_invalid")
    if not _is_hex(registry.get("source_definition_sha256"), 64):
        errors.append("receipt_source_definition_digest_invalid")

    outputs = receipt.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        errors.append("receipt_outputs_missing")
        outputs = []
    seen_paths: set[str] = set()
    allowed_output = {"path", "sha256", "bytes", "rows", "content_type"}
    for index, output in enumerate(outputs):
        prefix = f"receipt_output_{index}"
        if not isinstance(output, dict):
            errors.append(f"{prefix}_invalid")
            continue
        extra_output = sorted(set(output) - allowed_output)
        if extra_output:
            errors.append(f"{prefix}_unexpected_keys:" + ",".join(extra_output))
        path = output.get("path")
        if not isinstance(path, str) or not path.strip():
            errors.append(f"{prefix}_path_missing")
        else:
            try:
                normalized = safe_relative_path(path).as_posix()
            except ValueError:
                errors.append(f"{prefix}_path_unsafe")
            else:
                if normalized in seen_paths:
                    errors.append(f"{prefix}_path_duplicate")
                seen_paths.add(normalized)
        if not _is_hex(output.get("sha256"), 64):
            errors.append(f"{prefix}_sha256_invalid")
        size = output.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f"{prefix}_bytes_invalid")
        rows = output.get("rows")
        if rows is not None and (not isinstance(rows, int) or isinstance(rows, bool) or rows < 0):
            errors.append(f"{prefix}_rows_invalid")
        if "rows" not in output:
            errors.append(f"{prefix}_rows_missing")
        content_type = output.get("content_type")
        if content_type is not None and not isinstance(content_type, str):
            errors.append(f"{prefix}_content_type_invalid")

    validation = receipt.get("validation")
    if not isinstance(validation, dict):
        errors.append("receipt_validation_missing")
        validation = {}
    if validation.get("schema_valid") is not True:
        errors.append("receipt_schema_valid_flag_not_true")
    for key in ("positive_rows", "coverage_contract_pass"):
        if not isinstance(validation.get(key), bool):
            errors.append(f"receipt_validation_{key}_invalid")
    return sorted(set(errors))
