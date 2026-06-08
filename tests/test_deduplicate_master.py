"""Tests for scripts/deduplicate_master.py — cross-file deduplication."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.deduplicate_master import deduplicate, load_all_normalized, main as dedup_main


import logging


@pytest.fixture
def logger():
    return logging.getLogger("test_dedup")


class TestDeduplicate:
    def test_removes_cross_file_duplicates(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001", "C002"],
                "award_date": ["2020-01-01", "2020-01-01", "2021-06-15"],
                "vendor_name": ["ACME INC", "ACME INC", "BETA LLC"],
                "obligated_amount": ["1000.00", "1000.00", "2000.00"],
                "source_file": ["fpds_direct", "fpds_vendor", "fpds_direct"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 2

    def test_no_duplicates_unchanged(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C002", "C003"],
                "award_date": ["2020-01-01", "2021-06-15", "2022-03-10"],
                "vendor_name": ["ACME INC", "BETA LLC", "GAMMA CORP"],
                "obligated_amount": ["1000.00", "2000.00", "3000.00"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 3

    def test_empty_dataframe(self, logger):
        df = pd.DataFrame()
        result = deduplicate(df, logger)
        assert result.empty

    def test_missing_dedup_cols_returns_unchanged(self, logger):
        df = pd.DataFrame({"random_col": ["a", "b", "c"]})
        result = deduplicate(df, logger)
        assert len(result) == 3

    def test_source_file_consolidated(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME INC", "ACME INC"],
                "obligated_amount": ["1000.00", "1000.00"],
                "source_file": ["fpds_direct", "fpds_vendor"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 1
        # Source files should be merged into a comma-joined string
        src = result.iloc[0]["source_file"]
        assert "fpds_direct" in src
        assert "fpds_vendor" in src


class TestLoadAllNormalized:
    def test_empty_dir_returns_empty(self, tmp_project, logger):
        result = load_all_normalized(tmp_project, logger)
        assert result.empty

    def test_loads_multiple_files(self, tmp_project, logger):
        processed = tmp_project / "data" / "staging" / "processed"
        for i in range(3):
            df = pd.DataFrame(
                {
                    "contract_id": [f"C{i:03d}"],
                    "vendor_name": [f"VENDOR {i}"],
                    "award_date": ["2020-01-01"],
                    "obligated_amount": [str(1000 * (i + 1))],
                }
            )
            df.to_csv(processed / f"normalized_expansion_file{i}.csv", index=False)

        result = load_all_normalized(tmp_project, logger)
        assert len(result) == 3


class TestMain:
    def test_empty_processed_dir(self, tmp_project):
        stats = dedup_main(tmp_project)
        assert stats["master_rows"] == 0
        assert stats["duplicates_removed"] == 0
        assert stats["output_path"] is None

    def test_builds_master(self, tmp_project):
        processed = tmp_project / "data" / "staging" / "processed"
        # File a: C001 (shared) + C002 (unique)
        pd.DataFrame(
            {
                "contract_id": ["C001", "C002"],
                "award_date": ["2020-01-01", "2021-05-10"],
                "vendor_name": ["ACME INC", "GAMMA LLC"],
                "obligated_amount": ["5000.00", "8000.00"],
                "source_file": ["normalized_expansion_a", "normalized_expansion_a"],
            }
        ).to_csv(processed / "normalized_expansion_a.csv", index=False)

        # File b: C001 (shared, duplicate) + C003 (unique)
        pd.DataFrame(
            {
                "contract_id": ["C001", "C003"],
                "award_date": ["2020-01-01", "2022-03-15"],
                "vendor_name": ["ACME INC", "DELTA CORP"],
                "obligated_amount": ["5000.00", "3000.00"],
                "source_file": ["normalized_expansion_b", "normalized_expansion_b"],
            }
        ).to_csv(processed / "normalized_expansion_b.csv", index=False)

        stats = dedup_main(tmp_project)
        # 4 rows in, C001 duplicated once → 3 unique rows
        assert stats["master_rows"] == 3
        assert stats["duplicates_removed"] == 1
        assert (tmp_project / "data" / "staging" / "processed" / "pr_contracts_master.csv").exists()


# ---------------------------------------------------------------------------
# Dedup-key edge cases — pin current behavior (incl. known limitations).
#
# The composite dedup key is (contract_id, award_date, vendor_name,
# obligated_amount). The function does NOT normalize any of those fields
# before comparing — it uses raw `drop_duplicates`. The tests below pin
# that as the current contract so future normalization changes are explicit.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDedupEdgeCases:
    def test_vendor_name_trailing_whitespace_not_collapsed(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME", "ACME "],
                "obligated_amount": ["1000", "1000"],
                "source_file": ["a", "b"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 2

    def test_vendor_name_case_variance_not_collapsed(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["acme inc", "ACME INC"],
                "obligated_amount": ["1000", "1000"],
                "source_file": ["a", "b"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 2

    def test_amount_string_format_variance_not_collapsed(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME", "ACME"],
                "obligated_amount": ["1000", "1000.00"],
                "source_file": ["a", "b"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 2

    def test_amount_with_currency_symbols_not_collapsed(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME", "ACME"],
                "obligated_amount": ["$1,000.00", "1000"],
                "source_file": ["a", "b"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 2

    def test_nan_in_dedup_key_kept_separate(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME", "ACME"],
                "obligated_amount": [np.nan, np.nan],
                "source_file": ["a", "b"],
            }
        )
        result = deduplicate(df, logger)
        # pandas drop_duplicates treats NaN as equal under default semantics,
        # so these rows collapse to one. Pinning current behavior.
        assert len(result) == 1

    def test_source_file_aggregation_with_null_one_side(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME", "ACME"],
                "obligated_amount": ["1000", "1000"],
                "source_file": ["a", None],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 1
        # null side is dropped, not joined as "a,"
        assert result.iloc[0]["source_file"] == "a"

    def test_source_file_aggregation_deduplicates_within_group(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001", "C001"],
                "award_date": ["2020-01-01", "2020-01-01", "2020-01-01"],
                "vendor_name": ["ACME", "ACME", "ACME"],
                "obligated_amount": ["1000", "1000", "1000"],
                "source_file": ["a", "b", "a"],
            }
        )
        result = deduplicate(df, logger)
        assert len(result) == 1
        # set-based, sorted
        assert result.iloc[0]["source_file"] == "a,b"

    def test_malformed_award_date_compared_as_string(self, logger):
        df = pd.DataFrame(
            {
                "contract_id": ["C001", "C001"],
                "award_date": ["not-a-date", "not-a-date"],
                "vendor_name": ["ACME", "ACME"],
                "obligated_amount": ["1000", "1000"],
                "source_file": ["a", "b"],
            }
        )
        result = deduplicate(df, logger)
        # bytewise-identical strings → collapse
        assert len(result) == 1
