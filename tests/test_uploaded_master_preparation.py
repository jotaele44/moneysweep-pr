from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.prepare_uploaded_masters import prepare_uploaded_masters
from scripts.write_artifact_manifest import write_artifact_manifest


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_prepare_uploaded_masters_emits_canonical_processed_files(tmp_path):
    contracts = tmp_path / "pr_contracts_master_v2.csv"
    awards = tmp_path / "pr_all_awards_master.csv"
    lda = tmp_path / "lda_canonical_client_summary_all.csv"
    out = tmp_path / "processed"

    _write_csv(
        contracts,
        [
            "record_id",
            "dataset",
            "source_file",
            "evidence_tier",
            "vendor_name",
            "normalized_vendor",
            "agency_name",
            "normalized_agency",
            "recipient_uei",
            "award_date",
            "fiscal_year",
            "amount_usd",
            "total_obligated",
        ],
        [
            {
                "record_id": "c1",
                "dataset": "pdf_contracts",
                "source_file": "contract.pdf",
                "evidence_tier": "T1_FEDERAL",
                "vendor_name": "Alpha LLC",
                "normalized_vendor": "ALPHA LLC",
                "agency_name": "FEMA",
                "normalized_agency": "FEDERAL EMERGENCY MANAGEMENT AGENCY",
                "recipient_uei": "ALPHAUEI",
                "award_date": "",
                "fiscal_year": "2025",
                "amount_usd": "1000",
                "total_obligated": "",
            }
        ],
    )
    _write_csv(
        awards,
        [
            "award_id",
            "recipient_name",
            "recipient_name_normalized",
            "recipient_uei",
            "awarding_agency",
            "awarding_sub_agency",
            "obligated_amount",
            "award_date",
            "fiscal_year",
            "pop_state",
            "pop_county",
            "description",
            "source_file",
            "source_dataset",
            "award_category",
        ],
        [
            {
                "award_id": "a1",
                "recipient_name": "Beta Inc",
                "recipient_name_normalized": "BETA INC",
                "recipient_uei": "BETAUEI",
                "awarding_agency": "USACE",
                "awarding_sub_agency": "USACE",
                "obligated_amount": "2500",
                "award_date": "2024-05-01",
                "fiscal_year": "2024",
                "pop_state": "PR",
                "pop_county": "Ponce",
                "description": "work",
                "source_file": "awards.csv",
                "source_dataset": "contracts",
                "award_category": "contract",
            }
        ],
    )
    _write_csv(
        lda,
        [
            "canonical_client",
            "total_lobbying_amount",
            "report_rows",
            "nonzero_rows",
            "first_year",
            "last_year",
            "registrant_count",
            "source_client_variants",
            "pr_relevant",
            "active_years",
            "canonical_sector",
        ],
        [
            {
                "canonical_client": "GAMMA CLIENT",
                "total_lobbying_amount": "50000",
                "report_rows": "2",
                "nonzero_rows": "1",
                "first_year": "2020",
                "last_year": "2025",
                "registrant_count": "1",
                "source_client_variants": "1",
                "pr_relevant": "True",
                "active_years": "6",
                "canonical_sector": "infra",
            }
        ],
    )

    report = prepare_uploaded_masters(contracts, awards, lda, out)

    assert report["input_rows"] == {"contracts_master": 1, "awards_master": 1, "lda_summary": 1}
    for name in (
        "entities_resolved.csv",
        "contracts_master.csv",
        "financial_flows_master.csv",
        "entity_edges.csv",
    ):
        assert (out / name).exists()
        assert report["output_rows"][name] > 0

    contracts_rows = list(csv.DictReader((out / "contracts_master.csv").open(encoding="utf-8")))
    assert contracts_rows[0]["normalized_name"] == "BETA INC"
    assert contracts_rows[0]["geo_municipality_name"] == "Ponce"
    assert contracts_rows[0]["award_date"] == "2024-05-01"

    flow_rows = list(csv.DictReader((out / "financial_flows_master.csv").open(encoding="utf-8")))
    assert len(flow_rows) == 2
    assert {row["source_system"] for row in flow_rows} == {"pdf_contracts", "uploaded_lda_summary"}


def test_artifact_manifest_records_hashes_and_counts(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "manifest.json").write_text(
        '{"producer":"contract-sweeper","export_contract_version":"1.1.0"}\n', encoding="utf-8"
    )
    (package / "entities.jsonl").write_text(
        '{"entity_id":"e1"}\n{"entity_id":"e2"}\n', encoding="utf-8"
    )
    source = tmp_path / "source.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    manifest = write_artifact_manifest(package, source_files=[source])

    assert manifest["schema_version"] == "artifact_manifest.v1"
    assert manifest["export_contract_version"] == "1.1.0"
    artifact_counts = {item["path"]: item["record_count"] for item in manifest["artifacts"]}
    assert artifact_counts["entities.jsonl"] == 2
    assert manifest["sources"][0]["record_count"] == 2
    assert (package / "artifact_manifest.json").exists()
    written = json.loads((package / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert written["artifact_count"] == manifest["artifact_count"]
