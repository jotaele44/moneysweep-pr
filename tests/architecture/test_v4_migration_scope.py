import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "manifests" / "v4" / "v01_source_domain_mapping.csv"
SCOPE = ROOT / "manifests" / "v4" / "migration_scope.yaml"


def test_v4_migration_scope_closes_against_global_denominator():
    rows = list(csv.DictReader(MAPPING.read_text(encoding="utf-8").splitlines()))
    scope = yaml.safe_load(SCOPE.read_text(encoding="utf-8"))
    excluded = {row["source_id"] for row in scope["exclusions"]}
    included = {row["source_id"] for row in rows if row["mapping_state"] == "MAPPED"}
    all_ids = {row["source_id"] for row in rows}

    assert len(all_ids) == 167
    assert len(included) == 165
    assert len(excluded) == 2
    assert included.isdisjoint(excluded)
    assert included | excluded == all_ids
    assert excluded == {
        "prasa_completed_projects_ppp",
        "prasa_consulting_engineer_ppp",
    }


def test_blocked_exclusions_are_not_source_absence():
    scope = yaml.safe_load(SCOPE.read_text(encoding="utf-8"))
    assert all(row["state"] == "BLOCKED" for row in scope["exclusions"])
    assert all(row["contradiction_id"] == "V01-SOURCE-003" for row in scope["exclusions"])
