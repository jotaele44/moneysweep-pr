from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "manifests" / "macro" / "sector_decomposition_source_audit_v0.json"


def _audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_sector_target_remains_blocked_without_current_authoritative_allocation() -> None:
    audit = _audit()
    assert audit["certification_state"] == "BLOCKED"
    assert audit["target_measure"]["sector_denominator_state"] == "BLOCKED_PUBLIC_SOURCE_DENOMINATOR"


def test_current_sources_do_not_claim_sector_direct_investment_profit_allocation() -> None:
    current = [source for source in _audit()["audited_sources"] if source["current"]]
    assert current
    assert all(source["sector_direct_investment_profit_allocation_found"] is False for source in current)


def test_historical_sector_table_cannot_promote_current_allocation() -> None:
    historical = [source for source in _audit()["audited_sources"] if not source["current"]]
    assert historical
    assert any(source["sector_direct_investment_profit_allocation_found"] is True for source in historical)
    assert all(source["admissibility"] == "HISTORICAL_SUPPORTING_ONLY" for source in historical)


def test_proxy_allocators_are_explicitly_forbidden() -> None:
    forbidden = set(_audit()["forbidden_proxy_allocators"])
    assert {
        "INDUSTRY_GDP_SHARE",
        "INDUSTRY_NET_INCOME_SHARE",
        "PAYROLL_SHARE",
        "EMPLOYMENT_SHARE",
        "EXPORT_SHARE",
        "FACILITY_COUNT_SHARE",
        "HISTORICAL_SECTOR_SHARE",
    } <= forbidden


def test_public_source_exhaustion_remains_open_while_workbooks_are_unparsed() -> None:
    audit = _audit()
    assert audit["public_source_exhaustion_state"] == "OPEN_DOWNLOADABLE_WORKBOOKS_NOT_YET_PARSED"
    assert len(audit["discovered_unparsed_public_manifestations"]) == 3
    assert all(
        item["state"] == "DISCOVERED_DOWNLOAD_ENDPOINT_UNPARSED"
        for item in audit["discovered_unparsed_public_manifestations"]
    )
    conclusion = audit["bounded_conclusion"]
    assert "parsed audited source set" in conclusion
    assert "Public-source exhaustion is not claimed" in conclusion


def test_current_balance_of_payments_measure_keeps_accounting_concept_separate() -> None:
    bop = next(source for source in _audit()["audited_sources"] if source["source_id"] == "jp_balance_payments_2025")
    assert bop["admissibility"] == "AUTHORITATIVE_AGGREGATE_DIFFERENT_ACCOUNTING_CONCEPT"
    assert "DIRECT_INVESTMENT_INCOME_DEBIT" in bop["observed_measurements"]
