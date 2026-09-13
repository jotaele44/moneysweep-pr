from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        load_sources,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        load_sources,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
    )

SCHEMA_VERSION = "moneysweep.source_equivalence/v2"
REPORT_VERSION = "moneysweep.source_equivalence_verification/v3"
DECLARED_TEST_KEYS = (
    "semantic_scope_match",
    "temporal_scope_match",
    "selection_equivalent",
    "aggregation_equivalent",
)


def _hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _string_list(value: object, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(isinstance(item, str) and bool(item) for item in value)
        and len(value) == len(set(value))
    )


def _format_valid(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"encoding", "delimiter", "header_row"}
        and value.get("encoding") in {"utf-8", "utf-8-sig"}
        and isinstance(value.get("delimiter"), str)
        and len(value.get("delimiter", "")) == 1
        and isinstance(value.get("header_row"), int)
        and not isinstance(value.get("header_row"), bool)
        and value.get("header_row", 0) >= 1
    )


def validate_claim_shape(claim: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "schema_version",
        "source_id",
        "candidate_source",
        "tests",
        "comparison",
        "missing_fields",
        "extra_fields",
        "evidence",
        "notes",
    }
    extra = sorted(set(claim) - allowed)
    if extra:
        errors.append("unexpected_top_level_keys:" + ",".join(extra))
    if claim.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if not isinstance(claim.get("source_id"), str) or not str(claim.get("source_id")).strip():
        errors.append("source_id_missing")

    candidate = claim.get("candidate_source")
    if not isinstance(candidate, dict):
        errors.append("candidate_source_missing")
        candidate = {}
    candidate_extra = sorted(set(candidate) - {"name", "source_url", "authoritative"})
    if candidate_extra:
        errors.append("unexpected_candidate_keys:" + ",".join(candidate_extra))
    if not isinstance(candidate.get("name"), str) or not candidate.get("name", "").strip():
        errors.append("candidate_name_missing")
    if not isinstance(candidate.get("source_url"), str) or not candidate.get("source_url", "").strip():
        errors.append("candidate_source_url_missing")
    if not isinstance(candidate.get("authoritative"), bool):
        errors.append("candidate_authoritative_invalid")

    tests = claim.get("tests")
    if not isinstance(tests, dict):
        errors.append("tests_missing")
        tests = {}
    test_extra = sorted(set(tests) - set(DECLARED_TEST_KEYS))
    if test_extra:
        errors.append("unexpected_test_keys:" + ",".join(test_extra))
    for key in DECLARED_TEST_KEYS:
        if not isinstance(tests.get(key), bool):
            errors.append(f"test_{key}_invalid")

    comparison = claim.get("comparison")
    if not isinstance(comparison, dict):
        errors.append("comparison_missing")
        comparison = {}
    allowed_comparison = {
        "original_path",
        "candidate_path",
        "original_sha256",
        "candidate_sha256",
        "original_format",
        "candidate_format",
        "stable_key",
        "compare_fields",
        "field_mapping",
    }
    comparison_extra = sorted(set(comparison) - allowed_comparison)
    if comparison_extra:
        errors.append("unexpected_comparison_keys:" + ",".join(comparison_extra))
    for key in ("original_path", "candidate_path"):
        if not isinstance(comparison.get(key), str) or not comparison.get(key, "").strip():
            errors.append(f"comparison_{key}_missing")
    for key in ("original_sha256", "candidate_sha256"):
        if not _hex64(comparison.get(key)):
            errors.append(f"comparison_{key}_invalid")
    for key in ("original_format", "candidate_format"):
        if not _format_valid(comparison.get(key)):
            errors.append(f"comparison_{key}_invalid")
    for key in ("stable_key", "compare_fields"):
        if not _string_list(comparison.get(key), nonempty=True):
            errors.append(f"comparison_{key}_invalid")
    mapping = comparison.get("field_mapping")
    if (
        not isinstance(mapping, dict)
        or not mapping
        or any(
            not isinstance(left, str)
            or not left
            or not isinstance(right, str)
            or not right
            for left, right in mapping.items()
        )
    ):
        errors.append("comparison_field_mapping_invalid")

    for key in ("missing_fields", "extra_fields"):
        if not _string_list(claim.get(key)):
            errors.append(f"{key}_invalid")

    evidence = claim.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence_missing")
        evidence = []
    for index, item in enumerate(evidence):
        prefix = f"evidence_{index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}_invalid")
            continue
        extra_item = sorted(set(item) - {"kind", "locator", "sha256"})
        if extra_item:
            errors.append(f"{prefix}_unexpected_keys:" + ",".join(extra_item))
        if not isinstance(item.get("kind"), str) or not item.get("kind", "").strip():
            errors.append(f"{prefix}_kind_missing")
        if not isinstance(item.get("locator"), str) or not item.get("locator", "").strip():
            errors.append(f"{prefix}_locator_missing")
        if not _hex64(item.get("sha256")):
            errors.append(f"{prefix}_sha256_invalid")
    return sorted(set(errors))


