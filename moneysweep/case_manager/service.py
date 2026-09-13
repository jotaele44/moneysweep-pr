"""Transactional Case Manager command and query services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Callable, Iterable

from .ids import deterministic_id
from .models import (
    AuditEvent,
    Case,
    CaseEvidence,
    CaseSnapshot,
    Claim,
    ClaimEvidence,
    Contradiction,
    Finding,
    Lead,
    Visibility,
)
from .repository import SQLiteCaseManagerRepository

VISIBILITY_RANK = {"public": 0, "internal": 1, "restricted": 2}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class VisibilityPolicy:
    """Simple clearance filter used by query services and command authorization."""

    def __init__(self, clearance: str = "internal"):
        if clearance not in VISIBILITY_RANK:
            raise ValueError("invalid clearance")
        self.clearance = clearance

    def permits(self, visibility: str) -> bool:
        return VISIBILITY_RANK[visibility] <= VISIBILITY_RANK[self.clearance]

    def filter(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if self.permits(row.get("visibility", "internal"))]


class CaseCommandService:
    """Command-oriented writes; every command appends an audit event atomically."""

    def __init__(self, repository: SQLiteCaseManagerRepository):
        self.repository = repository

    def _require_evidence_ids(self, evidence_ids: Iterable[str]) -> None:
        ids = tuple(evidence_ids)
        if not ids or any(not item.startswith("evidence_") for item in ids):
            raise ValueError("canonical evidence identifiers required")
        for item in ids:
            exists = self.repository.canonical_evidence_exists(item)
            if exists is False:
                raise ValueError(f"canonical evidence identifier not found: {item}")

    def _require_case_object(
        self, table: str, id_column: str, object_id: str, case_id: str
    ) -> dict[str, Any]:
        row = self.repository.fetch_one(table, id_column, object_id)
        if row.get("case_id") != case_id:
            raise ValueError(f"{table} object does not belong to case {case_id}")
        return row

    def _execute(
        self,
        *,
        case_id: str,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        visibility: Visibility,
        payload: dict[str, Any],
        writer: Callable[[Any], None],
    ) -> dict[str, Any]:
        previous_sequence, previous_hash = self.repository.latest_audit(case_id)
        event = AuditEvent(
            audit_event_id=deterministic_id(
                "audit_event",
                case_id,
                previous_sequence + 1,
                action,
                object_id,
                _payload_hash(payload),
            ),
            case_id=case_id,
            sequence=previous_sequence + 1,
            occurred_at=_now(),
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload_sha256=_payload_hash(payload),
            previous_event_sha256=previous_hash,
            visibility=visibility,
        )
        with self.repository.transaction() as connection:
            writer(connection)
            self.repository.append_audit_event(event, previous_sequence, connection)
        return {"object": payload, "audit_event": asdict(event)}

    def create_case(self, case: Case, actor: str) -> dict[str, Any]:
        payload = asdict(case)
        return self._execute(
            case_id=case.case_id,
            actor=actor,
            action="create_case",
            object_type="case",
            object_id=case.case_id,
            visibility=case.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_case(case, connection),
        )

    def link_evidence(self, record: CaseEvidence, actor: str) -> dict[str, Any]:
        self._require_evidence_ids((record.evidence_id,))
        payload = asdict(record)
        return self._execute(
            case_id=record.case_id,
            actor=actor,
            action="link_evidence",
            object_type="case_evidence",
            object_id=record.case_evidence_id,
            visibility=record.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_case_evidence(record, connection),
        )

    def create_claim(self, claim: Claim, actor: str) -> dict[str, Any]:
        payload = asdict(claim)
        return self._execute(
            case_id=claim.case_id,
            actor=actor,
            action="create_claim",
            object_type="claim",
            object_id=claim.claim_id,
            visibility=claim.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_claim(claim, connection),
        )

    def link_claim_evidence(
        self, case_id: str, record: ClaimEvidence, actor: str
    ) -> dict[str, Any]:
        self._require_case_object("claims", "claim_id", record.claim_id, case_id)
        self._require_evidence_ids((record.evidence_id,))
        payload = asdict(record)
        return self._execute(
            case_id=case_id,
            actor=actor,
            action="link_claim_evidence",
            object_type="claim_evidence",
            object_id=record.claim_evidence_id,
            visibility=record.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_claim_evidence(record, connection),
        )

    def create_contradiction(self, record: Contradiction, actor: str) -> dict[str, Any]:
        if record.status != "open":
            raise ValueError("new contradictions must remain open")
        for claim_id in record.claim_ids:
            self._require_case_object("claims", "claim_id", claim_id, record.case_id)
        payload = asdict(record)
        return self._execute(
            case_id=record.case_id,
            actor=actor,
            action="create_contradiction",
            object_type="contradiction",
            object_id=record.contradiction_id,
            visibility=record.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_contradiction(record, connection),
        )

    def resolve_contradiction(
        self,
        *,
        case_id: str,
        contradiction_id: str,
        status: str,
        rationale: str,
        reviewer: str,
        actor: str,
        visibility: Visibility = "internal",
    ) -> dict[str, Any]:
        if status not in {"resolved", "held_apart"} or not rationale.strip():
            raise ValueError("explicit resolution status and rationale required")
        self._require_case_object("contradictions", "contradiction_id", contradiction_id, case_id)
        payload = {
            "contradiction_id": contradiction_id,
            "status": status,
            "resolution_rationale": rationale,
            "assigned_reviewer": reviewer,
        }
        return self._execute(
            case_id=case_id,
            actor=actor,
            action="resolve_contradiction",
            object_type="contradiction",
            object_id=contradiction_id,
            visibility=visibility,
            payload=payload,
            writer=lambda connection: self.repository.resolve_contradiction(
                contradiction_id, status, rationale, reviewer, connection
            ),
        )

    def create_lead(self, lead: Lead, actor: str) -> dict[str, Any]:
        payload = asdict(lead)
        return self._execute(
            case_id=lead.case_id,
            actor=actor,
            action="create_lead",
            object_type="lead",
            object_id=lead.lead_id,
            visibility=lead.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_lead(lead, connection),
        )

    def close_lead(
        self,
        *,
        case_id: str,
        lead_id: str,
        closure_evidence_ids: tuple[str, ...],
        actor: str,
        visibility: Visibility = "internal",
    ) -> dict[str, Any]:
        self._require_case_object("leads", "lead_id", lead_id, case_id)
        self._require_evidence_ids(closure_evidence_ids)
        payload = {"lead_id": lead_id, "closure_evidence_ids": closure_evidence_ids}
        return self._execute(
            case_id=case_id,
            actor=actor,
            action="close_lead",
            object_type="lead",
            object_id=lead_id,
            visibility=visibility,
            payload=payload,
            writer=lambda connection: self.repository.close_lead(
                lead_id, closure_evidence_ids, connection
            ),
        )

    def create_finding(self, finding: Finding, actor: str) -> dict[str, Any]:
        if finding.status != "draft":
            raise ValueError("findings must be created as drafts")
        self._require_case_object("claims", "claim_id", finding.claim_id, finding.case_id)
        payload = asdict(finding)
        return self._execute(
            case_id=finding.case_id,
            actor=actor,
            action="create_finding",
            object_type="finding",
            object_id=finding.finding_id,
            visibility=finding.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_finding(finding, connection),
        )

    def accept_finding(
        self,
        *,
        case_id: str,
        finding_id: str,
        actor: str,
        visibility: Visibility = "internal",
    ) -> dict[str, Any]:
        self._require_case_object("findings", "finding_id", finding_id, case_id)
        payload = {"finding_id": finding_id, "status": "accepted"}
        return self._execute(
            case_id=case_id,
            actor=actor,
            action="accept_finding",
            object_type="finding",
            object_id=finding_id,
            visibility=visibility,
            payload=payload,
            writer=lambda connection: self.repository.accept_finding(finding_id, connection),
        )

    def create_snapshot(self, snapshot: CaseSnapshot, actor: str) -> dict[str, Any]:
        self._require_evidence_ids(snapshot.evidence_ids)
        if snapshot.supersedes_snapshot_id:
            self._require_case_object(
                "case_snapshots",
                "case_snapshot_id",
                snapshot.supersedes_snapshot_id,
                snapshot.case_id,
            )
        payload = asdict(snapshot)
        return self._execute(
            case_id=snapshot.case_id,
            actor=actor,
            action="create_snapshot",
            object_type="case_snapshot",
            object_id=snapshot.case_snapshot_id,
            visibility=snapshot.visibility,
            payload=payload,
            writer=lambda connection: self.repository.insert_snapshot(snapshot, connection),
        )


class CaseQueryService:
    """Read-only query boundary with mandatory visibility filtering."""

    def __init__(self, repository: SQLiteCaseManagerRepository):
        self.repository = repository

    def list_cases(self, clearance: str) -> list[dict[str, Any]]:
        return VisibilityPolicy(clearance).filter(self.repository.list_cases())

    def get_case(self, case_id: str, clearance: str) -> dict[str, Any] | None:
        rows = VisibilityPolicy(clearance).filter(
            [self.repository.fetch_one("cases", "case_id", case_id)]
        )
        return rows[0] if rows else None

    def get_case_collection(
        self, case_id: str, collection: str, clearance: str
    ) -> list[dict[str, Any]]:
        aliases = {
            "evidence": "case_evidence",
            "claims": "claims",
            "contradictions": "contradictions",
            "events": "case_events",
            "leads": "leads",
            "findings": "findings",
            "snapshots": "case_snapshots",
            "audit-events": "case_audit_events",
        }
        if collection not in aliases:
            raise ValueError("unsupported collection")
        # Parent visibility dominates child visibility. A public child cannot leak
        # the existence/content of a restricted case when the case ID is guessed.
        if self.get_case(case_id, clearance) is None:
            return []
        return VisibilityPolicy(clearance).filter(
            self.repository.fetch_case_rows(aliases[collection], case_id)
        )
