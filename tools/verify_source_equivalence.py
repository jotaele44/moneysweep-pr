from __future__ import annotations

import argparse
import json
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

SCHEMA_VERSION = "moneysweep.source_equivalence/v1"
REPORT_VERSION = "moneysweep.source_equivalence_verification/v2"
TEST_KEYS = (
    "semantic_scope_match",
    "temporal_scope_match",
    "row_universe_match",
    "field_mapping_complete",
    "selection_equivalent",
    "aggregation_equivalent",
)


def _hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
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

    blockers: list[str] = []
    if candidate.get("authoritative") is not True:
        blockers.append("candidate_not_authoritative")
    for key in TEST_KEYS:
        if tests.get(key) is not True:
            blockers.append(key)
    if missing_fields:
        blockers.append("missing_fields_present")
    if errors:
        blockers.append("claim_contract_invalid")
    if not evidence_results or verified_evidence_count != len(evidence_results):
        blockers.append("evidence_not_byte_verified")

    if not blockers:
        decision = "CERTIFIED_EQUIVALENT"
    else:
        passed = sum(tests.get(key) is True for key in TEST_KEYS)
        if passed and registered is not None:
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
        "decision": decision,
        "certified_equivalent": decision == "CERTIFIED_EQUIVALENT",
        "tests": {key: tests.get(key) for key in TEST_KEYS},
        "missing_fields": missing_fields,
        "extra_fields": (
            claim.get("extra_fields") if isinstance(claim.get("extra_fields"), list) else []
        ),
        "evidence_count": len(evidence_items),
        "verified_evidence_count": verified_evidence_count,
        "evidence": evidence_results,
        "errors": sorted(set(errors)),
        "blockers": sorted(set(blockers)),
        "evidence_blockers": evidence_blockers,
        "policy": {
            "silent_substitution_allowed": False,
            "certification_requires_all_tests": True,
            "missing_fields_allowed_for_certified_equivalence": False,
            "byte_verified_evidence_required": True,
            "remote_only_evidence_can_certify": False,
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
