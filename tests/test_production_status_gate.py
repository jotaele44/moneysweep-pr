"""Tests for R0 production status gate."""

from __future__ import annotations

import json
from pathlib import Path

from contract_sweeper.validation.production_status import (
    STATUS_NON_PRODUCTION,
    STATUS_PARTIAL,
    STATUS_VALIDATED,
    evaluate_production_status,
    run_gate,
)


def _metrics(**overrides):
    base = {
        "data_layers_populated": 9,
        "unique_entities": 150,
        "bond_actor_count": 3,
        "parent_uei_coverage": 0.95,
        "fixture_or_synthetic_data_detected": False,
        "fixture_or_synthetic_reasons": [],
    }
    base.update(overrides)
    return base


def test_status_non_production_when_data_layers_below_minimum():
    status, blockers = evaluate_production_status(_metrics(data_layers_populated=7))
    assert status == STATUS_NON_PRODUCTION
    assert any(b["metric"] == "data_layers_populated" for b in blockers)


def test_status_non_production_when_unique_entities_below_minimum():
    status, blockers = evaluate_production_status(_metrics(unique_entities=25))
    assert status == STATUS_NON_PRODUCTION
    assert any(b["metric"] == "unique_entities" for b in blockers)


def test_status_non_production_when_fixture_detected():
    status, blockers = evaluate_production_status(_metrics(fixture_or_synthetic_data_detected=True))
    assert status == STATUS_NON_PRODUCTION
    assert any(b["metric"] == "fixture_or_synthetic_data_detected" for b in blockers)


def test_status_partial_when_bond_actor_layer_missing():
    status, blockers = evaluate_production_status(_metrics(bond_actor_count=0))
    assert status == STATUS_PARTIAL
    assert any(b["metric"] == "bond_actor_count" for b in blockers)


def test_status_partial_when_parent_uei_coverage_below_threshold():
    status, blockers = evaluate_production_status(_metrics(parent_uei_coverage=0.5))
    assert status == STATUS_PARTIAL
    assert any(b["metric"] == "parent_uei_coverage" for b in blockers)


def test_status_validated_when_all_gates_pass():
    status, blockers = evaluate_production_status(_metrics())
    assert status == STATUS_VALIDATED
    assert blockers == []


def test_run_gate_writes_outputs_and_stamps_report(tmp_path: Path):
    (tmp_path / "data" / "reports").mkdir(parents=True)
    (tmp_path / "data" / "staging" / "processed" / "graph").mkdir(parents=True)

    report_summary = {
        "generated_at": "2026-05-08 00:00 UTC",
        "data_layers": 3,
        "awards": {"unique_entities": 18},
        "power_network": {"bond_actors_count": 0, "total_ranked": 18},
    }
    (tmp_path / "data" / "reports" / "pr_report_summary.json").write_text(
        json.dumps(report_summary),
        encoding="utf-8",
    )
    (tmp_path / "data" / "reports" / "pr_investigative_report.md").write_text(
        "# Report\n\nBody\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "pr_power_network_summary.json").write_text(
        json.dumps({"total_entities": 18}),
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "dominance_summary.json").write_text(
        json.dumps({"unique_vendors": 18}),
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_summary.json").write_text(
        json.dumps({"prime_count": 18, "sub_count": 18, "pair_count": 300}),
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "graph" / "network_summary.json").write_text(
        json.dumps({"vendor_nodes": 18}),
        encoding="utf-8",
    )

    result = run_gate(tmp_path)

    assert result["production_status"] == STATUS_NON_PRODUCTION
    assert (tmp_path / "data" / "exports" / "production_status.json").exists()
    assert (tmp_path / "data" / "review_queue" / "production_blockers.csv").exists()

    report_text = (tmp_path / "data" / "reports" / "pr_investigative_report.md").read_text(
        encoding="utf-8"
    )
    assert report_text.startswith("> Production Status: NON_PRODUCTION_DIAGNOSTIC")

    stamped_summary = json.loads(
        (tmp_path / "data" / "reports" / "pr_report_summary.json").read_text(encoding="utf-8")
    )
    assert stamped_summary["production_status"] == STATUS_NON_PRODUCTION
