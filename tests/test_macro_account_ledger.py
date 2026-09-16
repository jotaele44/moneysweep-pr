from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator

from moneysweep.capital_flow.macro import (
    MacroCandidateState,
    MacroClosureState,
    MacroObservation,
    adjudicate_latest_manifestation,
    published_identity_closure,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "staging" / "processed" / "macro" / "pr_gdp_gnp_ledger_v0.csv"
SCHEMA = ROOT / "schemas" / "macro_account_observation.schema.json"


def _rows() -> list[dict[str, str]]:
    with LEDGER.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _obs(
    observation_id: str,
    year: int,
    vintage: str,
    table: str,
    gnp: str,
    gdp: str,
    state: MacroCandidateState = MacroCandidateState.CURRENT,
) -> MacroObservation:
    return MacroObservation(
        observation_id=observation_id,
        fiscal_year=year,
        manifestation_id=f"M_{vintage}",
        source_table=table,
        publication_vintage=vintage,
        gnp_millions=Decimal(gnp),
        gdp_millions=Decimal(gdp),
        reported_less_rest_of_world_millions=None,
        candidate_state=state,
    )


def test_macro_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_ledger_has_unique_observation_ids_and_complete_year_coverage() -> None:
    rows = _rows()
    ids = [row["observation_id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert {int(row["fiscal_year"]) for row in rows} == set(range(2010, 2026))


def test_historical_overlaps_are_preserved_not_deleted() -> None:
    rows = _rows()
    old_overlap = [
        row
        for row in rows
        if row["manifestation_id"] == "JP_AE2019" and 2016 <= int(row["fiscal_year"]) <= 2019
    ]
    assert len(old_overlap) == 4
    assert all(row["candidate_state"] == "SUPERSEDED" for row in old_overlap)
    assert all(row["superseded_by_observation_id"] for row in old_overlap)


def test_fy2021_conflict_is_preserved_and_unresolved() -> None:
    rows = [row for row in _rows() if int(row["fiscal_year"]) == 2021]
    assert len(rows) == 3
    assert all(row["candidate_state"] == "UNRESOLVED" for row in rows)
    assert all(row["certification_state"] == "UNRESOLVED" for row in rows)
    assert all(row["contradiction_class"] == "SCOPE" for row in rows)
    pairs = {(row["gdp_millions"], row["gnp_millions"]) for row in rows}
    assert pairs == {("106426.6", "73357.2"), ("106368.9", "72950.6")}


def test_no_other_latest_vintage_year_has_conflicting_value_pairs() -> None:
    grouped: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for row in _rows():
        if row["publication_vintage"] == "2025" and int(row["fiscal_year"]) != 2021:
            grouped[int(row["fiscal_year"])].add((row["gdp_millions"], row["gnp_millions"]))
    assert grouped
    assert all(len(value_pairs) == 1 for value_pairs in grouped.values())


def test_raw_strings_are_preserved_separately_from_numeric_values() -> None:
    row = next(row for row in _rows() if row["observation_id"] == "MACRO_JP2025_T9_FY2025")
    assert row["gnp_raw"] == "87,571.2"
    assert row["gdp_raw"] == "129,368.5"
    assert row["reported_less_rest_world_raw"] == "(41,797.3)"
    assert row["gnp_millions"] == "87571.2"
    assert row["gdp_millions"] == "129368.5"


def test_published_identity_closure_distinguishes_exact_rounding_and_failure() -> None:
    exact = published_identity_closure(
        gdp_millions=Decimal("129368.5"),
        gnp_millions=Decimal("87571.2"),
        reported_gap_millions=Decimal("41797.3"),
    )
    assert exact.state == MacroClosureState.EXACT

    rounded = published_identity_closure(
        gdp_millions=Decimal("102450.0"),
        gnp_millions=Decimal("68944.9"),
        reported_gap_millions=Decimal("33505.2"),
    )
    assert rounded.state == MacroClosureState.WITHIN_DECLARED_ROUNDING_BUDGET
    assert rounded.delta_millions == Decimal("-0.1")

    failed = published_identity_closure(
        gdp_millions=Decimal("100.0"),
        gnp_millions=Decimal("50.0"),
        reported_gap_millions=Decimal("49.0"),
    )
    assert failed.state == MacroClosureState.FAIL


def test_adjudicator_fails_closed_on_latest_vintage_conflict() -> None:
    observations = [
        _obs("MACRO_A", 2021, "2025", "TABLE_9", "73357.2", "106426.6"),
        _obs("MACRO_B", 2021, "2025", "TABLE_10", "72950.6", "106368.9"),
    ]
    assert adjudicate_latest_manifestation(observations) is None


def test_adjudicator_uses_later_agreeing_manifestation_without_deleting_history() -> None:
    observations = [
        _obs("MACRO_OLD", 2018, "2019", "TABLE_9", "67824.7", "100978.9", MacroCandidateState.HISTORICAL),
        _obs("MACRO_NEW_A", 2018, "2025", "TABLE_1", "67601.1", "100958.1"),
        _obs("MACRO_NEW_B", 2018, "2025", "TABLE_9", "67601.1", "100958.1"),
    ]
    result = adjudicate_latest_manifestation(observations)
    assert result is not None
    assert result.publication_vintage == "2025"
    assert result.gnp_millions == Decimal("67601.1")
