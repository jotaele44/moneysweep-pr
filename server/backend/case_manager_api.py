"""FastAPI router for the Case Manager Phase 1 service boundary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from moneysweep.case_manager.ids import deterministic_id
from moneysweep.case_manager.models import (
    Case,
    CaseEvidence,
    CaseSnapshot,
    Claim,
    ClaimEvidence,
    Contradiction,
    Finding,
    Lead,
)
from moneysweep.case_manager.repository import (
    CaseManagerConflict,
    CaseManagerNotFound,
    SQLiteCaseManagerRepository,
)
from moneysweep.case_manager.service import CaseCommandService, CaseQueryService
from server.backend.case_manager_auth import Identity, resolve_identity

ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.environ.get("MONEYSWEEP_CASE_DB", ROOT / "data" / "case_manager.sqlite3"))
MIGRATION_PATH = ROOT / "migrations" / "001_case_manager_v1.sql"

router = APIRouter(prefix="/cases", tags=["case-manager"])
_repository: SQLiteCaseManagerRepository | None = None


def _services() -> tuple[CaseCommandService, CaseQueryService]:
    global _repository
    if _repository is None:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _repository = SQLiteCaseManagerRepository(DATABASE_PATH)
        _repository.apply_migration(MIGRATION_PATH)
    return CaseCommandService(_repository), CaseQueryService(_repository)


def configure_repository(repository: SQLiteCaseManagerRepository | None) -> None:
    """Test hook; production callers use the configured SQLite path."""
    global _repository
    _repository = repository


def _raise(exc: Exception) -> None:
    if isinstance(exc, CaseManagerNotFound):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, (CaseManagerConflict, ValueError)):
        raise HTTPException(409, str(exc)) from exc
    raise exc


class CaseCreate(BaseModel):
    title: str
    case_type: str
    scope: str
    status: str = "open"
    priority: str = "normal"
    owner: str | None = None
    visibility: Literal["public", "internal", "restricted"] = "internal"


class EvidenceLinkCreate(BaseModel):
    evidence_id: str
    role: str
    relevance: str = "material"
    review_status: Literal["pending", "accepted", "rejected"] = "pending"
    analyst_note: str | None = None
    visibility: Literal["public", "internal", "restricted"] = "internal"


class ClaimCreate(BaseModel):
    statement: str
    claim_type: str
    status: str = "pending"
    confidence: float = Field(ge=0, le=1)
    language_tier: Literal["observed", "linked", "inferred", "blocked"]
    visibility: Literal["public", "internal", "restricted"] = "internal"


class ClaimEvidenceCreate(BaseModel):
    evidence_id: str
    relation: Literal["support", "contradict", "qualify", "supersede"]
    rationale: str | None = None
    visibility: Literal["public", "internal", "restricted"] = "internal"


class ContradictionCreate(BaseModel):
    claim_ids: list[str] = Field(min_length=2)
    contradiction_type: str
    severity: str
    assigned_reviewer: str | None = None
    visibility: Literal["public", "internal", "restricted"] = "internal"


class ContradictionResolution(BaseModel):
    status: Literal["resolved", "held_apart"]
    rationale: str
    reviewer: str
    visibility: Literal["public", "internal", "restricted"] = "internal"


class LeadCreate(BaseModel):
    question: str
    acquisition_target: str | None = None
    owner: str | None = None
    due_at: str | None = None
    visibility: Literal["public", "internal", "restricted"] = "internal"


class LeadClosure(BaseModel):
    closure_evidence_ids: list[str] = Field(min_length=1)
    visibility: Literal["public", "internal", "restricted"] = "internal"


class FindingCreate(BaseModel):
    claim_id: str
    conclusion: str
    confidence: float = Field(ge=0, le=1)
    reviewer: str
    contradiction_reviewed: bool
    visibility: Literal["public", "internal", "restricted"] = "internal"


class FindingAcceptance(BaseModel):
    visibility: Literal["public", "internal", "restricted"] = "internal"


class SnapshotCreate(BaseModel):
    created_at: str
    manifest_sha256: str
    evidence_ids: list[str]
    supersedes_snapshot_id: str | None = None
    redaction_profile: str = "internal"
    visibility: Literal["public", "internal", "restricted"] = "internal"


@router.get("")
def get_cases(identity: Identity = Depends(resolve_identity)):
    return _services()[1].list_cases(identity.clearance)


@router.get("/{case_id}")
def get_case(case_id: str, identity: Identity = Depends(resolve_identity)):
    try:
        result = _services()[1].get_case(case_id, identity.clearance)
    except Exception as exc:
        _raise(exc)
    if result is None:
        raise HTTPException(404, "case not visible or not found")
    return result


@router.get("/{case_id}/{collection}")
def get_case_collection(
    case_id: str,
    collection: Literal[
        "evidence",
        "claims",
        "contradictions",
        "events",
        "leads",
        "findings",
        "snapshots",
        "audit-events",
    ],
    identity: Identity = Depends(resolve_identity),
):
    try:
        return _services()[1].get_case_collection(case_id, collection, identity.clearance)
    except Exception as exc:
        _raise(exc)


@router.post("", status_code=201)
def create_case(payload: CaseCreate, identity: Identity = Depends(resolve_identity)):
    case = Case(
        case_id=deterministic_id("case", payload.title, payload.case_type, payload.scope),
        **payload.model_dump(),
    )
    try:
        return _services()[0].create_case(case, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/evidence-links", status_code=201)
def link_evidence(
    case_id: str,
    payload: EvidenceLinkCreate,
    identity: Identity = Depends(resolve_identity),
):
    record = CaseEvidence(
        case_evidence_id=deterministic_id(
            "case_evidence", case_id, payload.evidence_id, payload.role
        ),
        case_id=case_id,
        **payload.model_dump(),
    )
    try:
        return _services()[0].link_evidence(record, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/claims", status_code=201)
def create_claim(
    case_id: str, payload: ClaimCreate, identity: Identity = Depends(resolve_identity)
):
    claim = Claim(
        claim_id=deterministic_id("claim", case_id, payload.statement),
        case_id=case_id,
        **payload.model_dump(),
    )
    try:
        return _services()[0].create_claim(claim, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/claims/{claim_id}/evidence-relations", status_code=201)
def link_claim_evidence(
    case_id: str,
    claim_id: str,
    payload: ClaimEvidenceCreate,
    identity: Identity = Depends(resolve_identity),
):
    record = ClaimEvidence(
        claim_evidence_id=deterministic_id(
            "claim_evidence", claim_id, payload.evidence_id, payload.relation
        ),
        claim_id=claim_id,
        **payload.model_dump(),
    )
    try:
        return _services()[0].link_claim_evidence(case_id, record, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/contradictions", status_code=201)
def create_contradiction(
    case_id: str,
    payload: ContradictionCreate,
    identity: Identity = Depends(resolve_identity),
):
    record = Contradiction(
        contradiction_id=deterministic_id("contradiction", case_id, *sorted(payload.claim_ids)),
        case_id=case_id,
        claim_ids=tuple(payload.claim_ids),
        contradiction_type=payload.contradiction_type,
        severity=payload.severity,
        assigned_reviewer=payload.assigned_reviewer,
        visibility=payload.visibility,
    )
    try:
        return _services()[0].create_contradiction(record, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/contradictions/{contradiction_id}/resolution")
def resolve_contradiction(
    case_id: str,
    contradiction_id: str,
    payload: ContradictionResolution,
    identity: Identity = Depends(resolve_identity),
):
    try:
        return _services()[0].resolve_contradiction(
            case_id=case_id,
            contradiction_id=contradiction_id,
            status=payload.status,
            rationale=payload.rationale,
            reviewer=payload.reviewer,
            actor=identity.actor,
            visibility=payload.visibility,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/leads", status_code=201)
def create_lead(case_id: str, payload: LeadCreate, identity: Identity = Depends(resolve_identity)):
    lead = Lead(
        lead_id=deterministic_id("lead", case_id, payload.question),
        case_id=case_id,
        **payload.model_dump(),
    )
    try:
        return _services()[0].create_lead(lead, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/leads/{lead_id}/closure")
def close_lead(
    case_id: str,
    lead_id: str,
    payload: LeadClosure,
    identity: Identity = Depends(resolve_identity),
):
    try:
        return _services()[0].close_lead(
            case_id=case_id,
            lead_id=lead_id,
            closure_evidence_ids=tuple(payload.closure_evidence_ids),
            actor=identity.actor,
            visibility=payload.visibility,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/findings", status_code=201)
def create_finding(
    case_id: str, payload: FindingCreate, identity: Identity = Depends(resolve_identity)
):
    finding = Finding(
        finding_id=deterministic_id("finding", case_id, payload.claim_id, payload.conclusion),
        case_id=case_id,
        status="draft",
        **payload.model_dump(),
    )
    try:
        return _services()[0].create_finding(finding, identity.actor)
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/findings/{finding_id}/acceptance")
def accept_finding(
    case_id: str,
    finding_id: str,
    payload: FindingAcceptance,
    identity: Identity = Depends(resolve_identity),
):
    try:
        return _services()[0].accept_finding(
            case_id=case_id,
            finding_id=finding_id,
            actor=identity.actor,
            visibility=payload.visibility,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/{case_id}/snapshots", status_code=201)
def create_snapshot(
    case_id: str, payload: SnapshotCreate, identity: Identity = Depends(resolve_identity)
):
    snapshot = CaseSnapshot(
        case_snapshot_id=deterministic_id("case_snapshot", case_id, payload.manifest_sha256),
        case_id=case_id,
        evidence_ids=tuple(payload.evidence_ids),
        **payload.model_dump(exclude={"evidence_ids"}),
    )
    try:
        return _services()[0].create_snapshot(snapshot, identity.actor)
    except Exception as exc:
        _raise(exc)
