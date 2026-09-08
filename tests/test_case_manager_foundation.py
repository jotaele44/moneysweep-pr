import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from moneysweep.case_manager import (
    AuditEvent,
    Case,
    CaseEvidence,
    Claim,
    ClaimEvidence,
    Contradiction,
    Finding,
    ValidationError,
    deterministic_id,
    validate_append_only_events,
    validate_case_bundle,
)


def _case(case_id: str) -> Case:
    return Case(
        case_id=case_id,
        title="Test case",
        case_type="audit",
        status="open",
        scope="test scope",
    )


def _claim(case_id: str, claim_id: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        case_id=case_id,
        statement="The projected completion date changed.",
        claim_type="schedule",
        status="pending",
        confidence=0.85,
        language_tier="linked",
    )


def _event(
    case_id: str,
    sequence: int,
    payload_hash: str,
    previous_hash: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        audit_event_id=deterministic_id("audit_event", sequence),
        case_id=case_id,
        sequence=sequence,
        occurred_at=f"2026-01-{sequence:02d}T00:00:00Z",
        actor="tester",
        action="review",
        object_type="case",
        object_id=case_id,
        payload_sha256=payload_hash,
        previous_event_sha256=previous_hash,
    )


@pytest.fixture
def database():
    with closing(sqlite3.connect(":memory:")) as database:
        database.execute("PRAGMA foreign_keys = ON")
        database.executescript(Path("migrations/001_case_manager_v1.sql").read_text())
        yield database


def test_deterministic_ids_are_idempotent():
    left = deterministic_id("case", "FEMA", 4339, "PW", 8535)
    right = deterministic_id("case", "FEMA", 4339, "PW", 8535)
    assert left == right
    assert left.startswith("case_")


def test_claim_and_finding_are_separate():
    case_id = deterministic_id("case", "FEMA:4339:PW:8535")
    evidence_id = "evidence_carraizo_qpr_2026_q2_abc123"
    claim_id = deterministic_id("claim", case_id, "schedule changed")
    bundle = {
        "case": _case(case_id),
        "canonical_evidence_ids": (evidence_id,),
        "case_evidence": (
            CaseEvidence(
                case_evidence_id=deterministic_id(
                    "case_evidence",
                    case_id,
                    evidence_id,
                ),
                case_id=case_id,
                evidence_id=evidence_id,
                role="qpr",
            ),
        ),
        "claims": (_claim(case_id, claim_id),),
        "claim_evidence": (
            ClaimEvidence(
                claim_evidence_id=deterministic_id(
                    "claim_evidence",
                    claim_id,
                    evidence_id,
                    "support",
                ),
                claim_id=claim_id,
                evidence_id=evidence_id,
                relation="support",
            ),
        ),
        "contradictions": (),
        "findings": (
            Finding(
                finding_id=deterministic_id("finding", claim_id),
                case_id=case_id,
                claim_id=claim_id,
                conclusion="Schedule changed across reports.",
                confidence=0.85,
                reviewer="reviewer",
                contradiction_reviewed=True,
                status="accepted",
            ),
        ),
        "audit_events": (),
    }
    validate_case_bundle(bundle)


def test_unresolved_contradictions_are_not_auto_collapsed():
    case_id = deterministic_id("case", "x")
    first_claim = deterministic_id("claim", "a")
    second_claim = deterministic_id("claim", "b")
    contradiction = Contradiction(
        contradiction_id=deterministic_id(
            "contradiction",
            first_claim,
            second_claim,
        ),
        case_id=case_id,
        claim_ids=(first_claim, second_claim),
        contradiction_type="temporal",
        severity="high",
    )
    assert contradiction.status == "open"
    assert contradiction.claim_ids == (first_claim, second_claim)
    assert contradiction.visibility == "internal"


def test_accepted_finding_requires_contradiction_review():
    case_id = deterministic_id("case", "x")
    claim_id = deterministic_id("claim", "x")
    finding = Finding(
        finding_id=deterministic_id("finding", claim_id),
        case_id=case_id,
        claim_id=claim_id,
        conclusion="X",
        confidence=0.5,
        reviewer="reviewer",
        contradiction_reviewed=False,
        status="accepted",
    )
    bundle = {
        "case": _case(case_id),
        "canonical_evidence_ids": (),
        "case_evidence": (),
        "claims": (_claim(case_id, claim_id),),
        "claim_evidence": (),
        "contradictions": (),
        "findings": (finding,),
        "audit_events": (),
    }
    with pytest.raises(ValidationError):
        validate_case_bundle(bundle)


def test_audit_events_are_hash_chained():
    case_id = deterministic_id("case", "x")
    first_hash = hashlib.sha256(b"first").hexdigest()
    second_hash = hashlib.sha256(b"second").hexdigest()
    events = (
        _event(case_id, 1, first_hash),
        _event(case_id, 2, second_hash, first_hash),
    )
    validate_append_only_events(events)


