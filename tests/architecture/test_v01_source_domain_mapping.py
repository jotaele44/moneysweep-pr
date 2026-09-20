import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "manifests" / "v4" / "v01_source_domain_mapping.csv"
DOMAINS = ROOT / "architecture" / "v4" / "domain_registry.yaml"
CONTRACT = ROOT / "architecture" / "v4" / "source_mapping_contract.yaml"


def test_v01_mapping_denominator_is_exact():
    rows = list(csv.DictReader(MAPPING.read_text(encoding="utf-8").splitlines()))
    ids = [row["source_id"] for row in rows]
    assert len(rows) == 167
    assert len(set(ids)) == 167
    assert all(
        row["mapping_state"] in {"MAPPED", "PARTIAL", "UNMAPPED", "UNRESOLVED"} for row in rows
    )


def test_every_mapping_target_is_registered():
    rows = list(csv.DictReader(MAPPING.read_text(encoding="utf-8").splitlines()))
    domain_ids = set(yaml.safe_load(DOMAINS.read_text(encoding="utf-8"))["domains"])
    support_ids = set(
        yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["core_support_capabilities"]
    )
    for row in rows:
        targets = [x for x in row["targets"].split(";") if x]
        assert targets, row["source_id"]
        for target in targets:
            assert target in domain_ids or target in support_ids, (row["source_id"], target)


def test_partial_mapping_residue_remains_visible():
    rows = list(csv.DictReader(MAPPING.read_text(encoding="utf-8").splitlines()))
    partial = [row for row in rows if row["mapping_state"] == "PARTIAL"]
    assert partial
    assert len(partial) == 102
