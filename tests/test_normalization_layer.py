"""Tests for Phase 3 canonical normalization layer."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from contract_sweeper.normalization.canonical_contracts import CANONICAL_CONTRACT_FIELDS
from contract_sweeper.normalization.normalization_runner import run_normalization
from contract_sweeper.normalization.source_normalizer import SourceContractsNormalizer
from contract_sweeper.runtime.schema_registry import SchemaDefinition, SchemaRegistry
from contract_sweeper.runtime.source_registry import SourceDefinition, SourceRegistry


def _build_schema_registry() -> SchemaRegistry:
    return SchemaRegistry(
        version=1,
        datasets=[
            SchemaDefinition(
                name="contracts_master",
                format="parquet",
                required_fields=CANONICAL_CONTRACT_FIELDS,
                optional_fields=["municipality", "contract_type", "award_status"],
            )
        ],
    )


def test_source_normalizer_maps_common_columns():
    normalizer = SourceContractsNormalizer("usaspending_awards")
    row = {
        "award_id": "A-100",
        "recipient_name": "Acme Builders LLC",
        "recipient_uei": "UEI12345",
        "awarding_agency": "Department of Defense",
        "obligated_amount": "$1,250,000.50",
        "award_date": "2025-01-15",
        "pop_state": "PR",
        "pop_county": "San Juan",
        "source_url": "https://example.test/award/A-100",
    }

    normalized = normalizer.normalize_row(row)

    assert normalized["entity_id"] == "UEI12345"
    assert normalized["normalized_name"] == "ACME BUILDERS LLC"
    assert normalized["award_id"] == "A-100"
    assert normalized["agency"] == "Department of Defense"
    assert normalized["obligation_amount"] == 1250000.50
    assert normalized["geo_location"] == "San Juan, PR"
    assert normalized["source_system"] == "usaspending_awards"
    assert normalized["source_date"] == "2025-01-15"
    assert normalized["link_confidence"] >= 0.9


def test_source_normalizer_generates_anon_entity_without_uei():
    normalizer = SourceContractsNormalizer("municipal_contracts")
    row = {
        "vendor_name": "Municipal Services Corp",
        "contract_id": "M-0001",
        "obligated_amount": "77000",
    }

    normalized = normalizer.normalize_row(row)

    assert normalized["entity_id"].startswith("anon-")
    assert normalized["normalized_name"] == "MUNICIPAL SERVICES CORP"
    assert normalized["award_id"] == "M-0001"
    assert normalized["project_id"] == "M-0001"


def test_run_normalization_writes_canonical_master_outputs(tmp_path: Path):
    input_dir = tmp_path / "data" / "staging" / "processed"
    input_dir.mkdir(parents=True, exist_ok=True)

    src_file = input_dir / "pr_grants_master.csv"
    with src_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["award_id", "recipient_name", "obligated_amount", "awarding_agency", "award_date", "pop_state"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "award_id": "G-001",
                "recipient_name": "Island Health Group",
                "obligated_amount": "100000",
                "awarding_agency": "HHS",
                "award_date": "2024-10-01",
                "pop_state": "PR",
            }
        )

    source_registry = SourceRegistry(
        version=1,
        defaults={},
        sources=[
            SourceDefinition(
                source_id="usaspending_awards",
                enabled=True,
                priority=1,
                module="scripts.download_grants",
                entrypoint="run",
                description="test",
                output_paths=["data/staging/processed/pr_grants_master.csv"],
                required_fields=["award_id", "recipient_name", "obligated_amount", "source_dataset"],
                supports={
                    "pagination": True,
                    "retry_backoff": True,
                    "resume": True,
                    "cache": True,
                    "time_window_splitting": True,
                    "manifest": True,
                    "completeness_logging": True,
                },
            )
        ],
    )

    summary = run_normalization(
        project_root=tmp_path,
        source_registry=source_registry,
        schema_registry=_build_schema_registry(),
    )

    assert summary.total_rows == 1
    assert summary.contracts_master_csv.exists()
    assert summary.contracts_master_parquet.exists()

    csv_df = pd.read_csv(summary.contracts_master_csv)
    assert set(CANONICAL_CONTRACT_FIELDS).issubset(set(csv_df.columns))
    assert csv_df.iloc[0]["award_id"] == "G-001"
    assert csv_df.iloc[0]["source_system"] == "usaspending_awards"

    parquet_df = pd.read_parquet(summary.contracts_master_parquet)
    assert len(parquet_df) == 1
    assert parquet_df.iloc[0]["entity_id"] != ""
