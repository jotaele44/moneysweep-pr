from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        expected_outputs,
        load_sources,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        expected_outputs,
        load_sources,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )

ASSEMBLY_SCHEMA_VERSION = "moneysweep.keyless_operator_workspace/v2"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return payload


def _safe_rel(value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("artifact path missing")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RuntimeError(f"unsafe artifact path: {value!r}")
    return Path(*[part for part in path.parts if part not in {"", "."}])


def _declared(path: str, expected: list[str]) -> bool:
    return any(path == item or (item.endswith("/") and path.startswith(item)) for item in expected)


def _expected_satisfied(expected_path: str, actual_paths: set[str]) -> bool:
    if expected_path.endswith("/"):
        return any(path.startswith(expected_path) for path in actual_paths)
    return expected_path in actual_paths


def _copy_verified(*, source: Path, target: Path, expected_sha: str, expected_bytes: int) -> None:
    if not source.is_file():
        raise RuntimeError(f"artifact file missing: {source}")
    actual_sha = sha256_file(source)
    actual_bytes = source.stat().st_size
    if actual_sha != expected_sha:
        raise RuntimeError(f"artifact sha256 mismatch: {source}")
    if actual_bytes != expected_bytes:
        raise RuntimeError(f"artifact byte-count mismatch: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if sha256_file(target) != expected_sha or target.stat().st_size != expected_bytes:
        raise RuntimeError(f"copied artifact failed revalidation: {target}")


def _receipt_binding_errors(
    *,
    receipt: dict[str, Any],
    source: dict[str, Any],
    registry_digest: str,
    execution_expected: list[str],
) -> list[str]:
    errors = list(validate_receipt(receipt))
    source_id = str(source["source_id"])
    if receipt.get("source_id") != source_id:
        errors.append("receipt_source_id_mismatch")

    registry = receipt.get("registry")
    registry = registry if isinstance(registry, dict) else {}
    if registry.get("source_ids_sha256") != registry_digest:
        errors.append("receipt_registry_digest_mismatch")
    if registry.get("source_definition_sha256") != source_definition_digest(source):
        errors.append("receipt_source_definition_digest_mismatch")

    acquisition = receipt.get("acquisition")
    acquisition = acquisition if isinstance(acquisition, dict) else {}
    registered_producer = str(source.get("producer_script") or "").strip()
    if acquisition.get("producer") != registered_producer:
        errors.append("receipt_producer_mismatch")

    expected = expected_outputs(source)
    if execution_expected != expected:
        errors.append("execution_expected_outputs_registry_mismatch")

    receipt_outputs = receipt.get("outputs")
    receipt_outputs = receipt_outputs if isinstance(receipt_outputs, list) else []
    actual_paths: set[str] = set()
    for item in receipt_outputs:
        if not isinstance(item, dict):
            continue
        raw = item.get("path")
        if not isinstance(raw, str):
            continue
        try:
            rel = _safe_rel(raw).as_posix()
        except RuntimeError:
            continue
        actual_paths.add(rel)
        if not _declared(rel, expected):
            errors.append(f"receipt_output_not_declared:{rel}")

    missing_expected = sorted(
        item for item in expected if not _expected_satisfied(item, actual_paths)
    )
    if missing_expected:
        errors.append("receipt_expected_outputs_incomplete:" + ",".join(missing_expected))
    return sorted(set(errors))


def assemble(
    *,
    artifacts_root: Path,
    workspace_root: Path,
    registry_root: Path = Path("."),
    expected_keyless_count: int | None = None,
) -> dict[str, Any]:
    artifacts_root = artifacts_root.resolve()
    workspace_root = workspace_root.resolve()
    registry_root = registry_root.resolve()
    if not artifacts_root.is_dir():
        raise RuntimeError(f"artifact root does not exist: {artifacts_root}")

    sources, _ = load_sources(registry_root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    registry_digest = source_ids_digest(sources)

    execution_paths = sorted(artifacts_root.rglob("execution_receipt.json"))
    if not execution_paths:
        raise RuntimeError(f"no keyless execution receipts found below {artifacts_root}")

    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    receipts_dir = workspace_root / "receipts"
    executions_dir = workspace_root / "execution_receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    executions_dir.mkdir(parents=True, exist_ok=True)

    seen_sources: set[str] = set()
    claimed_paths: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for execution_path in execution_paths:
        execution = _load_json(execution_path)
        source_id = str(execution.get("source_id", "")).strip()
        if not source_id:
            raise RuntimeError(f"execution receipt has no source_id: {execution_path}")
        if source_id in seen_sources:
            raise RuntimeError(f"duplicate keyless artifact bundle for source_id: {source_id}")
        seen_sources.add(source_id)

        source = source_by_id.get(source_id)
        if source is None:
            raise RuntimeError(f"unknown keyless source_id for current registry: {source_id}")

        bundle_root = execution_path.parent
        declared_files = execution.get("declared_files")
        if not isinstance(declared_files, list):
            raise RuntimeError(f"declared_files must be a list for {source_id}")
        execution_expected_raw = execution.get("expected_outputs")
        if not isinstance(execution_expected_raw, list) or any(
            not isinstance(item, str) for item in execution_expected_raw
        ):
            raise RuntimeError(f"expected_outputs must be a string list for {source_id}")
        execution_expected = [str(item) for item in execution_expected_raw]

        receipt_path = bundle_root / "operator_evidence" / f"{source_id}.json"
        standardized_claim = execution.get("standardized_receipt_emitted") is True
        receipt_valid = False
        receipt_errors: list[str] = []
        receipt: dict[str, Any] | None = None
        if receipt_path.is_file():
            receipt = _load_json(receipt_path)
            receipt_errors = _receipt_binding_errors(
                receipt=receipt,
                source=source,
                registry_digest=registry_digest,
                execution_expected=execution_expected,
            )
            receipt_valid = not receipt_errors
        elif standardized_claim:
            receipt_errors.append("claimed_standardized_receipt_missing")

        copied_paths: list[str] = []
        declared_path_set: set[str] = set()
        for item in declared_files:
            if not isinstance(item, dict):
                raise RuntimeError(f"invalid declared file entry for {source_id}")
            rel = _safe_rel(item.get("path")).as_posix()
            if rel in declared_path_set:
                raise RuntimeError(f"duplicate declared file for {source_id}: {rel}")
            declared_path_set.add(rel)
            expected_sha = item.get("sha256")
            expected_bytes = item.get("bytes")
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise RuntimeError(f"invalid sha256 for {source_id}:{rel}")
            if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
                raise RuntimeError(f"invalid byte count for {source_id}:{rel}")
            prior_source = claimed_paths.get(rel)
            if prior_source is not None:
                raise RuntimeError(
                    f"ambiguous cross-source output claim: {rel} claimed by {prior_source} and {source_id}"
                )
            claimed_paths[rel] = source_id

            artifact_file = bundle_root / "files" / rel
            if receipt_valid:
                assert receipt is not None
                receipt_outputs = {
                    str(output.get("path")): output
                    for output in receipt.get("outputs") or []
                    if isinstance(output, dict)
                }
                receipt_output = receipt_outputs.get(rel)
                if receipt_output is None:
                    raise RuntimeError(f"declared file absent from standardized receipt: {source_id}:{rel}")
                if receipt_output.get("sha256") != expected_sha or receipt_output.get("bytes") != expected_bytes:
                    raise RuntimeError(f"execution/receipt byte identity mismatch: {source_id}:{rel}")
                _copy_verified(
                    source=artifact_file,
                    target=workspace_root / rel,
                    expected_sha=expected_sha,
                    expected_bytes=expected_bytes,
                )
                copied_paths.append(rel)

        if receipt_valid:
            assert receipt is not None
            receipt_path_set = {
                str(output.get("path"))
                for output in receipt.get("outputs") or []
                if isinstance(output, dict) and isinstance(output.get("path"), str)
            }
            if receipt_path_set != declared_path_set:
                raise RuntimeError(f"execution/receipt output inventory mismatch: {source_id}")
            shutil.copy2(receipt_path, receipts_dir / f"{source_id}.json")
        else:
            blockers.append(f"{source_id}:standardized_receipt_invalid_or_missing")

        shutil.copy2(execution_path, executions_dir / f"{source_id}.json")
        runner = execution.get("runner_summary")
        runner = runner if isinstance(runner, dict) else {}
        ran = runner.get("ran")
        ran = ran if isinstance(ran, list) else []
        source_run = next(
            (item for item in ran if isinstance(item, dict) and item.get("source") == source_id),
            {},
        )
        status = str(source_run.get("status") or runner.get("status") or "UNKNOWN")
        source_rows = source_run.get("rows")
        positive = isinstance(source_rows, int) and not isinstance(source_rows, bool) and source_rows > 0
        if not positive:
            blockers.append(f"{source_id}:nonpositive_or_unproven_rows")
        if execution.get("missing_expected_outputs"):
            blockers.append(f"{source_id}:missing_expected_outputs")
        if execution.get("workflow_step_outcome") != "success":
            blockers.append(f"{source_id}:workflow_step_not_success")

        rows.append(
            {
                "source_id": source_id,
                "runner_status": status,
                "rows": source_rows,
                "positive_rows": positive,
                "workflow_step_outcome": execution.get("workflow_step_outcome"),
                "missing_expected_outputs": execution.get("missing_expected_outputs") or [],
                "standardized_receipt_emitted": standardized_claim,
                "standardized_receipt_valid": receipt_valid,
                "receipt_errors": sorted(set(receipt_errors)),
                "source_definition_sha256": source_definition_digest(source),
                "promoted_workspace_files": sorted(copied_paths),
            }
        )

    if expected_keyless_count is not None and len(seen_sources) != expected_keyless_count:
        raise RuntimeError(
            f"keyless artifact count mismatch: observed={len(seen_sources)} expected={expected_keyless_count}"
        )

    manifest = {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "registry": {
            "total_sources": len(sources),
            "source_ids_sha256": registry_digest,
        },
        "artifact_source_count": len(seen_sources),
        "expected_keyless_count": expected_keyless_count,
        "valid_receipt_count": sum(row["standardized_receipt_valid"] for row in rows),
        "positive_row_source_count": sum(row["positive_rows"] for row in rows),
        "workspace_output_count": len(claimed_paths),
        "authority_asserted": False,
        "policy": {
            "assembly_is_operator_authority": False,
            "job_success_is_materialization_credit": False,
            "zero_row_receipts_may_be_preserved": True,
            "source_completion_requires_truth_regeneration": True,
            "receipt_registry_binding_required": True,
            "receipt_source_definition_binding_required": True,
            "receipt_registered_producer_binding_required": True,
            "historical_receipt_inheritance_allowed": False,
        },
        "sources": sorted(rows, key=lambda item: item["source_id"]),
        "blockers": sorted(set(blockers)),
    }
    manifest_path = workspace_root / "assembly_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble per-source keyless CI artifacts into one non-authoritative operator workspace."
    )
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("build/keyless-operator-workspace"))
    parser.add_argument("--registry-root", type=Path, default=Path("."))
    parser.add_argument("--expected-keyless-count", type=int)
    args = parser.parse_args()

    manifest = assemble(
        artifacts_root=args.artifacts_root,
        workspace_root=args.workspace_root,
        registry_root=args.registry_root,
        expected_keyless_count=args.expected_keyless_count,
    )
    print(
        json.dumps(
            {
                "artifact_source_count": manifest["artifact_source_count"],
                "valid_receipt_count": manifest["valid_receipt_count"],
                "positive_row_source_count": manifest["positive_row_source_count"],
                "blocker_count": len(manifest["blockers"]),
                "authority_asserted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
