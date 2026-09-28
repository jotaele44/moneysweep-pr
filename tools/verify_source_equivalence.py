from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
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
TEST_KEYS = (
    "semantic_scope_match",
    "temporal_scope_match",
    "row_universe_match",
    "field_mapping_complete",
    "selection_equivalent",
    "aggregation_equivalent",
)
IDENTITY_BASES = {
    "stable_id",
    "authoritative_binding",
    "certified_composite_key",
}


def _hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _name_only(fields: list[str]) -> bool:
    if not fields:
        return False
    tokens = [field.casefold().replace("-", "_") for field in fields]
    return all(
        token in {"name", "normalized_name", "canonical_name"}
        or token.endswith("_name")
        or token.startswith("name_")
        for token in tokens
    )


def validate_claim_shape(claim: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "schema_version",
        "source_id",
        "candidate_source",
        "tests",
        "missing_fields",
        "extra_fields",
        "evidence",
        "row_set_comparison",
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
    candidate_extra = sorted(set(candidate) - {"source_id", "name", "source_url", "authoritative"})
    if candidate_extra:
        errors.append("unexpected_candidate_keys:" + ",".join(candidate_extra))
    if (
        not isinstance(candidate.get("source_id"), str)
        or not candidate.get("source_id", "").strip()
    ):
        errors.append("candidate_source_id_missing")
    if not isinstance(candidate.get("name"), str) or not candidate.get("name", "").strip():
        errors.append("candidate_name_missing")
    if (
        not isinstance(candidate.get("source_url"), str)
        or not candidate.get("source_url", "").strip()
    ):
        errors.append("candidate_source_url_missing")
    if not isinstance(candidate.get("authoritative"), bool):
        errors.append("candidate_authoritative_invalid")

    tests = claim.get("tests")
    if not isinstance(tests, dict):
        errors.append("tests_missing")
        tests = {}
    test_extra = sorted(set(tests) - set(TEST_KEYS))
    if test_extra:
        errors.append("unexpected_test_keys:" + ",".join(test_extra))
    for key in TEST_KEYS:
        if not isinstance(tests.get(key), bool):
            errors.append(f"test_{key}_invalid")

    for key in ("missing_fields", "extra_fields"):
        value = claim.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{key}_invalid")
        elif len(value) != len(set(value)):
            errors.append(f"{key}_duplicates")

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

    comparison = claim.get("row_set_comparison")
    if not isinstance(comparison, dict):
        errors.append("row_set_comparison_missing")
        comparison = {}
    allowed_comparison = {"a_locator", "b_locator", "key_fields", "identity_basis"}
    comparison_extra = sorted(set(comparison) - allowed_comparison)
    if comparison_extra:
        errors.append("unexpected_row_set_comparison_keys:" + ",".join(comparison_extra))
    for locator_key in ("a_locator", "b_locator"):
        value = comparison.get(locator_key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{locator_key}_missing")
    key_fields = comparison.get("key_fields")
    if (
        not isinstance(key_fields, list)
        or not key_fields
        or any(not isinstance(item, str) or not item for item in key_fields)
    ):
        errors.append("key_fields_invalid")
    elif len(key_fields) != len(set(key_fields)):
        errors.append("key_fields_duplicates")
    if comparison.get("identity_basis") not in IDENTITY_BASES:
        errors.append("identity_basis_invalid")
    return sorted(set(errors))


def _verify_evidence(root: Path, evidence: object) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    if not isinstance(evidence, list):
        return results, ["evidence_missing"]

    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        locator = str(item.get("locator") or "")
        expected_sha = item.get("sha256")
        row: dict[str, Any] = {
            "kind": item.get("kind"),
            "locator": locator,
            "expected_sha256": expected_sha,
            "exists": False,
            "actual_sha256": None,
            "sha256_match": False,
        }
        try:
            rel = safe_relative_path(locator)
        except ValueError:
            errors.append(f"evidence_{index}_locator_not_repository_relative")
            results.append(row)
            continue

        path = root / rel
        row["resolved_path"] = rel.as_posix()
        if not path.is_file():
            errors.append(f"evidence_{index}_file_missing")
            results.append(row)
            continue

        actual_sha = sha256_file(path)
        row.update(
            {
                "exists": True,
                "actual_sha256": actual_sha,
                "sha256_match": actual_sha == expected_sha,
            }
        )
        if actual_sha != expected_sha:
            errors.append(f"evidence_{index}_sha256_mismatch")
        results.append(row)
    return results, errors


def _canonical_key_digest(keys: set[tuple[str, ...]]) -> str:
    serial = [list(key) for key in sorted(keys)]
    payload = json.dumps(serial, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_key_set(path: Path, key_fields: list[str]) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        missing_fields = [field for field in key_fields if field not in fieldnames]
        if missing_fields:
            return {
                "error": "missing_key_fields",
                "missing_key_fields": missing_fields,
                "row_count": 0,
                "unique_key_count": 0,
                "duplicate_key_rows": 0,
                "null_key_rows": 0,
                "keys": set(),
            }

        keys: list[tuple[str, ...]] = []
        null_key_rows = 0
        for row in reader:
            key = tuple(row.get(field, "") for field in key_fields)
            if any(value == "" for value in key):
                null_key_rows += 1
            keys.append(key)

    counts = Counter(keys)
    return {
        "error": None,
        "missing_key_fields": [],
        "row_count": len(keys),
        "unique_key_count": len(counts),
        "duplicate_key_rows": sum(count - 1 for count in counts.values() if count > 1),
        "null_key_rows": null_key_rows,
        "keys": set(counts),
    }


def _compute_row_set_comparison(
    *,
    root: Path,
    comparison: object,
    evidence_results: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    errors: list[str] = []
    blockers: list[str] = []
    if not isinstance(comparison, dict):
        return None, ["row_set_comparison_missing"], ["row_set_comparison_unverified"]

    a_locator = str(comparison.get("a_locator") or "")
    b_locator = str(comparison.get("b_locator") or "")
    key_fields = comparison.get("key_fields")
    key_fields = key_fields if isinstance(key_fields, list) else []
    key_fields = [str(item) for item in key_fields]
    identity_basis = comparison.get("identity_basis")

    if _name_only(key_fields):
        blockers.append("name_only_identity_disallowed")

    verified_locators = {
        str(item.get("locator"))
        for item in evidence_results
        if item.get("exists") is True and item.get("sha256_match") is True
    }
    for label, locator in (("a", a_locator), ("b", b_locator)):
        if locator not in verified_locators:
            blockers.append(f"{label}_comparison_bytes_not_verified")

    try:
        a_rel = safe_relative_path(a_locator)
        b_rel = safe_relative_path(b_locator)
    except ValueError:
        errors.append("row_set_locator_not_repository_relative")
        return None, errors, blockers

    a_path = root / a_rel
    b_path = root / b_rel
    if a_path.suffix.lower() != ".csv" or b_path.suffix.lower() != ".csv":
        blockers.append("row_set_comparison_requires_csv")
    if blockers and (
        "a_comparison_bytes_not_verified" in blockers
        or "b_comparison_bytes_not_verified" in blockers
        or "row_set_comparison_requires_csv" in blockers
    ):
        return None, errors, blockers

    try:
        a = _load_key_set(a_path, key_fields)
        b = _load_key_set(b_path, key_fields)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        errors.append(f"row_set_csv_unreadable:{type(exc).__name__}")
        return None, errors, [*blockers, "row_set_comparison_unverified"]

    for label, result in (("a", a), ("b", b)):
        if result["error"] == "missing_key_fields":
            blockers.append(
                f"{label}_missing_key_fields:" + ",".join(result["missing_key_fields"])
            )
        if result["duplicate_key_rows"]:
            blockers.append(f"{label}_duplicate_identity_keys")
        if result["null_key_rows"]:
            blockers.append(f"{label}_null_identity_keys")

    a_keys = a["keys"]
    b_keys = b["keys"]
    intersection = a_keys & b_keys
    a_only = a_keys - b_keys
    b_only = b_keys - a_keys
    union = a_keys | b_keys
    symmetric_difference = a_keys ^ b_keys

    if a_only or b_only:
        blockers.append("computed_row_universe_mismatch")

    result = {
        "identity_basis": identity_basis,
        "key_fields": key_fields,
        "a_locator": a_locator,
        "b_locator": b_locator,
        "a_row_count": a["row_count"],
        "b_row_count": b["row_count"],
        "a_unique_key_count": a["unique_key_count"],
        "b_unique_key_count": b["unique_key_count"],
        "a_duplicate_key_rows": a["duplicate_key_rows"],
        "b_duplicate_key_rows": b["duplicate_key_rows"],
        "a_null_key_rows": a["null_key_rows"],
        "b_null_key_rows": b["null_key_rows"],
        "intersection": len(intersection),
        "a_only": len(a_only),
        "b_only": len(b_only),
        "union": len(union),
        "symmetric_difference": len(symmetric_difference),
        "a_only_keys": [list(key) for key in sorted(a_only)],
        "b_only_keys": [list(key) for key in sorted(b_only)],
        "intersection_sha256": _canonical_key_digest(intersection),
        "union_sha256": _canonical_key_digest(union),
        "symmetric_difference_sha256": _canonical_key_digest(symmetric_difference),
    }
    return result, errors, sorted(set(blockers))


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
    candidate_source_id = str(candidate.get("source_id", "")).strip()
    candidate_registered = source_by_id.get(candidate_source_id)
    if candidate_registered is None:
        errors.append("candidate_source_id_not_registered")
    if source_id and candidate_source_id and source_id == candidate_source_id:
        errors.append("candidate_source_must_differ_from_target")

    tests = claim.get("tests")
    tests = tests if isinstance(tests, dict) else {}
    missing_fields = claim.get("missing_fields")
    missing_fields = missing_fields if isinstance(missing_fields, list) else []

    evidence_results, evidence_errors = _verify_evidence(root, claim.get("evidence"))
    errors.extend(evidence_errors)
    row_set, row_errors, row_blockers = _compute_row_set_comparison(
        root=root,
        comparison=claim.get("row_set_comparison"),
        evidence_results=evidence_results,
    )
    errors.extend(row_errors)

    blockers: list[str] = list(row_blockers)
    if candidate.get("authoritative") is not True:
        blockers.append("candidate_not_authoritative")
    for key in TEST_KEYS:
        if tests.get(key) is not True:
            blockers.append(key)
    if missing_fields:
        blockers.append("missing_fields_present")
    if evidence_errors or not evidence_results:
        blockers.append("evidence_not_byte_verified")
    if row_set is None:
        blockers.append("row_set_comparison_unverified")
    if errors:
        blockers.append("claim_contract_invalid")

    blockers = sorted(set(blockers))
    if not blockers:
        decision = "CERTIFIED_EQUIVALENT"
    else:
        passed = sum(tests.get(key) is True for key in TEST_KEYS)
        if passed and registered is not None and candidate_registered is not None:
            decision = "PARTIAL_EQUIVALENCE"
        elif registered is not None:
            decision = "UNPROVEN"
        else:
            decision = "NON_EQUIVALENT"

    return {
        "schema_version": REPORT_VERSION,
        "source_id": source_id,
        "registered_source_definition_sha256": (
            source_definition_digest(registered) if registered is not None else None
        ),
        "candidate_source": candidate,
        "candidate_registered_source_definition_sha256": (
            source_definition_digest(candidate_registered)
            if candidate_registered is not None
            else None
        ),
        "decision": decision,
        "certified_equivalent": decision == "CERTIFIED_EQUIVALENT",
        "tests": {key: tests.get(key) for key in TEST_KEYS},
        "missing_fields": missing_fields,
        "extra_fields": (
            claim.get("extra_fields") if isinstance(claim.get("extra_fields"), list) else []
        ),
        "row_set_comparison": row_set,
        "evidence_count": len(claim.get("evidence") or []),
        "evidence_verification": evidence_results,
        "errors": sorted(set(errors)),
        "blockers": blockers,
        "policy": {
            "silent_substitution_allowed": False,
            "certification_requires_all_tests": True,
            "missing_fields_allowed_for_certified_equivalence": False,
            "candidate_must_be_registered": True,
            "evidence_bytes_must_match_claimed_hashes": True,
            "computed_set_algebra_required": True,
            "name_only_identity_allowed": False,
            "duplicate_identity_keys_allowed": False,
            "null_identity_keys_allowed": False,
            "zero_symmetric_difference_required": True,
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
