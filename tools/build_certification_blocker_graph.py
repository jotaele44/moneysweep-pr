from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

PASS = "PASS"


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _logical_sha256(payload: object) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(data).hexdigest()


def _truth_inputs(
    scope_root: Path,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, str]], dict[str, Any]]:
    reports = scope_root / "reports"
    return (
        _csv(reports / "source_registry_status.csv"),
        _json(reports / "materialization_readiness.json"),
        _json(reports / "completeness_matrix.json"),
        _csv(reports / "source_freshness.csv"),
        _json(reports / "certification_truth.json"),
    )


def build_graph(*, certificate: dict[str, Any], scope_root: Path) -> dict[str, Any]:
    status_rows, readiness, completeness, freshness_rows, truth = _truth_inputs(scope_root)
    gates = {
        str(gate.get("id")): gate
        for gate in certificate.get("gates", [])
        if isinstance(gate, dict) and gate.get("id")
    }

    required_materialization = sorted(
        row["source_id"]
        for row in status_rows
        if row.get("required", "").strip().lower() == "true"
        and row.get("pipeline_status") != "fully_materialized"
    )
    execution = sorted(set(readiness.get("automatable_not_ready") or []))

    truth_sources = {
        str(row.get("source_id")): row
        for row in truth.get("sources", [])
        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
    }
    automatable = sorted(
        source_id for source_id, row in truth_sources.items() if row.get("automatable") is True
    )
    coverage = sorted(
        source_id
        for source_id in automatable
        if truth_sources[source_id].get("coverage_status") != "meets_contract"
    )

    freshness = sorted(
        row["source_id"]
        for row in freshness_rows
        if row.get("enabled", "").strip().lower() == "true"
        and row.get("freshness_status") not in {"FRESH", "FRESHNESS_NOT_APPLICABLE"}
    )

    source_blockers = {
        "G3_REQUIRED_SOURCE_MATERIALIZATION": required_materialization,
        "G5_AUTOMATABLE_EXECUTION": execution,
        "G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS": coverage,
        "G10_FRESHNESS": freshness,
    }
    gate_dependencies = {
        "G3_REQUIRED_SOURCE_MATERIALIZATION": [],
        "G5_AUTOMATABLE_EXECUTION": [],
        "G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS": [],
        "G7_ENTITY_RESOLUTION": [],
        "G8_PROVENANCE_AND_LINEAGE": [
            "G3_REQUIRED_SOURCE_MATERIALIZATION",
            "G5_AUTOMATABLE_EXECUTION",
            "G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS",
            "G10_FRESHNESS",
        ],
        "G9_CANONICAL_MASTER_INVARIANTS": ["G7_ENTITY_RESOLUTION", "G8_PROVENANCE_AND_LINEAGE"],
        "G10_FRESHNESS": [],
        "G11_PRODUCTION_EXPORT_AND_FEDERATION": ["G9_CANONICAL_MASTER_INVARIANTS"],
        "G12_RELEASE_CERTIFICATION": sorted(
            gate_id
            for gate_id, gate in gates.items()
            if gate_id != "G12_RELEASE_CERTIFICATION" and gate.get("state") != PASS
        ),
    }

    graph_nodes: dict[str, Any] = {}
    for gate_id, gate in sorted(gates.items()):
        graph_nodes[gate_id] = {
            "state": gate.get("state"),
            "blockers": list(gate.get("blockers") or []),
            "depends_on_gates": gate_dependencies.get(gate_id, []),
            "blocking_sources": source_blockers.get(gate_id, []),
        }

    unresolved_sources = sorted(
        set(required_materialization) | set(execution) | set(coverage) | set(freshness)
    )
    source_edges = [
        {"source_id": source_id, "blocks_gate": gate_id}
        for gate_id, source_ids in sorted(source_blockers.items())
        for source_id in source_ids
    ]
    gate_edges = [
        {"from_gate": dependency, "to_gate": gate_id}
        for gate_id, dependencies in sorted(gate_dependencies.items())
        for dependency in dependencies
    ]

    arithmetic = {
        "required_materialization_blockers": len(required_materialization),
        "execution_blockers": len(execution),
        "coverage_blockers": len(coverage),
        "freshness_blockers": len(freshness),
        "unique_blocking_sources": len(unresolved_sources),
        "source_edges": len(source_edges),
        "gate_edges": len(gate_edges),
        "automatable_sources": len(automatable),
    }
    payload = {
        "schema_version": "moneysweep.certification_blocker_graph/v2",
        "certification_state": certificate.get("certification_state"),
        "production_eligible": certificate.get("production_eligible"),
        "scope": certificate.get("scope"),
        "nodes": graph_nodes,
        "source_edges": source_edges,
        "gate_edges": gate_edges,
        "blocking_sources": unresolved_sources,
        "arithmetic": arithmetic,
        "policy": {
            "generated_from_frozen_truth": True,
            "hand_edited_status_allowed": False,
            "source_blocker_deduplication_changes_gate_counts": False,
            "missing_or_nonpass_gate_fails_closed": True,
            "g6_automatable_requires_meets_contract": True,
        },
    }
    payload["logical_sha256"] = _logical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the MoneySweep certification blocker DAG.")
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--scope-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    certificate = _json(args.certificate)
    graph = build_graph(certificate=certificate, scope_root=args.scope_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "arithmetic": graph["arithmetic"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
