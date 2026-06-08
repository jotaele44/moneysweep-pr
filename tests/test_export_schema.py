"""Schema-contract tests for the federation export JSON Schemas."""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

EXPECTED_REQUIRED = {
    "contract_sweeper_entity.schema.json": {
        "entity_id",
        "source_id",
        "name",
        "normalized_name",
        "entity_type",
        "jurisdiction",
        "confidence",
        "lineage",
        "synthetic",
        "created_at",
        "extracted_at",
    },
    "contract_sweeper_source.schema.json": {
        "source_id",
        "source_type",
        "source_name",
        "confidence",
        "lineage",
        "synthetic",
        "created_at",
        "extracted_at",
    },
    "contract_sweeper_funding_award.schema.json": {
        "award_id",
        "source_id",
        "recipient_entity_id",
        "funding_agency_entity_id",
        "amount",
        "currency",
        "fiscal_year",
        "award_type",
        "award_date",
        "confidence",
        "lineage",
        "synthetic",
        "created_at",
        "extracted_at",
    },
    "contract_sweeper_transaction.schema.json": {
        "transaction_id",
        "source_id",
        "payer_entity_id",
        "payee_entity_id",
        "amount",
        "currency",
        "transaction_date",
        "transaction_type",
        "confidence",
        "lineage",
        "synthetic",
        "created_at",
        "extracted_at",
    },
    "contract_sweeper_relationship.schema.json": {
        "relationship_id",
        "source_id",
        "source_entity_id",
        "target_entity_id",
        "relationship_type",
        "evidence_source_id",
        "confidence",
        "lineage",
        "synthetic",
        "created_at",
        "extracted_at",
    },
    "contract_sweeper_export_manifest.schema.json": {
        "package_id",
        "producer",
        "producer_version",
        "export_contract_version",
        "mode",
        "created_at",
        "extracted_at",
        "federation",
        "files",
    },
}

ALL_SCHEMA_FILES = sorted(EXPECTED_REQUIRED.keys())


@pytest.mark.unit
@pytest.mark.parametrize("filename", ALL_SCHEMA_FILES)
def test_schema_parses_and_has_metadata(filename):
    data = json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))
    assert data.get("$schema"), f"{filename} missing $schema"
    assert data.get("title"), f"{filename} missing title"
    assert data.get("type") == "object", f"{filename} type must be object"
    assert isinstance(data.get("required"), list), f"{filename} missing required[]"


@pytest.mark.unit
@pytest.mark.parametrize("filename", ALL_SCHEMA_FILES)
def test_schema_required_matches_contract(filename):
    data = json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))
    assert set(data["required"]) == EXPECTED_REQUIRED[filename]


@pytest.mark.unit
def test_all_expected_schema_files_exist():
    on_disk = {p.name for p in SCHEMAS_DIR.glob("*.schema.json")}
    assert set(EXPECTED_REQUIRED.keys()).issubset(on_disk)


@pytest.mark.unit
def test_manifest_schema_requires_federation_handshake():
    data = json.loads(
        (SCHEMAS_DIR / "contract_sweeper_export_manifest.schema.json").read_text(encoding="utf-8")
    )
    federation = data["properties"]["federation"]
    assert set(federation["required"]) == {
        "producer_repo",
        "consumer_repo",
        "consumer_component",
        "contract",
    }
    assert federation["properties"]["consumer_repo"]["const"] == "spiderweb-pr"
    assert federation["properties"]["consumer_component"]["const"] == "query-hub"
