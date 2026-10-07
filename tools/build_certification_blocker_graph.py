#!/usr/bin/env python3
"""Build a deterministic certification blocker dependency graph.

The graph is derived from the production certification report plus the governed
G0-G12 dependency DAG.  It does not create certification evidence or promote
any gate.  Its purpose is execution planning: preserve all blockers, distinguish
dependency-blocked gates from active gates, and expose the narrowest actionable
frontier without collapsing downstream residue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


PASS = "PASS"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return payload


def _load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected YAML mapping: {path}")
    return payload


def _stable_blocker_id(gate_id: str, blocker: str) -> str:
    digest = hashlib.sha256(f"{gate_id}\0{blocker}".encode("utf-8")).hexdigest()[:16]
    return f"BLOCKER_{digest}"


def build_graph(
    report: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    report_gates = report.get("gates")
    config_gates = config.get("gates")
    if not isinstance(report_gates, list):
        raise RuntimeError("Certification report must contain gates[]")
    if not isinstance(config_gates, list):
        raise RuntimeError("Certification config must contain gates[]")

    report_by_id: dict[str, dict[str, Any]] = {}
    for gate in report_gates:
        if not isinstance(gate, dict):
            raise RuntimeError("Certification report gate must be an object")
        gate_id = str(gate.get("id") or "").strip()
        if not gate_id:
            raise RuntimeError("Certification report contains gate without id")
        if gate_id in report_by_id:
            raise RuntimeError(f"Duplicate report gate id: {gate_id}")
        report_by_id[gate_id] = gate

    config_by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for gate in config_gates:
        if not isinstance(gate, dict):
            raise RuntimeError("Certification config gate must be an object")
        gate_id = str(gate.get("id") or "").strip()
        if not gate_id:
            raise RuntimeError("Certification config contains gate without id")
        if gate_id in config_by_id:
            raise RuntimeError(f"Duplicate config gate id: {gate_id}")
        config_by_id[gate_id] = gate
        order.append(gate_id)

    if set(report_by_id) != set(config_by_id):
        missing_report = sorted(set(config_by_id) - set(report_by_id))
        unknown_report = sorted(set(report_by_id) - set(config_by_id))
        raise RuntimeError(
            "Gate denominator mismatch: "
            f"missing_report={missing_report}; unknown_report={unknown_report}"
        )

    gate_nodes: list[dict[str, Any]] = []
    blocker_nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    active_frontier: list[str] = []

    for gate_id in order:
        definition = config_by_id[gate_id]
        observed = report_by_id[gate_id]
        depends_on = [str(item) for item in (definition.get("depends_on") or [])]
        unknown_dependencies = sorted(set(depends_on) - set(config_by_id))
        if unknown_dependencies:
            raise RuntimeError(
                f"{gate_id} has unknown dependencies: {unknown_dependencies}"
            )

        for dependency in depends_on:
            edges.append(
                {
                    "from": dependency,
                    "to": gate_id,
                    "kind": "gate_dependency",
                }
            )

        state = str(observed.get("state") or "UNKNOWN")
        dependency_states = {
            dependency: str(report_by_id[dependency].get("state") or "UNKNOWN")
            for dependency in depends_on
        }
        dependency_blockers = sorted(
            dependency
            for dependency, dependency_state in dependency_states.items()
            if dependency_state != PASS
        )

        raw_blockers = observed.get("blockers") or []
        if not isinstance(raw_blockers, list):
            raise RuntimeError(f"{gate_id}.blockers must be a list")
        blockers = sorted({str(item) for item in raw_blockers if str(item).strip()})

        direct_blocker_ids: list[str] = []
        for blocker in blockers:
            blocker_id = _stable_blocker_id(gate_id, blocker)
            direct_blocker_ids.append(blocker_id)
            blocker_nodes.append(
                {
                    "id": blocker_id,
                    "gate_id": gate_id,
                    "value": blocker,
                }
            )
            edges.append(
                {
                    "from": blocker_id,
                    "to": gate_id,
                    "kind": "direct_blocker",
                }
            )

        actionable = state != PASS and not dependency_blockers
        if actionable:
            active_frontier.append(gate_id)

        gate_nodes.append(
            {
                "id": gate_id,
                "state": state,
                "blocking": definition.get("blocking") is True,
                "depends_on": depends_on,
                "dependency_states": dependency_states,
                "dependency_blockers": dependency_blockers,
                "direct_blockers": blockers,
                "direct_blocker_ids": direct_blocker_ids,
                "actionable": actionable,
            }
        )

    nonpass = [node["id"] for node in gate_nodes if node["state"] != PASS]
    blocked_by_dependency = [
        node["id"]
        for node in gate_nodes
        if node["state"] != PASS and node["dependency_blockers"]
    ]

    return {
        "schema_version": "moneysweep.certification_blocker_graph/v1",
        "certification_state": report.get("certification_state"),
        "production_eligible": report.get("production_eligible") is True,
        "scope": report.get("scope"),
        "gate_order": order,
        "summary": {
            "gate_total": len(gate_nodes),
            "nonpass_gate_total": len(nonpass),
            "direct_blocker_total": len(blocker_nodes),
            "active_frontier": active_frontier,
            "dependency_blocked_gates": blocked_by_dependency,
        },
        "gates": gate_nodes,
        "blockers": sorted(blocker_nodes, key=lambda item: item["id"]),
        "edges": sorted(
            edges,
            key=lambda item: (item["kind"], item["from"], item["to"]),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic G0-G12 blocker dependency graph."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/production_certification.json"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("registries/production_certification.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/certification_blocker_graph.json"),
    )
    args = parser.parse_args()

    graph = build_graph(_load_json(args.report), _load_config(args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "active_frontier": graph["summary"]["active_frontier"],
                "nonpass_gate_total": graph["summary"]["nonpass_gate_total"],
                "direct_blocker_total": graph["summary"]["direct_blocker_total"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