def _verify_evidence_item(*, root: Path, item: dict[str, Any]) -> dict[str, Any]:
    locator = item.get("locator")
    expected_sha = item.get("sha256")
    result: dict[str, Any] = {
        "kind": item.get("kind"),
        "locator": locator,
        "expected_sha256": expected_sha,
        "actual_sha256": None,
        "verified": False,
        "blockers": [],
    }
    if not isinstance(locator, str) or not locator.strip():
        result["blockers"].append("locator_missing")
        return result
    if locator.startswith(("http://", "https://")):
        result["blockers"].append("remote_evidence_not_byte_verified")
        return result
    try:
        relative = safe_relative_path(locator)
    except ValueError:
        result["blockers"].append("unsafe_evidence_locator")
        return result
    path = root / relative
    if not path.is_file():
        result["blockers"].append("evidence_file_missing")
        return result
    actual_sha = sha256_file(path)
    result["actual_sha256"] = actual_sha
    if actual_sha != expected_sha:
        result["blockers"].append("evidence_sha256_mismatch")
        return result
    result["verified"] = True
    return result


def _read_csv_manifestation(
    *, root: Path, logical_path: object, expected_sha: object, format_spec: object, label: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": logical_path,
        "expected_sha256": expected_sha,
        "actual_sha256": None,
        "encoding": None,
        "delimiter": None,
        "header_row": None,
        "preamble_rows": None,
        "header": [],
        "row_count": 0,
        "rows": [],
        "errors": [],
    }
    if not isinstance(logical_path, str) or not logical_path.strip():
        result["errors"].append(f"{label}_path_missing")
        return result
    try:
        relative = safe_relative_path(logical_path)
    except ValueError:
        result["errors"].append(f"{label}_path_unsafe")
        return result
    path = root / relative
    if not path.is_file():
        result["errors"].append(f"{label}_file_missing")
        return result
    actual_sha = sha256_file(path)
    result["actual_sha256"] = actual_sha
    if actual_sha != expected_sha:
        result["errors"].append(f"{label}_sha256_mismatch")
    if not _format_valid(format_spec):
        result["errors"].append(f"{label}_format_invalid")
        return result
    assert isinstance(format_spec, dict)
    encoding = str(format_spec["encoding"])
    delimiter = str(format_spec["delimiter"])
    header_row = int(format_spec["header_row"])
    result.update(
        {
            "encoding": encoding,
            "delimiter": delimiter,
            "header_row": header_row,
            "preamble_rows": header_row - 1,
        }
    )
    try:
        with path.open("r", encoding=encoding, newline="") as stream:
            parsed = list(csv.reader(stream, delimiter=delimiter, strict=True))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        result["errors"].append(f"{label}_csv_unreadable:{type(exc).__name__}")
        return result
    if len(parsed) < header_row:
        result["errors"].append(f"{label}_header_row_out_of_range")
        return result
    header = parsed[header_row - 1]
    result["header"] = header
    if not header or any(column == "" for column in header):
        result["errors"].append(f"{label}_header_empty_column")
    if len(header) != len(set(header)):
        result["errors"].append(f"{label}_header_duplicate_columns")
    rows: list[dict[str, str]] = []
    for physical_row, values in enumerate(parsed[header_row:], start=header_row + 1):
        if len(values) != len(header):
            result["errors"].append(
                f"{label}_row_width_mismatch:{physical_row}:{len(values)}:{len(header)}"
            )
            continue
        rows.append(dict(zip(header, values)))
    result["rows"] = rows
    result["row_count"] = len(rows)
    return result


def _key_payload(fields: list[str], key: tuple[str, ...]) -> dict[str, str]:
    return {field: value for field, value in zip(fields, key)}


