from __future__ import annotations

import csv
import json
from pathlib import Path


from scripts.sources import fetch_lda_gov as lda


def test_api_root_fixture_discovers_expected_endpoints():
    endpoints, missing = lda.discover_endpoints(live=False)
    assert not missing
    assert set(lda.EXPECTED_ENDPOINTS).issubset(endpoints)
    assert endpoints["filings"].startswith("https://lda.gov/api/v1/filings/")


def test_drf_paginated_response_normalizes_correctly():
    pages = {
        "page1": {
            "count": 2,
            "next": "page2",
            "previous": None,
            "results": [{"id": "A", "name": "Alpha LLC"}],
        },
        "page2": {
            "count": 2,
            "next": None,
            "previous": "page1",
            "results": [{"id": "B", "name": "Beta LLC"}],
        },
    }

    def fetcher(url: str):
        return pages[url]

    records = lda.collect_records("registrants", "page1", live=True, limit=None, fetcher=fetcher)
    rows = [
        lda.normalize_record(
            "registrants", record, "page1", "2026-01-01T00:00:00Z", evidence_tier="T1"
        )
        for record in records
    ]
    assert [r["registrant_id"] for r in rows] == ["A", "B"]
    assert all(r["source_id"] == "lda_gov" for r in rows)


def test_raw_list_constants_response_normalizes_correctly():
    payload = [{"id": "BUD", "code": "BUD", "name": "Budget"}]
    records = lda._records_from_payload(payload)
    row = lda.normalize_record(
        "constants/filing/lobbyingactivityissues",
        records[0],
        "fixture-url",
        "2026-01-01T00:00:00Z",
        evidence_tier="T1",
    )
    assert row["reference_id"] == "BUD"
    assert row["code"] == "BUD"
    assert row["name"] == "Budget"
    assert row["raw_payload_stored"] is False


def test_dry_run_performs_no_network_call(tmp_path: Path):
    def exploding_fetcher(url: str):  # pragma: no cover - should never be called
        raise AssertionError(f"network path called in dry-run: {url}")

    readiness = lda.run(output_dir=tmp_path, live=False, fetcher=exploding_fetcher)
    assert readiness["live_mode_requested"] is False
    assert readiness["root_discovery_ok"] == "skipped_dry_run"
    assert not readiness["blockers"]


def test_live_is_required_for_network_path():
    calls: list[str] = []

    def fetcher(url: str):
        calls.append(url)
        return dict(lda.SYNTHETIC_ROOT)

    endpoints, _ = lda.discover_endpoints(live=False, fetcher=fetcher)
    assert endpoints
    assert calls == []

    live_endpoints, _ = lda.discover_endpoints(live=True, fetcher=fetcher)
    assert live_endpoints
    assert calls, "live mode should use fetcher/network path"


def test_missing_changed_endpoint_produces_readiness_warning(tmp_path: Path):
    def fetcher(url: str):
        if url.endswith("?format=json"):
            return {"filings": "https://lda.gov/api/v1/filings/?format=json"}
        return {"count": 0, "next": None, "previous": None, "results": []}

    readiness = lda.run(output_dir=tmp_path, live=True, fetcher=fetcher, limit=0)
    assert readiness["root_discovery_ok"] is False
    assert any(b.startswith("missing_or_changed_endpoints:") for b in readiness["blockers"])


def test_all_normalized_rows_contain_required_provenance_fields(tmp_path: Path):
    lda.run(output_dir=tmp_path, live=False)
    path = tmp_path / "outputs/normalized/lda/lda_filings.csv"
    rows = list(csv.DictReader(path.open()))
    assert rows
    required = {
        "source_id",
        "source_family",
        "source_endpoint",
        "source_url",
        "retrieved_at",
        "api_record_id",
        "record_hash",
        "raw_payload_stored",
        "evidence_tier",
    }
    assert required.issubset(rows[0])
    assert rows[0]["source_id"] == "lda_gov"
    assert rows[0]["raw_payload_stored"] == "False"


def test_raw_payload_stored_defaults_false():
    row = lda.normalize_record(
        "clients", {"id": "C1", "name": "Client"}, "url", "now", evidence_tier="T1"
    )
    assert row["raw_payload_stored"] is False
    assert "raw_payload_json" not in row


def test_static_seed_replacement_report_marks_static_sources(tmp_path: Path):
    lda.run(output_dir=tmp_path, live=False)
    report = json.loads((tmp_path / "reports/lda_static_seed_replacement_report.json").read_text())
    assert report["source_id"] == "lda_gov"
    assert report["static_seed_role_after_adapter"] == "regression_fixture"
    assert (
        report["replacement_decision"]["uploaded_static_lda_registrant_client_filing_snapshots"]
        == "replaced_by_api"
    )
    assert report["replacement_decision"]["Registrants.pdf"] == "retained_as_fixture"


def test_cli_dry_run_writes_expected_output_files(tmp_path: Path):
    code = lda.main(["--output-dir", str(tmp_path), "--limit", "1"])
    assert code == 0
    expected = [
        "outputs/normalized/lda/lda_registrants.csv",
        "outputs/normalized/lda/lda_clients.csv",
        "outputs/normalized/lda/lda_lobbyists.csv",
        "outputs/normalized/lda/lda_filings.csv",
        "outputs/normalized/lda/lda_contributions.csv",
        "outputs/reference/lda/lda_ref_filing_types.csv",
        "outputs/reference/lda/lda_ref_lobbying_issues.csv",
        "outputs/reference/lda/lda_ref_government_entities.csv",
        "outputs/reference/lda/lda_ref_countries.csv",
        "outputs/reference/lda/lda_ref_states.csv",
        "outputs/reference/lda/lda_ref_lobbyist_prefixes.csv",
        "outputs/reference/lda/lda_ref_lobbyist_suffixes.csv",
        "outputs/reference/lda/lda_ref_contribution_item_types.csv",
        "data/staging/processed/pr_lda_filings.csv",
        "reports/lda_api_readiness.json",
        "reports/lda_static_seed_replacement_report.json",
    ]
    missing = [p for p in expected if not (tmp_path / p).exists()]
    assert not missing
