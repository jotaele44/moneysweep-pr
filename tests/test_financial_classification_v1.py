"""Positive and adversarial regressions for additive financial observations."""

import unittest

from moneysweep.financial_classification_v1 import (
    ObservationError,
    classify_coverage,
    make_observation,
    undisbursed,
)

SHA = "a" * 64


def obs(measure="OBLIGATED", amount="100.25", **overrides):
    fields = dict(
        source_id="official:sample",
        source_record_id="source-row-001",
        source_sha256=SHA,
        source_version="2026-11-02",
        measure_type=measure,
        amount=amount,
        currency="USD",
        period="2026-08-31",
        accounting_basis="cash",
        scope_id="award:stable-001",
        source_field=measure.lower(),
        observation_kind="SNAPSHOT",
    )
    fields.update(overrides)
    return make_observation(**fields)


class FinancialObservationTests(unittest.TestCase):
    def test_stable_id_exact_amount_and_source(self):
        a = obs()
        self.assertEqual(a, obs())
        self.assertEqual(a["amount_decimal"], "100.25")
        self.assertTrue(a["observation_id"].startswith("finobs_"))
        self.assertEqual(a["source_sha256"], SHA)

    def test_distinct_source_record_not_collapsed_by_name(self):
        self.assertNotEqual(
            obs()["observation_id"], obs(source_record_id="source-row-002")["observation_id"]
        )

    def test_valid_balance(self):
        result = undisbursed(obs(), obs("DISBURSED", "20.10"))
        self.assertEqual(result["amount_decimal"], "80.15")
        self.assertEqual(result["evidence_class"], "COMPUTED")

    def test_negative_correction_allowed_in_raw_observation(self):
        self.assertEqual(
            obs("DEOBLIGATED", "-2.75", observation_kind="ACTION")["amount_decimal"], "-2.75"
        )

    def test_false_balance_from_negative_result_blocked(self):
        with self.assertRaises(ObservationError):
            undisbursed(obs("OBLIGATED", "20"), obs("DISBURSED", "25"))

    def test_incompatible_period_and_basis_blocked(self):
        for mutated in (
            obs("DISBURSED", "20", period="2026-09-30"),
            obs("DISBURSED", "20", accounting_basis="accrual"),
            obs("DISBURSED", "20", scope_id="award:another"),
            obs("DISBURSED", "20", source_sha256="b" * 64),
            obs("DISBURSED", "20", source_record_id="other"),
            obs("DISBURSED", "20", observation_kind="PERIOD_FLOW"),
        ):
            with self.subTest(mutated=mutated):
                with self.assertRaises(ObservationError):
                    undisbursed(obs(), mutated)

    def test_float_nan_and_bad_sha_blocked(self):
        for amount in (0.1, float("nan"), float("inf"), "NaN", "Infinity"):
            with self.subTest(amount=amount), self.assertRaises(ObservationError):
                obs(amount=amount)
        with self.assertRaises(ObservationError):
            obs(source_sha256="not-a-hash")

    def test_nonapplicable_cannot_have_value(self):
        with self.assertRaises(ObservationError):
            obs(applicability="NOT_APPLICABLE")
        self.assertIsNone(obs(amount=None, applicability="NOT_APPLICABLE")["amount_decimal"])

    def test_coverage_denominator_conservation(self):
        rows = [
            {"source_record_id": "A", "applicability": "APPLICABLE"},
            {"source_record_id": "B", "applicability": "UNKNOWN"},
            {"source_record_id": "C", "applicability": "NOT_APPLICABLE"},
        ]
        result = classify_coverage(rows, {"A", "B", "C"})
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["unresolved"], 1)
        for bad, expected in (
            (rows[:-1], {"A", "B", "C"}),
            (rows + [rows[0]], {"A", "B", "C"}),
            (rows, {"A", "B"}),
        ):
            with self.assertRaises(ObservationError):
                classify_coverage(bad, expected)

    def test_unknown_not_zero(self):
        self.assertIsNone(obs(amount=None, evidence_class="UNKNOWN")["amount_decimal"])
        self.assertNotEqual(
            obs(amount=None, evidence_class="UNKNOWN")["amount_decimal"],
            obs(amount=0)["amount_decimal"],
        )


if __name__ == "__main__":
    unittest.main()
