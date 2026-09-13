"""Build an immutable, local-only MoneySweep provisional baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from moneysweep.orchestrator._offline_baseline_core import (
    BaselineConfig,
    OfflineBaselineViolation,
    _write_json,
    block_network,
    sanitized_child_environment,
    sha256_file,
)
from moneysweep.orchestrator._offline_baseline_runner import run_offline_baseline
from moneysweep.runtime.source_registry import source_by_id

LOCAL_CORPUS_SCHEMA_VERSION = "moneysweep_local_corpus_v1"
LOCAL_CORPUS_CLASSIFICATION = "LOCAL_EVIDENCE_CORPUS_PROVISIONAL"
LOCAL_CORPUS_EXTENSIONS = frozenset(
    {
        ".csv",
        ".db",
        ".json",
        ".jsonl",
        ".parquet",
        ".pdf",
        ".sqlite",
        ".txt",
        ".xls",
        ".xlsx",
    }
)
_LOCAL_EXCLUDED_PARTS = frozenset({".env", ".git", "__pycache__", "credentials", "secrets"})


@dataclass(frozen=True)
class _LocalCorpusConfig:
    """Configuration for a read-only, bounded local evidence inventory.

    Bindings are keyed by exact corpus-relative path. A binding may carry
    existing ``source_ids``, ``semantic_class``, and ``evidence_class``.
    Bindings classify a source manifestation; they never assert entity identity.
    """

    input_dir: Path
    output_path: Path | None = None
    bindings: Mapping[str, Mapping[str, Any]] | None = None
    generated_at: str | None = None
    recursive: bool = True
    include_extensions: frozenset[str] = LOCAL_CORPUS_EXTENSIONS


__all__ = [
    "BaselineConfig",
    "OfflineBaselineViolation",
    "block_network",
    "run_offline_baseline",
    "sanitized_child_environment",
]


def _detected_format(path: Path) -> str:
    """Detect common evidence formats from bytes before consulting extension."""

    with path.open("rb") as handle:
        head = handle.read(16)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if head.startswith(b"PK\x03\x04"):
        return "zip_container"
    suffix = path.suffix.casefold()
    if suffix in {".json", ".jsonl"}:
        return suffix.lstrip(".")
    if suffix == ".csv":
        return "csv"
    if suffix == ".txt":
        return "text"
    return "unknown"


def _zip_member_manifest(path: Path) -> list[dict[str, Any]]:
    """Hash non-directory ZIP members by path and uncompressed size."""

    if _detected_format(path) != "zip_container":
        return []
    members: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                if info.is_dir():
                    continue
                members.append(
                    {
                        "path": info.filename,
                        "uncompressed_size": info.file_size,
                        "sha256": hashlib.sha256(archive.read(info.filename)).hexdigest(),
                    }
                )
    except (OSError, zipfile.BadZipFile):
        return []
    return members


def _certify_record_conservation(
    *,
    source_records: int,
    retained_records: int,
    excluded_records: int,
    unresolved_records: int,
    provenance_complete_records: int,
) -> dict[str, Any]:
    """Fail closed unless record arithmetic and provenance both close."""

    values = (
        source_records,
        retained_records,
        excluded_records,
        unresolved_records,
        provenance_complete_records,
    )
    if any(value < 0 for value in values):
        raise ValueError("record conservation counts must be non-negative")
    arithmetic_closed = source_records == retained_records + excluded_records
    provenance_closed = provenance_complete_records == source_records
    state = (
        "PASS" if arithmetic_closed and provenance_closed and unresolved_records == 0 else "FAIL"
    )
    return {
        "state": state,
        "source_records": source_records,
        "retained_records": retained_records,
        "excluded_records": excluded_records,
        "unresolved_records": unresolved_records,
        "provenance_complete_records": provenance_complete_records,
        "arithmetic_closed": arithmetic_closed,
        "provenance_closed": provenance_closed,
        "queryable": state == "PASS",
    }


def _excluded_local_path(relative_path: Path) -> bool:
    lowered = {part.casefold() for part in relative_path.parts}
    return bool(lowered & _LOCAL_EXCLUDED_PARTS)


def _binding_fields(
    *, relative_text: str, binding: Mapping[str, Any]
) -> tuple[list[str], str, str]:
    source_ids_raw = binding.get("source_ids") or []
    if not isinstance(source_ids_raw, list) or not all(
        isinstance(source_id, str) and source_id for source_id in source_ids_raw
    ):
        raise OfflineBaselineViolation(
            f"local binding source_ids for {relative_text!r} must be a list of non-empty strings"
        )
    source_ids = list(source_ids_raw)
    unknown_source_ids = [source_id for source_id in source_ids if source_by_id(source_id) is None]
    if unknown_source_ids:
        raise OfflineBaselineViolation(
            f"local binding for {relative_text!r} references unknown source_ids: "
            + ", ".join(unknown_source_ids)
        )
    evidence_class = str(binding.get("evidence_class") or "unresolved")
    if evidence_class not in {"financial", "control", "unresolved"}:
        raise OfflineBaselineViolation(
            f"local binding evidence_class for {relative_text!r} must be financial, control, or unresolved"
        )
    semantic_class = str(binding.get("semantic_class") or "UNRESOLVED")
    return source_ids, semantic_class, evidence_class


def _inventory_local_corpus(config: _LocalCorpusConfig) -> dict[str, Any]:
    """Freeze and classify one explicit local root without materializing rows.

    Symlinks are rejected to prevent root escape. Absolute operator paths are
    never persisted. Financial files remain non-queryable until source-specific
    materialization produces a PASS record-conservation receipt.
    """

    root = config.input_dir.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise OfflineBaselineViolation(f"local corpus root is not a directory: {root}")
    if config.output_path is not None:
        output_path = config.output_path.expanduser().resolve()
        if output_path == root or root in output_path.parents:
            raise OfflineBaselineViolation(
                "local corpus receipt must be written outside the inventoried root"
            )

    bindings = dict(config.bindings or {})
    iterator = root.rglob("*") if config.recursive else root.iterdir()
    files: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []

    for path in sorted(iterator, key=lambda item: item.as_posix()):
        relative_text = path.relative_to(root).as_posix()
        if path.is_symlink():
            excluded.append({"path": relative_text, "reason": "SYMLINK_REJECTED"})
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _excluded_local_path(relative):
            excluded.append({"path": relative_text, "reason": "SENSITIVE_OR_INTERNAL_PATH"})
            continue
        extension = path.suffix.casefold()
        if extension not in config.include_extensions:
            excluded.append({"path": relative_text, "reason": "UNSUPPORTED_EXTENSION"})
            continue

        binding = dict(bindings.get(relative_text) or {})
        source_ids, semantic_class, evidence_class = _binding_fields(
            relative_text=relative_text, binding=binding
        )
        detected = _detected_format(path)
        item: dict[str, Any] = {
            "relative_path": relative_text,
            "filename_raw": path.name,
            "extension": extension,
            "detected_format": detected,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "source_ids": source_ids,
            "semantic_class": semantic_class,
            "evidence_class": evidence_class,
            "binding_status": "BINDING" if binding else "UNRESOLVED",
            "file_conservation_status": "PASS",
            "record_conservation_status": (
                "NOT_APPLICABLE" if evidence_class == "control" else "OPEN"
            ),
            "provenance_status": "FILE_LEVEL_PASS",
            "queryable": False,
        }
        if detected == "zip_container":
            item["archive_members"] = _zip_member_manifest(path)
        files.append(item)

    by_hash: dict[str, list[str]] = {}
    for item in files:
        by_hash.setdefault(str(item["sha256"]), []).append(str(item["relative_path"]))
    duplicate_groups = [
        {
            "sha256": digest,
            "paths": sorted(paths),
            "classification": "BYTE_IDENTICAL",
        }
        for digest, paths in sorted(by_hash.items())
        if len(paths) > 1
    ]

    financial = [item for item in files if item["evidence_class"] == "financial"]
    control = [item for item in files if item["evidence_class"] == "control"]
    unresolved = [item for item in files if item["evidence_class"] == "unresolved"]
    file_arithmetic_closed = len(files) == len(financial) + len(control) + len(unresolved)
    generated_at = config.generated_at or datetime.now(timezone.utc).isoformat()

    manifest: dict[str, Any] = {
        "schema_version": LOCAL_CORPUS_SCHEMA_VERSION,
        "classification": LOCAL_CORPUS_CLASSIFICATION,
        "generated_at": generated_at,
        "root_disclosure": "REDACTED_OPERATOR_ROOT",
        "recursive": config.recursive,
        "file_count": len(files),
        "financial_file_count": len(financial),
        "control_file_count": len(control),
        "unresolved_file_count": len(unresolved),
        "excluded_path_count": len(excluded),
        "duplicate_byte_group_count": len(duplicate_groups),
        "files": files,
        "excluded_paths": excluded,
        "byte_duplicate_groups": duplicate_groups,
        "certification": {
            "scope": "bounded files discovered under the explicit local root",
            "file_conservation": "PASS" if file_arithmetic_closed else "FAIL",
            "file_arithmetic_closed": file_arithmetic_closed,
            "record_conservation": "OPEN" if financial else "NOT_APPLICABLE",
            "record_provenance": "OPEN" if financial else "NOT_APPLICABLE",
            "identity_certification": "NOT_ATTEMPTED",
            "canonical_certification": False,
            "queryable_evidence": False,
            "promotion_authorized": False,
        },
    }
    if config.output_path is not None:
        _write_json(config.output_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--git-sha", default="UNKNOWN")
    parser.add_argument("--generated-at")
    parser.add_argument("--strict-inputs", action="store_true")
    parser.add_argument(
        "--inventory-local-corpus",
        action="store_true",
        help=(
            "freeze/hash/classify supported files under --input-dir without "
            "materializing records or awarding canonical source credit"
        ),
    )
    parser.add_argument(
        "--local-bindings",
        help=(
            "optional JSON whose 'bindings' maps exact relative paths to existing "
            "source_ids, semantic_class, and evidence_class"
        ),
    )
    return parser


def _read_bindings(path: str | None) -> dict[str, dict[str, object]]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    bindings = payload.get("bindings", {}) if isinstance(payload, dict) else {}
    if not isinstance(bindings, dict):
        raise OfflineBaselineViolation("local binding file must contain an object named 'bindings'")
    result: dict[str, dict[str, object]] = {}
    for key, value in bindings.items():
        if not isinstance(value, dict):
            raise OfflineBaselineViolation(f"local binding for {key!r} must be an object")
        result[str(key)] = dict(value)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.inventory_local_corpus:
        output_path = Path(args.output_root) / "local_corpus_manifest.json"
        result = _inventory_local_corpus(
            _LocalCorpusConfig(
                input_dir=Path(args.input_dir),
                output_path=output_path,
                bindings=_read_bindings(args.local_bindings),
                generated_at=args.generated_at,
            )
        )
        print(json.dumps(result, indent=2))
        return 0 if result["certification"]["file_conservation"] == "PASS" else 1

    result = run_offline_baseline(
        BaselineConfig(
            input_dir=Path(args.input_dir),
            output_root=Path(args.output_root),
            repo_root=Path(args.repo_root) if args.repo_root else None,
            git_sha=args.git_sha,
            generated_at=args.generated_at,
            strict_inputs=args.strict_inputs,
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
