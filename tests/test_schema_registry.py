"""Tests for the schema registry loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from contract_sweeper.runtime import schema_registry as schemareg

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_load_schema_registry_returns_dict():
    reg = schemareg.load_schema_registry(REPO_ROOT)
    assert "canonical_columns" in reg
    assert "canonical_tables" in reg


@pytest.mark.unit
def test_canonical_tables_include_mission_set():
    tables = set(schemareg.all_tables(REPO_ROOT))
    must_have = {
        "contracts_master",
        "entities_resolved",
        "execution_chain_master",
        "execution_chain_per_asset",
        "execution_chain_per_municipality",
        "alias_registry",
        "entity_edges",
        "top_25_control_entities",
        "gap_analysis_report",
        "review_queue",
        "validation_report",
    }
    missing = must_have - tables
    assert not missing, f"canonical tables missing: {missing}"


@pytest.mark.unit
def test_validate_registry_passes():
    report = schemareg.validate_registry(REPO_ROOT)
    assert report["ok"], f"schema_registry validation errors: {report['errors']}"


@pytest.mark.unit
def test_canonical_columns_for_resolves_refs():
    cols = schemareg.canonical_columns_for("contracts_master", REPO_ROOT)
    names = [c.get("name") for c in cols]
    # Spot-check a few canonical fields from the 25-field mission schema.
    for required in ("award_id", "parent_uei", "obligation_amount", "source_hash", "source_system"):
        assert required in names, f"contracts_master missing canonical column {required}"


@pytest.mark.unit
def test_primary_key_columns_exist_in_table():
    """Every primary_key column must be declared in the table."""
    reg = schemareg.load_schema_registry(REPO_ROOT)
    for tname, tdef in reg["canonical_tables"].items():
        col_names = {(c.get("name") or c.get("ref")) for c in tdef.get("columns", [])}
        for pk in tdef.get("primary_key", []):
            assert pk in col_names, f"{tname}: primary_key '{pk}' not in columns"
