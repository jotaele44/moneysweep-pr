from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "staging" / "processed" / "macro" / "pr_factor_income_ledger_v0.csv"
SCHEMA = ROOT / "schemas" / "factor_income_observation.schema.json"


def _rows() -> list[dict[str, str]]:
    with LEDGER.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _amounts_by_year() -> dict[int, dict[str, Decimal]]:
    result: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for row in _rows():
        result[int(row["fiscal_year"])][row["component"]] = Decimal(row["amount_millions"])
    return result


def test_factor_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_factor_ledger_row_count_and_unique_ids() -> None:
    rows = _rows()
    assert len(rows) == 25
    assert len({row["observation_id"] for row in rows}) == 25
    assert {int(row["fiscal_year"]) for row in rows} == set(range(2021, 2026))


def test_each_year_preserves_complete_five_component_set() -> None:
    expected = {
        "NET_PROFIT_RECEIVED_REST_OF_WORLD",
        "DIVIDENDS_RECEIVED_ABROAD",
        "PROFITS_DIVIDENDS_PAID_REST_OF_WORLD",
        "DIVIDENDS_PAID_NONRESIDENTS",
        "DIRECT_INVESTMENT_PROFITS",
    }
    grouped: dict[int, set[str]] = defaultdict(set)
    for row in _rows():
        grouped[int(row["fiscal_year"])].add(row["component"])
    assert set(grouped) == set(range(2021, 2026))
    assert all(components == expected for components in grouped.values())


def test_rest_of_world_profit_identity_closes_exactly() -> None:
    for year, values in _amounts_by_year().items():
        assert values["DIVIDENDS_RECEIVED_ABROAD"] - values["PROFITS_DIVIDENDS_PAID_REST_OF_WORLD"] == values[
            "NET_PROFIT_RECEIVED_REST_OF_WORLD"
        ], year


def test_paid_profit_decomposition_preserves_published_precision_nonclosure() -> None:
    expected_delta = {2021: Decimal("0.0"), 2022: Decimal("0.1"), 2023: Decimal("0.0"), 2024: Decimal("0.0"), 2025: Decimal("0.0")}
    for year, values in _amounts_by_year().items():
        aggregate = values["PROFITS_DIVIDENDS_PAID_REST_OF_WORLD"]
        components = values["DIVIDENDS_PAID_NONRESIDENTS"] + values["DIRECT_INVESTMENT_PROFITS"]
        assert aggregate - components == expected_delta[year], year


def test_fy2022_authoritative_displayed_values_are_never_silently_corrected() -> None:
    values = _amounts_by_year()[2022]
    assert values["DIVIDENDS_PAID_NONRESIDENTS"] == Decimal("616.4")
    assert values["DIRECT_INVESTMENT_PROFITS"] == Decimal("36466.2")
    assert values["PROFITS_DIVIDENDS_PAID_REST_OF_WORLD"] == Decimal("37082.7")
    assert values["PROFITS_DIVIDENDS_PAID_REST_OF_WORLD"] != Decimal("37082.6")


def test_fy2021_is_preserved_but_blocked_from_current_macro_reconciliation() -> None:
    rows = [row for row in _rows() if row["fiscal_year"] == "2021"]
    assert len(rows) == 5
    assert all(row["macro_revision_alignment"] == "STALE_MACRO_REVISION_CONTEXT" for row in rows)
    assert all(row["certification_state"] == "UNRESOLVED" for row in rows)


def test_fy2022_through_fy2025_are_aligned_but_only_provisional() -> None:
    rows = [row for row in _rows() if int(row["fiscal_year"]) >= 2022]
    assert len(rows) == 20
    assert all(row["macro_revision_alignment"] == "ALIGNED" for row in rows)
    assert all(row["certification_state"] == "PROVISIONAL" for row in rows)
    assert all(row["source_bytes_frozen"] == "false" for row in rows)


def test_unknown_country_destination_is_not_synthesized() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert "destination_country" not in schema["required"]
    assert "ultimate_owner_id" not in schema["required"]
