"""Tests for scripts/validate_expansion_coverage.py — coverage validation."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_expansion_coverage import (
    COVERAGE_YEARS,
    CRITICAL_2007_FILES,
    check_2007_gap,
    check_file_coverage,
)


class TestCheckFileCoverage:
    def test_missing_file(self, tmp_path):
        result = check_file_coverage(tmp_path / "nonexistent.csv")
        assert result["exists"] is False
        assert len(result["fiscal_years"]) == 0

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("fiscal_year,vendor_name\n", encoding="utf-8")
        result = check_file_coverage(p)
        assert result["exists"] is True
        assert result["rows"] == 0
        assert len(result["fiscal_years"]) == 0

    def test_file_with_fiscal_years(self, tmp_path):
        p = tmp_path / "data.csv"
        df = pd.DataFrame(
            {
                "fiscal_year": [2005, 2006, 2007, 2008, 2005],
                "vendor_name": ["A", "B", "C", "D", "E"],
            }
        )
        df.to_csv(p, index=False)
        result = check_file_coverage(p)
        assert result["exists"] is True
        assert result["rows"] == 5
        assert result["fiscal_years"] == {2005, 2006, 2007, 2008}

    def test_filters_out_of_range_years(self, tmp_path):
        p = tmp_path / "outliers.csv"
        df = pd.DataFrame(
            {
                "fiscal_year": [1990, 2005, 2030],
                "vendor_name": ["A", "B", "C"],
            }
        )
        df.to_csv(p, index=False)
        result = check_file_coverage(p)
        # Only 2005 is within 2000-2026 range
        assert 2005 in result["fiscal_years"]
        assert 1990 not in result["fiscal_years"]
        assert 2030 not in result["fiscal_years"]


class TestCheck2007Gap:
    def test_2007_present(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"fiscal_years": {2005, 2006, 2007, 2008}},
            CRITICAL_2007_FILES[1]: {"fiscal_years": {2005, 2006, 2007, 2008}},
        }
        assert check_2007_gap(matrix) is True

    def test_2007_missing_in_one(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"fiscal_years": {2005, 2006, 2007, 2008}},
            CRITICAL_2007_FILES[1]: {"fiscal_years": {2005, 2006, 2008}},
        }
        assert check_2007_gap(matrix) is False

    def test_2007_missing_in_both(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"fiscal_years": {2005, 2006, 2008}},
            CRITICAL_2007_FILES[1]: {"fiscal_years": {2005, 2006, 2008}},
        }
        assert check_2007_gap(matrix) is False

    def test_empty_matrix(self):
        # Empty matrix means critical files are missing → 2007 gap is NOT verified
        assert check_2007_gap({}) is False

    def test_missing_file_entry(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"fiscal_years": {2005, 2006, 2007, 2008}},
            # CRITICAL_2007_FILES[1] missing entirely
        }
        assert check_2007_gap(matrix) is False


class TestCoverageYears:
    def test_range(self):
        assert COVERAGE_YEARS == list(range(2000, 2026))
        assert len(COVERAGE_YEARS) == 26

    def test_critical_files_exist(self):
        assert len(CRITICAL_2007_FILES) == 2
        assert all("2005_2008" in f for f in CRITICAL_2007_FILES)
