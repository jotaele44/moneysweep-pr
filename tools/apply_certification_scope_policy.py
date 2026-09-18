from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import canonical_json, sha256_bytes, sha256_file
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import canonical_json, sha256_bytes, sha256_file  # type: ignore[no-redef]

from scripts.build_source_recovery_matrix import PATH_TYPES

SCHEMA_VERSION = "moneysweep.certification_scope_policy/v1"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def apply(*, scope_dir: Path) -> dict[str, Any]:
    scope_dir = scope_dir.resolve()
    reports = scope_dir / "reports"
    truth_path = reports / "certification_truth.json"
    completeness_path = reports / "completeness_matrix.json"
    manifest_path = scope_dir / "scope_manifest.json"
    truth = _load(truth_path)
    completeness = _load(completeness_path)
    manifest = _load(manifest_path)

    source_results = truth.get("sources")
    if not isinstance(source_results, list):
        raise RuntimeError("certification truth sources list missing")

    excluded_ids: list[str] = []
    changed_ids: list[str] = []
    for row in source_results:
        if not isinstance(row, dict):
            continue
        path_type = str(row.get("path_type") or "")
        automatable = bool(PATH_TYPES.get(path_type, (False, ""))[0])
        if automatable:
            continue
        source_id = str(row.get("source_id") or "")
        excluded_ids.append(source_id)
        if row.get("coverage_status") != "uncontracted":
            row["coverage_status"] = "uncontracted"
            row["coverage_blockers"] = [f"excluded_by_path_type:{path_type or 'unknown'}"]
            changed_ids.append(source_id)

    coverage_counts = Counter(
        str(row.get("coverage_status") or "unknown")
        for row in source_results
        if isinstance(row, dict)
    )
    materiality_counts = Counter(
        str(row.get("materiality_label") or "unknown")
        for row in source_results
        if isinstance(row, dict)
    )
    truth_summary = truth.get("summary")
    if not isinstance(truth_summary, dict):
        raise RuntimeError("certification truth summary missing")
    truth_summary["coverage"] = dict(sorted(coverage_counts.items()))
    truth_summary["excluded_coverage_source_count"] = len(excluded_ids)

    completeness["by_coverage_status"] = dict(sorted(coverage_counts.items()))
    completeness["by_materiality_label"] = dict(sorted(materiality_counts.items()))
    completeness["source_results"] = [
        {
            "source_id": row.get("source_id"),
            "materialization_status": row.get("materialization_status"),
            "coverage_status": row.get("coverage_status"),
            "coverage_blockers": row.get("coverage_blockers") or [],
            "materiality_label": row.get("materiality_label"),
        }
        for row in source_results
        if isinstance(row, dict)
    ]
    completeness["scope_policy"] = {
        "schema_version": SCHEMA_VERSION,
        "nonautomatable_sources_are_outside_g6_contract_denominator": True,
        "excluded_source_count": len(excluded_ids),
        "excluded_source_ids": sorted(excluded_ids),
    }
    truth["scope_policy"] = completeness["scope_policy"]

    _write(truth_path, truth)
    _write(completeness_path, completeness)

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("scope manifest artifacts missing")
    for rel in ("reports/certification_truth.json", "reports/completeness_matrix.json"):
        path = scope_dir / rel
        artifacts[rel] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}

    identity = manifest.get("scope_identity")
    if not isinstance(identity, dict):
        raise RuntimeError("scope manifest identity missing")
    identity["truth_sha256"] = artifacts["reports/certification_truth.json"]["sha256"]
    identity["scope_policy_sha256"] = sha256_bytes(
        canonical_json(completeness["scope_policy"])
    )
    manifest["scope_id"] = sha256_bytes(canonical_json(identity))
    _write(manifest_path, manifest)

    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": manifest["scope_id"],
        "excluded_source_count": len(excluded_ids),
        "changed_source_count": len(changed_ids),
        "changed_source_ids": sorted(changed_ids),
        "coverage_status_counts": dict(sorted(coverage_counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the frozen certification denominator policy after truth derivation."
    )
    parser.add_argument(
        "--scope-dir",
        type=Path,
        default=Path("build/certification-scope"),
    )
    args = parser.parse_args()
    report = apply(scope_dir=args.scope_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
