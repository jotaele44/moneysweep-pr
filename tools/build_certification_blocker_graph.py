from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.verify_source_equivalence import verify as verify_equivalence
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from verify_source_equivalence import verify as verify_equivalence  # type: ignore[no-redef]

SCHEMA_VERSION = "moneysweep.certification_blocker_graph/v1"

GATE_DEPENDENCIES = {
    "G0_SCOPE_FREEZE": [],
    "G1_CONTROL_PLANE_RECONCILIATION": ["G0_SCOPE_FREEZE"],
    "G2_STRICT_PREFLIGHT": ["G1_CONTROL_PLANE_RECONCILIATION"],
    "G3_REQUIRED_SOURCE_MATERIALIZATION": ["G2_STRICT_PREFLIGHT"],
    "G4_FULL_SOURCE_CLASSIFICATION": ["G1_CONTROL_PLANE_RECONCILIATION"],
    "G5_AUTOMATABLE_EXECUTION": [
        "G3_REQUIRED_SOURCE_MATERIALIZATION",
        "G4_FULL_SOURCE_CLASSIFICATION",
    ],
    "G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS": ["G5_AUTOMATABLE_EXECUTION"],
    "G7_ENTITY_RESOLUTION": ["G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS"],
    "G8_PROVENANCE_AND_LINEAGE": ["G7_ENTITY_RESOLUTION"],
    "G9_CANONICAL_MASTER_INVARIANTS": ["G8_PROVENANCE_AND_LINEAGE"],
    "G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS": ["G9_CANONICAL_MASTER_INVARIANTS"],
    "G11_PRODUCTION_EXPORT_AND_FEDERATION": [
        "G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS"
    ],
    "G12_RELEASE_CERTIFICATION": [
        "G0_SCOPE_FREEZE",
        "G1_CONTROL_PLANE_RECONCILIATION",
        "G2_STRICT_PREFLIGHT",
        "G3_REQUIRED_SOURCE_MATERIALIZATION",
        "G4_FULL_SOURCE_CLASSIFICATION",
        "G5_AUTOMATABLE_EXECUTION",
        "G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS",
        "G7_ENTITY_RESOLUTION",
        "G8_PROVENANCE_AND_LINEAGE",
        "G9_CANONICAL_MASTER_INVARIANTS",
        "G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS",
        "G11_PRODUCTION_EXPORT_AND_FEDERATION",
    ],
}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return payload


def _equivalence_reports(root: Path, equivalence_dir: Path | None) -> list[dict[str, Any]]:
    if equivalence_dir is None or not equivalence_dir.is_dir():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(equivalence_dir.glob("*.json")):
        claim = _json(path)
        report = verify_equivalence(root=root, claim=claim)
        reports.append(
            {
                "claim_path": path.as_posix(),
                **report,
            }
        )
    return reports


