# MoneySweep Case Manager Phase 1 API Contract v0.12

## Scope

This phase adds an API-only, SQLite-backed Case Manager service stacked on PR #440. It does not implement production UI, mutate canonical evidence, promote evidence, collapse contradictions automatically, expose generic `PATCH`, or expose deletion routes.

## Runtime

```bash
uvicorn server.backend.case_manager_app:app --reload --port 8001
```

The database path defaults to `data/case_manager.sqlite3` and may be overridden with `MONEYSWEEP_CASE_DB`.

## Authorization boundary

Commands and private reads require `Authorization: Bearer <token>`, matched in
constant time against the server's `PRII_WRITE_TOKEN`. This follows the Hub's
shared-service bearer convention. Missing or blank server configuration disables
privileged access (503); missing or invalid caller credentials return 401.

The credential identifies one trusted service principal with restricted clearance.
Audit events use the server's `MONEYSWEEP_CASE_ACTOR` (default `case-service`).
This is not multi-user authentication or delegated per-user authorization. Keep the
credential on trusted service clients; never embed it in a public frontend bundle.
Runtime token rotation invalidates the previous credential on the next request.

Anonymous reads have public clearance. Nonpublic cases are omitted from lists and
return 404 through direct and collection reads. The former `X-Case-Actor` and
`X-Case-Clearance` headers are rejected with 400, including for authenticated callers,
so they cannot forge audit identity or elevate clearance. The standalone health
endpoint remains a database liveness check, not authentication readiness.

## Read endpoints

- `GET /cases`
- `GET /cases/{case_id}`
- `GET /cases/{case_id}/evidence`
- `GET /cases/{case_id}/claims`
- `GET /cases/{case_id}/contradictions`
- `GET /cases/{case_id}/events`
- `GET /cases/{case_id}/leads`
- `GET /cases/{case_id}/findings`
- `GET /cases/{case_id}/snapshots`
- `GET /cases/{case_id}/audit-events`

## Command endpoints

- `POST /cases`
- `POST /cases/{case_id}/evidence-links`
- `POST /cases/{case_id}/claims`
- `POST /cases/{case_id}/claims/{claim_id}/evidence-relations`
- `POST /cases/{case_id}/contradictions`
- `POST /cases/{case_id}/contradictions/{contradiction_id}/resolution`
- `POST /cases/{case_id}/leads`
- `POST /cases/{case_id}/leads/{lead_id}/closure`
- `POST /cases/{case_id}/findings`
- `POST /cases/{case_id}/findings/{finding_id}/acceptance`
- `POST /cases/{case_id}/snapshots`

## Transaction contract

Every command:

1. validates the command boundary;
2. starts `BEGIN IMMEDIATE`;
3. writes the analytical object or explicit lifecycle transition;
4. verifies the latest audit sequence and predecessor hash;
5. appends exactly one audit event;
6. commits once.

A failure in either the object write or audit append rolls back both. Concurrent writers that observed a stale audit sequence receive a conflict instead of creating a forked audit chain.

## Canonical evidence boundary

The service accepts canonical identifiers matching `evidence_*` for links, lead closure, and snapshots. The Case Manager schema contains no canonical evidence table and exposes no operation that can alter evidence text, tier, review status, or promotion state.

## Persistence certificate

- migration: `migrations/001_case_manager_v1.sql`;
- foreign keys: enabled;
- deletion behavior: restrictive;
- audit events: append-only triggers plus service-level sequence/hash verification;
- JSON arrays: SQLite JSON1 checks;
- canonical writes: none;
- generic update/delete API: absent.
