"""Offline-path coverage for scripts/audit_materialization_coverage.py.

These tests exercise the *offline* layer only — local-tree source classification
and the processed-file inventory (declared vs orphan). The network ``--probe``
layer is intentionally not exercised here so the suite stays hermetic; probe
functions are failure-tolerant by contract and return ``probe_failed`` rather
than raising.
"""

from __future__ import annotations

import json

import pytest

from scripts.audit_materialization_coverage import (
    TIER_BULK,
    TIER_EMPTY,
    TIER_MODERATE,
    TIER_SEED_STUB,
    _materiality_tier,
    build_audit,
    compute_local_coverage,
    inventory_processed_files,
)

pytestmark = pytest.mark.unit


def _write_csv(path, data_rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["col_a,col_b"] + [f"v{i},w{i}" for i in range(data_rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """A minimal synthetic repo: registry JSON + processed CSVs on disk."""
    (tmp_path / "registries").mkdir()
    registry = {
        "sources": [
            {  # all outputs present, well above min_rows -> fully_materialized, bulk
                "source_id": "big_full",
                "family": "federal",
                "required": True,
                "authentication": "none",
                "expected_outputs": ["data/staging/processed/pr_big.csv"],
                "validation_threshold": {"min_rows": 1},
            },
            {  # one of two outputs missing -> partially_materialized
                "source_id": "half_done",
                "family": "federal",
                "required": True,
                "authentication": "none",
                "expected_outputs": [
                    "data/staging/processed/pr_present.csv",
                    "data/staging/processed/pr_missing.csv",
                ],
                "validation_threshold": {"min_rows": 1},
            },
            {  # present but below min_rows -> partially_materialized (below threshold)
                "source_id": "under_thresh",
                "family": "territorial",
                "required": False,
                "authentication": "none",
                "expected_outputs": ["data/staging/processed/pr_small.csv"],
                "validation_threshold": {"min_rows": 100},
            },
            {  # declared output absent -> not_materialized
                "source_id": "absent_src",
                "family": "bonds",
                "required": False,
                "authentication": "none",
                "expected_outputs": ["data/staging/processed/pr_absent.csv"],
                "validation_threshold": {"min_rows": 1},
            },
        ]
    }
    (tmp_path / "registries" / "source_registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )

    proc = tmp_path / "data" / "staging" / "processed"
    _write_csv(proc / "pr_big.csv", 5000)  # bulk, declared
    _write_csv(proc / "pr_present.csv", 200)  # declared (half_done)
    _write_csv(proc / "pr_small.csv", 10)  # declared but under threshold
    _write_csv(proc / "pr_orphan.csv", 1234)  # ORPHAN: real data, no source
    _write_csv(proc / "pr_header_only.csv", 0)  # header only -> empty, ignored
    return tmp_path


def test_materiality_tier_boundaries():
    assert _materiality_tier(0) == TIER_EMPTY
    assert _materiality_tier(1) == TIER_SEED_STUB
    assert _materiality_tier(49) == TIER_SEED_STUB
    assert _materiality_tier(50) == TIER_MODERATE
    assert _materiality_tier(999) == TIER_MODERATE
    assert _materiality_tier(1000) == TIER_BULK


def test_local_status_classification(repo):
    by_id = {s["source_id"]: s for s in compute_local_coverage(repo)["sources"]}
    assert by_id["big_full"]["local_status"] == "fully_materialized"
    assert by_id["big_full"]["materiality_tier"] == TIER_BULK
    assert by_id["half_done"]["local_status"] == "partially_materialized"
    assert by_id["under_thresh"]["local_status"] == "partially_materialized"
    assert by_id["absent_src"]["local_status"] == "not_materialized"
    assert by_id["absent_src"]["local_rows"] == 0


def test_summary_counts(repo):
    s = compute_local_coverage(repo)["summary"]
    assert s["total_sources"] == 4
    assert s["required_sources"] == 2
    assert s["fully_materialized"] == 1
    assert s["partially_materialized"] == 2
    assert s["not_materialized"] == 1
    # registry-accounted rows = declared present files only (5000 + 200 + 10)
    assert s["total_local_rows"] == 5210


def test_orphan_inventory_surfaces_undeclared_data(repo):
    """The 1234-row pr_orphan.csv is real data no source declares — must be flagged."""
    inv = inventory_processed_files(repo)
    by_file = {f["file"]: f for f in inv["files"]}
    assert by_file["pr_orphan.csv"]["classification"] == "orphan"
    assert by_file["pr_big.csv"]["classification"] == "declared"
    assert by_file["pr_header_only.csv"]["classification"] == "empty"
    # total on disk counts everything; orphan bucket isolates the undeclared rows
    assert inv["total_rows_on_disk"] == 5000 + 200 + 10 + 1234
    assert inv["orphan_rows"] == 1234
    assert inv["orphan_file_count"] == 1
    # registry-accounted (declared) rows exclude the orphan
    assert inv["registry_accounted_rows"] == 5000 + 200 + 10


def test_intermediate_files_not_counted_as_orphans(repo):
    """normalized_expansion_* and vendor_targets.csv are non-terminal pipeline
    intermediates (folded into pr_contracts_master.csv) — they classify as
    'intermediate', never 'orphan'."""
    proc = repo / "data" / "staging" / "processed"
    _write_csv(proc / "normalized_expansion_fpds_2020_direct.csv", 777)
    _write_csv(proc / "vendor_targets.csv", 50)
    inv = inventory_processed_files(repo)
    by_file = {f["file"]: f for f in inv["files"]}
    assert by_file["normalized_expansion_fpds_2020_direct.csv"]["classification"] == "intermediate"
    assert by_file["vendor_targets.csv"]["classification"] == "intermediate"
    # the undeclared orphan (1234) is unchanged; intermediates are a separate bucket
    assert inv["orphan_rows"] == 1234
    assert inv["intermediate_rows"] == 777 + 50
    assert inv["intermediate_file_count"] == 2


def test_build_audit_offline_is_hermetic(repo):
    """probe=False must not touch the network and must still emit the inventory."""
    audit = build_audit(repo, probe=False)
    assert audit["probe_ran"] is False
    assert audit["universe_coverage"] == []
    assert audit["processed_file_inventory"]["orphan_rows"] == 1234
    assert "committed_ci_view" in audit
    assert audit["local_truth_summary"]["fully_materialized"] == 1
