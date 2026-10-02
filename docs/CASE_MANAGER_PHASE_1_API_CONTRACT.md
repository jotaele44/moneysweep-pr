# MoneySweep Case Manager Phase 1 API Contract v0.13

## Scope

This phase adds an API-only, SQLite-backed Case Manager service stacked on PR #440. It does not implement production UI, mutate canonical evidence, promote evidence, collapse contradictions automatically, expose generic `PATCH`, or expose deletion routes.

## Runtime

```bash
uvicorn server.backend.case_manager_app:app --reload --port 8001
```

The database path defaults to `data/case_manager.sqlite3` and may be overridden with `MONEYSWEEP_CASE_DB`.

## Authorization boundary

Every `/cases` route requires a credential. Clients supply **one** header:

- `X-Case-Token: <token>`

The acting identity and the read clearance are **derived from that token**, not
from the request. `X-Case-Actor` and `X-Case-Clearance` are no longer read; sending
them has no effect. This closes two defects in the previous contract, where those
headers were trusted verbatim and absent headers still authorized: any caller could
write audit history under any name, and could read restricted records by asserting
`X-Case-Clearance: restricted`.

Responses:

| Condition | Status |
|---|---|
| Caller is not on the loopback interface | `403` |
| Identity store not configured | `503` |
| `X-Case-Token` missing or unrecognized | `401` |
| Token recognized | request proceeds as that identity |

An unconfigured deployment **fails closed** with `503`. It does not fall back to the
previous permissive behavior — that fallback would leave the defect reachable by
simply not configuring the service.

### Identity store

`MONEYSWEEP_CASE_IDENTITIES` points at a JSON list; default
`data/case_manager_identities.json`:

```json
[{"token_sha256": "<sha256 of the token>", "actor": "analyst@example", "clearance": "internal"}]
```

Only SHA-256 **hashes** are stored, never raw tokens, so the file at rest holds no
usable credential (see `docs/SECRET_HANDLING_POLICY.md`). Generate an entry with
`python -c "import hashlib,secrets; t=secrets.token_urlsafe(32); print(t, hashlib.sha256(t.encode()).hexdigest())"`
— keep the first value, store the second.

`clearance` is one of `public|internal|restricted`; records above the caller's
clearance are omitted, as before.

This remains a bounded interim boundary, not the federation-wide authenticated
identity provider — but it is now an enforced one. See finding D4 in
`docs/GAP_ANALYSIS_AND_OPTIMIZATION_2026-09.md`.

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
