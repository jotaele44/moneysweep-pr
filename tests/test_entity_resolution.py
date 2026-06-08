"""Entity-resolution integrity tests (Gate ``testing``, item ``entity_resolution_tests``).

Cross-checks the merged entity-master family — masters, aliases, parent map, and
review queue — for referential integrity: every alias and relationship resolves
to a known master id, aliases resolve uniquely, and no review item is an orphan.
Fully offline (reads committed CSVs only).
"""

from __future__ import annotations

import csv

import pytest

from scripts import build_entity_master as bem

REPO_ROOT = bem.REPO_ROOT


def _read(rel: str) -> list[dict[str, str]]:
    with (REPO_ROOT / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def master_ids() -> set[str]:
    ids = {r["entity_id"] for r in _read("data/reference/entity_master.csv")}
    ids |= {r["agency_id"] for r in _read("data/reference/agency_master.csv")}
    ids |= {r["person_id"] for r in _read("data/reference/person_master.csv")}
    return ids


@pytest.mark.unit
def test_master_ids_unique_within_each_registry():
    for rel, key in [
        ("data/reference/entity_master.csv", "entity_id"),
        ("data/reference/agency_master.csv", "agency_id"),
        ("data/reference/person_master.csv", "person_id"),
    ]:
        ids = [r[key] for r in _read(rel)]
        assert len(set(ids)) == len(ids), f"duplicate ids in {rel}"


@pytest.mark.unit
def test_aliases_resolve_to_masters(master_ids):
    rows = _read("data/reference/entity_aliases.csv")
    assert rows
    for r in rows:
        assert r["entity_id"] in master_ids, (
            f"alias {r['alias']!r} -> unknown entity {r['entity_id']}"
        )


@pytest.mark.unit
def test_alias_normalization_resolves_uniquely():
    rows = _read("data/reference/entity_aliases.csv")
    # within an entity, a normalized alias maps to exactly one alias_id
    seen: dict[tuple[str, str], str] = {}
    for r in rows:
        key = (r["entity_id"], r["normalized_alias"])
        assert key not in seen or seen[key] == r["alias_id"], f"duplicate normalized alias {key}"
        seen[key] = r["alias_id"]
    # a well-known alias resolves to its entity
    em = {r["canonical_name"]: r["entity_id"] for r in _read("data/reference/entity_master.csv")}
    prepa = em["Puerto Rico Electric Power Authority"]
    prepa_aliases = {r["normalized_alias"] for r in rows if r["entity_id"] == prepa}
    assert any("PREPA" in a.upper() for a in prepa_aliases)


@pytest.mark.unit
def test_parent_map_referential_integrity(master_ids):
    rows = _read("data/reference/entity_parent_map.csv")
    assert rows
    for r in rows:
        assert r["parent_entity_id"] in master_ids, f"unknown parent {r['parent_entity_id']}"
        assert r["child_entity_id"] in master_ids, f"unknown child {r['child_entity_id']}"
        assert r["parent_entity_id"] != r["child_entity_id"]


@pytest.mark.unit
def test_review_queue_objects_are_not_orphans():
    person_ids = {r["person_id"] for r in _read("data/reference/person_master.csv")}
    rows = _read("reports/entity_resolution_review_queue.csv")
    assert rows
    for r in rows:
        if r["object_type"] == "person":
            assert r["object_id"] in person_ids, (
                f"review item references unknown person {r['object_id']}"
            )


@pytest.mark.unit
def test_influence_and_debt_endpoints_resolve(master_ids):
    for r in _read("data/reference/influence_edges.csv"):
        assert r["from_entity_id"] in master_ids
        assert r["to_entity_id"] in master_ids
    for r in _read("data/reference/debt_instruments.csv"):
        assert r["issuer_entity_id"] in master_ids
    for r in _read("data/reference/creditor_mapping.csv"):
        assert r["issuer_entity_id"] in master_ids
