"""Offline adversarial suite for bounded grant-award membership pagination."""
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts/enumerate_usaspending_fy2026_pr_grants.py"
spec = importlib.util.spec_from_file_location("grant_pages", PATH)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def item(ident: str, state: str = "PR") -> dict:
    return {
        "generated_internal_id": ident,
        "Recipient Location": {"state_code": state},
        "Primary Place of Performance": {"state_code": state},
    }


def page(rows: list[dict], index: int = 1, has_next: bool = False) -> dict:
    return {"results": rows, "page_metadata": {"page": index, "hasNext": has_next}}


class GrantPagingTests(unittest.TestCase):
    def test_scope_isolation(self):
        recipient = p.filters_for("recipient_pr")
        performance = p.filters_for("performance_pr")
        self.assertIn("recipient_locations", recipient)
        self.assertNotIn("place_of_performance_locations", recipient)
        self.assertIn("place_of_performance_locations", performance)
        self.assertNotIn("recipient_locations", performance)
        self.assertEqual(recipient["time_period"], [p.PERIOD])

    def test_unrecognized_scope_denied(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_LOCATION_SCOPE"):
            p.filters_for("other")

    def test_count_accepts_zero_but_not_bool(self):
        self.assertEqual(p.count_value({"spending_level": "awards", "results": {"grants": 0}}), 0)
        with self.assertRaisesRegex(ValueError, "INADMISSIBLE_COUNT_RESPONSE"):
            p.count_value({"spending_level": "awards", "results": {"grants": True}})

    def test_count_wrong_level_denied(self):
        with self.assertRaisesRegex(ValueError, "INADMISSIBLE_COUNT_RESPONSE"):
            p.count_value({"spending_level": "subawards", "results": {"grants": 1}})

    def test_valid_awards(self):
        rows, nxt = p.validate_page(page([item("111"), item("112")], has_next=True), 1, "recipient_pr")
        self.assertEqual(len(rows), 2)
        self.assertTrue(nxt)

    def test_page_number_drift_denied(self):
        with self.assertRaisesRegex(ValueError, "PAGE_NUMBER_DRIFT"):
            p.validate_page(page([item("111")], index=2), 1, "recipient_pr")

    def test_missing_has_next_denied(self):
        a = page([item("111")])
        del a["page_metadata"]["hasNext"]
        with self.assertRaisesRegex(ValueError, "PAGINATION_STATE_MISSING"):
            p.validate_page(a, 1, "recipient_pr")

    def test_duplicate_within_page_denied(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_ID_WITHIN_PAGE"):
            p.validate_page(page([item("111"), item("111")]), 1, "recipient_pr")

    def test_missing_internal_id_denied(self):
        with self.assertRaisesRegex(ValueError, "AWARD_INTERNAL_ID_MISSING"):
            p.validate_page(page([{"Recipient Location": {"state_code": "PR"}}]), 1, "recipient_pr")

    def test_unmatched_geo_denied(self):
        with self.assertRaisesRegex(ValueError, "FILTERED_GEO_NOT_PR"):
            p.validate_page(page([item("111", "FL")]), 1, "recipient_pr")

    def test_page_limit_denied(self):
        with self.assertRaisesRegex(ValueError, "OVERFULL_PAGE"):
            p.validate_page(page([item(str(i)) for i in range(p.LIMIT + 1)]), 1, "recipient_pr")

    def test_bad_response_denied(self):
        with self.assertRaisesRegex(ValueError, "MALFORMED_AWARD_RESPONSE"):
            p.validate_page({"results": "fake", "page_metadata": {"page": 1, "hasNext": False}},
                            1, "recipient_pr")

    def test_safety_ceiling_below_10k(self):
        self.assertLess(p.MAX_RECORDS, 10_000)
        self.assertEqual(p.LIMIT, 100)


if __name__ == "__main__":
    unittest.main()
