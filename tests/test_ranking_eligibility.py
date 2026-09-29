from moneysweep.ranking.eligibility import evaluate_ranking_row


def _valid_row():
    return {
        "identity_state": "PASS",
        "binding_basis": "STABLE_ID",
        "stable_id": "UEI:ABC123",
        "origin": "AUTHORITATIVE_API",
        "source_id": "fac",
        "source_snapshot_sha256": "a" * 64,
        "metric_name": "federal_expenditures",
        "metric_value": "1250000.00",
        "metric_unit": "USD",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "geographic_scope": "Puerto Rico",
    }


def test_valid_row_passes_without_ranking():
    decision = evaluate_ranking_row(_valid_row())
    assert decision.eligible is True
    assert decision.state == "PASS"
    assert str(decision.metric_value) == "1250000.00"


def test_seed_origin_is_blocked():
    row = _valid_row()
    row["origin"] = "FALLBACK_SEED"
    decision = evaluate_ranking_row(row)
    assert decision.eligible is False
    assert "ORIGIN_INELIGIBLE" in decision.reasons


def test_name_only_identity_is_blocked():
    row = _valid_row()
    row["binding_basis"] = "NORMALIZED_NAME_ONLY"
    row["stable_id"] = ""
    decision = evaluate_ranking_row(row)
    assert decision.eligible is False
    assert "BINDING_BASIS_INELIGIBLE" in decision.reasons
    assert "STABLE_ID_MISSING" in decision.reasons


def test_missing_unit_period_scope_and_hash_fail_closed():
    row = _valid_row()
    for key in (
        "metric_unit",
        "period_start",
        "period_end",
        "geographic_scope",
        "source_snapshot_sha256",
    ):
        row[key] = ""
    decision = evaluate_ranking_row(row)
    assert decision.eligible is False
    assert len(decision.reasons) == 5


def test_invalid_and_nonfinite_values_are_not_zero_coerced():
    for value in ("not-a-number", "NaN", "Infinity"):
        row = _valid_row()
        row["metric_value"] = value
        decision = evaluate_ranking_row(row)
        assert decision.eligible is False
        assert decision.metric_value is None
