from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from moneysweep.case_manager.ids import deterministic_id
from moneysweep.case_manager.models import Case, CaseEvidence, Claim, Finding
from moneysweep.case_manager.repository import (
    CaseManagerConflict,
    SQLiteCaseManagerRepository,
)
from moneysweep.case_manager.service import CaseCommandService, CaseQueryService


@pytest.fixture
def repository():
    with closing(sqlite3.connect(":memory:")) as connection:
        repository = SQLiteCaseManagerRepository(connection)
        repository.apply_migration(Path("migrations/001_case_manager_v1.sql"))
        yield repository


def _case(visibility: str = "internal") -> Case:
    return Case(
        case_id=deterministic_id("case", "FEMA:4339:PW:8535"),
        title="Carraizo Reservoir Dredging",
        case_type="project_oversight",
        status="open",
        scope="Read-only QPR consolidation pilot",
        visibility=visibility,
    )


def test_command_is_atomic_with_audit_event(repository):
    service = CaseCommandService(repository)
    case = _case()
    result = service.create_case(case, "tester")
    assert result["audit_event"]["sequence"] == 1
    assert repository.fetch_one("cases", "case_id", case.case_id)["title"] == case.title
    events = repository.fetch_case_rows("case_audit_events", case.case_id)
    assert len(events) == 1
    assert events[0]["action"] == "create_case"


def test_transaction_rolls_back_object_when_audit_insert_fails(monkeypatch, repository):
    service = CaseCommandService(repository)
    case = _case()

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(repository, "append_audit_event", fail)
    with pytest.raises(RuntimeError):
        service.create_case(case, "tester")
    assert repository.list_cases() == []


def test_visibility_filtering_is_mandatory(repository):
    commands = CaseCommandService(repository)
    queries = CaseQueryService(repository)
    public_case = _case("public")
    restricted_case = Case(
        case_id=deterministic_id("case", "restricted"),
        title="Restricted",
        case_type="audit",
        status="open",
        scope="restricted",
        visibility="restricted",
    )
    commands.create_case(public_case, "tester")
    commands.create_case(restricted_case, "tester")
    assert [row["case_id"] for row in queries.list_cases("public")] == [public_case.case_id]
    assert len(queries.list_cases("restricted")) == 2


def test_reference_integrity_and_no_canonical_mutation_path(repository):
    commands = CaseCommandService(repository)
    case = _case()
    commands.create_case(case, "tester")
    with pytest.raises(ValueError):
        commands.link_evidence(
            CaseEvidence(
                case_evidence_id="case_evidence_bad",
                case_id=case.case_id,
                evidence_id="not-canonical",
                role="qpr",
            ),
            "tester",
        )
    tables = {
        row[0]
        for row in repository.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "evidence" not in tables
    assert "canonical_evidence" not in tables


def test_hash_chain_continuity_across_commands(repository):
    commands = CaseCommandService(repository)
    case = _case()
    commands.create_case(case, "tester")
    claim = Claim(
        claim_id=deterministic_id("claim", case.case_id, "schedule changed"),
        case_id=case.case_id,
        statement="Projected completion changed.",
        claim_type="schedule",
        status="pending",
        confidence=0.8,
        language_tier="linked",
    )
    commands.create_claim(claim, "tester")
    events = repository.fetch_case_rows("case_audit_events", case.case_id)
    assert [row["sequence"] for row in events] == [1, 2]
    assert events[1]["previous_event_sha256"] == events[0]["payload_sha256"]


def test_concurrent_sequence_rejection(repository):
    commands = CaseCommandService(repository)
    case = _case()
    commands.create_case(case, "tester")
    event = repository.fetch_case_rows("case_audit_events", case.case_id)[0]
    from moneysweep.case_manager.models import AuditEvent

    duplicate = AuditEvent(
        audit_event_id=deterministic_id("audit_event", "duplicate"),
        case_id=case.case_id,
        sequence=2,
        occurred_at="2026-07-28T00:00:00Z",
        actor="tester",
        action="duplicate",
        object_type="case",
        object_id=case.case_id,
        payload_sha256="b" * 64,
        previous_event_sha256=event["payload_sha256"],
    )
    with repository.transaction() as connection:
        with pytest.raises(CaseManagerConflict):
            repository.append_audit_event(duplicate, 0, connection)


def test_finding_acceptance_requires_review(repository):
    commands = CaseCommandService(repository)
    case = _case()
    commands.create_case(case, "tester")
    claim = Claim(
        claim_id=deterministic_id("claim", case.case_id, "claim"),
        case_id=case.case_id,
        statement="A claim",
        claim_type="test",
        status="pending",
        confidence=0.5,
        language_tier="inferred",
    )
    commands.create_claim(claim, "tester")
    finding = Finding(
        finding_id=deterministic_id("finding", claim.claim_id),
        case_id=case.case_id,
        claim_id=claim.claim_id,
        conclusion="Draft only",
        confidence=0.5,
        reviewer="reviewer",
        contradiction_reviewed=False,
    )
    commands.create_finding(finding, "tester")
    with pytest.raises(CaseManagerConflict):
        commands.accept_finding(
            case_id=case.case_id,
            finding_id=finding.finding_id,
            actor="tester",
        )


def test_carraizo_fixture_remains_read_only():
    import json

    fixture = json.loads(Path("tests/fixtures/case_manager/carraizo_case.json").read_text())
    assert fixture["fixture_status"] == "read_only_pending_review"
    assert fixture["canonical_promotion"] is False
