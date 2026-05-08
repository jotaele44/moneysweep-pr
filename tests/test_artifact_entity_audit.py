"""Tests for Phase 6.5 artifact and entity audit."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.audit_artifact_entity_universe import (
    collect_entity_universe,
    compute_prime_sub_shape,
    run_audit,
)


def test_collect_entity_universe_merges_report_and_power_summaries():
    report_summary = {
        "awards": {
            "top_entities": [
                {"name": "Acme LLC", "obligated": 100},
                {"name": "Beta Inc", "obligated": 50},
            ]
        }
    }
    power_summary = {
        "top_entities": [
            {"name": "Acme LLC", "rank": 1, "influence_score": 99, "source_presence": 3},
            {"name": "Gamma Corp", "rank": 2, "influence_score": 88, "source_presence": 2},
        ]
    }

    rows = collect_entity_universe(report_summary, power_summary)

    assert {row["entity_key"] for row in rows} == {"ACME", "BETA", "GAMMA"}
    acme = next(row for row in rows if row["entity_key"] == "ACME")
    assert acme["seen_in_awards"] is True
    assert acme["seen_in_power_network"] is True
    assert acme["power_rank"] == 1


def test_compute_prime_sub_shape_detects_self_and_dense_pairs():
    report = """
## 3. Prime-to-Subcontractor Flows
| Prime | Subcontractor | Flow | Contracts |
|-------|--------------|------|-----------|
| Acme LLC | Acme LLC | $1M | 1 |
| Acme LLC | Beta Inc | $1M | 1 |
| Beta Inc | Acme LLC | $1M | 1 |

## 4. Other
"""
    summary = {"prime_count": 2, "sub_count": 2, "pair_count": 3}

    shape = compute_prime_sub_shape(report, summary)

    assert shape["self_pair_ratio"] == 0.3333
    assert shape["reciprocal_pair_count"] == 2
    assert shape["dense_matrix_score"] == 0.75


def test_run_audit_writes_required_outputs(tmp_path: Path):
    (tmp_path / "data" / "reports").mkdir(parents=True)
    (tmp_path / "data" / "staging" / "processed" / "graph").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "data" / "raw").mkdir(parents=True)

    (tmp_path / "scripts" / "generate_report.py").write_text("Report exists\\nCACHED\\n", encoding="utf-8")
    (tmp_path / "scripts" / "build_unified_master.py").write_text("already exists\\n--force\\n", encoding="utf-8")
    (tmp_path / "run_all.py").write_text("--skip-download\\ngen_report\\n", encoding="utf-8")
    (tmp_path / "data" / "raw" / "source.csv").write_text("a\\n1\\n", encoding="utf-8")

    report_summary = {
        "generated_at": "2026-05-04 07:05 UTC",
        "data_layers": 3,
        "awards": {
            "unique_entities": 2,
            "top_entities": [
                {"name": "Acme LLC", "obligated": 10_000_000},
                {"name": "Beta Inc", "obligated": 5_000_000},
            ],
        },
        "power_network": {"total_ranked": 2, "bond_actors_count": 0},
        "prime_sub": {"unique_primes": 2, "unique_subs": 2},
    }
    (tmp_path / "data" / "reports" / "pr_report_summary.json").write_text(
        __import__("json").dumps(report_summary),
        encoding="utf-8",
    )
    (tmp_path / "data" / "reports" / "pr_investigative_report.md").write_text(
        """
# Report
*Generated: 2026-05-04 07:05 UTC*
## 3. Prime-to-Subcontractor Flows
| Prime | Subcontractor | Flow | Contracts |
|-------|--------------|------|-----------|
| Acme LLC | Acme LLC | $1M | 1 |
""",
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "pr_power_network_summary.json").write_text(
        '{"total_entities": 2, "top_entities": [{"name": "Acme LLC", "rank": 1, "influence_score": 1, "source_presence": 1}]}',
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_summary.json").write_text(
        '{"prime_count": 2, "sub_count": 2, "pair_count": 3, "top_pairs": [{"prime_award_ids": "PRIME-SUB-1"}]}',
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "graph" / "network_summary.json").write_text(
        '{"vendor_nodes": 2, "parent_entity_nodes": 0}',
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "dominance_summary.json").write_text(
        '{"unique_vendors": 2}',
        encoding="utf-8",
    )
    (tmp_path / "data" / "staging" / "processed" / "pr_all_awards_summary.json").write_text(
        '{"unique_recipients": 2}',
        encoding="utf-8",
    )

    summary = run_audit(tmp_path)

    assert summary["status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert summary["graph_build_allowed"] is False
    assert (tmp_path / "data" / "exports" / "output_validation_audit.json").exists()
    assert (tmp_path / "data" / "exports" / "entity_universe_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "entity_collapse_diagnostics.csv").exists()
    assert (tmp_path / "data" / "exports" / "artifact_lineage_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "cache_reuse_audit.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "suspect_entity_collapses.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "graph_coverage_blockers.csv").exists()

    blockers = pd.read_csv(tmp_path / "data" / "review_queue" / "graph_coverage_blockers.csv")
    assert "bond_actor_count" in set(blockers["metric"])