def test_audit_event_rejects_wrong_predecessor_hash():
    case_id = deterministic_id("case", "x")
    first_hash = hashlib.sha256(b"first").hexdigest()
    second_hash = hashlib.sha256(b"second").hexdigest()
    events = (
        _event(case_id, 1, first_hash),
        _event(case_id, 2, second_hash, "0" * 64),
    )
    with pytest.raises(ValidationError):
        validate_append_only_events(events)


def test_case_manager_schema_is_valid_draft7():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path("schemas/case_manager_v1/case_manager.schema.json")
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    assert "definitions" in schema
    assert "$defs" not in schema
    for definition in (
        "claim_evidence",
        "case_event",
        "contradiction",
        "lead",
        "finding",
        "case_snapshot",
        "audit_event",
    ):
        assert "visibility" in schema["definitions"][definition]["required"]


def test_sql_migration_is_idempotent_from_clean_state():
    sql = Path("migrations/001_case_manager_v1.sql").read_text()
    query = "SELECT name FROM sqlite_master WHERE type='table'"
    for _ in range(2):
        database = sqlite3.connect(":memory:")
        database.executescript(sql)
        database.executescript(sql)
        names = {row[0] for row in database.execute(query)}
        tables = {name for name in names if not name.startswith("sqlite_")}
        assert len(tables) == 11
        assert "cases" in tables
        assert "case_audit_events" in tables
        database.close()


def test_sql_migration_creates_required_indexes(database):
    index_rows = database.execute("SELECT name FROM sqlite_master WHERE type='index'")
    names = {row[0] for row in index_rows}
    expected = {
        "idx_case_evidence_case",
        "idx_case_evidence_evidence",
        "idx_claims_case",
        "idx_claim_evidence_claim",
        "idx_claim_evidence_evidence",
        "idx_case_entities_case",
        "idx_case_events_case_occurred",
        "idx_contradictions_case_status",
        "idx_leads_case_status",
        "idx_findings_case_status",
        "idx_case_audit_events_case_sequence",
    }
    assert expected.issubset(names)


def test_sql_rejects_invalid_visibility_and_json(database):
    database.execute(
        "INSERT INTO cases(case_id,title,case_type,status,scope,visibility) "
        "VALUES('case_x','X','audit','open','scope','internal')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "INSERT INTO case_events VALUES"
            "('case_event_x','case_x','status','2026-01-01','X','[]',NULL,1,'secret')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "INSERT INTO contradictions VALUES"
            "('contradiction_x','case_x','not-json','temporal','high','open',"
            "NULL,NULL,'internal')"
        )


def test_sql_foreign_keys_are_restrictive(database):
    database.execute(
        "INSERT INTO cases(case_id,title,case_type,status,scope,visibility) "
        "VALUES('case_x','X','audit','open','scope','internal')"
    )
    database.execute(
        "INSERT INTO claims VALUES"
        "('claim_x','case_x','X','test','pending',0.5,'inferred','internal')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("DELETE FROM cases WHERE case_id='case_x'")


def test_sql_migration_blocks_audit_event_mutation(database):
    database.execute(
        "INSERT INTO cases(case_id,title,case_type,status,scope,visibility) "
        "VALUES('case_x','X','audit','open','scope','internal')"
    )
    database.execute(
        "INSERT INTO case_audit_events"
        "(audit_event_id,case_id,sequence,occurred_at,actor,action,object_type,"
        "object_id,payload_sha256,previous_event_sha256,visibility) VALUES"
        "('audit_event_x','case_x',1,'2026-01-01','tester','create',"
        "'case','case_x',?,NULL,'internal')",
        ("a" * 64,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("UPDATE case_audit_events SET actor='other'")
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("DELETE FROM case_audit_events")


def test_fixture_is_read_only_and_not_promoted():
    fixture_path = Path("tests/fixtures/case_manager/carraizo_case.json")
    fixture = json.loads(fixture_path.read_text())
    assert fixture["fixture_status"] == "read_only_pending_review"
    assert fixture["canonical_promotion"] is False


def test_contradiction_rejects_duplicate_claim_ids():
    case_id = deterministic_id("case", "x")
    claim_id = deterministic_id("claim", "a")
    bundle = {
        "case": _case(case_id),
        "canonical_evidence_ids": (),
        "case_evidence": (),
        "claims": (_claim(case_id, claim_id),),
        "claim_evidence": (),
        "contradictions": (
            Contradiction(
                contradiction_id=deterministic_id("contradiction", claim_id, claim_id),
                case_id=case_id,
                claim_ids=(claim_id, claim_id),
                contradiction_type="temporal",
                severity="high",
            ),
        ),
        "findings": (),
        "audit_events": (),
    }
    with pytest.raises(ValidationError):
        validate_case_bundle(bundle)


def test_patterned_schema_fields_declare_string_type():
    schema = json.loads(Path("schemas/case_manager_v1/case_manager.schema.json").read_text())

    def walk(node):
        if isinstance(node, dict):
            if "pattern" in node:
                declared = node.get("type")
                assert declared == "string" or (
                    isinstance(declared, list) and "string" in declared
                ), f"patterned field must declare a string type, got {declared!r}"
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
