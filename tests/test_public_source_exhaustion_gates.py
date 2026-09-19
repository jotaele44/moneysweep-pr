from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXHAUSTION = ROOT / "data" / "manifests" / "macro" / "jp_public_exhaustion_v1.json"
QUESTIONNAIRES = ROOT / "data" / "manifests" / "macro" / "jp_questionnaire_universe_v1.json"
BOP = ROOT / "data" / "manifests" / "macro" / "jp_bop_iip_lineage_v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_records_gate_remains_closed_while_public_artifacts_are_unretrieved() -> None:
    audit = _load(EXHAUSTION)
    assert audit["public_source_exhaustion"] == "OPEN"
    assert audit["foia_or_public_records_eligibility"] == "NOT_YET_REACHED"
    assert any(workbook["raw_bytes_frozen"] is False for workbook in audit["mandatory_workbooks"])


def test_unretrieved_workbook_is_not_encoded_as_source_absence() -> None:
    audit = _load(EXHAUSTION)
    for workbook in audit["mandatory_workbooks"]:
        assert workbook["logical_discovery"] == "PASS"
        assert workbook["raw_bytes_frozen"] is False
        assert workbook["sha256"] is None
        assert workbook["hidden_sheet_audit"] == "BLOCKED"


def test_sector_dollar_conservation_remains_fully_unclassified() -> None:
    target = _load(EXHAUSTION)["macro_target"]
    total = Decimal(str(target["direct_investment_profits_millions"]))
    classified = Decimal(str(target["sector_classified_millions"]))
    unclassified = Decimal(str(target["sector_unclassified_millions"]))
    assert classified + unclassified == total
    assert classified == Decimal("0.0")
    assert unclassified == Decimal("41664.1")


def test_questionnaire_listing_does_not_promote_microdata_or_sector_allocation() -> None:
    manifest = _load(QUESTIONNAIRES)
    assert manifest["state"] == "DISCOVERED_CONTENT_NOT_EXHAUSTED"
    assert manifest["interpretation"]["content_review_state"] == "BLOCKED_ARTIFACT_RETRIEVAL"
    assert manifest["interpretation"]["public_source_exhaustion"] == "OPEN"
    assert len(manifest["forms"]) >= 30


def test_broken_questionnaire_manifestation_is_not_source_absence() -> None:
    forms = _load(QUESTIONNAIRES)["forms"]
    broken = next(row for row in forms if row["code"] == "JP-560-63210")
    assert broken["document_state"] == "LISTED_BUT_CLICKED_MANIFESTATION_404"
    assert broken["source_absence"] is False


def test_bop_and_national_accounts_di_measures_remain_nonidentical() -> None:
    bridge = _load(BOP)["cross_account_check"]
    national = Decimal(str(bridge["fy2025_national_accounts_direct_investment_profits_millions"]))
    bop = Decimal(str(bridge["fy2025_bop_direct_investment_income_debit_millions"]))
    difference = Decimal(str(bridge["difference_millions"]))
    assert bop - national == difference
    assert difference == Decimal("1585.6")
    assert bridge["equivalence_state"] == "FAIL_NONCOMPARABLE_AS_IDENTITY"


def test_no_parsed_bop_publication_claims_current_sector_or_country_bridge() -> None:
    lineage = _load(BOP)["publications"]
    parsed = [row for row in lineage if row["pdf_parsed"] is True]
    assert parsed
    assert all(row["sector_di_income_breakdown_found"] is False for row in parsed)
    assert all(row["country_di_income_breakdown_found"] is False for row in parsed)
