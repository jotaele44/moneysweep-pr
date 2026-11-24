from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.operator_corpus_common import (
    expected_outputs,
    load_sources,
    safe_relative_path,
    sha256_file,
)
from tools.write_operator_evidence_receipt import build_receipt

SCHEMA_VERSION = "moneysweep.keyless_execution/v2"


def build_source_evidence(
    *,
    root: Path,
    source_id: str,
    step_outcome: str,
    scope_sha: str,
    implementation_sha: str,
    output_root: Path,
) -> dict[str, Any]:
    root = root.resolve()
    output_root = (
        output_root.resolve() if output_root.is_absolute() else (root / output_root).resolve()
    )
    sources, _ = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    if source_id not in source_by_id:
        raise ValueError(f"unknown source_id: {source_id}")
    source = source_by_id[source_id]

    expected_paths = expected_outputs(source)
    declared_files: list[Path] = []
    missing_expected: list[str] = []
    for expected in expected_paths:
        relative = safe_relative_path(expected)
        path = root / relative
        try:
            path.resolve().relative_to(root)
        except ValueError:
            missing_expected.append(expected)
            continue
        if expected.endswith("/"):
            files = (
                sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else []
            )
            if files:
                declared_files.extend(files)
            else:
                missing_expected.append(expected)
        elif path.is_file():
            declared_files.append(path)
        else:
            missing_expected.append(expected)

    unique_files: list[Path] = []
    seen: set[str] = set()
    for path in declared_files:
        relative = path.relative_to(root).as_posix()
        if relative not in seen:
            seen.add(relative)
            unique_files.append(path)

    out = output_root / source_id
    if out.exists():
        shutil.rmtree(out)
    evidence_dir = out / "operator_evidence"
    file_dir = out / "files"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    file_dir.mkdir(parents=True, exist_ok=True)

    standardized_receipt = None
    receipt_error = None
    execution_succeeded = step_outcome == "success"
    if unique_files and execution_succeeded:
        producer = str(source.get("producer_script") or "").strip()
        source_url = str(source.get("endpoint_url") or source.get("source_url") or "").strip()
        if not source_url:
            source_url = "repository://jotaele44/moneysweep-pr/" + (producer or source_id)
        try:
            standardized_receipt = build_receipt(
                root=root,
                source_id=source_id,
                outputs=[path.relative_to(root).as_posix() for path in unique_files],
                producer_sha=implementation_sha,
                producer=producer or None,
                source_url=source_url,
                completed_at=datetime.now(timezone.utc).isoformat(),
                coverage_contract_pass=False,
            )
        except Exception as exc:
            receipt_error = f"{type(exc).__name__}:{exc}"
        else:
            (evidence_dir / f"{source_id}.json").write_text(
                json.dumps(standardized_receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    elif unique_files:
        receipt_error = "execution_not_successful_no_acquisition_receipt"
    elif expected_paths:
        receipt_error = (
            "missing_expected_outputs_no_acquisition_receipt"
            if execution_succeeded
            else "execution_not_successful_no_outputs"
        )

    copied = []
    for path in unique_files:
        relative = path.relative_to(root)
        target = file_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )

    runner_summary = root / "data/staging/materialization_run_summary.json"
    runner = None
    runner_summary_error = None
    if runner_summary.exists():
        try:
            runner = json.loads(runner_summary.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            runner_summary_error = f"{type(exc).__name__}:{exc}"
    execution_receipt = {
        "schema_version": SCHEMA_VERSION,
        "source_id": source_id,
        "certification_scope_sha": scope_sha,
        "certification_implementation_sha": implementation_sha,
        "workflow_step_outcome": step_outcome,
        "execution_succeeded": execution_succeeded,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_outputs": expected_paths,
        "missing_expected_outputs": missing_expected,
        "declared_files": copied,
        "standardized_receipt_emitted": standardized_receipt is not None,
        "standardized_receipt_error": receipt_error,
        "coverage_contract_pass": False,
        "runner_summary": runner,
        "runner_summary_error": runner_summary_error,
    }
    (out / "execution_receipt.json").write_text(
        json.dumps(execution_receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return execution_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Build immutable keyless source evidence.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--step-outcome", required=True)
    parser.add_argument("--scope-sha", required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("certification_out"))
    args = parser.parse_args()
    receipt = build_source_evidence(
        root=args.root,
        source_id=args.source_id,
        step_outcome=args.step_outcome,
        scope_sha=args.scope_sha,
        implementation_sha=args.implementation_sha,
        output_root=args.output_root,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
