from pathlib import Path

from scripts.validate_top_form_controls import (
    ALLOWED_PRIORITIES,
    ALLOWED_STATUSES,
    REQUIRED_COLUMNS,
    REQUIRED_GATES,
    read_matrix,
    validate_all,
    validate_doc,
    validate_matrix,
    validate_schema,
)


def test_top_form_control_artifacts_validate_cleanly():
    assert validate_all() == []


def test_top_form_gap_matrix_has_required_columns():
    rows = read_matrix()
    assert rows, "top_form_gap_matrix.csv must contain rows"

    first = rows[0]
    for column in REQUIRED_COLUMNS:
        assert column in first


def test_top_form_gap_matrix_status_and_priority_values_are_allowed():
    rows = read_matrix()

    for row in rows:
        assert row["status"] in ALLOWED_STATUSES
        assert row["priority"] in ALLOWED_PRIORITIES


def test_top_form_gap_matrix_contains_required_gates():
    rows = read_matrix()
    gates = {row["gate"] for row in rows}

    missing = REQUIRED_GATES - gates
    assert not missing, f"missing required gates: {sorted(missing)}"


def test_top_form_checklist_doc_exists_and_has_expected_sections():
    path = Path("docs/TOP_FORM_DEVELOPMENT_CHECKLIST.md")
    assert path.exists()

    content = path.read_text(encoding="utf-8")
    expected = [
        "## Purpose",
        "## Status Vocabulary",
        "## Evidence Tiers",
        "## Production Gates",
        "## Production Complete Definition",
    ]

    for heading in expected:
        assert heading in content


def test_individual_validators_are_clean():
    assert validate_doc() == []
    assert validate_matrix() == []
    assert validate_schema() == []
