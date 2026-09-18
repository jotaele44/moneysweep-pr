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
        csv_rows,
        expected_outputs,
        load_sources,
        safe_relative_path,
        sha256_file,
        source_ids_digest,
        validate_receipt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        csv_rows,
        expected_outputs,
        load_sources,
        safe_relative_path,
        sha256_file,
        source_ids_digest,
        validate_receipt,
    )

from moneysweep.update_controller.models import CADENCE_SLA_HOURS
from scripts.build_source_recovery_matrix import (
    PATH_TYPES,
    QUEUED_PATH_TYPES,
    _classify,
)

TRUTH_SCHEMA_VERSION = "moneysweep.certification_truth/v1"
SCOPE_SCHEMA_VERSION = "moneysweep.certification_scope/v1"


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
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_valid(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


def _directory_file_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def evaluate_output(
    *,
    evidence_root: Path,
    source: dict[str, Any],
    output_path: str,
) -> dict[str, Any]:
    """Evaluate whether one declared output is usable, not merely present."""
    rel = safe_relative_path(output_path).as_posix()
    path = evidence_root / rel
    threshold = source.get("validation_threshold") or {}
    min_rows = threshold.get("min_rows", 1)
    if not isinstance(min_rows, int) or isinstance(min_rows, bool) or min_rows < 0:
        min_rows = 1

    if output_path.endswith("/"):
        exists = path.is_dir()
        files = _directory_file_count(path) if exists else 0
        return {
            "path": rel + ("/" if not rel.endswith("/") else ""),
            "kind": "directory",
            "exists": exists,
            "usable": exists and files > 0,
            "file_count": files,
            "rows": None,
            "bytes": None,
            "sha256": None,
            "reason": None if exists and files > 0 else "directory_empty_or_missing",
        }

    exists = path.is_file()
    if not exists:
        return {
            "path": rel,
            "kind": "file",
            "exists": False,
            "usable": False,
            "rows": None,
            "bytes": None,
            "sha256": None,
            "reason": "missing",
        }

    size = path.stat().st_size
    digest = sha256_file(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = csv_rows(path)
        usable = rows is not None and rows >= min_rows
        reason = None
        if rows is None:
            reason = "csv_unreadable"
        elif rows < min_rows:
            reason = f"below_min_rows:{rows}<{min_rows}"
        return {
            "path": rel,
            "kind": "csv",
            "exists": True,
            "usable": usable,
            "rows": rows,
            "min_rows": min_rows,
            "bytes": size,
            "sha256": digest,
            "reason": reason,
        }
    if suffix == ".json":
        valid = size > 0 and _json_valid(path)
        return {
            "path": rel,
            "kind": "json",
            "exists": True,
            "usable": valid,
            "rows": None,
            "bytes": size,
            "sha256": digest,
            "reason": None if valid else "json_empty_or_invalid",
        }

    usable = size > 0
    return {
        "path": rel,
        "kind": "file",
        "exists": True,
        "usable": usable,
        "rows": None,
        "bytes": size,
        "sha256": digest,
        "reason": None if usable else "empty_file",
    }


def _load_receipts(receipts_dir: Path | None) -> dict[str, dict[str, Any]]:
    if receipts_dir is None or not receipts_dir.exists():
        return {}
    receipts: dict[str, dict[str, Any]] = {}
    for path in sorted(receipts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        source_id = str(payload.get("source_id", "")).strip()
        if not source_id or source_id in receipts:
            continue
        receipts[source_id] = payload
    return receipts


def _coverage_state(
    source: dict[str, Any],
    materialization: str,
    outputs: list[dict[str, Any]],
    receipt: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    threshold = source.get("validation_threshold") or {}
    if not threshold:
        return "uncontracted", []
    if materialization != "fully_materialized":
        return "unverifiable", ["source_not_fully_materialized"]

    unsupported = sorted(key for key in threshold if key != "min_rows")
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
        age_hours = max((as_of - completed_at).total_seconds() / 3600.0, 0.0)

    if path_type in {"deferred_stub", "semantic_duplicate"}:
        status = "TERMINAL"
    elif not automatable:
        status = "NOT_APPLICABLE"
    elif materialization != "fully_materialized":
        status = "NEVER_MATERIALIZED"
    elif not receipt_valid or completed_at is None:
        status = "FRESHNESS_UNPROVEN"
    elif sla in (None, 0):
        status = "FRESH"
    elif age_hours is not None and age_hours <= float(sla):
        status = "FRESH"
    else:
        status = "STALE"

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
    }


def derive(
    *,
    root: Path,
    evidence_root: Path,
    receipts_dir: Path | None,
    scope_dir: Path,
    as_of: datetime,
    operator_corpus_id: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    evidence_root = evidence_root.resolve()
    scope_dir = scope_dir.resolve()
    sources, registry_paths = load_sources(root)
    registry_digest = source_ids_digest(sources)
    receipts = _load_receipts(receipts_dir)

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
        coverage_status, coverage_blockers = _coverage_state(
            source,
            materialization,
            outputs,
            receipt,
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
            receipt=receipt,
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
                "receipt_valid": bool(receipt is not None and not validate_receipt(receipt)),
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
        "verified_operator_corpus_mount" if operator_corpus_id else "checkout_or_operator_workspace"
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

    scope_reports = scope_dir / "reports"
    scope_reports.mkdir(parents=True, exist_ok=True)

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
        "automatable_ready": automatable_total,
        "automatable_not_ready": [],
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

    scope_identity = {
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
