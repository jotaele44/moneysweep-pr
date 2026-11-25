"""Adversarial compatibility tests for source-native financial observations."""

import unittest

from moneysweep.financial_classification_v1 import ObservationError
from moneysweep.financial_flow_compatibility_v1 import adapt_legacy_flows


def legacy(flow_id="unstable-1", amount="100.00", **overrides):
    row = {
        "flow_id": flow_id,
        "source_system": "openfema_v2",
        "source_file": "fema_pa_projects_v2.parquet",
        "amount_type": "federal_share_obligated",
        "amount": amount,
    }
    row.update(overrides)
    return row


def verified_binding(**overrides):
    bound = {
        "source_id": "official:fema-pa",
        "source_record_id": "project:stable-002",
        "source_sha256": "a" * 64,
        "source_field": "federal_share_obligated",
        "source_version": "2026-11-12",
        "scope_id": "project:stable-002",
        "measure_type": "OBLIGATED",
        "period": "2026-08-31",
        "accounting_basis": "accrual",
        "currency": "USD",
        "observation_kind": "SNAPSHOT",
        "source_amount": "100.00",
        "expected_source_system": "openfema_v2",
        "expected_source_file": "fema_pa_projects_v2.parquet",
        "expected_amount_type": "federal_share_obligated",
    }
    bound.update(overrides)
    return bound


def adapt(rows, bindings=None, expected=None):
    return adapt_legacy_flows(
        rows,
        bindings=bindings if bindings is not None else {},
        expected_flow_ids=expected if expected is not None else {r["flow_id"] for r in rows},
    )


class CompatibilityTests(unittest.TestCase):
    def test_bound_row_has_canonical_identity_without_overwriting_legacy_id(self):
        row = legacy()
        result = adapt([row], {"unstable-1": verified_binding()})
        self.assertEqual(result["mapped"], 1)
        self.assertEqual(result["unresolved"], 0)
        self.assertEqual(result["observations"][0]["legacy_flow_id"], "unstable-1")
        self.assertEqual(result["observations"][0]["observation"]["amount_decimal"], "100.00")
        self.assertEqual(row["flow_id"], "unstable-1")
        self.assertFalse(result["source_universe_certified"])
        self.assertFalse(result["promotion_authorized"])

    def test_unbound_rows_remain_unresolved_not_assumed_zero(self):
        result = adapt([legacy()])
        self.assertEqual(result["mapped"], 0)
        self.assertEqual(result["unresolved"], 1)
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["unresolved_rows"][0]["reason"], "SOURCE_BINDING_UNVERIFIED")

    def test_missing_or_unexpected_rows_fail(self):
        with self.assertRaises(ObservationError):
            adapt([legacy()], expected={"unstable-1", "unstable-2"})
        with self.assertRaises(ObservationError):
            adapt([legacy()], expected={"unexpected"})
        with self.assertRaises(ObservationError):
            adapt([legacy(), legacy()])

    def test_stale_or_extra_bindings_fail(self):
        with self.assertRaises(ObservationError):
            adapt([legacy()], {"other-flow": verified_binding()})

    def test_incomplete_binding_fails(self):
        for key in verified_binding():
            bound = verified_binding()
            del bound[key]
            with self.subTest(field=key), self.assertRaises(ObservationError):
                adapt([legacy()], {"unstable-1": bound})

    def test_unverified_accounting_semantics_not_guessed(self):
        row = legacy(amount_type="grant_amount")
        self.assertEqual(adapt([row])["unresolved"], 1)
        with self.assertRaises(ObservationError):
            adapt([row], {"unstable-1": verified_binding()})

    def test_binding_source_system_and_file_mismatch_fail(self):
        for field, value in (
            ("source_system", "other"),
            ("source_file", "another.parquet"),
            ("amount_type", "drawdown"),
        ):
            with self.subTest(field=field), self.assertRaises(ObservationError):
                adapt([legacy(**{field: value})], {"unstable-1": verified_binding()})

    def test_mismatch_amount_and_float_fail_closed(self):
        for amount in ("99.99", "garbled", 100.0, None):
            with self.subTest(amount=amount), self.assertRaises(ObservationError):
                adapt([legacy(amount=amount)], {"unstable-1": verified_binding()})
        with self.assertRaises(ObservationError):
            adapt([legacy()], {"unstable-1": verified_binding(source_amount="101.00")})

    def test_source_sha_required(self):
        with self.assertRaises(ObservationError):
            adapt([legacy()], {"unstable-1": verified_binding(source_sha256="invalid")})

    def test_duplicate_native_observation_not_double_counted(self):
        rows = [legacy(flow_id="unstable-1"), legacy(flow_id="unstable-2")]
        bindings = {"unstable-1": verified_binding(), "unstable-2": verified_binding()}
        with self.assertRaises(ObservationError):
            adapt(rows, bindings)

    def test_empty_inventory_is_not_certification(self):
        result = adapt([], expected=set())
        self.assertEqual(result["legacy_rows"], 0)
        self.assertFalse(result["source_universe_certified"])
        self.assertFalse(result["promotion_authorized"])


if __name__ == "__main__":
    unittest.main()