def _compute_comparison(*, root: Path, comparison: dict[str, Any]) -> dict[str, Any]:
    original = _read_csv_manifestation(
        root=root,
        logical_path=comparison.get("original_path"),
        expected_sha=comparison.get("original_sha256"),
        format_spec=comparison.get("original_format"),
        label="original",
    )
    candidate = _read_csv_manifestation(
        root=root,
        logical_path=comparison.get("candidate_path"),
        expected_sha=comparison.get("candidate_sha256"),
        format_spec=comparison.get("candidate_format"),
        label="candidate",
    )
    errors = list(original["errors"]) + list(candidate["errors"])
    stable_key = comparison.get("stable_key")
    compare_fields = comparison.get("compare_fields")
    mapping = comparison.get("field_mapping")
    stable_key = list(stable_key) if _string_list(stable_key, nonempty=True) else []
    compare_fields = list(compare_fields) if _string_list(compare_fields, nonempty=True) else []
    mapping = dict(mapping) if isinstance(mapping, dict) else {}

    needed_original = list(dict.fromkeys(stable_key + compare_fields))
    missing_mapping = sorted(field for field in needed_original if field not in mapping)
    missing_original_columns = sorted(field for field in needed_original if field not in original["header"])
    missing_candidate_columns = sorted(
        mapping[field]
        for field in needed_original
        if field in mapping and mapping[field] not in candidate["header"]
    )
    if missing_mapping:
        errors.append("comparison_mapping_missing:" + ",".join(missing_mapping))
    if missing_original_columns:
        errors.append("original_columns_missing:" + ",".join(missing_original_columns))
    if missing_candidate_columns:
        errors.append("candidate_columns_missing:" + ",".join(missing_candidate_columns))

    original_by_key: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    candidate_by_key: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    if not errors:
        for row in original["rows"]:
            key = tuple(row[field] for field in stable_key)
            original_by_key[key].append(row)
        for row in candidate["rows"]:
            key = tuple(row[mapping[field]] for field in stable_key)
            candidate_by_key[key].append(row)

    original_duplicate_keys = sorted(key for key, rows in original_by_key.items() if len(rows) != 1)
    candidate_duplicate_keys = sorted(key for key, rows in candidate_by_key.items() if len(rows) != 1)
    if original_duplicate_keys:
        errors.append("original_stable_key_not_unique")
    if candidate_duplicate_keys:
        errors.append("candidate_stable_key_not_unique")

    original_keys = set(original_by_key)
    candidate_keys = set(candidate_by_key)
    intersection = sorted(original_keys & candidate_keys)
    a_only = sorted(original_keys - candidate_keys)
    b_only = sorted(candidate_keys - original_keys)
    union = sorted(original_keys | candidate_keys)
    symmetric_difference = sorted(original_keys ^ candidate_keys)

    projection_differences: list[dict[str, Any]] = []
    if not errors:
        for key in intersection:
            original_rows = original_by_key[key]
            candidate_rows = candidate_by_key[key]
            if len(original_rows) != 1 or len(candidate_rows) != 1:
                continue
            left = original_rows[0]
            right = candidate_rows[0]
            left_values = {field: left[field] for field in compare_fields}
            right_values = {field: right[mapping[field]] for field in compare_fields}
            if left_values != right_values:
                projection_differences.append(
                    {
                        "key": _key_payload(stable_key, key),
                        "original": left_values,
                        "candidate_mapped": right_values,
                    }
                )

    return {
        "original": {key: value for key, value in original.items() if key != "rows"},
        "candidate": {key: value for key, value in candidate.items() if key != "rows"},
        "stable_key": stable_key,
        "compare_fields": compare_fields,
        "field_mapping": mapping,
        "mapping_complete": not missing_mapping and not missing_original_columns and not missing_candidate_columns,
        "original_duplicate_keys": [_key_payload(stable_key, key) for key in original_duplicate_keys],
        "candidate_duplicate_keys": [_key_payload(stable_key, key) for key in candidate_duplicate_keys],
        "set_arithmetic": {
            "INTERSECTION": len(intersection),
            "A_ONLY": len(a_only),
            "B_ONLY": len(b_only),
            "UNION": len(union),
            "SYMMETRIC_DIFFERENCE": len(symmetric_difference),
            "intersection_keys": [_key_payload(stable_key, key) for key in intersection],
            "a_only_keys": [_key_payload(stable_key, key) for key in a_only],
            "b_only_keys": [_key_payload(stable_key, key) for key in b_only],
            "union_keys": [_key_payload(stable_key, key) for key in union],
            "symmetric_difference_keys": [
                _key_payload(stable_key, key) for key in symmetric_difference
            ],
        },
        "projection_difference_count": len(projection_differences),
        "projection_differences": projection_differences,
        "row_universe_match": not symmetric_difference and not original_duplicate_keys and not candidate_duplicate_keys,
        "row_projection_match": not projection_differences and not errors,
        "errors": sorted(set(errors)),
    }


