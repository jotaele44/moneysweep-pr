"""Fail-closed input guards; byte integrity is not producer authenticity.

This module neither grants corpus authority nor authorizes production. Its JSON
serialization is the repository's v1 Python profile, not an RFC 8785 claim.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


class EvidenceError(ValueError):
    """Evidence cannot safely support a computed assertion."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EvidenceError(f"nonfinite_json_number:{value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise EvidenceError("nonfinite_json_number:" + value)
    return parsed


def strict_json(text: str) -> Any:
    return json.loads(
        text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


def digest_json(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def bounded_path(root: Path, relative: str) -> Path:
    """Reject lexical escapes and symlinks; never normalize a source identity."""
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise EvidenceError("unsafe_evidence_path")
    clean = relative.removesuffix("/")
    parts = clean.split("/")
    if any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise EvidenceError("unsafe_evidence_path")
    if PurePosixPath(clean).is_absolute():
        raise EvidenceError("unsafe_evidence_path")
    current = root.resolve()
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceError("symlink_evidence_path")
    if not current.resolve().is_relative_to(root.resolve()):
        raise EvidenceError("evidence_path_escape")
    return current


def evaluate_output(*, evidence_root: Path, source: dict[str, Any], output_path: str) -> dict[str, Any]:
    """Validate a CSV snapshot using an explicit parse/schema contract.

    Non-tabular outputs need a dedicated adapter: nonempty bytes alone are not a
    schema proof. Results preserve failed observations without granting credit.
    """
    result: dict[str, Any] = {
        "path": output_path, "kind": "file", "exists": False, "usable": False,
        "rows": None, "bytes": None, "sha256": None, "schema_valid": False,
        "reason": None,
    }
    try:
        path = bounded_path(evidence_root, output_path)
        result["exists"] = path.exists()
        if output_path.endswith("/"):
            result.update(kind="directory", reason="directory_validation_contract_unimplemented")
            return result
        if not path.is_file():
            result["reason"] = "missing"
            return result
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise EvidenceError("output_changed_during_read")
        result.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if path.suffix.lower() != ".csv":
            if path.suffix.lower() == ".json":
                result["kind"] = "json"
                try:
                    strict_json(raw.decode("utf-8"))
                except (ValueError, UnicodeError):
                    result["reason"] = "json_empty_or_invalid"
                    return result
            result["reason"] = "source_specific_validator_unimplemented"
            return result
        result["kind"] = "csv"
        contract = source.get("validation_threshold")
        if not isinstance(contract, dict):
            raise EvidenceError("validation_contract_missing")
        minimum = contract.get("min_rows")
        if type(minimum) is not int or minimum < 0:
            raise EvidenceError("invalid_min_rows_contract")
        columns = contract.get("required_columns")
        if (not isinstance(columns, list) or not columns
                or any(not isinstance(c, str) or not c for c in columns)
                or len(set(columns)) != len(columns)):
            raise EvidenceError("declared_column_contract_missing_or_invalid")
        parsing = contract.get("csv", {})
        if not isinstance(parsing, dict) or set(parsing) - {"encoding", "delimiter", "header_row"}:
            raise EvidenceError("unsupported_csv_parse_contract")
        delimiter = parsing.get("delimiter", ",")
        encoding = parsing.get("encoding", "utf-8-sig")
        header_row = parsing.get("header_row", 0)
        if (not isinstance(delimiter, str) or len(delimiter) != 1
                or delimiter in {"\r", "\n", "\x00"}
                or not isinstance(encoding, str)
                or type(header_row) is not int or header_row < 0):
            raise EvidenceError("invalid_csv_parse_contract")
        reader = csv.reader(io.StringIO(raw.decode(encoding), newline=""), delimiter=delimiter,
                            strict=True)
        for _ in range(header_row):
            if next(reader, None) is None:
                raise EvidenceError("csv_preamble_incomplete")
        header = next(reader, None)
        if (not header or any(not h.strip() for h in header)
                or len(set(header)) != len(header)):
            raise EvidenceError("csv_header_missing_empty_or_duplicate")
        if not set(columns).issubset(header):
            raise EvidenceError("csv_required_columns_missing")
        row_count = 0
        for row in reader:
            if len(row) != len(header):
                raise EvidenceError(f"csv_row_width_mismatch:{row_count + 1}")
            row_count += 1
        result.update(rows=row_count, min_rows=minimum, schema_valid=True,
                      columns_raw=header, parse_contract={"encoding": encoding,
                      "delimiter": delimiter, "header_row": header_row})
        result["usable"] = row_count >= minimum
        result["reason"] = None if result["usable"] else f"below_min_rows:{row_count}<{minimum}"
    except (OSError, UnicodeError, csv.Error, LookupError, ValueError) as exc:
        result["reason"] = str(exc) if isinstance(exc, EvidenceError) else "output_unreadable"
    return result


def load_receipts(receipts_dir: Path | None) -> dict[str, dict[str, Any]]:
    if receipts_dir is None or not receipts_dir.exists():
        return {}
    if not receipts_dir.is_dir() or receipts_dir.is_symlink():
        raise EvidenceError("invalid_receipt_directory")
    receipts: dict[str, dict[str, Any]] = {}
    for entry in sorted(receipts_dir.iterdir()):
        if entry.suffix != ".json" or not entry.is_file() or entry.is_symlink():
            raise EvidenceError(f"unclassified_receipt_entry:{entry.name}")
        payload = strict_json(entry.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvidenceError(f"receipt_not_object:{entry.name}")
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id != source_id.strip():
            raise EvidenceError(f"invalid_raw_source_id:{entry.name}")
        if source_id in receipts:
            raise EvidenceError(f"duplicate_source_receipts:{source_id}")
        receipts[source_id] = payload
    return receipts


def receipt_binding_errors(
    *, receipt: dict[str, Any] | None, source: dict[str, Any], registry_digest: str,
    outputs: list[dict[str, Any]],
) -> list[str]:
    if receipt is None:
        return ["receipt_missing"]
    errors: list[str] = []
    if receipt.get("source_id") != source["source_id"]:
        errors.append("receipt_source_id_mismatch")
    registry = receipt.get("registry")
    if not isinstance(registry, dict):
        registry = {}
    if registry.get("source_ids_sha256") != registry_digest:
        errors.append("receipt_registry_digest_mismatch")
    if registry.get("source_definition_sha256") != digest_json(source):
        errors.append("receipt_source_definition_mismatch")
    acquisition = receipt.get("acquisition")
    if not isinstance(acquisition, dict):
        acquisition = {}
    if acquisition.get("producer") != source.get("producer_script"):
        errors.append("receipt_producer_mismatch")
    claims = receipt.get("outputs")
    if not isinstance(claims, list):
        return sorted(set(errors + ["receipt_outputs_missing"]))
    by_path: dict[str, Any] = {}
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("path"), str):
            errors.append("receipt_output_invalid")
            continue
        path = claim["path"]
        if path in by_path:
            errors.append("receipt_output_duplicate")
        by_path[path] = claim
    actual = {o["path"]: o for o in outputs if o.get("exists")}
    if len({o["path"] for o in outputs}) != len(outputs):
        errors.append("registry_output_duplicate")
    if set(actual) != set(by_path):
        errors.append("receipt_output_inventory_mismatch")
    for path in sorted(set(actual) & set(by_path)):
        for field in ("sha256", "bytes", "rows"):
            claimed = by_path[path].get(field)
            observed = actual[path].get(field)
            if type(claimed) is not type(observed) or claimed != observed:
                errors.append(f"receipt_output_{field}_mismatch:{path}")
    return sorted(set(errors))


def execution_state(
    *, execution: dict[str, Any] | None, receipt: dict[str, Any] | None,
    source: dict[str, Any], receipt_errors: list[str], materialization: str, as_of: datetime,
) -> tuple[str, list[str]]:
    """Validate the v1 execution envelope, never a bare CI outcome Boolean.

    This is evidence consistency only. An authenticated corpus must still bind
    the producer identity before any production gate can consume this result.
    """
    if execution is None:
        return "NOT_ATTEMPTED", ["execution_receipt_missing"]
    errors = list(receipt_errors)
    if execution.get("schema_version") != "moneysweep.source_execution/v1":
        errors.append("execution_schema_unproven")
    if execution.get("source_id") != source["source_id"]:
        errors.append("execution_source_id_mismatch")
    if receipt is None or execution.get("evidence_receipt_sha256") != digest_json(receipt):
        errors.append("execution_evidence_binding_mismatch")
    producer = execution.get("producer_git_sha")
    acquisition = receipt.get("acquisition", {}) if receipt else {}
    if not isinstance(acquisition, dict):
        acquisition = {}
    if (not isinstance(producer, str) or not re.fullmatch(r"[0-9a-f]{40}", producer)
            or producer != acquisition.get("producer_sha")):
        errors.append("execution_producer_binding_mismatch")
    started = aware_datetime(execution.get("started_at"))
    completed = aware_datetime(execution.get("completed_at"))
    receipt_completed = aware_datetime(acquisition.get("completed_at"))
    if (started is None or completed is None or started > completed or completed > as_of
            or completed != receipt_completed):
        errors.append("execution_time_unproven")
    if execution.get("execution_status") != "SUCCESS":
        errors.append("execution_not_successful")
    if materialization != "fully_materialized":
        errors.append("execution_output_invalid")
    return ("EXECUTED_VALID" if not errors else "EXECUTION_UNPROVEN", sorted(set(errors)))


def derived_execution_blockers(truth: dict[str, Any], automatable: set[str]) -> list[str]:
    rows = truth.get("sources")
    if not isinstance(rows, list):
        return ["execution_truth_missing"]
    errors: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source_id"), str):
            errors.append("execution_truth_row_invalid")
            continue
        source_id = row["source_id"]
        if source_id in by_id:
            errors.append(f"execution_truth_duplicate:{source_id}")
        by_id[source_id] = row
    selected = {sid for sid, row in by_id.items() if row.get("automatable") is True}
    if selected != automatable:
        errors.append("execution_automatable_identity_mismatch")
    for source_id in sorted(automatable):
        row = by_id.get(source_id, {})
        if (row.get("execution_status") != "EXECUTED_VALID"
                or row.get("receipt_valid") is not True
                or row.get("materialization_status") != "fully_materialized"
                or row.get("execution_blockers") != []):
            errors.append(f"execution_unproven:{source_id}")
    return sorted(set(errors))


def release_boundary(upstream_nonpass: list[str], historical_claim: object) -> dict[str, Any]:
    """Quarantine v1 activation assertions until authenticated activation exists.

    Deliberately no authorization input or success path: this is an explicit
    migration interlock, not an activation verifier pretending to be complete.
    """
    return {
        "state": "BLOCKED",
        "production_activation_authorized": False,
        "historical_activation_claim": historical_claim,
        "upstream_nonpass_gates": list(upstream_nonpass),
        "blockers": list(upstream_nonpass) + [
            "production_activation_not_authorized",
            "scope_bound_activation_verifier_unimplemented",
        ],
    }


def freshness_status(
    *, cadence: str, basis: object, sla: object, materialization: str,
    receipt_valid: bool, completed_at: datetime | None, as_of: datetime,
) -> str:
    if materialization != "fully_materialized":
        return "NEVER_MATERIALIZED"
    if (as_of.tzinfo is None or as_of.utcoffset() is None or not receipt_valid
            or completed_at is None or completed_at.tzinfo is None
            or completed_at.utcoffset() is None or completed_at > as_of):
        return "FRESHNESS_UNPROVEN"
    if cadence == "one_time" and basis == "one_time_archival":
        return "FRESHNESS_NOT_APPLICABLE"
    if (basis != "acquisition_receipt" or type(sla) not in (int, float)
            or not math.isfinite(sla) or sla <= 0):
        return "FRESHNESS_UNPROVEN"
    age_hours = (as_of - completed_at).total_seconds() / 3600.0
    return "FRESH" if age_hours <= sla else "STALE"
