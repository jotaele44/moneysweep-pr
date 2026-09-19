from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "macro" / "jp_methodology_bridge_v1.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_methodology_proves_sector_production_path_not_current_amounts() -> None:
    manifest = _manifest()
    ids = {row["id"] for row in manifest["findings"]}
    assert "DI_PROFIT_BASE_BY_INDUSTRIAL_SECTOR" in ids
    assert manifest["current_sector_bridge_state"] == (
        "METHODOLOGY_PROVES_SECTOR_PRODUCTION_PATH_BUT_CURRENT_PUBLIC_2025_TABLE_UNRETRIEVED"
    )
    assert manifest["certification_effect"]["sector_allocation"] == "BLOCKED"


def test_methodology_preserves_denominator_control() -> None:
    finding = next(row for row in _manifest()["findings"] if row["id"] == "DI_FIRM_UNIVERSE_CONTROL")
    assert finding["state"] == "FACT_METHODOLOGY"
    assert "universe" in finding["description"].lower()


def test_parent_company_expense_is_separate_mechanism() -> None:
    finding = next(row for row in _manifest()["findings"] if row["id"] == "PARENT_COMPANY_EXPENSE_TREATMENT")
    assert set(finding["source_inputs"]) == {"Hacienda income-tax returns", "IP-11", "IP-546"}
    assert "separate" in finding["implication"].lower()


def test_source_instruments_are_discovery_targets_not_assumed_public_data() -> None:
    manifest = _manifest()
    instruments = set(manifest["source_instruments_identified"])
    assert {"BP-11", "IP-11", "IP-546", "IP-553"} <= instruments
    for code in ("BP-11", "IP-11", "IP-546", "IP-553"):
        assert manifest["public_search_result_for_instruments"][code].startswith("NO_SEPARATE_PUBLIC_FORM_LOCATED")


def test_public_records_gate_stays_closed() -> None:
    effect = _manifest()["certification_effect"]
    assert effect["public_source_exhaustion"] == "OPEN"
    assert effect["foia_or_public_records"] == "NOT_YET_REACHED"
