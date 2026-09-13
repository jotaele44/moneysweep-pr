from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from moneysweep.case_manager.ids import deterministic_id
from moneysweep.case_manager.models import Case, CaseEvidence, Claim, Finding
from moneysweep.case_manager.repository import SQLiteCaseManagerRepository
from moneysweep.case_manager.service import CaseCommandService, CaseQueryService
from moneysweep.validation import canonical_v1_schema as cv1
from moneysweep.validation.case_manager_sqlite import certify_sqlite
from moneysweep.validation.evidence_provenance import audit_evidence
from moneysweep.validation.federation_package import certify_federation_package
from scripts.certify_database_release import build_report
from scripts import remediate_canonical_evidence_provenance as remediation

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_database_release_certifier_direct_entrypoint_is_cwd_independent(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/certify_database_release.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--allow-blocked-sqlite" in result.stdout


def test_repo_database_release_preserves_all_current_blockers():
    report = build_report(REPO_ROOT, REPO_ROOT / "data/case_manager.sqlite3")

    assert report["vectors"] == {
        "A_CANONICAL_DATABASE": "PASS",
        "B_PROVENANCE_AND_FEDERATION": "FAIL",
        "C_SQLITE_RUNTIME": "BLOCKED",
    }
    assert report["evidence_provenance"]["t1_state_counts"] == {
        "noncanonical": 127,
        "unresolved": 36,
    }
    assert report["evidence_provenance"]["unbound_t1_count"] == 163
    assert report["status"] == "FAIL"
    assert report["zero_unresolved_residue"] is False


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_atomic_csv_preserves_write_failure_when_temp_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation.tempfile, "mkstemp", lambda **_kwargs: (99, "missing"))

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("primary write failure")

    monkeypatch.setattr(remediation.os, "fdopen", fail_write)
    monkeypatch.setattr(
        remediation.os,
        "unlink",
        lambda _path: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(RuntimeError, match="primary write failure"):
        remediation.atomic_csv(tmp_path / "target.csv", ["id"], [{"id": "one"}])


def test_revenue_stream_is_inside_canonical_denominator():
    assert cv1.TABLES["revenue_streams"][1] == "revenue_streams.csv"
    assert (REPO_ROOT / "schemas/canonical_v1/revenue_streams.schema.json").exists()


def test_primary_key_duplicate_is_certification_failure():
    tables = {"entities": [{"entity_id": "entity_a"}, {"entity_id": "entity_a"}]}
    report = cv1.ValidationReport()
    cv1.validate_primary_key_uniqueness(tables, report)
    assert any("duplicate primary key" in error for error in report.errors)


def test_unregistered_canonical_csv_is_discovered(tmp_path: Path):
    data_dir = tmp_path / cv1.DATA_DIR
    data_dir.mkdir(parents=True)
    (data_dir / "shadow_table.csv").write_text("id\n1\n", encoding="utf-8")
    report = cv1.ValidationReport()
    cv1.validate_denominator_headers_and_rows(report, tmp_path)
    assert any("unregistered canonical table present: shadow_table.csv" in e for e in report.errors)


def test_repo_canonical_denominator_is_exact():
    expected = {csv_name for _schema, csv_name, _pk in cv1.TABLES.values()}
    actual = {path.name for path in (REPO_ROOT / cv1.DATA_DIR).glob("*.csv")}
    assert actual == expected


def test_internal_t1_without_authority_binding_is_open(tmp_path: Path):
    _write_csv(
        tmp_path / "data/canonical_v1/evidence.csv",
        [
            "evidence_id",
            "source_type",
            "source_name",
            "source_path_or_url",
            "page_or_line_ref",
            "claim",
            "evidence_tier",
            "extraction_method",
            "confidence",
            "review_status",
        ],
        [
            {
                "evidence_id": "evidence_x",
                "source_type": "registry",
                "source_name": "Internal seed",
                "source_path_or_url": "data/reference/seed.csv",
                "page_or_line_ref": "row 2",
                "claim": "x",
                "evidence_tier": "T1",
                "extraction_method": "manual",
                "confidence": "0.95",
                "review_status": "accepted",
            }
        ],
    )
    report = audit_evidence(tmp_path)
    assert not report.ok
    assert report.unbound_t1_count == 1
    assert report.issues[0]["classification"] == "SOURCE_TAXONOMY_NOT_IDENTITY"


def test_explicit_authority_binding_can_certify_t1(tmp_path: Path):
    evidence = tmp_path / "data/canonical_v1/evidence.csv"
    _write_csv(
        evidence,
        [
            "evidence_id",
            "source_type",
            "source_name",
            "source_path_or_url",
            "page_or_line_ref",
            "claim",
            "evidence_tier",
            "extraction_method",
            "confidence",
            "review_status",
        ],
        [
            {
                "evidence_id": "evidence_x",
                "source_type": "registry",
                "source_name": "Official export",
                "source_path_or_url": "data/raw/official.csv",
                "page_or_line_ref": "row 2",
                "claim": "x",
                "evidence_tier": "T1",
                "extraction_method": "manual",
                "confidence": "0.95",
                "review_status": "accepted",
            }
        ],
    )
    bindings = tmp_path / "data/manifests/evidence_source_bindings.json"
    bindings.parent.mkdir(parents=True, exist_ok=True)
    bindings.write_text(
        json.dumps(
            {
                "bindings": [
                    {
                        "binding_key": "data/raw/official.csv",
                        "status": "authoritative",
                        "stable_id": "official-record-123",
                        "sha256": "a" * 64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = audit_evidence(tmp_path)
    assert report.ok
    assert report.authoritative_binding_count == 1


def test_federation_manifest_hash_and_count_are_enforced(tmp_path: Path):
    package = tmp_path / "data/exports/canonical_v1_federation"
    package.mkdir(parents=True)
    payload = '{"id":"x"}\n'
    stream = package / "entities.jsonl"
    stream.write_text(payload, encoding="utf-8")
    sha = hashlib.sha256(payload.encode()).hexdigest()
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "package_id": "pkg_test",
                "files": [
                    {
                        "filename": "entities.jsonl",
                        "stream": "entities",
                        "record_count": 1,
                        "sha256": sha,
                        "schema_id": "federation_entity.schema.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert certify_federation_package(tmp_path).ok
    stream.write_text(payload + '{"id":"y"}\n', encoding="utf-8")
    assert not certify_federation_package(tmp_path).ok


def _case(case_key: str, visibility: str = "internal") -> Case:
    return Case(
        case_id=deterministic_id("case", case_key),
        title=case_key,
        case_type="audit",
        status="open",
        scope="test",
        visibility=visibility,
    )


def test_configured_catalog_rejects_dangling_case_evidence(tmp_path: Path):
    evidence_path = tmp_path / "evidence.csv"
    _write_csv(evidence_path, ["evidence_id"], [{"evidence_id": "evidence_real"}])
    connection = sqlite3.connect(":memory:")
    repository = SQLiteCaseManagerRepository(connection, canonical_evidence_path=evidence_path)
    repository.apply_migration(REPO_ROOT / "migrations/001_case_manager_v1.sql")
    commands = CaseCommandService(repository)
    case = _case("catalog")
    commands.create_case(case, "tester")
    with pytest.raises(ValueError, match="not found"):
        commands.link_evidence(
            CaseEvidence(
                case_evidence_id="case_evidence_missing",
                case_id=case.case_id,
                evidence_id="evidence_missing",
                role="source",
            ),
            "tester",
        )


def test_parent_case_visibility_dominates_public_child():
    connection = sqlite3.connect(":memory:")
    repository = SQLiteCaseManagerRepository(connection)
    repository.apply_migration(REPO_ROOT / "migrations/001_case_manager_v1.sql")
    commands = CaseCommandService(repository)
    queries = CaseQueryService(repository)
    case = _case("restricted-parent", "restricted")
    commands.create_case(case, "tester")
    claim = Claim(
        claim_id=deterministic_id("claim", case.case_id, "public-child"),
        case_id=case.case_id,
        statement="public child",
        claim_type="test",
        status="pending",
        confidence=0.5,
        language_tier="inferred",
        visibility="public",
    )
    commands.create_claim(claim, "tester")
    assert queries.get_case_collection(case.case_id, "claims", "public") == []
    assert len(queries.get_case_collection(case.case_id, "claims", "restricted")) == 1


def test_cross_case_finding_is_rejected():
    connection = sqlite3.connect(":memory:")
    repository = SQLiteCaseManagerRepository(connection)
    repository.apply_migration(REPO_ROOT / "migrations/001_case_manager_v1.sql")
    commands = CaseCommandService(repository)
    case_a = _case("a")
    case_b = _case("b")
    commands.create_case(case_a, "tester")
    commands.create_case(case_b, "tester")
    claim = Claim(
        claim_id=deterministic_id("claim", case_a.case_id, "claim"),
        case_id=case_a.case_id,
        statement="claim",
        claim_type="test",
        status="pending",
        confidence=0.5,
        language_tier="inferred",
    )
    commands.create_claim(claim, "tester")
    finding = Finding(
        finding_id=deterministic_id("finding", case_b.case_id, claim.claim_id),
        case_id=case_b.case_id,
        claim_id=claim.claim_id,
        conclusion="wrong case",
        confidence=0.5,
        reviewer="tester",
        contradiction_reviewed=True,
    )
    with pytest.raises(ValueError, match="does not belong"):
        commands.create_finding(finding, "tester")


def test_sqlite_runtime_certifier_passes_quiesced_database(tmp_path: Path):
    evidence_path = tmp_path / "data/canonical_v1/evidence.csv"
    _write_csv(evidence_path, ["evidence_id"], [{"evidence_id": "evidence_real"}])
    db_path = tmp_path / "case_manager.sqlite3"
    repository = SQLiteCaseManagerRepository(db_path, canonical_evidence_path=evidence_path)
    repository.apply_migration(REPO_ROOT / "migrations/001_case_manager_v1.sql")
    CaseCommandService(repository).create_case(_case("runtime"), "tester")
    repository.close()
    report = certify_sqlite(db_path, evidence_path)
    assert report.ok, report.to_dict()
    assert report.integrity_check == ["ok"]
    assert report.foreign_key_violations == []
