"""Tests for R1 artifact lineage and cache audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.validation.cache_audit import run_audit


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _touch_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_r1_audit_writes_required_outputs(tmp_path: Path):
    # Minimal producer scripts.
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "generate_report.py").write_text("Report exists\nCACHED\n", encoding="utf-8")
    (tmp_path / "scripts" / "analyze_power_network.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "scripts" / "dominance_analysis.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "scripts" / "network_graph.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "scripts" / "analyze_prime_sub.py").write_text("print('ok')\n", encoding="utf-8")

    # run_all without skip-download recompute forwarding should be flagged.
    (tmp_path / "run_all.py").write_text("--skip-download\nrun_report(root=root)\n", encoding="utf-8")

    # Existing status from R0 gate.
    _write_json(
        tmp_path / "data" / "exports" / "production_status.json",
        {"production_status": "NON_PRODUCTION_DIAGNOSTIC", "status_message": "Diagnostic output only — not production-valid."},
    )

    # Required summaries.
    _write_json(
        tmp_path / "data" / "reports" / "pr_report_summary.json",
        {
            "generated_at": "2026-05-04 07:05 UTC",
            "data_layers": 3,
            "awards": {"unique_entities": 18, "top_entities": [{"name": "Acme LLC"} for _ in range(18)]},
            "power_network": {"total_ranked": 18, "bond_actors_count": 0},
        },
    )
    (tmp_path / "data" / "reports" / "pr_investigative_report.md").write_text("# Report\n", encoding="utf-8")
    _write_json(tmp_path / "data" / "staging" / "processed" / "pr_power_network_summary.json", {"total_entities": 18})
    _write_json(tmp_path / "data" / "staging" / "processed" / "dominance_summary.json", {"unique_vendors": 18})
    _write_json(
        tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_summary.json",
        {"prime_count": 18, "sub_count": 18, "pair_count": 300},
    )
    _write_json(tmp_path / "data" / "staging" / "processed" / "graph" / "network_summary.json", {"vendor_nodes": 18})
    (tmp_path / "data" / "staging" / "processed" / "graph" / "network.graphml").write_text("<graphml/>", encoding="utf-8")

    # Source input present and newer than report to force stale-candidate detection.
    _touch_csv(
        tmp_path / "data" / "staging" / "processed" / "entity_master.csv",
        [{"entity_key": "ACME"}],
        fieldnames=["entity_key"],
    )

    result = run_audit(tmp_path)

    assert (tmp_path / "data" / "exports" / "artifact_lineage_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "cache_reuse_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "rebuild_status.json").exists()

    assert result["phase_7_8_blocked"] is True
    assert result["skip_download_recompute_guard"] is False
    assert result["top_n_truncation_suspected"] is True
    assert result["fixture_or_demo_replay_suspected"] is True


def test_lineage_csv_contains_required_diagnostics(tmp_path: Path):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    for script in (
        "generate_report.py",
        "analyze_power_network.py",
        "dominance_analysis.py",
        "network_graph.py",
        "analyze_prime_sub.py",
    ):
        (tmp_path / "scripts" / script).write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "run_all.py").write_text("force_recompute_outputs = bool(skip_download)\n_call_step(\nforce_recompute=force_recompute_outputs\n", encoding="utf-8")
    _write_json(tmp_path / "data" / "exports" / "production_status.json", {"production_status": "NON_PRODUCTION_DIAGNOSTIC"})

    _write_json(tmp_path / "data" / "reports" / "pr_report_summary.json", {"awards": {"unique_entities": 18}, "power_network": {"total_ranked": 18}})
    (tmp_path / "data" / "reports" / "pr_investigative_report.md").write_text("# R\n", encoding="utf-8")
    _write_json(tmp_path / "data" / "staging" / "processed" / "pr_power_network_summary.json", {"total_entities": 18})
    _write_json(tmp_path / "data" / "staging" / "processed" / "dominance_summary.json", {"unique_vendors": 18})
    _write_json(tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_summary.json", {"prime_count": 18, "sub_count": 18, "pair_count": 300})
    _write_json(tmp_path / "data" / "staging" / "processed" / "graph" / "network_summary.json", {"vendor_nodes": 18})
    (tmp_path / "data" / "staging" / "processed" / "graph" / "network.graphml").write_text("<graphml/>", encoding="utf-8")

    run_audit(tmp_path)

    lineage_path = tmp_path / "data" / "exports" / "artifact_lineage_audit.csv"
    rows = list(csv.DictReader(lineage_path.open("r", encoding="utf-8")))
    assert rows, "lineage rows should not be empty"

    required = {
        "artifact_path",
        "artifact_type",
        "created_at",
        "modified_at",
        "source_inputs",
        "input_modified_at_min",
        "input_modified_at_max",
        "artifact_hash",
        "prior_artifact_hash",
        "was_recomputed",
        "cache_hit",
        "stale_candidate",
        "producer_script",
        "producer_phase",
        "source_row_count",
        "output_row_count",
    }
    assert required.issubset(rows[0].keys())

