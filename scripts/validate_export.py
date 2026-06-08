"""Contract-Sweeper federation export validator.

Fail-closed integrity checks for a packaged export directory. JSON Schemas
in ``schemas/`` are loaded for required-field lists; value-shape rules are
implemented in plain Python so the validator has no external dependencies.

Public API::

    from scripts.validate_export import validate_package, ValidationError
    errors = validate_package(package_dir, mode="test")

Returns ``[]`` on a clean package. CLI wraps this and exits 1 on any error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

STREAM_ID_FIELDS: dict[str, str] = {
    "entities": "entity_id",
    "sources": "source_id",
    "funding_awards": "award_id",
    "transactions": "transaction_id",
    "relationships": "relationship_id",
}

STREAM_FILENAMES: dict[str, str] = {
    "entities": "entities.jsonl",
    "sources": "sources.jsonl",
    "funding_awards": "funding_awards.jsonl",
    "transactions": "transactions.jsonl",
    "relationships": "relationships.jsonl",
}

STREAM_SCHEMA_FILES: dict[str, str] = {
    "entities": "contract_sweeper_entity.schema.json",
    "sources": "contract_sweeper_source.schema.json",
    "funding_awards": "contract_sweeper_funding_award.schema.json",
    "transactions": "contract_sweeper_transaction.schema.json",
    "relationships": "contract_sweeper_relationship.schema.json",
}

MONEY_STREAMS = ("funding_awards", "transactions")

# Cross-repo federation handshake the producer must declare so the spiderweb-pr
# query hub can route and version-check the package on ingest.
FEDERATION_EXPECTED = {
    "producer_repo": "contract-sweeper",
    "consumer_repo": "spiderweb-pr",
    "consumer_component": "query-hub",
    "contract": "contract-sweeper-export",
}

# Iteration order: streams whose IDs are referenced by others come first.
STREAM_ORDER = ("sources", "entities", "funding_awards", "transactions", "relationships")


@dataclass(frozen=True)
class ValidationError:
    """One fail-closed finding from :func:`validate_package`."""

    code: str
    location: str
    message: str

    def format(self) -> str:
        return f"[FAIL {self.code}] {self.location}: {self.message}"


def _load_schema_required(stream: str) -> list[str]:
    path = SCHEMAS_DIR / STREAM_SCHEMA_FILES[stream]
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("required", []))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_tz_aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_location(location: Any, loc: str) -> list[ValidationError]:
    """Validate an optional `location` object (awards/transactions)."""
    errors: list[ValidationError] = []
    if not isinstance(location, dict):
        return [ValidationError("location_invalid", loc, "location must be an object")]
    for field_name, lo, hi in (
        ("latitude", -90.0, 90.0),
        ("longitude", -180.0, 180.0),
        ("attribution_confidence", 0.0, 1.0),
    ):
        if field_name in location:
            value = location[field_name]
            if not _is_finite_number(value) or not (lo <= float(value) <= hi):
                errors.append(
                    ValidationError(
                        "location_invalid",
                        loc,
                        f"location.{field_name}={value!r} is outside [{lo}, {hi}] or not a number",
                    )
                )
    return errors


def _check_external_ids(external_ids: Any, loc: str) -> list[ValidationError]:
    """Validate an optional entity `external_ids` object (string values only)."""
    if not isinstance(external_ids, dict):
        return [ValidationError("external_ids_invalid", loc, "external_ids must be an object")]
    errors: list[ValidationError] = []
    for key, value in external_ids.items():
        if not isinstance(value, str):
            errors.append(
                ValidationError(
                    "external_ids_invalid",
                    loc,
                    f"external_ids.{key}={value!r} must be a string",
                )
            )
    return errors


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[ValidationError]]:
    rows: list[dict[str, Any]] = []
    errors: list[ValidationError] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                errors.append(
                    ValidationError(
                        code="jsonl_unparseable",
                        location=f"{path.name}:line {line_no}",
                        message=f"JSON parse failed: {exc.msg}",
                    )
                )
    return rows, errors


def validate_package(package_dir: str | Path, mode: str = "test") -> list[ValidationError]:
    """Run all fail-closed gates on a packaged export directory.

    Returns a list of :class:`ValidationError`; empty list means the package
    is valid for the requested mode.
    """
    if mode not in ("test", "production"):
        raise ValueError(f"invalid mode: {mode!r}")

    pkg = Path(package_dir)
    errors: list[ValidationError] = []

    manifest_path = pkg / "manifest.json"
    if not manifest_path.exists():
        return [ValidationError("manifest_missing", str(pkg), "manifest.json not found")]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [ValidationError("manifest_unparseable", "manifest.json", exc.msg)]

    # Manifest top-level timestamp checks.
    for ts_field in ("created_at", "extracted_at"):
        if ts_field in manifest and _parse_tz_aware(manifest[ts_field]) is None:
            errors.append(
                ValidationError(
                    "timestamp_invalid",
                    "manifest.json",
                    f"{ts_field}={manifest.get(ts_field)!r} is not a tz-aware ISO-8601 timestamp",
                )
            )

    # Cross-repo federation handshake descriptor (routable to spiderweb-pr/query-hub).
    federation = manifest.get("federation")
    if not isinstance(federation, dict):
        errors.append(
            ValidationError(
                "federation_invalid",
                "manifest.json",
                "missing or non-object federation descriptor",
            )
        )
    else:
        for key, expected in FEDERATION_EXPECTED.items():
            actual = federation.get(key)
            if actual != expected:
                errors.append(
                    ValidationError(
                        "federation_invalid",
                        "manifest.json",
                        f"federation.{key}={actual!r} (expected {expected!r})",
                    )
                )

    files_decl = manifest.get("files")
    if not isinstance(files_decl, list) or len(files_decl) < 5:
        errors.append(
            ValidationError(
                "manifest_files_missing",
                "manifest.json",
                f"expected 5 file entries, got "
                f"{len(files_decl) if isinstance(files_decl, list) else 'none'}",
            )
        )

    declared_by_stream: dict[str, dict[str, Any]] = {}
    if isinstance(files_decl, list):
        for entry in files_decl:
            stream = entry.get("stream") if isinstance(entry, dict) else None
            if stream in STREAM_FILENAMES and isinstance(entry, dict):
                declared_by_stream[stream] = entry

    for stream, filename in STREAM_FILENAMES.items():
        if stream not in declared_by_stream:
            errors.append(
                ValidationError(
                    "manifest_files_missing",
                    "manifest.json",
                    f"missing files[] entry for stream={stream}",
                )
            )
            continue
        path = pkg / filename
        if not path.exists():
            errors.append(
                ValidationError(
                    "manifest_files_missing",
                    filename,
                    "declared stream file not found on disk",
                )
            )

    rows_by_stream: dict[str, list[dict[str, Any]]] = {}
    for stream in STREAM_ORDER:
        filename = STREAM_FILENAMES[stream]
        path = pkg / filename
        if not path.exists():
            continue
        rows, parse_errs = _read_jsonl(path)
        errors.extend(parse_errs)
        rows_by_stream[stream] = rows

        if stream in declared_by_stream:
            actual_sha = _sha256_file(path)
            declared_sha = declared_by_stream[stream].get("sha256")
            if declared_sha != actual_sha:
                errors.append(
                    ValidationError(
                        "manifest_sha256_mismatch",
                        filename,
                        f"declared sha256={declared_sha!r} but actual={actual_sha!r}",
                    )
                )
            declared_count = declared_by_stream[stream].get("record_count")
            actual_count = len(rows)
            if declared_count != actual_count:
                errors.append(
                    ValidationError(
                        "manifest_row_count_mismatch",
                        filename,
                        f"declared record_count={declared_count!r} but actual={actual_count!r}",
                    )
                )

    entity_ids: set[str] = set()
    source_ids: set[str] = set()
    for row in rows_by_stream.get("entities", []):
        eid = row.get("entity_id")
        if isinstance(eid, str):
            entity_ids.add(eid)
    for row in rows_by_stream.get("sources", []):
        sid = row.get("source_id")
        if isinstance(sid, str):
            source_ids.add(sid)

    for stream in STREAM_ORDER:
        if stream not in rows_by_stream:
            continue
        rows = rows_by_stream[stream]
        required = _load_schema_required(stream)
        id_field = STREAM_ID_FIELDS[stream]
        seen_ids: dict[str, int] = {}

        for i, row in enumerate(rows):
            loc = f"{STREAM_FILENAMES[stream]}:row {i + 1}"

            for field_name in required:
                if field_name not in row:
                    errors.append(
                        ValidationError(
                            "required_fields_missing",
                            loc,
                            f"missing required field {field_name!r}",
                        )
                    )

            if stream == "sources" and "source_url" not in row and "source_ref" not in row:
                errors.append(
                    ValidationError(
                        "required_fields_missing",
                        loc,
                        "sources row must include source_url or source_ref",
                    )
                )

            if "confidence" not in row:
                errors.append(ValidationError("confidence_missing", loc, "missing confidence"))
            else:
                conf = row["confidence"]
                if not _is_finite_number(conf) or not (0.0 <= float(conf) <= 1.0):
                    errors.append(
                        ValidationError(
                            "confidence_out_of_range",
                            loc,
                            f"confidence={conf!r} is outside [0.0, 1.0]",
                        )
                    )

            lineage = row.get("lineage")
            if lineage is None:
                errors.append(ValidationError("lineage_missing", loc, "missing lineage"))
            elif not isinstance(lineage, dict):
                errors.append(ValidationError("lineage_invalid", loc, "lineage must be an object"))
            else:
                if not isinstance(lineage.get("producer_script"), str):
                    errors.append(
                        ValidationError(
                            "lineage_invalid",
                            loc,
                            "lineage.producer_script missing or not a string",
                        )
                    )
                if not isinstance(lineage.get("producer_phase"), str):
                    errors.append(
                        ValidationError(
                            "lineage_invalid",
                            loc,
                            "lineage.producer_phase missing or not a string",
                        )
                    )
                if not isinstance(lineage.get("source_inputs"), list):
                    errors.append(
                        ValidationError(
                            "lineage_invalid",
                            loc,
                            "lineage.source_inputs missing or not a list",
                        )
                    )

            for ts_field in ("created_at", "extracted_at"):
                if ts_field in row and _parse_tz_aware(row[ts_field]) is None:
                    errors.append(
                        ValidationError(
                            "timestamp_invalid",
                            loc,
                            f"{ts_field}={row.get(ts_field)!r} is not a tz-aware ISO-8601 timestamp",
                        )
                    )

            if stream in MONEY_STREAMS:
                amount = row.get("amount")
                if amount is not None:
                    if not _is_finite_number(amount):
                        errors.append(
                            ValidationError(
                                "amount_invalid",
                                loc,
                                f"amount={amount!r} is not a finite number",
                            )
                        )
                    elif float(amount) < 0:
                        errors.append(
                            ValidationError(
                                "amount_negative",
                                loc,
                                f"amount={amount!r} is negative",
                            )
                        )

                currency = row.get("currency")
                if currency is None:
                    errors.append(ValidationError("currency_missing", loc, "missing currency"))
                elif not (isinstance(currency, str) and CURRENCY_RE.match(currency)):
                    errors.append(
                        ValidationError(
                            "currency_invalid",
                            loc,
                            f"currency={currency!r} is not a 3-letter uppercase code",
                        )
                    )

            if mode == "production" and row.get("synthetic") is True:
                errors.append(
                    ValidationError(
                        "synthetic_in_production",
                        loc,
                        "synthetic=true rows are not permitted in mode=production",
                    )
                )

            # Optional location object (awards & transactions) — for hub spatial matching.
            if "location" in row:
                errors.extend(_check_location(row["location"], loc))

            # Optional entity external_ids — for cross-repo entity matching.
            if stream == "entities" and "external_ids" in row:
                errors.extend(_check_external_ids(row["external_ids"], loc))

            row_id = row.get(id_field)
            if isinstance(row_id, str):
                prev = seen_ids.get(row_id)
                if prev is not None:
                    errors.append(
                        ValidationError(
                            "duplicate_id",
                            loc,
                            f"{id_field}={row_id!r} also seen at row {prev}",
                        )
                    )
                else:
                    seen_ids[row_id] = i + 1

            envelope_src = row.get("source_id")
            if isinstance(envelope_src, str) and envelope_src not in source_ids:
                errors.append(
                    ValidationError(
                        "dangling_source_ref",
                        loc,
                        f"envelope source_id={envelope_src!r} not found in sources.jsonl",
                    )
                )

            entity_ref_fields: list[str] = []
            source_ref_fields: list[str] = []
            if stream == "funding_awards":
                entity_ref_fields = ["recipient_entity_id", "funding_agency_entity_id"]
            elif stream == "transactions":
                entity_ref_fields = ["payer_entity_id", "payee_entity_id"]
            elif stream == "relationships":
                entity_ref_fields = ["source_entity_id", "target_entity_id"]
                source_ref_fields = ["evidence_source_id"]

            for ref_field in entity_ref_fields:
                v = row.get(ref_field)
                if isinstance(v, str) and v not in entity_ids:
                    errors.append(
                        ValidationError(
                            "dangling_entity_ref",
                            loc,
                            f"{ref_field}={v!r} not found in entities.jsonl",
                        )
                    )
            for ref_field in source_ref_fields:
                v = row.get(ref_field)
                if isinstance(v, str) and v not in source_ids:
                    errors.append(
                        ValidationError(
                            "dangling_entity_ref",
                            loc,
                            f"{ref_field}={v!r} not found in sources.jsonl",
                        )
                    )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Contract-Sweeper export package (fail-closed).",
    )
    parser.add_argument("--package", required=True, help="path to package directory")
    parser.add_argument("--mode", choices=("test", "production"), default="test")
    args = parser.parse_args(argv)

    errors = validate_package(args.package, mode=args.mode)
    if errors:
        for err in errors:
            print(err.format())
        print(f"[FAIL] {len(errors)} validation error(s) in mode={args.mode}")
        return 1
    print(f"[OK] export package valid in mode={args.mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
