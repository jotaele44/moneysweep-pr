"""Tests for scripts/config.py — core helpers and manifest."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import (
    COLUMN_FAMILIES,
    DOWNLOAD_MANIFEST,
    STANDARD_COLUMNS,
    clean_column_name,
    find_column,
    get_expected_filenames,
    get_normalized_filename,
    read_csv_safe,
)


# ---------------------------------------------------------------------------
# clean_column_name
# ---------------------------------------------------------------------------

class TestCleanColumnName:
    def test_strips_whitespace(self):
        assert clean_column_name("  Date Signed  ") == "Date Signed"

    def test_strips_bom(self):
        assert clean_column_name("\ufeffAward ID") == "Award ID"

    def test_normalizes_newlines(self):
        assert clean_column_name("Period of Performance\nStart Date") == "Period of Performance Start Date"

    def test_normalizes_carriage_return(self):
        assert clean_column_name("Award\r\nAmount") == "Award Amount"

    def test_passthrough_clean_name(self):
        assert clean_column_name("vendor_name") == "vendor_name"


# ---------------------------------------------------------------------------
# find_column
# ---------------------------------------------------------------------------

class TestFindColumn:
    def test_exact_match(self):
        cols = ["Date Signed", "Vendor Name", "Amount"]
        assert find_column(cols, "date") == "Date Signed"

    def test_case_insensitive(self):
        cols = ["date_signed", "vendor_name"]
        assert find_column(cols, "date") == "date_signed"

    def test_newline_in_column(self):
        cols = ["Period of Performance\nStart Date", "Amount"]
        assert find_column(cols, "date") == "Period of Performance\nStart Date"

    def test_returns_none_no_match(self):
        cols = ["foo", "bar", "baz"]
        assert find_column(cols, "date") is None

    def test_returns_none_unknown_family(self):
        cols = ["Date Signed"]
        assert find_column(cols, "nonexistent_family") is None

    def test_vendor_family(self):
        cols = ["recipient_name", "agency"]
        assert find_column(cols, "vendor") == "recipient_name"

    def test_agency_family(self):
        cols = ["Awarding Agency", "other"]
        assert find_column(cols, "agency") == "Awarding Agency"

    def test_amount_family(self):
        cols = ["Federal Action Obligation", "other"]
        assert find_column(cols, "amount") == "Federal Action Obligation"

    def test_contract_id_family(self):
        cols = ["piid", "other"]
        assert find_column(cols, "contract_id") == "piid"

    def test_pop_state_family(self):
        cols = ["Primary Place of Performance State Code", "other"]
        assert find_column(cols, "pop_state") == "Primary Place of Performance State Code"

    def test_prefers_first_candidate(self):
        """find_column should return the first match in COLUMN_FAMILIES order."""
        cols = ["action_date", "Date Signed"]
        result = find_column(cols, "date")
        # "Date Signed" appears before "action_date" in the family list
        assert result == "Date Signed"


# ---------------------------------------------------------------------------
# read_csv_safe
# ---------------------------------------------------------------------------

class TestReadCsvSafe:
    def test_reads_utf8(self, tmp_path):
        p = tmp_path / "test.csv"
        p.write_text("col_a,col_b\n1,2\n3,4\n", encoding="utf-8")
        df = read_csv_safe(p)
        assert len(df) == 2
        assert list(df.columns) == ["col_a", "col_b"]

    def test_reads_latin1_fallback(self, tmp_path):
        p = tmp_path / "latin.csv"
        p.write_bytes("vendor,amount\nCaf\xe9,100\n".encode("latin-1"))
        df = read_csv_safe(p)
        assert len(df) == 1
        assert "vendor" in df.columns

    def test_cleans_bom_columns(self, tmp_path):
        p = tmp_path / "bom.csv"
        p.write_text("\ufeffDate Signed,Amount\n2020-01-01,100\n", encoding="utf-8-sig")
        df = read_csv_safe(p)
        assert "Date Signed" in df.columns

    def test_reads_as_str_dtype(self, tmp_path):
        p = tmp_path / "types.csv"
        p.write_text("id,amount\n001,00100\n", encoding="utf-8")
        df = read_csv_safe(p)
        assert df["id"].iloc[0] == "001"
        assert df["amount"].iloc[0] == "00100"

    def test_nrows_limit(self, tmp_path):
        p = tmp_path / "big.csv"
        lines = ["x\n"] + [f"{i}\n" for i in range(100)]
        p.write_text("".join(lines), encoding="utf-8")
        df = read_csv_safe(p, nrows=5)
        assert len(df) == 5

    def test_raises_on_nonexistent(self, tmp_path):
        with pytest.raises(Exception):
            read_csv_safe(tmp_path / "nope.csv")


# ---------------------------------------------------------------------------
# Manifest & helpers
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_has_13_entries(self):
        assert len(DOWNLOAD_MANIFEST) == 13

    def test_all_entries_have_required_keys(self):
        required = {"filename", "source", "url", "year_start", "year_end", "filter_type", "filters", "description"}
        for entry in DOWNLOAD_MANIFEST:
            missing = required - set(entry.keys())
            assert not missing, f"{entry['filename']} missing keys: {missing}"

    def test_sources_are_valid(self):
        valid = {"FPDS", "USASpending", "FSRS"}
        for entry in DOWNLOAD_MANIFEST:
            assert entry["source"] in valid, f"Bad source: {entry['source']}"

    def test_fpds_count(self):
        fpds = [e for e in DOWNLOAD_MANIFEST if e["source"] == "FPDS"]
        assert len(fpds) == 8

    def test_usaspending_count(self):
        usa = [e for e in DOWNLOAD_MANIFEST if e["source"] == "USASpending"]
        assert len(usa) == 4

    def test_fsrs_count(self):
        fsrs = [e for e in DOWNLOAD_MANIFEST if e["source"] == "FSRS"]
        assert len(fsrs) == 1

    def test_get_expected_filenames(self):
        names = get_expected_filenames()
        assert len(names) == 13
        assert all(n.endswith(".csv") for n in names)

    def test_get_normalized_filename(self):
        assert get_normalized_filename("expansion_fpds_2000_2004_direct.csv") == "normalized_expansion_fpds_2000_2004_direct.csv"

    def test_standard_columns_present(self):
        expected = {"contract_id", "award_date", "vendor_name", "agency_name",
                    "obligated_amount", "pop_state", "source_file", "fiscal_year"}
        assert expected.issubset(set(STANDARD_COLUMNS))

    def test_column_families_keys(self):
        expected = {"date", "vendor", "agency", "amount", "contract_id", "pop_state"}
        assert expected == set(COLUMN_FAMILIES.keys())
