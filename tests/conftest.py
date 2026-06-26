"""Shared fixtures for moneysweep-pr test suite."""

import csv
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Committed, deterministic, generated report files that some tests regenerate
# in place against the real repo root. Snapshotting + restoring them around
# every test keeps the working tree clean and prevents one test leaving a
# mutated file as a polluted baseline for another's committed-vs-regenerated
# comparison. Content is captured and rewritten verbatim.
#
# Note: the strongest data-presence-dependent invariant
# (test_status_csv_regenerates_identically) does NOT rely on this fixture — it
# regenerates inside a clean ``git worktree`` of HEAD, so it is immune to
# working-tree pollution regardless of collection order. This fixture is
# defence-in-depth + working-tree hygiene for the registry-derived comparison
# tests.
_PROTECTED_REPORT_FILES = (
    "reports/source_registry_status.csv",
    "reports/source_recovery_matrix.csv",
    "reports/source_recovery_matrix.md",
    "reports/materialization_readiness.json",
    "reports/gap_analysis_report.csv",
    "reports/gap_analysis_report.json",
)


@pytest.fixture(autouse=True)
def _restore_committed_reports():
    """Restore committed report files to their pre-test bytes after each test."""
    snapshots: dict[Path, bytes | None] = {}
    for rel in _PROTECTED_REPORT_FILES:
        p = PROJECT_ROOT / rel
        snapshots[p] = p.read_bytes() if p.exists() else None
    try:
        yield
    finally:
        for p, original in snapshots.items():
            if original is None:
                if p.exists():
                    p.unlink()
            elif not p.exists() or p.read_bytes() != original:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(original)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project directory structure matching the pipeline layout."""
    dirs = [
        tmp_path / "data" / "staging" / "expansion",
        tmp_path / "data" / "staging" / "processed",
        tmp_path / "data" / "raw",
        tmp_path / "data" / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def sample_fpds_csv(tmp_project):
    """Create a sample FPDS-style CSV with realistic column names."""
    path = tmp_project / "data" / "staging" / "expansion" / "expansion_fpds_2017_2025_direct.csv"
    rows = [
        {
            "PIID": "W911NF20C0001",
            "Date Signed": "2020-03-15",
            "Vendor Name": "ACME CONSTRUCTION INC",
            "Contracting Agency Name": "Department of the Army",
            "Dollars Obligated": "$1,234,567.89",
            "Place of Performance State": "PR",
        },
        {
            "PIID": "W911NF21C0042",
            "Date Signed": "2021-10-05",
            "Vendor Name": "CARIBBEAN BUILDERS LLC",
            "Contracting Agency Name": "Department of the Navy",
            "Dollars Obligated": "987654.32",
            "Place of Performance State": "PR",
        },
        {
            "PIID": "W911NF21C0042",
            "Date Signed": "2021-10-05",
            "Vendor Name": "CARIBBEAN BUILDERS LLC",
            "Contracting Agency Name": "Department of the Navy",
            "Dollars Obligated": "987654.32",
            "Place of Performance State": "PR",
        },
    ]
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def sample_usaspending_csv(tmp_project):
    """Create a sample USASpending-style CSV with different column naming."""
    path = tmp_project / "data" / "staging" / "expansion" / "expansion_dod_upr_2016_2025.csv"
    rows = [
        {
            "Award ID": "SPE4A620F0001",
            "Start Date": "2020-07-01",
            "Recipient Name": "PR MEDICAL SUPPLIES CORP",
            "Awarding Agency": "Department of Defense",
            "Award Amount": "500000",
            "Place of Performance State Code": "PR",
        },
        {
            "Award ID": "SPE4A621F0099",
            "Start Date": "2021-11-20",
            "Recipient Name": "ISLAND TECH SOLUTIONS",
            "Awarding Agency": "Department of Defense",
            "Award Amount": "250000",
            "Place of Performance State Code": "PR",
        },
    ]
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return path
