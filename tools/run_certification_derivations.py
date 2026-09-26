from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moneysweep.runtime.source_registry import load_source_registry
from moneysweep.update_controller.policy import REQUIRED_DAG
from scripts.config import setup_logging
from scripts.run_automatable_sources import (
    _bind_legacy_config_to_workspace,
    run_one,
)
from tools.derive_certification_truth import evaluate_output
from tools.operator_corpus_common import expected_outputs
from tools.write_operator_evidence_receipt import build_receipt

DERIVATION_SCHEMA_VERSION = "moneysweep.certification_derivations/v1"

# Certification-only dependency edges that are intentionally absent from the
# normal source-update DAG. A terminal semantic duplicate may still need a
# concrete registered output for G3, so it is derived only after its sibling
# evidence is usable.
CERTIFICATION_EXTRA_DAG: dict[str, list[str]] = {
    "fsrs_subawards": ["usaspending_subawards"],
}


def _combined_dag() -> dict[str, list[str]]:
    dag = {source_id: list(parents) for source_id, parents in REQUIRED_DAG.items()}
    for source_id, parents in CERTIFICATION_EXTRA_DAG.items():
        dag[source_id] = list(parents)
    return dag


def _topological_order(dag: dict[str, list[str]]) -> list[str]:
    nodes = set(dag)
    for parents in dag.values():
        nodes.update(parents)

    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise RuntimeError(f"derivation dependency cycle detected at {node}")
        visiting.add(node)
        for parent in sorted(dag.get(node, [])):
            visit(parent)
        visiting.remove(node)
        visited.add(node)
        if node in dag:
            order.append(node)

    for node in sorted(dag):
        visit(node)
    return order


def _source_materialization(
    *,
    workspace: Path,
    source: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    outputs = [
        evaluate_output(
            evidence_root=workspace,
            source=source,
            output_path=rel,
        )
        for rel in expected_outputs(source)
    ]
    if not outputs:
        return "no_outputs_declared", outputs
    usable = sum(item["usable"] for item in outputs)
    if usable == len(outputs):
        return "fully_materialized", outputs
    if usable:
        return "partially_materialized", outputs
    return "not_materialized", outputs


def _present_output_paths(
    *,
    workspace: Path,
    source: dict[str, Any],
) -> list[str]:
    paths: list[str] = []
    for expected in expected_outputs(source):
        path = workspace / expected
        if expected.endswith("/"):
            if path.is_dir():
                paths.extend(
                    item.relative_to(workspace).as_posix()
                    for item in sorted(path.rglob("*"))
                    if item.is_file()
                )
        elif path.is_file():
            paths.append(Path(expected).as_posix())
    return sorted(set(paths))


def execute(
    *,
    registry_root: Path,
    workspace: Path,
    receipts_dir: Path,
    producer_sha: str,
) -> dict[str, Any]:
    registry_root = registry_root.resolve()
    workspace = workspace.resolve()
    receipts_dir = receipts_dir.resolve()
    receipts_dir.mkdir(parents=True, exist_ok=True)

    sources = load_source_registry(registry_root).get("sources", [])
    source_by_id = {
        str(source["source_id"]): source
        for source in sources
        if source.get("source_id")
    }
    dag = _combined_dag()
    order = _topological_order(dag)
    logger = setup_logging("run_certification_derivations")

    # Producers with legacy module-level paths must write into the assembled
    # workspace, while registry identity remains bound to registry_root.
    _bind_legacy_config_to_workspace(workspace)

    results: list[dict[str, Any]] = []
    for source_id in order:
        source = source_by_id.get(source_id)
        if source is None:
            results.append(
                {
                    "source_id": source_id,
                    "state": "SOURCE_NOT_REGISTERED",
                    "dependencies": dag[source_id],
                }
            )
            continue

        before, before_outputs = _source_materialization(
            workspace=workspace,
            source=source,
        )
        if before == "fully_materialized":
            results.append(
                {
                    "source_id": source_id,
                    "state": "ALREADY_MATERIALIZED",
                    "dependencies": dag[source_id],
                    "before": before,
                    "after": before,
                    "outputs": before_outputs,
                }
            )
            continue

        dependency_states: dict[str, str] = {}
        for dependency_id in dag[source_id]:
            dependency = source_by_id.get(dependency_id)
            if dependency is None:
                dependency_states[dependency_id] = "source_not_registered"
                continue
            dependency_state, _ = _source_materialization(
                workspace=workspace,
                source=dependency,
            )
            dependency_states[dependency_id] = dependency_state

        blockers = sorted(
            dependency_id
            for dependency_id, state in dependency_states.items()
            if state != "fully_materialized"
        )
        if blockers:
            results.append(
                {
                    "source_id": source_id,
                    "state": "BLOCKED_DEPENDENCIES",
                    "dependencies": dag[source_id],
                    "dependency_states": dependency_states,
                    "blocking_dependencies": blockers,
                    "before": before,
                    "after": before,
                    "outputs": before_outputs,
                }
            )
            continue

        runner_result = run_one(workspace, source, logger)
        after, after_outputs = _source_materialization(
            workspace=workspace,
            source=source,
        )
        output_paths = _present_output_paths(
            workspace=workspace,
            source=source,
        )

        receipt_path = None
        receipt_error = None
        if output_paths:
            source_url = str(
                source.get("endpoint_url")
                or source.get("source_url")
                or ""
            ).strip()
            if not source_url:
                source_url = (
                    "repository://jotaele44/moneysweep-pr/"
                    + str(source.get("producer_script") or source_id)
                )
            try:
                receipt = build_receipt(
                    root=workspace,
                    registry_root=registry_root,
                    source_id=source_id,
                    outputs=output_paths,
                    producer_sha=producer_sha,
                    producer=str(source.get("producer_script") or "").strip() or None,
                    source_url=source_url,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    coverage_contract_pass=False,
                )
            except Exception as exc:  # noqa: BLE001 - evidence report captures failure
                receipt_error = f"{type(exc).__name__}:{exc}"
            else:
                receipt_path = receipts_dir / f"{source_id}.json"
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

        results.append(
            {
                "source_id": source_id,
                "state": (
                    "DERIVED_FULLY_MATERIALIZED"
                    if after == "fully_materialized"
                    else "DERIVATION_INCOMPLETE"
                ),
                "dependencies": dag[source_id],
                "dependency_states": dependency_states,
                "before": before,
                "after": after,
                "runner_result": runner_result,
                "outputs": after_outputs,
                "receipt_path": (
                    receipt_path.as_posix() if receipt_path is not None else None
                ),
                "receipt_error": receipt_error,
            }
        )

    counts: dict[str, int] = {}
    for result in results:
        state = str(result["state"])
        counts[state] = counts.get(state, 0) + 1

    return {
        "schema_version": DERIVATION_SCHEMA_VERSION,
        "registry_root": str(registry_root),
        "workspace": str(workspace),
        "order": order,
        "state_counts": dict(sorted(counts.items())),
        "sources": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run dependency-bearing certification sources against assembled evidence."
    )
    parser.add_argument("--registry-root", type=Path, default=Path("."))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/certification_derivations.json"),
    )
    args = parser.parse_args()

    report = execute(
        registry_root=args.registry_root,
        workspace=args.workspace,
        receipts_dir=args.receipts_dir,
        producer_sha=args.producer_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "state_counts": report["state_counts"],
                "order": report["order"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
