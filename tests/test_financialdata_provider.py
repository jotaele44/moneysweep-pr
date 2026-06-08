"""
Tests for the OPTIONAL FinancialData.net provider adapter and enrichment CLI.

Hard contract enforced here:
  - Default state: provider skips cleanly (no key, no license, no network call).
  - Any live HTTP call without configuration is an assertion failure (the
    default transport raises; this test confirms it).
  - Match routing is deterministic + dependency-free.
  - CLI dry-run produces every declared output, even when entity list is empty.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.providers import ProviderReadiness
from scripts.providers.financialdata_net import (
    PROVIDER_NAME,
    ENDPOINTS,
    FinancialDataNetProvider,
    from_config,
)
from scripts.enrichment.enrich_financialdata_entities import (
    OUTPUT_COLUMNS,
    SYNTHETIC_CANDIDATES,
    build_output_row,
    normalize_name,
    route_match,
    run,
)


# ---------------------------------------------------------------------------
# Provider readiness / gating
# ---------------------------------------------------------------------------


def test_provider_skips_without_api_key():
    """No key + no license → status='missing_both', ready_for_live=False."""
    p = FinancialDataNetProvider(api_key=None, license_approved=False)
    readiness = p.readiness()
    assert isinstance(readiness, ProviderReadiness)
    assert readiness.provider == PROVIDER_NAME
    assert readiness.key_present is False
    assert readiness.license_approved is False
    assert readiness.ready_for_live is False
    assert readiness.status == "missing_both"
    assert readiness.license_status == "not_approved"
    assert p.is_ready() is False


def test_provider_skips_without_license_approval():
    """Key present but license not approved → status='missing_license'."""
    p = FinancialDataNetProvider(api_key="dummy-key-not-real", license_approved=False)
    readiness = p.readiness()
    assert readiness.key_present is True
    assert readiness.license_approved is False
    assert readiness.ready_for_live is False
    assert readiness.status == "missing_license"
    assert p.is_ready() is False


def test_provider_skips_with_license_but_no_key():
    """License acknowledged but no key → status='missing_key'."""
    p = FinancialDataNetProvider(api_key=None, license_approved=True)
    readiness = p.readiness()
    assert readiness.status == "missing_key"
    assert readiness.ready_for_live is False


def test_provider_ready_only_with_both():
    p = FinancialDataNetProvider(api_key="x", license_approved=True)
    assert p.is_ready() is True
    assert p.readiness().status == "ready"
    assert p.readiness().license_status == "approved"


# ---------------------------------------------------------------------------
# Network safety: no live call in any test path
# ---------------------------------------------------------------------------


def test_default_transport_refuses_without_configuration():
    """Calling _request() with no transport + no config must raise loudly."""
    p = FinancialDataNetProvider(api_key=None, license_approved=False)
    with pytest.raises(RuntimeError, match="without a configured key"):
        p._request("company_information", {"identifier": "ACM"})


def test_no_network_call_in_test_path():
    """Even with `requests` patched, our default path should never reach it."""
    p = FinancialDataNetProvider(api_key=None, license_approved=False)
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        with pytest.raises(RuntimeError):
            p._request("company_information", {"identifier": "X"})
        assert mock_get.call_count == 0
        assert mock_post.call_count == 0


def test_transport_injection_bypasses_default():
    """A test transport receives the request and the default refuser is not used."""
    calls = []

    def mock_transport(method, url, params, headers, timeout):
        calls.append({"method": method, "url": url, "params": params})
        return {"data": [{"ticker": "ACM", "cik": "0000868857"}]}

    p = FinancialDataNetProvider(api_key="k", license_approved=True, transport=mock_transport)
    out = p.company_information("AECOM")
    assert calls and calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(ENDPOINTS["company_information"])
    assert out and out["data"][0]["ticker"] == "ACM"


# ---------------------------------------------------------------------------
# Match routing
# ---------------------------------------------------------------------------


def test_deterministic_cusip_match():
    entity = {"name": "AECOM", "cusip": "00766T100"}
    candidates = SYNTHETIC_CANDIDATES["AECOM"]
    result = route_match(entity, candidates)
    assert result.method == "deterministic_cusip"
    assert result.confidence == 1.0
    assert result.review_required is False
    assert result.evidence_tier == "T1"
    assert result.chosen and result.chosen["ticker"] == "ACM"


def test_deterministic_isin_match():
    entity = {"name": "Fluor Corp", "isin": "US3434121022"}
    candidates = SYNTHETIC_CANDIDATES["FLUOR"]
    result = route_match(entity, candidates)
    assert result.method == "deterministic_isin"
    assert result.evidence_tier == "T1"
    assert result.review_required is False


def test_deterministic_ticker_match():
    entity = {"name": "Parsons Corp", "ticker": "PSN"}
    candidates = SYNTHETIC_CANDIDATES["PARSONS"]
    result = route_match(entity, candidates)
    assert result.method == "deterministic_ticker"
    assert result.confidence == 1.0


def test_ambiguous_multi_match_routes_to_review():
    entity = {"name": "ACME Corporation"}
    candidates = SYNTHETIC_CANDIDATES["ACME"]
    result = route_match(entity, candidates)
    assert result.method == "ambiguous_multi"
    assert result.review_required is True
    assert result.evidence_tier == "T3"


def test_fuzzy_name_routes_to_review():
    entity = {"name": "Black and Veatch Infrastructure Inc"}
    candidates = SYNTHETIC_CANDIDATES["BLACK AND VEATCH INFRASTRUCTURE"]
    result = route_match(entity, candidates)
    assert result.method == "fuzzy_name"
    assert result.review_required is True
    # No identifier on the synthetic candidate → T4
    assert result.evidence_tier == "T4"


def test_private_or_unmatched_entity_is_not_failure():
    entity = {"name": "Local Family LLC"}
    result = route_match(entity, candidates=[])
    assert result.method == "not_public_market_resolved"
    assert result.review_required is False
    assert result.evidence_tier == "T4"
    assert result.chosen is None


def test_normalize_name_strips_suffixes_and_punctuation():
    assert normalize_name("ACME, Inc.") == "ACME"
    assert normalize_name("Black & Veatch Holding Co.") == "BLACK VEATCH"
    assert normalize_name("  Fluor Corporation  ") == "FLUOR"


# ---------------------------------------------------------------------------
# Schema-shape validation (without requiring jsonschema dependency)
# ---------------------------------------------------------------------------


def _required_schema_fields() -> set[str]:
    schema_path = Path("schemas/canonical_v1/financialdata_enrichment.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return set(schema.get("required", []))


def _schema_provider_const() -> str:
    schema_path = Path("schemas/canonical_v1/financialdata_enrichment.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return schema["properties"]["provider"]["const"]


def test_schema_required_keys_present_in_row():
    entity = {"source_entity_id": "ent_aecom", "name": "AECOM", "cusip": "00766T100"}
    candidates = SYNTHETIC_CANDIDATES["AECOM"]
    result = route_match(entity, candidates)
    row = build_output_row(
        entity, result, license_status="not_approved", retrieved_at="2026-06-04T00:00:00Z"
    )
    for required in _required_schema_fields():
        assert required in row, f"missing required schema field: {required}"
    assert row["provider"] == _schema_provider_const()
    assert row["raw_payload_stored"] is False


def test_schema_enums_respected_for_match_methods():
    schema_path = Path("schemas/canonical_v1/financialdata_enrichment.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    allowed_methods = set(schema["properties"]["match_method"]["enum"])
    allowed_tiers = set(schema["properties"]["evidence_tier"]["enum"])
    allowed_endpoints = set(schema["properties"]["provider_endpoint"]["enum"])

    cases = [
        ({"name": "AECOM", "cusip": "00766T100"}, SYNTHETIC_CANDIDATES["AECOM"]),
        ({"name": "ACME Corporation"}, SYNTHETIC_CANDIDATES["ACME"]),
        (
            {"name": "Black and Veatch Infrastructure Inc"},
            SYNTHETIC_CANDIDATES["BLACK AND VEATCH INFRASTRUCTURE"],
        ),
        ({"name": "Local Family LLC"}, []),
    ]
    for entity, candidates in cases:
        result = route_match(entity, candidates)
        row = build_output_row(entity, result, "not_approved", "2026-06-04T00:00:00Z")
        assert row["match_method"] in allowed_methods
        assert row["evidence_tier"] in allowed_tiers
        assert row["provider_endpoint"] in allowed_endpoints


# ---------------------------------------------------------------------------
# CLI dry-run end-to-end (no network)
# ---------------------------------------------------------------------------


def test_cli_dry_run_writes_expected_outputs(tmp_path, monkeypatch):
    """Dry-run mode with the synthetic fixture writes all four declared outputs."""
    # Force the readiness/config helpers to "no key, no license" regardless of host env.
    monkeypatch.delenv("FINANCIALDATA_API_KEY", raising=False)
    monkeypatch.delenv("FINANCIALDATA_LICENSE_APPROVED", raising=False)

    # Redirect the readiness JSON path to the tmp dir so we don't write to the real repo.
    from scripts.enrichment import enrich_financialdata_entities as cli_mod

    readiness_target = tmp_path / "reports" / "financialdata_enrichment_readiness.json"
    monkeypatch.setattr(cli_mod, "READINESS_PATH", readiness_target)

    fixture = Path("tests/fixtures/financialdata_synthetic_entities.csv")
    assert fixture.exists(), "synthetic fixture missing"

    output_dir = tmp_path / "outputs"
    summary = run(input_path=fixture, output_dir=output_dir, dry_run=True)

    # Status + counts
    assert summary["status"] == "SKIPPED_OPTIONAL"  # no key + no license
    assert summary["dry_run"] is True
    assert summary["entity_count"] == 6
    # Synthetic fixture contains: 3 deterministic (AECOM/Fluor/Parsons),
    # 1 ambiguous (ACME), 1 fuzzy (B&V), 1 unmatched (Local Family).
    assert summary["matched"] >= 3
    assert summary["review"] >= 2  # ACME + B&V
    assert summary["unmatched"] >= 1  # Local Family

    # All declared output files exist
    crosswalk = output_dir / "enrichment" / "financialdata_identifier_crosswalk.csv"
    matches = output_dir / "enrichment" / "financialdata_entity_matches.csv"
    review = output_dir / "review" / "financialdata_match_review_queue.csv"
    assert crosswalk.exists()
    assert matches.exists()
    assert review.exists()
    assert readiness_target.exists()

    # CSV schemas match
    with crosswalk.open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == OUTPUT_COLUMNS

    # Readiness JSON carries gate status
    readiness = json.loads(readiness_target.read_text(encoding="utf-8"))
    assert readiness["provider"] == PROVIDER_NAME
    assert readiness["ready_for_live"] is False
    assert readiness["status"] == "missing_both"
    assert readiness["license_status"] == "not_approved"


def test_cli_dry_run_no_network_call(tmp_path, monkeypatch):
    """Belt-and-braces: patch requests so any accidental live call would crash."""
    monkeypatch.delenv("FINANCIALDATA_API_KEY", raising=False)
    monkeypatch.delenv("FINANCIALDATA_LICENSE_APPROVED", raising=False)

    from scripts.enrichment import enrich_financialdata_entities as cli_mod

    monkeypatch.setattr(
        cli_mod, "READINESS_PATH", tmp_path / "reports" / "financialdata_enrichment_readiness.json"
    )

    fixture = Path("tests/fixtures/financialdata_synthetic_entities.csv")
    with (
        patch("requests.get", side_effect=AssertionError("no network in tests")),
        patch("requests.post", side_effect=AssertionError("no network in tests")),
    ):
        summary = run(input_path=fixture, output_dir=tmp_path / "outputs", dry_run=True)
    assert summary["entity_count"] == 6


def test_from_config_respects_env(monkeypatch):
    """from_config() reads scripts.config helpers — both signals flowable."""
    monkeypatch.setenv("FINANCIALDATA_API_KEY", "k123")
    monkeypatch.setenv("FINANCIALDATA_LICENSE_APPROVED", "true")
    p = from_config()
    assert p.api_key == "k123"
    assert p.license_approved is True
    assert p.is_ready() is True

    monkeypatch.delenv("FINANCIALDATA_API_KEY", raising=False)
    monkeypatch.setenv("FINANCIALDATA_LICENSE_APPROVED", "no")
    p2 = from_config()
    assert p2.api_key is None
    assert p2.license_approved is False
    assert p2.is_ready() is False
