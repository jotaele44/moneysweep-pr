from __future__ import annotations

from pathlib import Path

import pytest

from tools.build_certification_blocker_graph import build

pytestmark = pytest.mark.unit


def _truth() -> dict:
    return {
        "registry": {
            "total_sources": 2,
            "required_sources": 1,
            "source_ids_sha256": "a" * 64,
        },
        "summary": {
            "required_fully_materialized": 0,
            "automatable_total": 2,
        },
        "sources": [
            {
                "source_id": "required_alpha",
                "required": True,
                "path_type": "api_producer",
                "materialization_status": "not_materialized",
                "coverage_status": "unverifiable",
            },
            {
                "source_id": "optional_beta",
                "required": False,
                "path_type": "api_adapter",
                "materialization_status": "fully_materialized",
                "coverage_status": "meets_contract",
            },
        ],
    }


def test_graph_separates_required_materialization_and_freshness_blockers(tmp_path: Path) -> None:
    freshness = [
        {"source_id": "required_alpha", "freshness_status": "NEVER_MATERIALIZED"},
        {"source_id": "optional_beta", "freshness_status": "FRESH"},
    ]
    graph = build(
        root=tmp_path,
        truth=_truth(),
        freshness_rows=freshness,
        equivalence_dir=None,
    )

    assert graph["summary"]["required_total"] == 1
    assert graph["summary"]["required_blocker_count"] == 1
    assert graph["required_source_blockers"][0]["source_id"] == "required_alpha"
    assert graph["summary"]["automatable_materialization_blocker_count"] == 1
    assert graph["summary"]["freshness_blocker_count"] == 1
    assert graph["release_policy"]["production_activation_authorized"] is False


def test_g0_g11_summary_requires_every_upstream_gate_pass(tmp_path: Path) -> None:
    gate_ids = [
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
    ]
    production = {"gates": [{"id": gate_id, "state": "PASS", "blockers": []} for gate_id in gate_ids]}
    graph = build(
        root=tmp_path,
        truth=_truth(),
        freshness_rows=[],
        equivalence_dir=None,
        production_report=production,
    )
    assert graph["summary"]["g0_g11_all_pass"] is True

    production["gates"][8]["state"] = "BLOCKED"
    graph = build(
        root=tmp_path,
        truth=_truth(),
        freshness_rows=[],
        equivalence_dir=None,
        production_report=production,
    )
    assert graph["summary"]["g0_g11_all_pass"] is False
