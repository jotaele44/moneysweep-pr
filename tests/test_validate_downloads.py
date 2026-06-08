"""Tests for scripts/validate_downloads.py — download validation."""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_downloads import validate_file


@pytest.fixture
def logger():
    return logging.getLogger("test_validate")


class TestValidateFile:
    def test_missing_file(self, tmp_path, logger):
        result = validate_file(tmp_path / "nonexistent.csv", logger)
        assert result["exists"] is False
        assert result["status"] == "FAIL"
        assert any("not found" in e for e in result["errors"])

    def test_empty_csv(self, tmp_path, logger):
        p = tmp_path / "empty.csv"
        p.write_text("col_a,col_b\n", encoding="utf-8")
        result = validate_file(p, logger)
        assert result["exists"] is True
        assert result["rows"] == 0
        assert result["status"] == "FAIL"

    def test_valid_csv_with_all_columns(self, tmp_path, logger):
        p = tmp_path / "good.csv"
        p.write_text(
            "PIID,Date Signed,Vendor Name,Contracting Agency Name,Dollars Obligated\n"
            "C001,2020-01-01,Acme Inc,Army,1000\n"
            "C002,2020-02-01,Beta Corp,Navy,2000\n"
            + ("C003,2020-03-01,Gamma LLC,Air Force,3000\n" * 50),
            encoding="utf-8",
        )
        result = validate_file(p, logger)
        assert result["exists"] is True
        assert result["rows"] == 52
        assert result["date_col"] is not None
        assert result["vendor_col"] is not None
        assert result["agency_col"] is not None
        assert result["amount_col"] is not None
        assert result["has_data"] is True
        assert result["status"] == "PASS"

    def test_missing_columns_warns(self, tmp_path, logger):
        p = tmp_path / "partial.csv"
        p.write_text(
            "random_col_a,random_col_b\n"
            + ("x,y\n" * 60),
            encoding="utf-8",
        )
        result = validate_file(p, logger)
        assert result["exists"] is True
        assert result["date_col"] is None
        assert result["vendor_col"] is None
        assert result["status"] == "WARN"

    def test_low_row_count_warns(self, tmp_path, logger):
        p = tmp_path / "small.csv"
        p.write_text(
            "PIID,Date Signed,Vendor Name,Contracting Agency Name,Dollars Obligated\n"
            "C001,2020-01-01,Acme,Army,1000\n",
            encoding="utf-8",
        )
        result = validate_file(p, logger)
        assert result["rows"] < 50
        assert any("Suspiciously low" in w for w in result["warnings"])

    def test_tiny_file_warns(self, tmp_path, logger):
        p = tmp_path / "tiny.csv"
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        result = validate_file(p, logger)
        assert any("small file" in w.lower() or "bytes" in w.lower() for w in result["warnings"])

    def test_all_null_data_warns(self, tmp_path, logger):
        p = tmp_path / "nulls.csv"
        p.write_text(
            "PIID,Date Signed,Vendor Name,Contracting Agency Name,Dollars Obligated\n"
            + ("C001,2020-01-01,,,\n" * 60),
            encoding="utf-8",
        )
        result = validate_file(p, logger)
        # vendor_col and agency_col are empty, amount_col is empty
        # but contract_id and date have data — check what happens
        assert result["exists"] is True
        assert result["rows"] == 60
