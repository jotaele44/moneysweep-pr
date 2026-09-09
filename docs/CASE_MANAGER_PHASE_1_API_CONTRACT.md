# MoneySweep Case Manager Phase 1 API Contract v0.13

## Scope

This phase adds an API-only, SQLite-backed Case Manager service stacked on PR #440. It does not implement production UI, mutate canonical evidence, promote evidence, collapse contradictions automatically, expose generic `PATCH`, or expose deletion routes.

## Runtime

```bash
uvicorn server.backend.case_manager_app:app --reload --port 8001
```

The database path defaults to `data/case_manager.sqlite3` and may be overridden with `MONEYSWEEP_CASE_DB`.

## Authorization boundary

The Case Manager no longer trusts caller-supplied actor or clearance as identity proof.

Server-side configuration:

- `PRII_WRITE_TOKEN` enables authenticated Case Manager access. The credential is runtime-only and must not be committed.
- `MONEYSWEEP_CASE_ACTOR` defines the authenticated actor written to command audit events. If omitted while authentication is enabled, the bounded default is `authenticated-case-operator`.
- `MONEYSWEEP_CASE_CLEARANCE` defines the authenticated principal's maximum view: `public|internal|restricted`. The bounded default is `internal`.

Fail-closed behavior:

- when `PRII_WRITE_TOKEN` is unset, unauthenticated `GET` requests are restricted to `public` data and every Case Manager command is disabled;
- when the token is configured, command endpoints require `Authorization: Bearer <runtime token>`;
- authenticated reads may omit `X-Case-Clearance` to use the server-configured maximum, or request a lower/equal clearance;
- `X-Case-Clearance` can never elevate beyond the authenticated principal's server-configured maximum;
- `X-Case-Actor` is a compatibility assertion only: if supplied on an authenticated command, it must exactly match the server-derived actor; otherwise the request is rejected;
- public reads remain available without credentials, but an unauthenticated caller cannot self-assert `internal` or `restricted` clearance.

No runtime credential value is stored in this contract, repository configuration, fixtures, or source control.

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

## Authorization regression gates

`tests/test_case_manager_auth.py` must prove both positive and negative behavior:

- public reads remain available without configuration;
- unauthenticated clearance elevation is rejected;
- writes fail closed when no runtime credential is configured;
- configured command access rejects missing authentication;
- authenticated callers cannot exceed their server-configured clearance;
- authenticated callers cannot spoof the audit actor;
- successful authenticated commands use the server-derived actor;
- authenticated principals may deliberately request a lower-clearance view.
