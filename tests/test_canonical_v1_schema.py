"""Tests for the Canonical Entity Relationship Model v1 schema + integrity validator."""

import json
from pathlib import Path

import pytest

from contract_sweeper.validation import canonical_v1_schema as cv1

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "canonical_v1"


@pytest.mark.unit
@pytest.mark.parametrize("table", sorted(cv1.TABLES))
def test_schema_file_parses_and_is_wellformed(table):
    data = json.loads((SCHEMA_DIR / cv1.TABLES[table][0]).read_text(encoding="utf-8"))
    assert data.get("$schema"), f"{table} missing $schema"
    assert data.get("title"), f"{table} missing title"
    assert data.get("type") == "object"
    # every required field is a declared property
    props = set(data.get("properties", {}))
    assert set(data.get("required", [])) <= props


@pytest.mark.unit
def test_templates_match_schema_required_columns():
    """Each CSV template header must contain every required column."""
    import csv as _csv

    for table, (_schema, csv_name, _pk) in cv1.TABLES.items():
        schema = cv1.load_schema(table, REPO_ROOT)
        header = _csv.reader(
            (REPO_ROOT / cv1.DATA_DIR / csv_name).read_text().splitlines()
        ).__next__()
        assert set(schema.get("required", [])) <= set(header), (
            f"{table} header missing required cols"
        )


@pytest.mark.unit
def test_validate_row_flags_missing_required():
    schema = cv1.load_schema("people", REPO_ROOT)
    errors = cv1.validate_row({"full_name": "Jane Doe"}, schema)
    assert any("person_id" in e for e in errors)
    assert any("normalized_name" in e for e in errors)


@pytest.mark.unit
def test_validate_row_flags_bad_enum_pattern_and_range():
    schema = cv1.load_schema("entities", REPO_ROOT)
    row = {
        "entity_id": "BADID",
        "name": "X",
        "normalized_name": "X",
        "entity_type": "spaceship",
        "confidence": "1.5",
    }
    errors = cv1.validate_row(row, schema)
    assert any("entity_id" in e and "pattern" in e for e in errors)
    assert any("entity_type" in e and "enum" in e for e in errors)
    assert any("confidence" in e and "maximum" in e for e in errors)


@pytest.mark.unit
def test_valid_row_passes():
    schema = cv1.load_schema("entities", REPO_ROOT)
    row = {
        "entity_id": "entity_abc123",
        "name": "PREPA",
        "normalized_name": "PREPA",
        "entity_type": "utility",
        "confidence": "0.9",
    }
    assert cv1.validate_row(row, schema) == []


def _good_tables():
    return {
        "people": [],
        "entities": [
            {
                "entity_id": "entity_a",
                "name": "A",
                "normalized_name": "A",
                "entity_type": "agency",
                "confidence": "0.9",
                "evidence_id": "evidence_x",
            }
        ],
        "roles": [],
        "contracts": [],
        "projects": [],
        "debt_instruments": [],
        "lobbying_records": [],
        "funding_sources": [],
        "properties": [],
        "municipalities": [],
        "edges": [
            {
                "edge_id": "edge_1",
                "source_node_type": "Entity",
                "source_node_id": "entity_a",
                "edge_type": "OWNS_OR_CONTROLS",
                "target_node_type": "Entity",
                "target_node_id": "entity_a",
                "confidence": "0.8",
                "evidence_id": "evidence_x",
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence_x",
                "source_type": "registry",
                "source_name": "S",
                "claim": "c",
                "evidence_tier": "T1",
                "confidence": "0.95",
                "review_status": "accepted",
            }
        ],
        "review_queue": [],
    }


@pytest.mark.unit
def test_referential_integrity_detects_broken_fk():
    tables = _good_tables()
    tables["entities"][0]["parent_entity_id"] = "entity_missing"
    report = cv1.ValidationReport()
    cv1.validate_referential_integrity(tables, report)
    assert any("broken reference" in e and "entity_missing" in e for e in report.errors)


@pytest.mark.unit
def test_referential_integrity_detects_broken_edge_endpoint():
    tables = _good_tables()
    tables["edges"][0]["target_node_id"] = "entity_ghost"
    report = cv1.ValidationReport()
    cv1.validate_referential_integrity(tables, report)
    assert any("broken endpoint" in e for e in report.errors)


@pytest.mark.unit
def test_controlled_vocab_gate_flags_unknown_verb():
    tables = _good_tables()
    tables["edges"][0]["edge_type"] = "SECRETLY_CONTROLS"
    report = cv1.ValidationReport()
    offenders = cv1.validate_controlled_vocab(tables, report)
    assert len(offenders) == 1
    assert any("uncontrolled edge_type" in e for e in report.errors)


@pytest.mark.unit
def test_evidence_presence_gate():
    tables = _good_tables()
    tables["edges"][0]["evidence_id"] = ""
    report = cv1.ValidationReport()
    cv1.validate_evidence_presence(tables, report)
    assert any("missing evidence_id" in e for e in report.errors)

    tables = _good_tables()
    tables["edges"][0]["evidence_id"] = "evidence_nope"
    report = cv1.ValidationReport()
    cv1.validate_evidence_presence(tables, report)
    assert any("not found in evidence table" in e for e in report.errors)


@pytest.mark.unit
def test_in_memory_good_tables_pass_all_integrity_checks():
    tables = _good_tables()
    report = cv1.ValidationReport()
    cv1.validate_referential_integrity(tables, report)
    cv1.validate_controlled_vocab(tables, report)
    cv1.validate_evidence_presence(tables, report)
    assert report.ok, report.errors


@pytest.mark.integration
def test_validate_all_on_repo_tables_is_clean():
    """The committed canonical_v1 tables must always validate clean.

    Once a source is ingested (e.g. the 78 municipalities) the table is no
    longer empty, but it must still pass schema + referential-integrity +
    controlled-vocab + evidence-presence checks.
    """
    report = cv1.validate_all(REPO_ROOT)
    assert report.ok, report.errors