def verify(*, root: Path, claim: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    errors = validate_claim_shape(claim)
    sources, _ = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    source_id = str(claim.get("source_id", "")).strip()
    registered = source_by_id.get(source_id)
    if registered is None:
        errors.append("source_id_not_registered")

    candidate = claim.get("candidate_source")
    candidate = candidate if isinstance(candidate, dict) else {}
    tests = claim.get("tests")
    tests = tests if isinstance(tests, dict) else {}
    missing_fields = claim.get("missing_fields")
    missing_fields = missing_fields if isinstance(missing_fields, list) else []

    raw_evidence = claim.get("evidence")
    evidence_items = raw_evidence if isinstance(raw_evidence, list) else []
    evidence_results = [
        _verify_evidence_item(root=root, item=item)
        for item in evidence_items
        if isinstance(item, dict)
    ]
    verified_evidence_count = sum(item["verified"] is True for item in evidence_results)
    evidence_blockers = sorted(
        {
            blocker
            for item in evidence_results
            for blocker in item.get("blockers", [])
        }
    )

    comparison_payload = claim.get("comparison")
    comparison = (
        _compute_comparison(root=root, comparison=comparison_payload)
        if isinstance(comparison_payload, dict)
        else {
            "set_arithmetic": {
                "INTERSECTION": 0,
                "A_ONLY": 0,
                "B_ONLY": 0,
                "UNION": 0,
                "SYMMETRIC_DIFFERENCE": 0,
            },
            "mapping_complete": False,
            "row_universe_match": False,
            "row_projection_match": False,
            "errors": ["comparison_missing"],
        }
    )

    blockers: list[str] = []
    if candidate.get("authoritative") is not True:
        blockers.append("candidate_not_authoritative")
    for key in DECLARED_TEST_KEYS:
        if tests.get(key) is not True:
            blockers.append(key)
    if missing_fields:
        blockers.append("missing_fields_present")
    if errors:
        blockers.append("claim_contract_invalid")
    if not evidence_results or verified_evidence_count != len(evidence_results):
        blockers.append("evidence_not_byte_verified")
    if comparison.get("errors"):
        blockers.append("comparison_execution_failed")
    if comparison.get("mapping_complete") is not True:
        blockers.append("field_mapping_incomplete")
    if comparison.get("row_universe_match") is not True:
        blockers.append("row_universe_mismatch")
    if comparison.get("row_projection_match") is not True:
        blockers.append("row_projection_mismatch")

    blockers = sorted(set(blockers))
    if not blockers:
        decision = "CERTIFIED_EQUIVALENT"
    else:
        arithmetic = comparison.get("set_arithmetic", {})
        intersection_count = int(arithmetic.get("INTERSECTION", 0) or 0)
        union_count = int(arithmetic.get("UNION", 0) or 0)
        explicitly_non_equivalent = any(tests.get(key) is False for key in DECLARED_TEST_KEYS)
        if explicitly_non_equivalent or (union_count > 0 and intersection_count == 0):
            decision = "NON_EQUIVALENT"
        elif intersection_count > 0:
            decision = "PARTIAL_EQUIVALENCE"
        else:
            decision = "UNPROVEN"

    return {
        "schema_version": REPORT_VERSION,
        "source_id": source_id,
        "registered_source_definition_sha256": (
            source_definition_digest(registered) if registered is not None else None
        ),
        "candidate_source": candidate,
        "decision": decision,
        "certified_equivalent": decision == "CERTIFIED_EQUIVALENT",
        "declared_tests": {key: tests.get(key) for key in DECLARED_TEST_KEYS},
        "comparison": comparison,
        "missing_fields": missing_fields,
        "extra_fields": (
            claim.get("extra_fields") if isinstance(claim.get("extra_fields"), list) else []
        ),
        "evidence_count": len(evidence_items),
        "verified_evidence_count": verified_evidence_count,
        "evidence": evidence_results,
        "errors": sorted(set(errors)),
        "blockers": blockers,
        "evidence_blockers": evidence_blockers,
        "policy": {
            "silent_substitution_allowed": False,
            "certification_requires_computed_set_arithmetic": True,
            "certification_requires_unique_stable_keys": True,
            "certification_requires_exact_mapped_row_projection": True,
            "missing_fields_allowed_for_certified_equivalence": False,
            "byte_verified_evidence_required": True,
            "remote_only_evidence_can_certify": False,
            "normalization_can_prove_identity": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a source-equivalence claim fail-closed.")
    parser.add_argument("claim", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.claim.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("claim must contain a JSON object")
    report = verify(root=args.root, claim=payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["certified_equivalent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