def build(
    *,
    root: Path,
    truth: dict[str, Any],
    equivalence_dir: Path | None = None,
    production_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    sources = truth.get("sources")
    if not isinstance(sources, list):
        raise RuntimeError("certification truth has no sources list")

    required_blockers: list[dict[str, Any]] = []
    automatable_blockers: list[dict[str, Any]] = []
    coverage_blockers: list[dict[str, Any]] = []
    freshness_blockers: list[dict[str, Any]] = []
    source_nodes: list[dict[str, Any]] = []

    freshness_by_id: dict[str, Any] = {}
    for row in truth.get("freshness") or []:
        if isinstance(row, dict) and row.get("source_id"):
            freshness_by_id[str(row["source_id"])] = row

    automatable_types = {"api_adapter", "api_producer"}
    for raw in sources:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id", ""))
        materialization = str(raw.get("materialization_status", ""))
        path_type = str(raw.get("path_type", ""))
        required = raw.get("required") is True
        coverage = str(raw.get("coverage_status", ""))
        freshness = freshness_by_id.get(source_id, {})
        freshness_state = freshness.get("freshness_status")

        blockers: list[str] = []
        if materialization != "fully_materialized":
            blockers.append(f"materialization:{materialization or 'unknown'}")
        if coverage not in {"meets_contract", "uncontracted"}:
            blockers.append(f"coverage:{coverage or 'unknown'}")
        if path_type in automatable_types and freshness_state not in {"FRESH", "TERMINAL"}:
            blockers.append(f"freshness:{freshness_state or 'unknown'}")

        node = {
            "source_id": source_id,
            "required": required,
            "path_type": path_type,
            "materialization_status": materialization,
            "coverage_status": coverage,
            "freshness_status": freshness_state,
            "blockers": blockers,
        }
        source_nodes.append(node)
        if required and materialization != "fully_materialized":
            required_blockers.append(node)
        if path_type in automatable_types and materialization != "fully_materialized":
            automatable_blockers.append(node)
        if path_type in automatable_types and coverage != "meets_contract":
            coverage_blockers.append(node)
        if path_type in automatable_types and freshness_state != "FRESH":
            freshness_blockers.append(node)

    equivalence = _equivalence_reports(root, equivalence_dir)
    equivalence_blockers = [
        {
            "source_id": report["source_id"],
            "decision": report["decision"],
            "blockers": report["blockers"],
            "claim_path": report["claim_path"],
        }
        for report in equivalence
        if not report["certified_equivalent"]
    ]

    gate_states: dict[str, Any] = {}
    if production_report:
        for gate in production_report.get("gates") or []:
            if isinstance(gate, dict) and gate.get("id"):
                gate_states[str(gate["id"])] = {
                    "state": gate.get("state"),
                    "blockers": gate.get("blockers") or [],
                }

    gate_nodes = []
    for gate_id, dependencies in GATE_DEPENDENCIES.items():
        gate_nodes.append(
            {
                "id": gate_id,
                "depends_on": dependencies,
                **gate_states.get(gate_id, {"state": "NOT_EVALUATED", "blockers": []}),
            }
        )

    registry = truth.get("registry") if isinstance(truth.get("registry"), dict) else {}
    summary = truth.get("summary") if isinstance(truth.get("summary"), dict) else {}
    required_total = int(registry.get("required_sources") or 0)
    required_full = int(summary.get("required_fully_materialized") or 0)
    graph = {
        "schema_version": SCHEMA_VERSION,
        "registry": registry,
        "summary": {
            "required_total": required_total,
            "required_fully_materialized": required_full,
            "required_blocker_count": len(required_blockers),
            "automatable_total": int(summary.get("automatable_total") or 0),
            "automatable_materialization_blocker_count": len(automatable_blockers),
            "coverage_blocker_count": len(coverage_blockers),
            "freshness_blocker_count": len(freshness_blockers),
            "equivalence_blocker_count": len(equivalence_blockers),
            "g0_g11_all_pass": all(
                gate_states.get(f"G{number}_" + next(
                    (key.split("_", 1)[1] for key in GATE_DEPENDENCIES if key.startswith(f"G{number}_")),
                    "",
                ), {}).get("state") == "PASS"
                for number in range(12)
            ) if production_report else False,
        },
        "required_source_blockers": required_blockers,
        "automatable_materialization_blockers": automatable_blockers,
        "coverage_blockers": coverage_blockers,
        "freshness_blockers": freshness_blockers,
        "equivalence_reports": equivalence,
        "equivalence_blockers": equivalence_blockers,
        "sources": sorted(source_nodes, key=lambda item: item["source_id"]),
        "gates": gate_nodes,
        "release_policy": {
            "production_activation_authorized": False,
            "g12_may_self_authorize": False,
            "certified_requires_g0_g11_pass_and_explicit_activation": True,
        },
    }
    return graph


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the machine-readable MAX certification blocker graph."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("reports/certification_truth.json"),
    )
    parser.add_argument(
        "--equivalence-dir",
        type=Path,
        default=Path("registries/source_equivalence_claims"),
    )
    parser.add_argument("--production-report", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/certification_blocker_graph.json"),
    )
    args = parser.parse_args()
    truth = _json(args.truth)
    production = _json(args.production_report) if args.production_report else None
    graph = build(
        root=args.root,
        truth=truth,
        equivalence_dir=args.equivalence_dir,
        production_report=production,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(graph["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
