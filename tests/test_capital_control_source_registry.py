from datetime import date

import pytest

from moneysweep.capital_control.source_adapter import (
    SEC_SOURCE_DEFINITIONS,
    FilingIndexRecord,
    assert_source_registry_invariants,
    build_filing_denominator,
    source_definition,
    source_for_form_type,
)


def _record(accession: str, form_type: str) -> FilingIndexRecord:
    return FilingIndexRecord(
        accession_number=accession,
        cik="0001067983",
        form_type=form_type,
        filing_date=date(2026, 5, 15),
        report_date=date(2026, 3, 31),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1067983/"
            f"{accession.replace('-', '')}/index.htm"
        ),
    )


def test_registry_has_disjoint_form_type_universe() -> None:
    assert_source_registry_invariants(SEC_SOURCE_DEFINITIONS)
    assert source_for_form_type("13F-HR").source_key == "SEC_13F"
    assert source_for_form_type("SC 13G/A").source_key == "SEC_13D_G"
    assert source_for_form_type("4").source_key == "SEC_FORMS_3_4_5"
    assert source_for_form_type("NPORT-P").source_key == "SEC_NPORT"


def test_unknown_form_does_not_fall_through_to_nearest_source() -> None:
    with pytest.raises(ValueError):
        source_for_form_type("10-K")


def test_denominator_classifies_whole_authoritative_index_rows() -> None:
    definition = source_definition("SEC_13F")
    rows = [
        _record("0001193125-26-226661", "13F-HR"),
        _record("0001193125-26-226662", "13F-HR/A"),
        _record("0001193125-26-226663", "10-K"),
    ]
    result = build_filing_denominator(rows, definition)
    assert result.input_count == 3
    assert result.retained_count == 2
    assert result.excluded_count == 1
    assert result.input_count == result.retained_count + result.excluded_count
    assert result.exclusion_counts == (("FORM_TYPE_OUT_OF_SCOPE", 1),)


def test_duplicate_accession_fails_closed() -> None:
    definition = source_definition("SEC_13F")
    row = _record("0001193125-26-226661", "13F-HR")
    with pytest.raises(ValueError, match="duplicate accession_number"):
        build_filing_denominator([row, row], definition)
