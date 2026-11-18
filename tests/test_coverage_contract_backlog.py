from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from tools.build_coverage_contract_backlog import build


def _write_registry(root: Path) -> None:
    path = root / "registries/source_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "test_v1",
                "sources": [
                    {
                        "source_id": "ready",
                        "family": "test",
                        "required": True,
                        "authentication": "none",
                        "producer_script": "scripts/ready.py",
                        "expected_outputs": ["data/ready.csv"],
                        "validation_threshold": {"min_rows": 1},
                    },
                    {
                        "source_id": "unmeasured",
                        "family": "test",
                        "required": True,
                        "authentication": "none",
                        "producer_script": "scripts/unmeasured.py",
                        "expected_outputs": ["data/unmeasured.csv"],
                        "validation_threshold": {"min_rows": 1},
                    },
                    {
                        "source_id": "missing",
                        "family": "test",
                        "required": False,
                        "authentication": "manual_export",
                        "producer_script": "scripts/missing.py",
                        "expected_outputs": ["data/missing.csv"],
                        "validation_threshold": {"min_rows": 1},
                    },
                    {
                        "source_id": "name_only",
                        "family": "test",
                        "required": False,
                        "authentication": "none",
                        "producer_script": "scripts/name_only.py",
                        "expected_outputs": ["data/name_only.csv"],
                        "validation_threshold": {"min_rows": 1},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_recovery(root: Path) -> None:
    path = root / "reports/source_recovery_matrix.csv"
    path.parent.mkdir(parents=True)
    fields = [
        "source_id",
        "required",
        "automatable",
        "path_type",
        "authentication",
    ]
    rows = [
        {
            "source_id": "ready",
            "required": "True",
            "automatable": "True",
            "path_type": "api_producer",
            "authentication": "none",
        },
        {
            "source_id": "unmeasured",
            "required": "True",
            "automatable": "True",
            "path_type": "api_producer",
            "authentication": "none",
        },
        {
            "source_id": "missing",
            "required": "False",
            "automatable": "False",
            "path_type": "manual_export",
            "authentication": "manual_export",
        },
        {
            "source_id": "name_only",
            "required": "False",
            "automatable": "True",
            "path_type": "api_producer",
            "authentication": "none",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_contracts(root: Path) -> None:
    path = root / "registries/coverage_contracts.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "coverage_contracts_v1",
                "contracts": [
                    {
                        "source_id": "ready",
                        "contract_version": 1,
                        "authoritative_universe_method": "portal_count",
                        "authoritative_universe_ref": "https://example.invalid/ready",
                        "authoritative_universe_total": 10,
                        "uniqueness_key": ["stable_id"],
                    },
                    {
                        "source_id": "unmeasured",
                        "contract_version": 1,
                        "authoritative_universe_method": "api_metadata",
                        "authoritative_universe_total": None,
                        "uniqueness_key": ["stable_id"],
                    },
                    {
                        "source_id": "name_only",
                        "contract_version": 1,
                        "authoritative_universe_method": "portal_count",
                        "authoritative_universe_total": 5,
                        "uniqueness_key": ["vendor_name"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write_registry(root)
    _write_recovery(root)
    _write_contracts(root)
    return root


def test_backlog_partitions_exact_source_id_sets(tmp_path: Path) -> None:
    root = _fixture(tmp_path)

    report = build(root=root)
    by_id = {row["source_id"]: row for row in report["sources"]}

    assert report["summary"]["registry_total"] == 4
    assert report["summary"]["recovery_total"] == 4
    assert report["summary"]["contract_total"] == 3
    assert report["summary"]["automatable_total"] == 3
    assert report["summary"]["required_total"] == 2
    assert by_id["ready"]["contract_state"] == "CONTRACT_STRUCTURALLY_READY"
    assert by_id["unmeasured"]["contract_state"] == "DENOMINATOR_UNMEASURED"
    assert by_id["missing"]["contract_state"] == "CONTRACT_MISSING"
    assert by_id["name_only"]["contract_state"] == "IDENTITY_KEY_NAME_ONLY"
    assert report["summary"]["automatable_state_counts"] == {
        "CONTRACT_STRUCTURALLY_READY": 1,
        "DENOMINATOR_UNMEASURED": 1,
        "IDENTITY_KEY_NAME_ONLY": 1,
    }
    assert report["automatable_blocker_ids"] == ["name_only", "unmeasured"]
    assert report["required_blocker_ids"] == ["unmeasured"]


def test_structural_ready_never_claims_coverage_complete(tmp_path: Path) -> None:
    root = _fixture(tmp_path)

    report = build(root=root)
    ready = next(row for row in report["sources"] if row["source_id"] == "ready")

    assert ready["contract_state"] == "CONTRACT_STRUCTURALLY_READY"
    assert "does not establish" in report["claim"]


def test_recovery_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    recovery = root / "reports/source_recovery_matrix.csv"
    text = recovery.read_text(encoding="utf-8")
    recovery.write_text(text.replace("missing,False", "ghost,False"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="recovery matrix identity mismatch"):
        build(root=root)


def test_unknown_contract_source_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    contracts = root / "registries/coverage_contracts.yaml"
    payload = yaml.safe_load(contracts.read_text(encoding="utf-8"))
    payload["contracts"].append(
        {
            "source_id": "ghost",
            "contract_version": 1,
            "authoritative_universe_method": "portal_count",
            "authoritative_universe_total": 1,
            "uniqueness_key": ["stable_id"],
        }
    )
    contracts.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="coverage contract identity mismatch"):
        build(root=root)


def test_duplicate_contract_source_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    contracts = root / "registries/coverage_contracts.yaml"
    payload = yaml.safe_load(contracts.read_text(encoding="utf-8"))
    payload["contracts"].append(dict(payload["contracts"][0]))
    contracts.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="coverage contract identity mismatch"):
        build(root=root)
