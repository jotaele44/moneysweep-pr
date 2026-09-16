from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.build_certification_blocker_graph import build_graph

pytestmark = pytest.mark.unit


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _scope(tmp_path: Path) -> Path:
    scope = tmp_path / "scope"
    reports = scope / "reports"
    reports.mkdir(parents=True)
    _write_csv(
        reports / "source_registry_status.csv",
        ["source_id", "required", "pipeline_status"],
        [
            {"source_id": "alpha", "required": True, "pipeline_status": "fully_materialized"},
            {"source_id": "beta", "required": True, "pipeline_status": "not_materialized"},
            {"source_id": "gamma", "required": False, "pipeline_status": "not_materialized"},
        ],
    )
    (reports / "materialization_readiness.json").write_text(
        json.dumps({"automatable_not_ready": ["beta", "gamma"]}), encoding="utf-8"
    )
    (reports / "completeness_matrix.json").write_text(
        json.dumps(
            {
                "source_results": [
                    {"source_id": "alpha", "coverage_status": "meets_contract"},
                    {"source_id": "beta", "coverage_status": "unverifiable"},
                    {"source_id": "gamma", "coverage_status": "uncontracted"},
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        reports / "source_freshness.csv",
        ["source_id", "enabled", "freshness_status"],
        [
            {"source_id": "alpha", "enabled": True, "freshness_status": "FRESH"},
            {"source_id": "beta", "enabled": True, "freshness_status": "STALE"},
            {"source_id": "gamma", "enabled": False, "freshness_status": "FRESHNESS_UNPROVEN"},
        ],
    )
    return scope


def _certificate() -> dict:
    ids = [
        "G3_REQUIRED_SOURCE_MATERIALIZATION",
        "G5_EXECUTION_COMPLETENESS",
        "G6_SOURCE_CONTRACTS",
        "G7_ENTITY_RESOLUTION",
        "G8_PROVENANCE_AND_LINEAGE",
        "G9_CANONICAL_MASTER_INVARIANTS",
        "G10_FRESHNESS",
        "G11_PRODUCTION_EXPORT_AND_FEDERATION",
        "G12_RELEASE_CERTIFICATION",
    ]
    return {
        "certification_state": "NON_PRODUCTION_DIAGNOSTIC",
        "production_eligible": False,
        "scope": {"registry_total_sources": 3},
        "gates": [
            {
                "id": gate_id,
                "state": "PASS" if gate_id in {"G7_ENTITY_RESOLUTION"} else "BLOCKED",
                "blockers": [] if gate_id == "G7_ENTITY_RESOLUTION" else ["fixture"],
            }
            for gate_id in ids
        ],
    }


def test_graph_derives_sources_and_arithmetic_from_truth(tmp_path: Path) -> None:
    graph = build_graph(certificate=_certificate(), scope_root=_scope(tmp_path))

    assert graph["nodes"]["G3_REQUIRED_SOURCE_MATERIALIZATION"]["blocking_sources"] == ["beta"]
    assert graph["nodes"]["G5_EXECUTION_COMPLETENESS"]["blocking_sources"] == ["beta", "gamma"]
    assert graph["nodes"]["G6_SOURCE_CONTRACTS"]["blocking_sources"] == ["beta"]
    assert graph["nodes"]["G10_FRESHNESS"]["blocking_sources"] == ["beta"]
    assert graph["blocking_sources"] == ["beta", "gamma"]
    assert graph["arithmetic"] == {
        "required_materialization_blockers": 1,
        "execution_blockers": 2,
        "coverage_blockers": 1,
        "freshness_blockers": 1,
        "unique_blocking_sources": 2,
        "source_edges": 5,
        "gate_edges": 14,
    }
    assert len(graph["logical_sha256"]) == 64


def test_g12_dependencies_are_exact_current_nonpass_upstream_gates(tmp_path: Path) -> None:
    graph = build_graph(certificate=_certificate(), scope_root=_scope(tmp_path))
    dependencies = graph["nodes"]["G12_RELEASE_CERTIFICATION"]["depends_on_gates"]

    assert "G7_ENTITY_RESOLUTION" not in dependencies
    assert "G8_PROVENANCE_AND_LINEAGE" in dependencies
    assert "G11_PRODUCTION_EXPORT_AND_FEDERATION" in dependencies
    assert "G12_RELEASE_CERTIFICATION" not in dependencies
