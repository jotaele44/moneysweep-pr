"""Tests for R2 entity universe and collapse audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.validation.entity_universe_audit import run_audit


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_r2_audit_blocks_phase_7_8_for_18_entity_universe(tmp_path: Path):
    # Baseline summaries reflecting constrained universe.
    _write_json(
        tmp_path / "data/reports/pr_report_summary.json",
        {
            "data_layers": 3,
            "awards": {"unique_entities": 18},
            "power_network": {"total_ranked": 18, "bond_actors_count": 0},
        },
    )
    _write_json(
        tmp_path / "data/staging/processed/dominance_summary.json",
        {"total_rows": 4503, "unique_vendors": 18},
    )
    _write_json(
        tmp_path / "data/staging/processed/pr_all_awards_summary.json",
        {"total_rows": 4503, "unique_recipients": 18},
    )
    _write_json(
        tmp_path / "data/staging/processed/pr_power_network_summary.json",
        {
            "top_entities": [
                {"name": "Acme Corp", "awards_total": 2_000_000, "sources": ["awards"]},
                {"name": "Beta LLC", "awards_total": 1_500_000, "sources": ["awards"]},
            ]
        },
    )
    _write_json(
        tmp_path / "data/staging/processed/pr_prime_sub_summary.json",
        {"prime_count": 18, "sub_count": 18, "pair_count": 268},
    )
    _write_json(
        tmp_path / "data/staging/processed/graph/network_summary.json", {"vendor_nodes": 18}
    )

    _write_csv(
        tmp_path / "data/staging/processed/graph/top_nodes.csv",
        [
            {"node": "Acme Corp", "node_type": "vendor"},
            {"node": "Beta LLC", "node_type": "vendor"},
            {"node": "Department of Energy", "node_type": "agency"},
        ],
        fieldnames=["node", "node_type"],
    )
    _write_csv(
        tmp_path / "data/staging/processed/graph/entity_edges.csv",
        [
            {"source_entity": "Acme Corp", "contract_count": 200},
            {"source_entity": "Beta LLC", "contract_count": 180},
        ],
        fieldnames=["source_entity", "contract_count"],
    )
    _write_json(
        tmp_path / "data/exports/rebuild_status.json",
        {"phase_7_8_blocked": True, "r1_gate_passed": False},
    )

    result = run_audit(tmp_path)

    assert result["r2_gate_passed"] is False
    assert result["phase_7_8_blocked"] is True
    assert result["unique_normalized_entity_count"] == 2
    assert result["parent_uei_coverage"] == 0.0
    assert result["high_value_overcollapse_suspect_count"] >= 1
    assert result["inferred_18_entity_collapse_stage"] == "collapse_before_or_at_master_table"

    assert (tmp_path / "data/exports/entity_universe_audit.csv").exists()
    assert (tmp_path / "data/exports/entity_collapse_diagnostics.csv").exists()
    assert (tmp_path / "data/review_queue/suspect_entity_collapses.csv").exists()
    assert (tmp_path / "data/review_queue/high_value_unresolved_entities.csv").exists()


def test_r2_audit_can_pass_when_minimum_thresholds_are_met(tmp_path: Path):
    # Build a synthetic healthy entity master with >100 entities and parent UEIs.
    rows = []
    for i in range(120):
        rows.append(
            {
                "canonical_name": f"Entity {i} LLC",
                "entity_key": f"ENTITY {i}",
                "parent_uei": f"PARENT-{i:04d}",
                "parent_name": f"Parent Entity {i}",
                "award_count": 3,
                "total_obligated": 50000 + i,
                "source_datasets": "contracts|grants",
            }
        )

    _write_csv(
        tmp_path / "data/staging/processed/entity_master.csv",
        rows,
        fieldnames=[
            "canonical_name",
            "entity_key",
            "parent_uei",
            "parent_name",
            "award_count",
            "total_obligated",
            "source_datasets",
        ],
    )
    _write_json(
        tmp_path / "data/staging/processed/dominance_summary.json",
        {"total_rows": 2000, "unique_vendors": 120},
    )
    _write_json(
        tmp_path / "data/staging/processed/pr_all_awards_summary.json",
        {"total_rows": 2000, "unique_recipients": 120},
    )
    _write_json(
        tmp_path / "data/staging/processed/graph/network_summary.json", {"vendor_nodes": 120}
    )
    _write_json(
        tmp_path / "data/staging/processed/pr_power_network_summary.json", {"top_entities": []}
    )
    _write_json(
        tmp_path / "data/staging/processed/pr_prime_sub_summary.json",
        {"prime_count": 120, "sub_count": 100, "pair_count": 200},
    )

    top_nodes = [{"node": f"Entity {i} LLC", "node_type": "vendor"} for i in range(120)]
    _write_csv(
        tmp_path / "data/staging/processed/graph/top_nodes.csv",
        top_nodes,
        fieldnames=["node", "node_type"],
    )
    _write_json(
        tmp_path / "data/exports/rebuild_status.json",
        {"phase_7_8_blocked": False, "r1_gate_passed": True},
    )

    result = run_audit(tmp_path)
    assert result["r2_gate_passed"] is True
    assert result["phase_7_8_blocked"] is False
    assert result["unique_normalized_entity_count"] == 120
    assert result["parent_uei_coverage"] > 0
    assert result["high_value_overcollapse_suspect_count"] == 0
    assert result["high_value_unresolved_count"] == 0
