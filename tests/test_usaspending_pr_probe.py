"""Strict offline USAspending page and geography controls; no network."""
import importlib.util
import json
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "scripts" / "probe_usaspending_pr_awards.py"
spec = importlib.util.spec_from_file_location("usaspending_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def response(rows, has_next=False, page=1):
    return json.dumps({
        "results": rows,
        "page_metadata": {"page": page, "hasNext": has_next},
    }).encode("utf-8")


class ProbeTests(unittest.TestCase):
    def test_distinct_geographies(self):
        recipient = json.loads(probe.request_body("recipient_pr"))
        performance = json.loads(probe.request_body("performance_pr"))
        self.assertEqual(
            recipient["filters"]["recipient_locations"],
            [{"country": "USA", "state": "PR"}],
        )
        self.assertNotIn("place_of_performance_locations", recipient["filters"])
        self.assertIn("place_of_performance_locations", performance["filters"])
        self.assertNotIn("recipient_locations", performance["filters"])
        self.assertEqual(recipient["filters"]["award_type_codes"], ["02", "03", "04", "05"])
        self.assertFalse(recipient["subawards"])

    def test_disallow_unknown_scope(self):
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_LOCATION_SCOPE"):
            probe.request_body("unbounded")

    def test_valid_bounded_page_never_certifies(self):
        item = probe.parse_page(
            response([{"generated_internal_id": "A1"}], has_next=True),
            "recipient_pr",
        )
        self.assertEqual(item["rows_observed"], 1)
        self.assertTrue(item["has_next"])
        self.assertFalse(item["full_period_complete"])
        self.assertFalse(item["public_program_identity_adjudicated"])

    def test_second_page_rejected(self):
        with self.assertRaisesRegex(ValueError, "API_PAGINATION_NOT_VERIFIABLE"):
            probe.parse_page(response([{"generated_internal_id": "A1"}], page=2), "recipient_pr")

    def test_missing_metadata_rejected(self):
        with self.assertRaisesRegex(ValueError, "API_RESULTS_OR_METADATA_MISSING"):
            probe.parse_page(b'{"results":[{"generated_internal_id":"A"}]}', "performance_pr")

    def test_duplicate_award_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_AWARD_ON_PAGE"):
            probe.parse_page(
                response([
                    {"generated_internal_id": "A1"},
                    {"generated_internal_id": "A1"},
                ]),
                "performance_pr",
            )

    def test_missing_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, "MISSING_AWARD_IDENTITY"):
            probe.parse_page(response([{"Award ID": "KNOWN"}]), "recipient_pr")

    def test_empty_response_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "NO_ROWS_PROVES_NOTHING"):
            probe.parse_page(response([]), "recipient_pr")


if __name__ == "__main__":
    unittest.main()
