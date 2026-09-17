from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "macro" / "jp_di_profit_sector_lineage_v1.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_historical_sector_table_is_preserved_but_not_current() -> None:
    rows = _manifest()["observations"]
    historical = next(row for row in rows if row["publication_year"] == 1995)
    assert historical["sector_allocation_present"] is True
    assert historical["admissibility"] == "HISTORICAL_SUPPORTING_ONLY"
    assert historical["carry_forward_to_2025"] is False


def test_later_definition_continuity_does_not_promote_current_sector_values() -> None:
    later = [row for row in _manifest()["observations"] if row["publication_year"] >= 2020]
    assert later
    assert all(row["definition_present"] is True for row in later)
    assert all(row["current_sector_allocation_found_in_parsed_public_report"] is False for row in later)


def test_methodology_path_is_distinct_from_current_amounts() -> None:
    bridge = _manifest()["methodology_binding"]
    assert bridge["sector_production_path_documented"] is True
    assert bridge["current_fy2025_sector_values_recovered"] is False


def test_historical_share_cannot_unlock_sector_denominator() -> None:
    gates = set(_manifest()["hard_gates"])
    assert "HISTORICAL_SECTOR_SHARE_IS_NOT_CURRENT_SECTOR_SHARE" in gates
    assert "METHODOLOGY_EXISTS_IS_NOT_CURRENT_AMOUNT" in gates
