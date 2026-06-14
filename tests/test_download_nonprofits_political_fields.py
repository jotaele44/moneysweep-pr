"""Tests for the 990 political-activity signal added in Phase B."""

from __future__ import annotations

import pytest

from scripts.download_nonprofits import OUTPUT_COLUMNS, _derive_politically_active


@pytest.mark.unit
def test_output_columns_include_political_fields():
    for col in (
        "lobbying_expenditure",
        "political_expenditure",
        "schedule_c_filed",
        "politically_active",
    ):
        assert col in OUTPUT_COLUMNS, f"{col} missing from download_nonprofits OUTPUT_COLUMNS"


@pytest.mark.unit
def test_politically_active_true_for_c4_c5_c6():
    for sub in ("4", "5", "6"):
        assert _derive_politically_active(sub, "", "", "") == "true"


@pytest.mark.unit
def test_politically_active_false_for_c3_with_no_political_signal():
    assert _derive_politically_active("3", "", "", "") == "false"


@pytest.mark.unit
def test_politically_active_true_for_c3_with_political_expenditure():
    """501(c)(3) is restricted from campaign intervention, but ProPublica may
    still report non-zero political expenditure — the flag should reflect the
    filed-data signal, not just the subsection."""
    assert _derive_politically_active("3", "", 5000.0, "") == "true"


@pytest.mark.unit
def test_schedule_c_filed_marker_triggers_active():
    assert _derive_politically_active("7", "", "", "true") == "true"
    assert _derive_politically_active("7", "", "", "false") == "false"


@pytest.mark.unit
def test_lobbying_only_triggers_active():
    assert _derive_politically_active("7", 100.0, "", "") == "true"


@pytest.mark.unit
def test_unknown_subsection_defaults_to_false():
    assert _derive_politically_active("", "", "", "") == "false"
