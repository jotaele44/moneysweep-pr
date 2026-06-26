"""R4.9H raw USAspending source discovery and candidate validation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from moneysweep.pipeline.acquisition_package import (
    read_csv,
    read_json,
    safe_int,
    utc_now,
    write_csv,
    write_json,
)
from moneysweep.pipeline.delivered_source_validation import contains_forbidden_token
from moneysweep.pipeline.raw_source_candidate_validation import (
    classify_source_type,
    is_usaspending_like,
    validate_raw_candidate,
)

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".parquet", ".json", ".zip"}
ZIP_MEMBER_EXTENSIONS = {".csv", ".xlsx", ".xls", ".parquet", ".json"}
MAX_CSV_HEADER_BYTES = 1024 * 1024


def _relative_posix(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_csv_profile(handle: BinaryIO) -> tuple[list[str], int, str]:
    try:
        text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace", newline="")
        reader = csv.reader(text)
        header = next(reader, [])
        row_count = sum(1 for _ in reader)
        return [str(column).strip() for column in header], row_count, "csv_inspected"
    except Exception as exc:
        return [], 0, f"csv_inspection_failed:{type(exc).__name__}"


def _read_csv_profile_from_path(path: Path) -> tuple[list[str], int, str]:
    with path.open("rb") as handle:
        return _read_csv_profile(handle)


def _read_json_profile_from_bytes(data: bytes) -> tuple[list[str], int, str]:
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as exc:
        return [], 0, f"json_inspection_failed:{type(exc).__name__}"

    if isinstance(payload, list):
        first = payload[0] if payload else {}
        columns = sorted(first.keys()) if isinstance(first, dict) else []
        return [str(column) for column in columns], len(payload), "json_inspected"
    if isinstance(payload, dict):
        return [str(column) for column in sorted(payload.keys())], 1, "json_inspected"
    return [], 0, "json_scalar_unsupported"


def _read_json_profile_from_path(path: Path) -> tuple[list[str], int, str]:
    return _read_json_profile_from_bytes(path.read_bytes())


def _read_tabular_profile_from_path(path: Path) -> tuple[list[str], int, str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_profile_from_path(path)
    if suffix == ".json":
        return _read_json_profile_from_path(path)
    if suffix == ".parquet":
        try:
            frame = pd.read_parquet(path)
            return [str(column) for column in frame.columns], int(len(frame)), "parquet_inspected"
        except Exception as exc:
            return [], 0, f"parquet_inspection_failed:{type(exc).__name__}"
    if suffix in {".xlsx", ".xls"}:
        try:
            frame = pd.read_excel(path, dtype=str)
            return [str(column) for column in frame.columns], int(len(frame)), "excel_inspected"
        except Exception as exc:
            return [], 0, f"excel_inspection_failed:{type(exc).__name__}"
    return [], 0, "unsupported_extension"


def _read_tabular_profile_from_zip_member(
    zf: zipfile.ZipFile,
    member: zipfile.ZipInfo,
) -> tuple[list[str], int, str, str]:
    suffix = Path(member.filename).suffix.lower()
    try:
        data = zf.read(member)
    except Exception as exc:
        return [], 0, "", f"zip_member_read_failed:{type(exc).__name__}"

    digest = _sha256_bytes(data)
    if suffix == ".csv":
        columns, row_count, status = _read_csv_profile(io.BytesIO(data))
        return columns, row_count, digest, status
    if suffix == ".json":
        columns, row_count, status = _read_json_profile_from_bytes(data)
        return columns, row_count, digest, status
    if suffix == ".parquet":
        try:
            frame = pd.read_parquet(io.BytesIO(data))
            return (
                [str(column) for column in frame.columns],
                int(len(frame)),
                digest,
                "parquet_inspected",
            )
        except Exception as exc:
            return [], 0, digest, f"parquet_inspection_failed:{type(exc).__name__}"
    if suffix in {".xlsx", ".xls"}:
        try:
            frame = pd.read_excel(io.BytesIO(data), dtype=str)
            return (
                [str(column) for column in frame.columns],
                int(len(frame)),
                digest,
                "excel_inspected",
            )
        except Exception as exc:
            return [], 0, digest, f"excel_inspection_failed:{type(exc).__name__}"
    return [], 0, digest, "unsupported_zip_member_extension"


def _is_zip_member_candidate(member: zipfile.ZipInfo) -> bool:
    if member.is_dir():
        return False
    name = member.filename
    path = Path(name)
    if name.startswith("__MACOSX/") or path.name.startswith("._") or path.name == ".DS_Store":
        return False
    return path.suffix.lower() in ZIP_MEMBER_EXTENSIONS


def _inventory_path(root: Path, path: Path, generated_at: str) -> list[dict[str, Any]]:
    relpath = _relative_posix(root, path)
    suffix = path.suffix.lower()
    rows: list[dict[str, Any]] = []

    if suffix == ".zip":
        zip_sha = _sha256_path(path)
        zip_row = {
            "generated_at": generated_at,
            "display_path": relpath,
            "container_path": relpath,
            "member_path": "",
            "extension": ".zip",
            "is_zip_member": False,
            "file_size": path.stat().st_size,
            "compressed_size": path.stat().st_size,
            "row_count": 0,
            "column_count": 0,
            "columns": "",
            "sha256": zip_sha,
            "zip_listed": False,
            "usaspending_like": is_usaspending_like(relpath, []),
            "likely_source_type": classify_source_type(relpath, []),
            "inspection_status": "zip_not_listed",
        }
        try:
            with zipfile.ZipFile(path) as zf:
                zip_row["zip_listed"] = True
                zip_row["inspection_status"] = "zip_listed_without_extraction"
                for member in zf.infolist():
                    if not _is_zip_member_candidate(member):
                        continue
                    member_suffix = Path(member.filename).suffix.lower()
                    columns, row_count, digest, inspection_status = (
                        _read_tabular_profile_from_zip_member(zf, member)
                    )
                    display_path = f"{relpath}::{member.filename}"
                    usaspending_like = is_usaspending_like(display_path, columns)
                    rows.append(
                        {
                            "generated_at": generated_at,
                            "display_path": display_path,
                            "container_path": relpath,
                            "member_path": member.filename,
                            "extension": member_suffix,
                            "is_zip_member": True,
                            "file_size": member.file_size,
                            "compressed_size": member.compress_size,
                            "row_count": row_count,
                            "column_count": len(columns),
                            "columns": "|".join(columns),
                            "sha256": digest,
                            "zip_listed": True,
                            "usaspending_like": usaspending_like,
                            "likely_source_type": classify_source_type(display_path, columns),
                            "inspection_status": inspection_status,
                        }
                    )
        except Exception as exc:
            zip_row["inspection_status"] = f"zip_listing_failed:{type(exc).__name__}"
        rows.insert(0, zip_row)
        return rows

    columns, row_count, inspection_status = _read_tabular_profile_from_path(path)
    usaspending_like = is_usaspending_like(relpath, columns)
    rows.append(
        {
            "generated_at": generated_at,
            "display_path": relpath,
            "container_path": relpath,
            "member_path": "",
            "extension": suffix,
            "is_zip_member": False,
            "file_size": path.stat().st_size,
            "compressed_size": path.stat().st_size,
            "row_count": row_count,
            "column_count": len(columns),
            "columns": "|".join(columns),
            "sha256": _sha256_path(path),
            "zip_listed": False,
            "usaspending_like": usaspending_like,
            "likely_source_type": classify_source_type(relpath, columns),
            "inspection_status": inspection_status,
        }
    )
    return rows


def discover_raw_usaspending_files(root: Path, generated_at: str) -> list[dict[str, Any]]:
    raw_dir = root / "data" / "raw"
    if not raw_dir.exists():
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("._") or path.name == ".DS_Store":
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rows.extend(_inventory_path(root, path, generated_at))
    return rows


def _still_blocked_targets(root: Path) -> list[dict[str, str]]:
    blocked_rows = read_csv(root / "data" / "review_queue" / "sources_still_blocked_r4_9g.csv")
    checklist_rows = read_csv(
        root / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv"
    )
    checklist_lookup = {
        str(row.get("expected_input", "")).strip(): row
        for row in checklist_rows
        if str(row.get("expected_input", "")).strip()
    }

    out: list[dict[str, str]] = []
    for row in blocked_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        merged = dict(checklist_lookup.get(expected_input, {}))
        merged.update({key: value for key, value in row.items() if value != ""})
        out.append(merged)
    return out


def _already_validated_targets(root: Path) -> set[str]:
    rows = read_csv(root / "data" / "exports" / "scoped_unfreeze_candidates_r4_9g.csv")
    return {
        str(row.get("expected_input", "")).strip()
        for row in rows
        if str(row.get("expected_input", "")).strip()
    }


def _candidate_matches(
    *,
    inventory_rows: list[dict[str, Any]],
    target_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for inventory in inventory_rows:
        if not bool(inventory.get("usaspending_like")):
            continue
        if not _is_plausible_delivery_file(str(inventory.get("display_path", ""))):
            continue
        if safe_int(inventory.get("row_count")) <= 0:
            continue
        display_path = str(inventory.get("display_path", "")).strip()
        if contains_forbidden_token(display_path):
            continue
        for target in target_rows:
            validation = validate_raw_candidate(target_row=target, inventory_row=inventory)
            reason = str(validation.get("validation_reason", "")).strip()
            if reason == "raw_source_type_not_applicable_to_target":
                continue
            matches.append(validation)
    return matches


def _is_plausible_delivery_file(display_path: str) -> bool:
    lowered = str(display_path or "").lower()
    basename = Path(lowered.split("::")[-1]).name
    if any(
        token in lowered
        for token in (
            "/tests/",
            "/testing_data/",
            "/api_contracts/",
            "/references/",
            "/docs/",
            "/database_scripts/",
            "/etl/",
            "__macosx/",
        )
    ):
        return False
    if "usaspending-api-master/" in lowered and not any(
        token in lowered for token in ("/csv_downloads/", "/bulk_downloads/")
    ):
        return False
    plausible_location = any(
        token in lowered
        for token in (
            "::usas/data/",
            "data/raw/usas/",
            "csv_downloads",
            "bulk_downloads",
            "all_contracts",
            "all_assistance",
        )
    )
    plausible_name = any(
        token in basename
        for token in (
            "federal_spending",
            "contracts_clean",
            "master_contracts",
            "raw_",
            "all_contracts",
            "all_assistance",
            "subaward",
        )
    )
    return plausible_location and plausible_name


def _sources_still_blocked(
    *,
    generated_at: str,
    target_rows: list[dict[str, str]],
    validated_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    validated_targets = {
        str(row.get("expected_input", "")).strip()
        for row in validated_rows
        if str(row.get("expected_input", "")).strip()
    }
    rows: list[dict[str, Any]] = []
    for row in target_rows:
        expected_input = str(row.get("expected_input", "")).strip()
        if expected_input in validated_targets:
            continue
        rows.append(
            {
                "generated_at": generated_at,
                "expected_input": expected_input,
                "source_family": str(row.get("source_family", "")).strip(),
                "blocker_class": str(row.get("blocker_class", "")).strip(),
                "target_dropzone_path": str(row.get("target_dropzone_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "blocker_reason": str(row.get("blocker_reason", "")).strip()
                or "no_validated_raw_usaspending_candidate",
                "next_action": "external_source_delivery_or_raw_transform_mapping_review",
                "validation_command": str(row.get("validation_command", "")).strip(),
                "unfreeze_condition": str(row.get("unfreeze_condition", "")).strip(),
                "r4_9h_status": "still_blocked",
            }
        )
    return rows


def run_raw_usaspending_discovery(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    generated_at = utc_now()
    rebuild_status = read_json(exports_dir / "rebuild_status.json")
    _ = read_json(exports_dir / "scoped_unfreeze_status_r4_9g.json")
    _ = read_csv(root / "data" / "review_queue" / "source_recovery_resume_conditions_r4_9z.csv")

    inventory_rows = discover_raw_usaspending_files(root, generated_at)
    target_rows_all = _still_blocked_targets(root)
    already_validated = _already_validated_targets(root)
    target_rows = [
        row
        for row in target_rows_all
        if str(row.get("expected_input", "")).strip() not in already_validated
    ]

    match_rows = _candidate_matches(inventory_rows=inventory_rows, target_rows=target_rows)
    validated_rows = [
        row for row in match_rows if str(row.get("validation_status", "")).strip() == "validated"
    ]
    rejected_rows = [
        row for row in match_rows if str(row.get("validation_status", "")).strip() != "validated"
    ]
    still_blocked_rows = _sources_still_blocked(
        generated_at=generated_at,
        target_rows=target_rows,
        validated_rows=validated_rows,
    )

    raw_files_scanned = len(inventory_rows)
    usaspending_like_files_found = sum(
        1 for row in inventory_rows if bool(row.get("usaspending_like"))
    )
    candidate_matches = len(match_rows)
    candidates_validated = len(validated_rows)
    candidates_rejected = len(rejected_rows)
    new_unfreeze_candidates = len(
        {
            str(row.get("expected_input", "")).strip()
            for row in validated_rows
            if str(row.get("expected_input", "")).strip()
        }
    )
    sources_still_blocked = len(still_blocked_rows)

    downloads_executed = False
    endpoint_retries_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    forbidden_artifact_usage = False
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))
    downstream_phases_blocked = bool(rebuild_status.get("downstream_phases_blocked", True))

    gate_passed = bool(
        raw_files_scanned >= 0
        and usaspending_like_files_found >= 0
        and candidate_matches == candidates_validated + candidates_rejected
        and len(target_rows) <= len(target_rows_all)
        and not downloads_executed
        and not endpoint_retries_executed
        and rows_ingested == 0
        and production_inputs_staged == 0
        and not forbidden_artifact_usage
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and phase_7_8_blocked
        and downstream_phases_blocked
    )

    status_payload = {
        "generated_at": generated_at,
        "r4_9h_gate_passed": gate_passed,
        "r4_9h_raw_files_scanned": raw_files_scanned,
        "r4_9h_usaspending_like_files_found": usaspending_like_files_found,
        "r4_9h_candidate_matches": candidate_matches,
        "r4_9h_candidates_validated": candidates_validated,
        "r4_9h_candidates_rejected": candidates_rejected,
        "r4_9h_new_unfreeze_candidates": new_unfreeze_candidates,
        "r4_9h_sources_still_blocked": sources_still_blocked,
        "r4_9h_downloads_executed": downloads_executed,
        "r4_9h_endpoint_retries_executed": endpoint_retries_executed,
        "r4_9h_rows_ingested": rows_ingested,
        "r4_9h_production_inputs_staged": production_inputs_staged,
        "r4_9h_forbidden_artifact_usage": forbidden_artifact_usage,
        "production_status": production_status,
        "phase_7_8_blocked": phase_7_8_blocked,
        "downstream_phases_blocked": downstream_phases_blocked,
    }

    write_json(exports_dir / "raw_usaspending_discovery_status_r4_9h.json", status_payload)
    write_csv(
        exports_dir / "raw_usaspending_file_inventory_r4_9h.csv",
        inventory_rows,
        [
            "generated_at",
            "display_path",
            "container_path",
            "member_path",
            "extension",
            "is_zip_member",
            "file_size",
            "compressed_size",
            "row_count",
            "column_count",
            "columns",
            "sha256",
            "zip_listed",
            "usaspending_like",
            "likely_source_type",
            "inspection_status",
        ],
    )
    write_csv(
        exports_dir / "raw_usaspending_candidate_matches_r4_9h.csv",
        match_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_output_path",
            "target_dropzone_path",
            "raw_display_path",
            "raw_container_path",
            "raw_member_path",
            "raw_extension",
            "raw_row_count",
            "raw_sha256",
            "likely_source_type",
            "required_columns",
            "raw_columns",
            "mapped_columns",
            "missing_columns",
            "mapping_profile",
            "validation_status",
            "validation_reason",
        ],
    )
    write_csv(
        exports_dir / "raw_usaspending_validation_report_r4_9h.csv",
        match_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_output_path",
            "target_dropzone_path",
            "raw_display_path",
            "raw_container_path",
            "raw_member_path",
            "raw_extension",
            "raw_row_count",
            "raw_sha256",
            "likely_source_type",
            "required_columns",
            "raw_columns",
            "mapped_columns",
            "missing_columns",
            "mapping_profile",
            "validation_status",
            "validation_reason",
        ],
    )
    write_csv(
        review_dir / "raw_usaspending_unfreeze_candidates_r4_9h.csv",
        validated_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_output_path",
            "target_dropzone_path",
            "raw_display_path",
            "raw_container_path",
            "raw_member_path",
            "raw_extension",
            "raw_row_count",
            "raw_sha256",
            "likely_source_type",
            "required_columns",
            "raw_columns",
            "mapped_columns",
            "missing_columns",
            "mapping_profile",
            "validation_status",
            "validation_reason",
        ],
    )
    write_csv(
        review_dir / "raw_usaspending_rejected_candidates_r4_9h.csv",
        rejected_rows,
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_output_path",
            "target_dropzone_path",
            "raw_display_path",
            "raw_container_path",
            "raw_member_path",
            "raw_extension",
            "raw_row_count",
            "raw_sha256",
            "likely_source_type",
            "required_columns",
            "raw_columns",
            "mapped_columns",
            "missing_columns",
            "mapping_profile",
            "validation_status",
            "validation_reason",
        ],
    )
    write_csv(
        review_dir / "sources_still_blocked_r4_9h.csv",
        still_blocked_rows,
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "blocker_reason",
            "next_action",
            "validation_command",
            "unfreeze_condition",
            "r4_9h_status",
        ],
    )

    rebuild_status.update(
        {
            "r4_9h_generated_at": generated_at,
            "r4_9h_gate_passed": gate_passed,
            "r4_9h_raw_files_scanned": raw_files_scanned,
            "r4_9h_usaspending_like_files_found": usaspending_like_files_found,
            "r4_9h_candidate_matches": candidate_matches,
            "r4_9h_candidates_validated": candidates_validated,
            "r4_9h_candidates_rejected": candidates_rejected,
            "r4_9h_new_unfreeze_candidates": new_unfreeze_candidates,
            "r4_9h_sources_still_blocked": sources_still_blocked,
            "r4_9h_downloads_executed": downloads_executed,
            "r4_9h_endpoint_retries_executed": endpoint_retries_executed,
            "r4_9h_rows_ingested": rows_ingested,
            "r4_9h_production_inputs_staged": production_inputs_staged,
            "r4_9h_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "phase_7_8_blocked": phase_7_8_blocked,
            "downstream_phases_blocked": downstream_phases_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
