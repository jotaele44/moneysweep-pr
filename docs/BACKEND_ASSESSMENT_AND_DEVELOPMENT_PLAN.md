# Backend Assessment & Development Plan — moneysweep-pr

## Scope & method

Read-only assessment of the backend at `main` (`f17bc8a`, "Rebind skillpack conformance
baseline"). `moneysweep-pr` is the public-money/procurement-intelligence producer node in
the PRII federation: it ingests, resolves, and fuses Puerto Rico government contracting,
campaign-finance, and SEC-ownership data into canonical CSV/JSONL, exposes it through a
diagnostic FastAPI backend, and exports a federation package to `thehub-pr`. This document
cross-references rather than re-derives the repo's own already-thorough self-tracking:
`federation.json` (`production_status: NON_PRODUCTION_DIAGNOSTIC`,
`ready_for_hub_live_execution: false`, live `blocking_conditions`),
`reports/current_blockers.md` (4 active blockers), and `docs/placeholder_detection.md` /
`tests/test_stub_adapter_deferral.py` (a first-class test of intentionally-deferred
adapters).

## Tech stack & backend inventory

- **Framework**: FastAPI, split across `server/backend/main.py` (core reads) plus routers
  `campaign_finance.py`, `case_manager_api.py`, `ownership_api.py`, `government_changes.py`,
  `api_keys.py`.
- **Storage**: mostly flat CSV/JSONL "canonical" files read via pandas for the read API;
  **SQLite** for the case-manager subsystem (`migrations/001_case_manager_v1.sql`, via
  `SQLiteCaseManagerRepository`).
- **Endpoints**:
  - `main.py`: `/health`, `/contracts` (filterable), `/entities`, `/edges`,
    `/municipalities`, `/stats` — reads 4 canonical CSVs eagerly at import and fails loud at
    startup on header drift from `EXPECTED` schema (deliberate, good design).
  - `campaign_finance.py`: `/campaign-finance/summary`, `/contributions` (cross-source
    FEC/CEE/OCE normalization), `/entities`, `/reports` — read-only, mtime-cached.
  - `case_manager_api.py` (11 KB): `/cases` REST surface — create case, link evidence,
    create claims, evidence-relations, contradictions + resolution, leads + closure,
    findings + acceptance, snapshots. Backed by SQLite via
    `moneysweep/case_manager/{models,repository,service}.py`.
  - `ownership_api.py`: `/deep-dive/ownership/*` — SEC 13F ownership certification, only
    certified for ticker `BPOP`; `OFG`/`EVTC` return 409 as uncertified "regression issuers."
  - `api_keys.py`: local-only (`127.0.0.1`/`::1` + origin check) API-key management for the
    pipeline's `.env`; never touches a running pipeline process.
- **Auth**: `api_keys.py` is loopback-only by design. **The case-manager API has no
  authentication at all** — `X-Case-Clearance` and `X-Case-Actor` are client-supplied
  headers with no identity verification; any caller can self-assert `restricted` clearance
  or any actor name. This is the most concrete, active security gap found across the entire
  7-repo federation review (not a roadmap item — a live hole in a write API).
- **Business logic**: `moneysweep/` — `capital_control/`, `case_manager/`,
  `entity_resolution/`, `federation/`, `forensics/`, `fusion/`, `orchestrator/`, `pipeline/`,
  `political_finance/`, `query/`, `runtime/`, `update_controller/`, `validation/`.
- **Background jobs**: no in-process scheduler; a registry-driven "source update
  controller" (`docs/SOURCE_UPDATE_CONTROLLER.md`) tracks per-source freshness/due-ness,
  triggered by scheduled GitHub Actions (`source-update-{weekly,monthly,quarterly,yearly}.yml`).
- **Tests/CI**: ~290 test files (the largest suite of the 6 producers), covering scrapers,
  schema contracts, "no secret leakage," and repo-quality-audit meta-tests. 48 CI workflows
  — the most elaborate of the 6 producers.

## Completion assessment

- **Fully implemented**: core read API over canonical contracts/entities/edges; campaign-
  finance read API; case-manager write API with SQLite-backed audit trail; local-only
  API-key management; source-registry-driven ingestion orchestrator.
- **Explicitly self-declared incomplete**: `federation.json`'s `blocking_conditions` —
  Tranche B manual-source ingestion partial (7 output files seeded, awaiting operator file
  drops), COR3 live endpoints return no data (JS-rendered portal, no API), 2 true scraper
  stubs (`hacienda_sut_ivu`, `pr_act_154_excise`), missing `PROPUBLICA_API_KEY`.
  `reports/current_blockers.md` additionally tracks SAM API rate limiting, an empty FEC
  crossref join, missing manual-export files, and a mis-calibrated validation-gate
  threshold.
- **Missing/weak**: case-manager clearance/actor headers are unauthenticated (see above);
  ownership API certified for exactly one issuer by design.

## Development plan — hardest tasks first

Ordering rationale: item 1 is sequenced first **regardless of engineering difficulty**
because it is an active, exploitable gap, not architecture debt — it should not wait behind
harder-but-lower-urgency items. Items 2–5 are then ordered by genuine difficulty/uncertainty
(external rate limits and portal-rendering constraints first, since they gate what's even
possible, before narrower per-source parser work).

1. **Real authentication/authorization for the case-manager API** — Effort: **M**,
   Urgency: **immediate**. `X-Case-Clearance`/`X-Case-Actor` need to become verified
   identity (session- or token-derived), not client-asserted headers. No auth layer exists
   anywhere in this codebase to build on, so this is greenfield within the repo — but
   should adopt whatever contract `thehub-pr` ships federation-wide (see that repo's plan
   doc) rather than a one-off local token, to avoid a second migration later.
2. **SAM entity-resolution API rate-limit workaround** — Effort: **L**, externally bound.
   2,334 UEIs need resolution against a 1,000-req/day API; needs either a paid tier, a
   multi-day scheduling strategy, or heavier reliance on the offline USASpending-derived
   parent lookup. Hard because it's bound by an external quota, not code quality.
3. **Validation-gate threshold recalibration (per-source-family, not global)** — Effort:
   **L**. A single global `≥0.90` confidence threshold is wrong for PR-government-agency
   sources vs. corporate-prime sources; fixing this correctly means a per-source-family
   threshold model that interacts with `source_registry.yaml`'s gating logic across dozens
   of sources — a structural design fix, not a config tweak.
4. **Tranche B manual-source ingestion completion** — Effort: **L**, ongoing. 6+ manual-
   export sources (FEMA 178-PW, HUD DRGR, PDFs like `Registro de cabilderos`) each need a
   bespoke parser + lineage + validation + review-gate, against real-world messy PDF/Excel
   formats.
5. **COR3 live-endpoint replacement** — Effort: **M**, ongoing operational investment. The
   live portal requires JS rendering (no API); a durable fix needs either a fragile
   headless-browser scraper (with monitoring) or a permanent manual-CSV-export process with
   lineage tracking.

## Quick wins (sequenced after/alongside the above, not skipped)

- Close the two true scraper stubs (`hacienda_sut_ivu`, `pr_act_154_excise`) — small in
  scope relative to the rest of the pipeline, already identified precisely.
- Satisfy the `entities_resolved.csv` dependency to unblock `pr_fec_crossref.csv`
  (currently header-only) — already partially done upstream.
- As an interim step before item 1 lands fully, gate the case-manager write endpoints with
  the same shared-secret pattern `aguayluz-pr`/`thehub-pr` already use — closes the biggest
  share of the risk with comparatively little code, even before the federation-wide auth
  contract exists.
