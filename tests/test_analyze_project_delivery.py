"""Tests for analyze_project_delivery — sub-scorers and composite score."""

import pandas as pd
import pytest

from scripts.analyze_project_delivery import (
    _safe_float,
    _match_name,
    _fema_score,
    _cor3_score,
    _usace_ok,
    _eqb_violations,
    WEIGHT_FEMA_COMPLETION,
    WEIGHT_COR3_DISBURSEMENT,
    WEIGHT_USACE_PERMIT,
    WEIGHT_EQB_COMPLIANCE,
    RISK_HIGH,
    RISK_MEDIUM,
)


def test_weights_sum_to_one():
    total = (
        WEIGHT_FEMA_COMPLETION
        + WEIGHT_COR3_DISBURSEMENT
        + WEIGHT_USACE_PERMIT
        + WEIGHT_EQB_COMPLIANCE
    )
    assert abs(total - 1.0) < 1e-9


def test_safe_float_valid():
    assert _safe_float("3.14") == pytest.approx(3.14)


def test_safe_float_none():
    assert _safe_float(None) == 0.0


def test_safe_float_bad_string():
    assert _safe_float("n/a") == 0.0


# ---------------------------------------------------------------------------
# _match_name
# ---------------------------------------------------------------------------

def test_match_name_exact_hit():
    df = pd.DataFrame({"name": ["ACME CORP", "OTHER INC"]})
    result = _match_name("ACME CORP", df, "name")
    assert len(result) == 1
    assert result.iloc[0]["name"] == "ACME CORP"


def test_match_name_empty_df():
    result = _match_name("ACME", pd.DataFrame(), "name")
    assert result.empty


def test_match_name_empty_entity():
    df = pd.DataFrame({"name": ["ACME"]})
    result = _match_name("", df, "name")
    assert result.empty


def test_match_name_no_hit():
    df = pd.DataFrame({"name": ["TOTALLY DIFFERENT COMPANY"]})
    result = _match_name("ACME CORP", df, "name")
    assert result.empty


# ---------------------------------------------------------------------------
# _fema_score
# ---------------------------------------------------------------------------

def test_fema_score_neutral_on_empty():
    n, rate = _fema_score("ACME", pd.DataFrame())
    assert n == 0
    assert rate == 0.5


def test_fema_score_all_complete():
    df = pd.DataFrame({
        "recipient_name_normalized": ["ACME CORP", "ACME CORP"],
        "project_status": ["completed", "closed"],
    })
    n, rate = _fema_score("ACME CORP", df)
    assert n == 2
    assert rate == pytest.approx(1.0)


def test_fema_score_partial_complete():
    df = pd.DataFrame({
        "recipient_name_normalized": ["ACME CORP", "ACME CORP", "ACME CORP", "ACME CORP"],
        "project_status": ["completed", "open", "open", "open"],
    })
    n, rate = _fema_score("ACME CORP", df)
    assert n == 4
    assert rate == pytest.approx(0.25)


def test_fema_score_no_status_column():
    df = pd.DataFrame({"recipient_name_normalized": ["ACME CORP"]})
    n, rate = _fema_score("ACME CORP", df)
    assert n == 1
    assert rate == 0.5   # neutral when status column absent


# ---------------------------------------------------------------------------
# _cor3_score
# ---------------------------------------------------------------------------

def test_cor3_score_neutral_on_empty():
    n, rate = _cor3_score("ACME", pd.DataFrame())
    assert n == 0
    assert rate == 0.5


def test_cor3_score_computes_mean():
    df = pd.DataFrame({
        "applicant_normalized": ["ACME CORP", "ACME CORP"],
        "disbursement_rate": ["0.80", "0.40"],
    })
    n, rate = _cor3_score("ACME CORP", df)
    assert n == 2
    assert rate == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# _usace_ok
# ---------------------------------------------------------------------------

def test_usace_ok_neutral_on_empty():
    assert _usace_ok("ACME", pd.DataFrame()) == 1


def test_usace_ok_active_permit():
    df = pd.DataFrame({
        "applicant_normalized": ["ACME CORP"],
        "status": ["active"],
    })
    assert _usace_ok("ACME CORP", df) == 1


def test_usace_ok_no_record():
    df = pd.DataFrame({
        "applicant_normalized": ["TOTALLY DIFFERENT"],
        "status": ["active"],
    })
    assert _usace_ok("ACME CORP", df) == 0


def test_usace_ok_expired_permit():
    df = pd.DataFrame({
        "applicant_normalized": ["ACME CORP"],
        "status": ["expired"],
    })
    assert _usace_ok("ACME CORP", df) == 0


# ---------------------------------------------------------------------------
# _eqb_violations
# ---------------------------------------------------------------------------

def test_eqb_violations_neutral_on_empty():
    flag, count = _eqb_violations("ACME", pd.DataFrame())
    assert flag == 0
    assert count == 0


def test_eqb_violations_with_violations():
    df = pd.DataFrame({
        "facility_normalized": ["ACME CORP"],
        "violation_count": ["3"],
    })
    flag, count = _eqb_violations("ACME CORP", df)
    assert flag == 1
    assert count == 3


def test_eqb_violations_zero_violations():
    df = pd.DataFrame({
        "facility_normalized": ["ACME CORP"],
        "violation_count": ["0"],
    })
    flag, count = _eqb_violations("ACME CORP", df)
    assert flag == 0
    assert count == 0


# ---------------------------------------------------------------------------
# Risk tier thresholds
# ---------------------------------------------------------------------------

def test_risk_tier_boundary_values():
    assert RISK_HIGH < RISK_MEDIUM
    assert RISK_HIGH >= 1
    assert RISK_MEDIUM <= 99


def test_score_max_is_100():
    # All sub-scores at maximum → composite = 100
    score = (
        WEIGHT_FEMA_COMPLETION * 1.0 * 100
        + WEIGHT_COR3_DISBURSEMENT * 1.0 * 100
        + WEIGHT_USACE_PERMIT * 1 * 100
        + WEIGHT_EQB_COMPLIANCE * (1 - 0) * 100
    )
    assert score == pytest.approx(100.0)


def test_score_min_is_0():
    score = (
        WEIGHT_FEMA_COMPLETION * 0.0 * 100
        + WEIGHT_COR3_DISBURSEMENT * 0.0 * 100
        + WEIGHT_USACE_PERMIT * 0 * 100
        + WEIGHT_EQB_COMPLIANCE * (1 - 1) * 100
    )
    assert score == pytest.approx(0.0)
