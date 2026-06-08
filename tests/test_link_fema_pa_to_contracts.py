"""Tests for scripts/link_fema_pa_to_contracts.py."""

import logging

import pandas as pd
import pytest

from scripts import link_fema_pa_to_contracts as mod


def _logger():
    return logging.getLogger("test_link_fema_pa")


@pytest.mark.unit
def test_municipality_prefers_portal_field_over_county():
    # v2 carries only county; the matched portal row carries a real municipality.
    df_v2 = pd.DataFrame(
        [
            {
                "pw_number": "100",
                "disaster_number": "4339",
                "applicant_name": "Municipality of Ponce",
                "county": "Ponce",
            }
        ]
    )
    df_portal = pd.DataFrame(
        [
            {
                "pw_number": "100",
                "disaster_number": "4339",
                "municipality": "Ponce Pueblo",
                "county": "Ponce",
                "eligible_amount": "1000",
                "federal_share": "900",
            }
        ]
    )
    empty = pd.DataFrame()
    out = mod._build_linkage(df_v2, df_portal, empty, empty, empty, _logger())
    row = out.iloc[0]
    assert row["municipality"] == "Ponce Pueblo"  # not the county
    assert row["county"] == "Ponce"


@pytest.mark.unit
def test_municipality_falls_back_to_county_when_no_portal_match():
    # No portal row for this PW: county is the PR municipio, used as fallback.
    df_v2 = pd.DataFrame(
        [
            {
                "pw_number": "200",
                "disaster_number": "4339",
                "applicant_name": "Municipality of Adjuntas",
                "county": "Adjuntas",
            }
        ]
    )
    empty = pd.DataFrame()
    out = mod._build_linkage(df_v2, empty, empty, empty, empty, _logger())
    row = out.iloc[0]
    assert row["municipality"] == "Adjuntas"
    assert row["county"] == "Adjuntas"


@pytest.mark.unit
def test_contract_and_cor3_matches_set_confidence():
    # Regression: lookups previously stored pandas Series, so bool(row)/if row
    # raised "truth value ambiguous" whenever a PW actually matched. Storing
    # dicts makes matched_* flags and link_confidence work.
    df_v2 = pd.DataFrame(
        [
            {
                "pw_number": "300",
                "disaster_number": "4339",
                "applicant_name": "City of Caguas",
                "county": "Caguas",
            }
        ]
    )
    df_cor3 = pd.DataFrame(
        [
            {
                "applicant_normalized": mod._norm("City of Caguas"),
                "project_id": "COR3-1",
                "total_approved": "500",
            }
        ]
    )
    df_contracts = pd.DataFrame(
        [
            {
                "recipient_name": "City of Caguas",
                "award_id": "AW-9",
            }
        ]
    )
    empty = pd.DataFrame()
    out = mod._build_linkage(df_v2, empty, df_cor3, df_contracts, empty, _logger())
    row = out.iloc[0]
    assert bool(row["matched_cor3"]) is True
    assert bool(row["matched_contract"]) is True
    assert row["link_confidence"] == "exact"
    assert row["cor3_project_id"] == "COR3-1"
    assert row["contract_id"] == "AW-9"


@pytest.mark.unit
def test_asset_type_classification():
    assert mod._classify_asset_type("Category C - Roads and Bridges") == "roads_bridges"
    assert mod._classify_asset_type("Cat. F", "PREPA") == "utilities"
    assert mod._classify_asset_type("Debris Removal") == "debris"
    assert mod._classify_asset_type("Buildings and Equipment") == "buildings"
    assert mod._classify_asset_type("", "") == "other"


@pytest.mark.unit
def test_asset_type_in_linkage_output():
    df_v2 = pd.DataFrame(
        [
            {
                "pw_number": "400",
                "disaster_number": "4339",
                "applicant_name": "Municipality of Loiza",
                "county": "Loiza",
                "category": "Category C - Roads and Bridges",
            }
        ]
    )
    empty = pd.DataFrame()
    out = mod._build_linkage(df_v2, empty, empty, empty, empty, _logger())
    assert out.loc[0, "asset_type"] == "roads_bridges"


@pytest.mark.unit
def test_municipality_helper_priority():
    assert mod._municipality_of({"county": "Ponce"}, {"municipality": "Real Muni"}) == "Real Muni"
    assert mod._municipality_of({"county": "Ponce"}, {}) == "Ponce"
    assert (
        mod._municipality_of({"municipality": "Vega Baja", "county": "Vega Baja"}, {})
        == "Vega Baja"
    )
    assert mod._municipality_of({}, None) == ""
