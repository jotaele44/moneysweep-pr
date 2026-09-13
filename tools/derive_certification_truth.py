from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        expected_outputs,
        load_sources,
        sha256_file,
        source_ids_digest,
        validate_receipt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        expected_outputs,
        load_sources,
        sha256_file,
        source_ids_digest,
        validate_receipt,
    )

try:
    from tools.certification_truth_guards import (
        EvidenceError,
        aware_datetime,
        digest_json,
        evaluate_output,
        execution_state,
        freshness_status,
        load_receipts,
        receipt_binding_errors,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution fallback
    from certification_truth_guards import (  # type: ignore[no-redef]
        EvidenceError,
        aware_datetime,
        digest_json,
        evaluate_output,
        execution_state,
        freshness_status,
        load_receipts,
        receipt_binding_errors,
    )


from moneysweep.update_controller.models import CADENCE_SLA_HOURS
from scripts.build_source_recovery_matrix import (
    PATH_TYPES,
    QUEUED_PATH_TYPES,
    _classify,
)

TRUTH_SCHEMA_VERSION = "moneysweep.certification_truth/v2"
SCOPE_SCHEMA_VERSION = "moneysweep.certification_scope/v2"


def _git_head(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _parse_datetime(value: object) -> datetime | None:
    return aware_datetime(value)


def _load_receipts(receipts_dir: Path | None) -> dict[str, dict[str, Any]]:
    return load_receipts(receipts_dir)


def _coverage_state(
    source: dict[str, Any],
    materialization: str,
    outputs: list[dict[str, Any]],
    receipt: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    threshold = source.get("validation_threshold") or {}
    if not threshold:
        return "uncontracted", []
    if not isinstance(threshold, dict):
        return "unverifiable", ["invalid_validation_contract"]
    if materialization != "fully_materialized":
        return "unverifiable", ["source_not_fully_materialized"]

    unsupported = sorted(set(threshold) - {"min_rows", "required_columns", "csv"})
    blockers: list[str] = []
    if unsupported:
        blockers.append("unsupported_contract_keys:" + ",".join(unsupported))
    if any(not output["usable"] for output in outputs):
        blockers.append("unusable_output")

    receipt_coverage = None
    if receipt is not None:
        validation = receipt.get("validation")
        if isinstance(validation, dict):
            receipt_coverage = validation.get("coverage_contract_pass")
    if receipt is None:
        blockers.append("receipt_absent_or_invalid")
    if receipt_coverage is False:
        blockers.append("receipt_coverage_not_proven")

    if blockers:
        return "unverifiable", sorted(set(blockers))
    return "meets_contract", []


def _freshness_state(
    *,
    source: dict[str, Any],
    path_type: str,
    materialization: str,
    receipt: dict[str, Any] | None,
    as_of: datetime,
) -> dict[str, Any]:
    cadence = str(source.get("update_cadence") or "").strip().lower()
    sla = CADENCE_SLA_HOURS.get(cadence)
    automatable = bool(PATH_TYPES.get(path_type, (False, ""))[0])

    completed_at = None
    receipt_valid = False
    if receipt is not None:
        receipt_valid = not validate_receipt(receipt)
        acquisition = receipt.get("acquisition")
        if isinstance(acquisition, dict):
            completed_at = _parse_datetime(acquisition.get("completed_at"))

    age_hours = None
    if completed_at is not None:
        age_hours = (as_of - completed_at).total_seconds() / 3600.0

    basis = source.get("freshness_basis")
    status = freshness_status(
        cadence=cadence, basis=basis, sla=sla, materialization=materialization,
        receipt_valid=receipt_valid, completed_at=completed_at, as_of=as_of,
    )

    return {
        "source_id": source["source_id"],
        "path_type": path_type,
        "required": source.get("required") is True,
        "enabled": automatable,
        "update_cadence": cadence,
        "freshness_sla_hours": float(sla or 0),
        "last_materialized_at": (completed_at.isoformat() if completed_at is not None else None),
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "freshness_status": status,
        "receipt_valid": receipt_valid,
        "freshness_basis": basis,
    }


def derive(
    *,
    root: Path,
    evidence_root: Path,
    receipts_dir: Path | None,
    scope_dir: Path,
    as_of: datetime,
    operator_corpus_id: str | None = None,
    execution_receipts_dir: Path | None = None,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise EvidenceError("evaluation_time_requires_timezone")
    root = root.resolve()
    evidence_root = evidence_root.resolve()
    scope_dir = scope_dir.resolve()
    sources, registry_paths = load_sources(root)
    registry_digest = source_ids_digest(sources)
    receipts = _load_receipts(receipts_dir)
    executions = _load_receipts(execution_receipts_dir)
    registered = {str(source["source_id"]) for source in sources}
    extra = (set(receipts) | set(executions)) - registered
    if extra:
        raise EvidenceError("unregistered_receipts:" + ",".join(sorted(extra)))

    source_rows: list[dict[str, Any]] = []
    freshness_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    path_counts: Counter[str] = Counter()
    coverage_counts: Counter[str] = Counter()
    materiality_counts: Counter[str] = Counter()
    required_full = 0

    for source in sources:
        source_id = str(source["source_id"])
        outputs = [
            evaluate_output(
                evidence_root=evidence_root,
                source=source,
                output_path=rel,
            )
            for rel in expected_outputs(source)
        ]
        usable_count = sum(output["usable"] for output in outputs)
        if not outputs:
            materialization = "no_outputs_declared"
        elif usable_count == len(outputs):
            materialization = "fully_materialized"
        elif usable_count:
            materialization = "partially_materialized"
        else:
            materialization = "not_materialized"
        status_counts[materialization] += 1
        if source.get("required") is True and materialization == "fully_materialized":
            required_full += 1

        path_type = _classify(source, root)
        path_counts[path_type] += 1
        receipt = receipts.get(source_id)
        receipt_errors = receipt_binding_errors(
            receipt=receipt, source=source, registry_digest=registry_digest, outputs=outputs
        )
        if receipt is not None:
            receipt_errors.extend(validate_receipt(receipt))
        bound_receipt = receipt if not receipt_errors else None
        execution_status, execution_blockers = execution_state(
            execution=executions.get(source_id), receipt=receipt, source=source,
            receipt_errors=receipt_errors, materialization=materialization, as_of=as_of,
        )
        coverage_status, coverage_blockers = _coverage_state(
            source,
            materialization,
            outputs,
            bound_receipt,
        )
        coverage_counts[coverage_status] += 1

        total_rows = sum(
            int(output["rows"] or 0) for output in outputs if output.get("rows") is not None
        )
        if materialization == "not_materialized":
            materiality = "empty"
        elif coverage_status == "meets_contract":
            materiality = "validated_complete"
        elif total_rows <= 10:
            materiality = "seed"
        else:
            materiality = "substantial"
        materiality_counts[materiality] += 1

        freshness = _freshness_state(
            source=source,
            path_type=path_type,
            materialization=materialization,
            receipt=bound_receipt,
            as_of=as_of,
        )
        freshness_rows.append(freshness)
        source_rows.append(
            {
                "source_id": source_id,
                "family": source.get("family"),
                "required": source.get("required") is True,
                "authentication": source.get("authentication"),
                "producer_script": source.get("producer_script"),
                "expected_outputs": expected_outputs(source),
                "update_cadence": source.get("update_cadence"),
                "path_type": path_type,
                "materialization_status": materialization,
                "usable_output_count": usable_count,
                "expected_output_count": len(outputs),
                "local_rows": total_rows,
                "coverage_status": coverage_status,
                "coverage_blockers": coverage_blockers,
                "materiality_label": materiality,
                "receipt_present": receipt is not None,
                "receipt_logical_sha256": digest_json(receipt) if receipt is not None else None,
                "execution_logical_sha256": (
                    digest_json(executions[source_id]) if source_id in executions else None
                ),
                "receipt_valid": not receipt_errors,
                "receipt_errors": sorted(set(receipt_errors)),
                "execution_status": execution_status,
                "execution_blockers": execution_blockers,
                "automatable": bool(PATH_TYPES.get(path_type, (False, ""))[0]),
                "outputs": outputs,
            }
        )

    automatable_total = sum(
        count
        for path_type, count in path_counts.items()
        if PATH_TYPES.get(path_type, (False, ""))[0]
    )
    queued = {path_type: path_counts.get(path_type, 0) for path_type in QUEUED_PATH_TYPES}
    queued_total = sum(queued.values())

    evidence_class = (
        "claimed_operator_corpus_unverified" if operator_corpus_id else "checkout_or_operator_workspace"
    )
    truth = {
        "schema_version": TRUTH_SCHEMA_VERSION,
        "as_of": as_of.isoformat(),
        "registry": {
            "total_sources": len(sources),
            "required_sources": sum(source.get("required") is True for source in sources),
            "source_ids_sha256": registry_digest,
            "registry_paths": registry_paths,
        },
        "evidence": {
            "class": evidence_class,
            "operator_corpus_id": operator_corpus_id,
            "receipt_count": len(receipts),
        },
        "summary": {
            "materialization": dict(sorted(status_counts.items())),
            "required_fully_materialized": required_full,
            "automatable_total": automatable_total,
            "queued_excluded_total": queued_total,
            "queued_excluded": queued,
            "coverage": dict(sorted(coverage_counts.items())),
            "materiality": dict(sorted(materiality_counts.items())),
        },
        "sources": sorted(source_rows, key=lambda item: item["source_id"]),
    }

    # A completed or interrupted prior scope is evidence, not an overwrite target.
    scope_dir.mkdir(parents=True, exist_ok=False)
    scope_reports = scope_dir / "reports"
    scope_reports.mkdir()
    execution_not_ready = sorted(
        row["source_id"] for row in source_rows
        if row["automatable"] and row["execution_status"] != "EXECUTED_VALID"
    )

    status_path = scope_reports / "source_registry_status.csv"
    with status_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = [
            "source_id",
            "family",
            "required",
            "authentication",
            "producer_script",
            "expected_outputs",
            "update_cadence",
            "pipeline_status",
            "blocker_notes",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in truth["sources"]:
            blockers = []
            for output in row["outputs"]:
                if not output["usable"]:
                    blockers.append(f"{output['path']}:{output['reason']}")
            writer.writerow(
                {
                    "source_id": row["source_id"],
                    "family": row["family"],
                    "required": row["required"],
                    "authentication": row["authentication"],
                    "producer_script": row["producer_script"],
                    "expected_outputs": ";".join(row["expected_outputs"]),
                    "update_cadence": row["update_cadence"],
                    "pipeline_status": row["materialization_status"],
                    "blocker_notes": ";".join(blockers),
                }
            )

    readiness = {
        "schema_version": "r5_readiness_scope_v1",
        "total_sources": len(sources),
        "automatable_total": automatable_total,
        "automatable_ready": automatable_total - len(execution_not_ready),
        "automatable_not_ready": execution_not_ready,
        "readiness_basis": "bound_successful_execution_and_valid_output",
        "queued_excluded": queued,
        "queued_excluded_total": queued_total,
        "source_count_provenance": {
            "computed_from_live_registry": True,
            "source_ids_sha256": registry_digest,
        },
    }
    readiness_path = scope_reports / "materialization_readiness.json"
    readiness_path.write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    completeness = {
        "schema_version": "completeness_matrix_scope_v1",
        "total_sources": len(sources),
        "contracted_sources": sum(bool(source.get("validation_threshold")) for source in sources),
        "by_materialization_status": dict(sorted(status_counts.items())),
        "by_coverage_status": dict(sorted(coverage_counts.items())),
        "by_materiality_label": dict(sorted(materiality_counts.items())),
        "source_results": [
            {
                "source_id": row["source_id"],
                "materialization_status": row["materialization_status"],
                "coverage_status": row["coverage_status"],
                "coverage_blockers": row["coverage_blockers"],
                "materiality_label": row["materiality_label"],
            }
            for row in truth["sources"]
        ],
    }
    completeness_path = scope_reports / "completeness_matrix.json"
    completeness_path.write_text(
        json.dumps(completeness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    freshness_path = scope_reports / "source_freshness.csv"
    with freshness_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = [
            "source_id",
            "required",
            "path_type",
            "enabled",
            "update_cadence",
            "freshness_sla_hours",
            "last_materialized_at",
            "age_hours",
            "freshness_status",
            "receipt_valid",
            "freshness_basis",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(freshness_rows, key=lambda item: item["source_id"]))

    truth_path = scope_reports / "certification_truth.json"
    truth_path.write_text(
        json.dumps(truth, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    artifacts = {}
    for path in (
        status_path,
        readiness_path,
        completeness_path,
        freshness_path,
        truth_path,
    ):
        artifacts[path.relative_to(scope_dir).as_posix()] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    implementation_root = Path(__file__).resolve().parents[1]
    tool_paths = (
        "tools/derive_certification_truth.py", "tools/certification_truth_guards.py",
        "tools/operator_corpus_common.py", "scripts/build_source_recovery_matrix.py",
        "moneysweep/update_controller/models.py",
    )
    tool_hashes = {
        rel: sha256_file(implementation_root / rel) for rel in tool_paths
    }
    configuration = root / "registries/production_certification.yaml"
    scope_identity = {
        "registry_artifacts": {rel: sha256_file(root / rel) for rel in registry_paths},
        "source_definitions_sha256": digest_json({
            source["source_id"]: digest_json(source) for source in sources
        }),
        "scope_generation_tools": tool_hashes,
        "configuration_sha256": sha256_file(configuration) if configuration.is_file() else None,
        "artifacts_sha256": digest_json(artifacts),
        "registry_source_ids_sha256": registry_digest,
        "operator_corpus_id": operator_corpus_id,
        "implementation_sha": _git_head(Path(__file__).resolve().parents[1]),
        "scope_repository_sha": _git_head(root),
        "truth_sha256": artifacts["reports/certification_truth.json"]["sha256"],
    }
    scope_manifest = {
        "schema_version": SCOPE_SCHEMA_VERSION,
        "scope_identity": scope_identity,
        "scope_id": _sha256_json(scope_identity),
        "artifacts": artifacts,
    }
    scope_manifest_path = scope_dir / "scope_manifest.json"
    scope_manifest_path.write_text(
        json.dumps(scope_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "truth": truth,
        "scope_manifest": scope_manifest,
        "scope_manifest_path": str(scope_manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive certification truth from usable evidence bytes."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--receipts-dir", type=Path)
    parser.add_argument("--execution-receipts-dir", type=Path)
    parser.add_argument(
        "--scope-dir",
        type=Path,
        default=Path("build/certification-scope"),
    )
    parser.add_argument("--operator-corpus-id")
    parser.add_argument("--as-of")
    args = parser.parse_args()

    root = args.root.resolve()
    evidence_root = (args.evidence_root or root).resolve()
    receipts_dir = args.receipts_dir.resolve() if args.receipts_dir else None
    as_of = _parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of is None:
        raise SystemExit("--as-of must be an ISO-8601 timestamp")

    result = derive(
        root=root,
        evidence_root=evidence_root,
        receipts_dir=receipts_dir,
        scope_dir=args.scope_dir,
        as_of=as_of,
        operator_corpus_id=args.operator_corpus_id,
        execution_receipts_dir=args.execution_receipts_dir,
    )
    print(
        json.dumps(
            {
                "scope_id": result["scope_manifest"]["scope_id"],
                "materialization": result["truth"]["summary"]["materialization"],
                "required_fully_materialized": result["truth"]["summary"][
                    "required_fully_materialized"
                ],
                "automatable_total": result["truth"]["summary"]["automatable_total"],
                "queued_excluded_total": result["truth"]["summary"]["queued_excluded_total"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
