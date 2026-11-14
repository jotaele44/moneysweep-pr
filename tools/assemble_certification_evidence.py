from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        csv_rows,
        load_sources,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        csv_rows,
        load_sources,
        safe_relative_path,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )

ASSEMBLY_SCHEMA_VERSION = "moneysweep.certification_evidence_assembly/v1"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON evidence must contain an object: {path}")
    return payload


def _copy_verified(source: Path, target: Path) -> tuple[bool, str]:
    digest = sha256_file(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file() or sha256_file(target) != digest:
            raise RuntimeError(f"conflicting artifact bytes for {target}")
        return False, digest
    shutil.copy2(source, target)
    if sha256_file(target) != digest:
        raise RuntimeError(f"post-copy hash mismatch for {target}")
    return True, digest


def _runner_state(execution: dict[str, Any], source_id: str) -> dict[str, Any]:
    summary = execution.get("runner_summary")
    rows = None
    status = None
    error = None
    if isinstance(summary, dict):
        for item in summary.get("ran") or []:
            if isinstance(item, dict) and item.get("source") == source_id:
                status = item.get("status")
                rows = item.get("rows")
                error = item.get("error")
                break
    return {
        "workflow_step_outcome": execution.get("workflow_step_outcome"),
        "runner_status": status,
        "runner_rows": rows,
        "runner_error": error,
        "missing_expected_outputs": execution.get("missing_expected_outputs") or [],
        "standardized_receipt_emitted": execution.get("standardized_receipt_emitted") is True,
        "standardized_receipt_error": execution.get("standardized_receipt_error"),
    }


def assemble(
    *,
    registry_root: Path,
    artifacts_root: Path,
    workspace_root: Path,
    receipts_dir: Path,
) -> dict[str, Any]:
    registry_root = registry_root.resolve()
    artifacts_root = artifacts_root.resolve()
    workspace_root = workspace_root.resolve()
    receipts_dir = receipts_dir.resolve()

    sources, registry_paths = load_sources(registry_root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    registry_digest = source_ids_digest(sources)

    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    if receipts_dir.exists():
        shutil.rmtree(receipts_dir)
    workspace_root.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    structural_errors: list[str] = []
    source_results: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    copied_paths: dict[str, str] = {}

    artifact_dirs = sorted(path for path in artifacts_root.iterdir() if path.is_dir())
    for artifact_dir in artifact_dirs:
        execution_path = artifact_dir / "execution_receipt.json"
        if not execution_path.is_file():
            continue
        try:
            execution = _load_json(execution_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
            structural_errors.append(
                f"{artifact_dir.name}:execution_receipt_unreadable:{type(exc).__name__}"
            )
            continue

        source_id = str(execution.get("source_id") or "").strip()
        if not source_id:
            structural_errors.append(f"{artifact_dir.name}:source_id_missing")
            continue
        if source_id in seen_source_ids:
            structural_errors.append(f"duplicate_source_artifact:{source_id}")
            continue
        seen_source_ids.add(source_id)
        source = source_by_id.get(source_id)
        if source is None:
            structural_errors.append(f"unknown_source_artifact:{source_id}")
            continue

        result: dict[str, Any] = {
            "source_id": source_id,
            "artifact": artifact_dir.name,
            **_runner_state(execution, source_id),
            "copied_files": [],
            "receipt_valid": False,
            "receipt_present": False,
            "receipt_validation_errors": [],
        }

        files_root = artifact_dir / "files"
        if files_root.is_dir():
            for source_file in sorted(path for path in files_root.rglob("*") if path.is_file()):
                rel = source_file.relative_to(files_root).as_posix()
                try:
                    safe_relative_path(rel)
                    copied, digest = _copy_verified(source_file, workspace_root / rel)
                except (OSError, ValueError, RuntimeError) as exc:
                    structural_errors.append(
                        f"{source_id}:file_copy:{rel}:{type(exc).__name__}:{exc}"
                    )
                    continue
                previous = copied_paths.get(rel)
                if previous is not None and previous != digest:
                    structural_errors.append(f"{source_id}:conflicting_output_claim:{rel}")
                copied_paths[rel] = digest
                result["copied_files"].append(
                    {
                        "path": rel,
                        "sha256": digest,
                        "bytes": source_file.stat().st_size,
                        "rows": csv_rows(source_file),
                        "new_copy": copied,
                    }
                )

        evidence_dir = artifact_dir / "operator_evidence"
        receipt_candidates = sorted(evidence_dir.glob("*.json")) if evidence_dir.is_dir() else []
        if len(receipt_candidates) > 1:
            structural_errors.append(f"{source_id}:multiple_operator_receipts")
        if receipt_candidates:
            receipt_path = receipt_candidates[0]
            result["receipt_present"] = True
            try:
                receipt = _load_json(receipt_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
                errors = [f"receipt_unreadable:{type(exc).__name__}"]
                receipt = {}
            else:
                errors = validate_receipt(receipt)
                if receipt.get("source_id") != source_id:
                    errors.append("receipt_source_id_mismatch")
                registry = receipt.get("registry")
                if not isinstance(registry, dict):
                    errors.append("receipt_registry_missing")
                else:
                    if registry.get("source_ids_sha256") != registry_digest:
                        errors.append("receipt_registry_digest_mismatch")
                    if registry.get("source_definition_sha256") != source_definition_digest(source):
                        errors.append("receipt_source_definition_digest_mismatch")

                for output in receipt.get("outputs") or []:
                    if not isinstance(output, dict):
                        continue
                    rel = str(output.get("path") or "")
                    try:
                        rel = safe_relative_path(rel).as_posix()
                    except ValueError:
                        errors.append("receipt_output_path_unsafe")
                        continue
                    mounted = workspace_root / rel
                    if not mounted.is_file():
                        errors.append(f"receipt_output_missing_from_assembly:{rel}")
                        continue
                    if sha256_file(mounted) != output.get("sha256"):
                        errors.append(f"receipt_output_sha256_mismatch:{rel}")
                    if mounted.stat().st_size != output.get("bytes"):
                        errors.append(f"receipt_output_bytes_mismatch:{rel}")
                    if csv_rows(mounted) != output.get("rows"):
                        errors.append(f"receipt_output_rows_mismatch:{rel}")

            result["receipt_validation_errors"] = sorted(set(errors))
            result["receipt_valid"] = not errors
            if errors:
                structural_errors.extend(
                    f"{source_id}:receipt:{item}" for item in sorted(set(errors))
                )
            else:
                target = receipts_dir / f"{source_id}.json"
                try:
                    _copy_verified(receipt_path, target)
                except (OSError, RuntimeError) as exc:
                    structural_errors.append(f"{source_id}:receipt_copy:{type(exc).__name__}:{exc}")

        if result["receipt_valid"]:
            validation = receipt.get("validation") or {}
            if validation.get("positive_rows") is True:
                terminal_state = "RECEIPTED_POSITIVE"
            else:
                terminal_state = "RECEIPTED_NONPOSITIVE"
        elif result["runner_status"] in {
            "ERROR",
            "IMPORT_ERROR",
            "NO_ENTRYPOINT",
            "NO_PRODUCER",
        }:
            terminal_state = "EXECUTION_FAILED"
        elif result["missing_expected_outputs"]:
            terminal_state = "OUTPUTS_MISSING"
        else:
            terminal_state = "NO_VALID_RECEIPT"
        result["terminal_state"] = terminal_state
        source_results.append(result)

    source_results.sort(key=lambda item: item["source_id"])
    states: dict[str, int] = {}
    for result in source_results:
        state = str(result["terminal_state"])
        states[state] = states.get(state, 0) + 1

    return {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "registry": {
            "total_sources": len(sources),
            "required_sources": sum(source.get("required") is True for source in sources),
            "source_ids_sha256": registry_digest,
            "registry_paths": registry_paths,
        },
        "artifact_directories_seen": len(artifact_dirs),
        "execution_receipts_seen": len(source_results),
        "valid_operator_receipts": sum(
            result["receipt_valid"] is True for result in source_results
        ),
        "assembled_file_count": len(copied_paths),
        "terminal_state_counts": dict(sorted(states.items())),
        "structural_integrity_pass": not structural_errors,
        "structural_errors": sorted(set(structural_errors)),
        "sources": source_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble per-source certification artifacts into one evidence workspace."
    )
    parser.add_argument("--registry-root", type=Path, default=Path("."))
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("build/certification-evidence"),
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=Path("build/certification-evidence-receipts"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/certification_evidence_assembly.json"),
    )
    args = parser.parse_args()

    report = assemble(
        registry_root=args.registry_root,
        artifacts_root=args.artifacts_root,
        workspace_root=args.workspace_root,
        receipts_dir=args.receipts_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "execution_receipts_seen": report["execution_receipts_seen"],
                "valid_operator_receipts": report["valid_operator_receipts"],
                "assembled_file_count": report["assembled_file_count"],
                "terminal_state_counts": report["terminal_state_counts"],
                "structural_integrity_pass": report["structural_integrity_pass"],
                "structural_error_count": len(report["structural_errors"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["structural_integrity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
