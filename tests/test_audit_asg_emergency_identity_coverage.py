from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.audit_asg_emergency_identity_coverage import audit


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "control_number",
        "vendor_name",
        "vendor_registration_id",
        "vendor_identity_scheme",
        "vendor_identity_state",
        "obligation_amount",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_coverage(path: Path, total) -> Path:
    path.write_text(
        json.dumps(
            {
                "contracts": [
                    {
                        "source_id": "asg_emergency_purchases",
                        "authoritative_universe_total": total,
                        "minimum_coverage_pct": 95.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
def test_missing_materialization_fails_closed(tmp_path: Path):
    result = audit(tmp_path / "missing.csv", _write_coverage(tmp_path / "coverage.json", 1))
    assert result["state"] == "OPEN_NOT_MATERIALIZED"
    assert result["leaderboardPromotionReady"] is False
    assert result["wholeSourceLeaderboardReady"] is False
    assert result["boundedSourceNativeLeaderboardReady"] is False
    assert result["blockingResidue"] == ["SOURCE_NOT_MATERIALIZED"]
    assert result["boundedSourceNativeBlockingResidue"] == ["SOURCE_NOT_MATERIALIZED"]


@pytest.mark.unit
def test_source_native_subset_is_diagnostic_but_name_only_residue_blocks(tmp_path: Path):
    source = _write_csv(
        tmp_path / "purchases.csv",
        [
            {
                "control_number": "26-ASG-AAA-0001",
                "vendor_name": "A1 Generator Services Incorporated",
                "vendor_registration_id": "28546",
                "vendor_identity_scheme": "asg_licitador_id",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "$8,575.00",
            },
            {
                "control_number": "22-ASG-TTF-001",
                "vendor_name": "Legacy Vendor",
                "vendor_registration_id": "",
                "vendor_identity_scheme": "",
                "vendor_identity_state": "UNRESOLVED_NAME_ONLY",
                "obligation_amount": "$100.00",
            },
        ],
    )
    result = audit(source, _write_coverage(tmp_path / "coverage.json", 2))
    assert result["identity"]["sourceNativeRows"] == 1
    assert result["identity"]["nameOnlyRows"] == 1
    assert result["financialValue"]["candidateRows"] == 1
    assert result["financialValue"]["candidateAmountTotal"] == 8575.0
    assert "NAME_ONLY_VENDOR_IDENTITY_RESIDUE" in result["blockingResidue"]
    assert result["wholeSourceLeaderboardReady"] is False
    assert result["boundedSourceNativeBlockingResidue"] == []
    assert result["boundedSourceNativeLeaderboardReady"] is True
    assert result["boundedSourceNativeScope"]["outOfScopeNameOnlyRows"] == 1
    assert result["boundedSourceNativeScope"]["claimsCompleteASGEmergencyUniverse"] is False
    assert result["leaderboardPromotionReady"] is False


@pytest.mark.unit
def test_unmeasured_drifted_denominator_blocks_even_clean_identity_rows(tmp_path: Path):
    source = _write_csv(
        tmp_path / "purchases.csv",
        [
            {
                "control_number": "26-ASG-AAA-0001",
                "vendor_name": "A1 Generator Services Incorporated",
                "vendor_registration_id": "28546",
                "vendor_identity_scheme": "asg_licitador_id",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "$8,575.00",
            }
        ],
    )
    result = audit(source, _write_coverage(tmp_path / "coverage.json", None))
    assert result["coverage"]["state"] == "UNVERIFIABLE_DENOMINATOR"
    assert "CURRENT_DENOMINATOR_UNMEASURED" in result["blockingResidue"]
    assert "CURRENT_DENOMINATOR_UNMEASURED" in result["boundedSourceNativeBlockingResidue"]
    assert result["boundedSourceNativeLeaderboardReady"] is False
    assert result["leaderboardPromotionReady"] is False


@pytest.mark.unit
def test_clean_complete_source_can_become_promotion_ready(tmp_path: Path):
    source = _write_csv(
        tmp_path / "purchases.csv",
        [
            {
                "control_number": "26-ASG-AAA-0001",
                "vendor_name": "A1 Generator Services Incorporated",
                "vendor_registration_id": "28546",
                "vendor_identity_scheme": "asg_licitador_id",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "$8,575.00",
            },
            {
                "control_number": "26-ASG-AAA-0002",
                "vendor_name": "Caribbean Composting Inc.",
                "vendor_registration_id": "4381",
                "vendor_identity_scheme": "asg_licitador_id",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "$47,200.00",
            },
        ],
    )
    result = audit(source, _write_coverage(tmp_path / "coverage.json", 2))
    assert result["coverage"]["state"] == "MEETS_CONTRACT"
    assert result["blockingResidue"] == []
    assert result["boundedSourceNativeBlockingResidue"] == []
    assert result["wholeSourceLeaderboardReady"] is True
    assert result["boundedSourceNativeLeaderboardReady"] is True
    assert result["leaderboardPromotionReady"] is True


@pytest.mark.unit
def test_below_contract_coverage_never_promotes(tmp_path: Path):
    source = _write_csv(
        tmp_path / "purchases.csv",
        [
            {
                "control_number": "26-ASG-AAA-0001",
                "vendor_name": "A1 Generator Services Incorporated",
                "vendor_registration_id": "28546",
                "vendor_identity_scheme": "asg_licitador_id",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "$8,575.00",
            }
        ],
    )
    result = audit(source, _write_coverage(tmp_path / "coverage.json", 2))
    assert result["coverage"]["state"] == "BELOW_CONTRACT"
    assert "COVERAGE_NOT_CLOSED" in result["blockingResidue"]
    assert "COVERAGE_NOT_CLOSED" in result["boundedSourceNativeBlockingResidue"]
    assert result["boundedSourceNativeLeaderboardReady"] is False
    assert result["leaderboardPromotionReady"] is False


@pytest.mark.unit
def test_wrong_identity_namespace_blocks_promotion(tmp_path: Path):
    source = _write_csv(
        tmp_path / "purchases.csv",
        [
            {
                "control_number": "26-ASG-AAA-0001",
                "vendor_name": "A1 Generator Services Incorporated",
                "vendor_registration_id": "28546",
                "vendor_identity_scheme": "unscoped_numeric",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "$8,575.00",
            }
        ],
    )
    result = audit(source, _write_coverage(tmp_path / "coverage.json", 1))
    assert result["identity"]["identitySchemeMismatchRows"] == 1
    assert "IDENTITY_SCHEME_MISMATCH" in result["blockingResidue"]
    assert "IDENTITY_SCHEME_MISMATCH" in result["boundedSourceNativeBlockingResidue"]
    assert result["boundedSourceNativeLeaderboardReady"] is False
    assert result["leaderboardPromotionReady"] is False


@pytest.mark.unit
def test_source_native_invalid_amount_blocks_bounded_scope(tmp_path: Path):
    source = _write_csv(
        tmp_path / "purchases.csv",
        [
            {
                "control_number": "26-ASG-AAA-0001",
                "vendor_name": "A1 Generator Services Incorporated",
                "vendor_registration_id": "28546",
                "vendor_identity_scheme": "asg_licitador_id",
                "vendor_identity_state": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "obligation_amount": "",
            },
            {
                "control_number": "26-ASG-AAA-0002",
                "vendor_name": "Legacy Vendor",
                "vendor_registration_id": "",
                "vendor_identity_scheme": "",
                "vendor_identity_state": "UNRESOLVED_NAME_ONLY",
                "obligation_amount": "$100.00",
            },
        ],
    )
    result = audit(source, _write_coverage(tmp_path / "coverage.json", 2))
    assert result["financialValue"]["sourceNativeInvalidAmountRows"] == 1
    assert "SOURCE_NATIVE_INVALID_AMOUNT_RESIDUE" in result["boundedSourceNativeBlockingResidue"]
    assert result["boundedSourceNativeLeaderboardReady"] is False
