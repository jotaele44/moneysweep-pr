"""Offline adversarial checks for bounded 'other' assistance awards."""

import importlib.util
import unittest
from pathlib import Path

p = (
    Path(__file__).resolve().parents[1]
    / "research/pr_program_registry/enumerate_other_fy2023_fy2024.py"
)
spec = importlib.util.spec_from_file_location("pr_other", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def page(rows, number=1, next_page=False):
    return {"results": rows, "page_metadata": {"page": number, "hasNext": next_page}}


def row(key, st="PR"):
    return {
        "generated_internal_id": key,
        "Recipient Location": {"state_code": st},
        "Primary Place of Performance": {"state_code": st},
    }


class OtherTests(unittest.TestCase):
    def test_code_set_exact(self):
        self.assertEqual(m.CODES, ["09", "11", "F005", "F008", "F009", "F010"])

    def test_exact_fiscal_boundaries(self):
        for year in (2023, 2024):
            self.assertEqual(
                m.filters("recipient_pr", year)["time_period"],
                [{"start_date": f"{year - 1}-10-01", "end_date": f"{year}-09-30"}],
            )

    def test_receipt_schema_matches_fiscal_year(self):
        for year in (2023, 2024):
            self.assertEqual(
                m.receipt_schema(year),
                f"pr_registry_fy{year}_expanded_other_award_ids_v1",
            )

    def test_receipt_schema_invalid_year_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_YEAR"):
            m.receipt_schema(2025)

    def test_out_of_scope_year_denied(self):
        for year in (2022, 2025, 2026):
            with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_YEAR"):
                m.filters("recipient_pr", year)

    def test_geo_independent(self):
        self.assertNotIn("recipient_locations", m.filters("performance_pr", 2024))
        self.assertNotIn("place_of_performance_locations", m.filters("recipient_pr", 2024))

    def test_bad_geo_denied(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_GEOGRAPHY"):
            m.filters("global", 2024)

    def test_positive(self):
        rows, hasnext = m.page(page([row("1")]), "recipient_pr", 1)
        self.assertEqual(len(rows), 1)
        self.assertFalse(hasnext)

    def test_missing_id(self):
        with self.assertRaisesRegex(ValueError, "MISSING_AWARD_STABLE_ID"):
            m.page(page([{"Recipient Location": {"state_code": "PR"}}]), "recipient_pr", 1)

    def test_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_ID_WITHIN_PAGE"):
            m.page(page([row("a"), row("a")]), "recipient_pr", 1)

    def test_not_pr_denied(self):
        with self.assertRaisesRegex(ValueError, "FILTERED_GEOGRAPHY_NOT_PR"):
            m.page(page([row("a", "FL")]), "recipient_pr", 1)

    def test_unexpected_page_denied(self):
        with self.assertRaisesRegex(ValueError, "PAGINATION_DRIFT"):
            m.page(page([row("1")], number=2), "recipient_pr", 1)

    def test_missing_hasnext_denied(self):
        with self.assertRaisesRegex(ValueError, "PAGINATION_DRIFT"):
            m.page({"results": [row("1")], "page_metadata": {"page": 1}}, "recipient_pr", 1)

    def test_wrong_level_denied(self):
        with self.assertRaisesRegex(ValueError, "WRONG_SPENDING_LEVEL"):
            m.count({"spending_level": "subawards", "results": {"other": 12}})

    def test_boolean_count_denied(self):
        with self.assertRaisesRegex(ValueError, "BAD_OTHER_COUNT"):
            m.count({"spending_level": "awards", "results": {"other": True}})

    def test_negative_count_denied(self):
        with self.assertRaisesRegex(ValueError, "BAD_OTHER_COUNT"):
            m.count({"spending_level": "awards", "results": {"other": -1}})

    def test_max_below_suspected_api_cap(self):
        self.assertLess(m.MAX_AWARDS, 10000)


if __name__ == "__main__":
    unittest.main()
