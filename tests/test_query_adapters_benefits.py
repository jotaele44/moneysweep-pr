"""Tests for the USASpending agency+CFDA benefit-program adapters (queue C)."""
from pathlib import Path

import pytest

from contract_sweeper.query.adapters import ADAPTER_REGISTRY, get_adapter
from contract_sweeper.query.adapters.usaspending import (
    HUDHCVSection8Adapter,
    SNAPNAPAdapter,
    VABenefitsAdapter,
    WICAdapter,
    WIOAAdapter,
)
from contract_sweeper.query.types import Query

REPO_ROOT = Path(__file__).resolve().parent.parent
BENEFIT_SOURCE_IDS = ["va_benefits", "wioa", "wic", "snap_nap", "hud_hcv_section8"]


def _agency_names(payload):
    return [a["name"] for a in payload["filters"]["agencies"]]


@pytest.mark.unit
@pytest.mark.parametrize("sid", BENEFIT_SOURCE_IDS)
def test_benefit_adapters_registered(sid):
    assert sid in ADAPTER_REGISTRY
    assert get_adapter(sid, root=REPO_ROOT).source_id == sid


@pytest.mark.unit
def test_wic_pins_usda_and_cfda():
    payload = WICAdapter(root=REPO_ROOT)._payload(Query(fiscal_years=(2024,)), 1)
    assert "Department of Agriculture" in _agency_names(payload)
    assert payload["filters"]["program_numbers"] == ["10.557"]


@pytest.mark.unit
def test_wioa_pins_dol_and_three_titles():
    payload = WIOAAdapter(root=REPO_ROOT)._payload(Query(fiscal_years=(2024,)), 1)
    assert "Department of Labor" in _agency_names(payload)
    assert set(payload["filters"]["program_numbers"]) == {"17.258", "17.259", "17.278"}


@pytest.mark.unit
def test_snap_nap_and_hud_hcv_cfda():
    snap = SNAPNAPAdapter(root=REPO_ROOT)._payload(Query(fiscal_years=(2024,)), 1)
    assert set(snap["filters"]["program_numbers"]) == {"10.551", "10.559", "10.568"}
    hcv = HUDHCVSection8Adapter(root=REPO_ROOT)._payload(Query(fiscal_years=(2024,)), 1)
    assert "Department of Housing and Urban Development" in _agency_names(hcv)
    assert hcv["filters"]["program_numbers"] == ["14.871"]


@pytest.mark.unit
def test_va_is_agency_only_no_cfda():
    payload = VABenefitsAdapter(root=REPO_ROOT)._payload(Query(fiscal_years=(2024,)), 1)
    assert "Department of Veterans Affairs" in _agency_names(payload)
    assert "program_numbers" not in payload["filters"]
    # VA spans grants, contracts, and direct payments.
    assert set(payload["filters"]["award_type_codes"]) >= {"02", "A", "06"}


@pytest.mark.unit
def test_caller_supplied_agency_is_not_overridden():
    payload = WICAdapter(root=REPO_ROOT)._payload(
        Query(fiscal_years=(2024,), agencies=("Custom Agency",)), 1
    )
    assert "Custom Agency" in _agency_names(payload)
