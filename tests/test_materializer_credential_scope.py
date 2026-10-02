from __future__ import annotations

import os

from scripts import run_automatable_sources_scoped as scoped


def test_declared_api_key_uses_registry_authentication_contract() -> None:
    assert scoped._declared_api_key({"authentication": "api_key:EIA_API_KEY"}) == "EIA_API_KEY"
    assert scoped._declared_api_key({"authentication": "none"}) is None
    assert scoped._declared_api_key({}) is None


def test_source_scope_hides_unrelated_provider_credentials(monkeypatch) -> None:
    monkeypatch.setenv("EIA_API_KEY", "fixture-eia")
    monkeypatch.setenv("FRED_API_KEY", "fixture-fred")
    monkeypatch.setenv("OPENSTATES_API_KEY", "fixture-openstates")

    names = {"EIA_API_KEY", "FRED_API_KEY", "OPENSTATES_API_KEY"}
    with scoped._source_scoped_environment(names, "EIA_API_KEY"):
        assert os.environ.get("EIA_API_KEY") == "fixture-eia"
        assert "FRED_API_KEY" not in os.environ
        assert "OPENSTATES_API_KEY" not in os.environ

    assert os.environ.get("EIA_API_KEY") == "fixture-eia"
    assert os.environ.get("FRED_API_KEY") == "fixture-fred"
    assert os.environ.get("OPENSTATES_API_KEY") == "fixture-openstates"


def test_keyless_source_scope_hides_all_provider_credentials(monkeypatch) -> None:
    monkeypatch.setenv("SAM_API_KEY", "fixture-sam")
    monkeypatch.setenv("FAC_API_KEY", "fixture-fac")

    names = {"SAM_API_KEY", "FAC_API_KEY"}
    with scoped._source_scoped_environment(names, None):
        assert "SAM_API_KEY" not in os.environ
        assert "FAC_API_KEY" not in os.environ

    assert os.environ.get("SAM_API_KEY") == "fixture-sam"
    assert os.environ.get("FAC_API_KEY") == "fixture-fac"


def test_license_gate_is_fail_closed(monkeypatch) -> None:
    src = {"license_gate": "FINANCIALDATA_LICENSE_APPROVED"}

    monkeypatch.delenv("FINANCIALDATA_LICENSE_APPROVED", raising=False)
    assert scoped._license_allowed(src) is False

    monkeypatch.setenv("FINANCIALDATA_LICENSE_APPROVED", "false")
    assert scoped._license_allowed(src) is False

    monkeypatch.setenv("FINANCIALDATA_LICENSE_APPROVED", "true")
    assert scoped._license_allowed(src) is True


def test_source_without_license_gate_is_allowed(monkeypatch) -> None:
    monkeypatch.delenv("FINANCIALDATA_LICENSE_APPROVED", raising=False)
    assert scoped._license_allowed({}) is True
