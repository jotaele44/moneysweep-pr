# Investigation capabilities upgrade v1

## Scope and provenance

User-authorized development is confined to `jotaele44/moneysweep-pr`. External
applications enter only for a demonstrated dependency and a separately recorded
scope decision. No hub or other producer changes are included.

Planning/source baseline: `81a9190f9c5c0bd1ba8297d0a8b36809439c4977`.
Snapshot date: 2026-10-28, America/Puerto_Rico.

The adopted denominator is the 24 stable IDs in
`registry/investigation_lenses_v1.json`, checked against the independent fixed
list in `moneysweep/investigation/lenses.py`. A later denominator amendment must
version the contract and account for every addition/removal; silently dropping a
blocked lens is prohibited. Registry accounting is not universal research
exhaustion or an implementation/source/finding certificate.

## Delivered bounded slice

- Frozen per-lens question, relationship vocabulary, source families and
  falsification test.
- Separate implementation, source coverage and finding states. All 24 begin
  UNATTEMPTED: existing subsystem reuse is not an end-to-end lens certificate.
- Ten non-waivable gate records per lens. PASS requires evidence references;
  those references are not independently verified by this validator.
- Read-only `GET /investigation/lenses`, with exact registry SHA-256 and baseline
  revision. Missing or malformed input returns 503, never an empty success.
- Discoverable dashboard Research Lenses tab, loading/error/retry, per-lens
  contract and provenance. Static offline exports hide the live-only tab.
- No new case writes, acquisitions, entity merges, findings or federation
  activation. Removing the tab/router deactivates the slice without data loss.

The current dashboard remains the existing development/diagnostic surface. This
slice does not change the accepted federation product architecture or claim a
production investigation workspace. A MoneySweep-local full case workspace is
the user-directed development target below; its eventual product designation
requires explicit architecture/release reconciliation, not changes to the hub.

## Verified source inventory (bounded inspection)

| Existing component | Evidence | Reuse decision and remaining work |
| --- | --- | --- |
| Case domain, service and repository | `moneysweep/case_manager/{models,service,repository,validators}.py` | Reuse transactions and immutable audit. Full GUI, evidence boundary and lifecycle audit remain open |
| Case API and identity boundary | `server/backend/case_manager_{api,app,auth}.py` | Separate app exists; do not add an unauthenticated proxy or reuse caller-supplied identity headers |
| Identity/control core | `moneysweep/capital_control/resolution_core/{identity,models,gates}.py` | Reuse candidate preservation and binding vocabulary after lens-specific verification; do not equate priority with resolved contradictions |
| Ownership analysis | `server/backend/ownership_api.py`, `dashboard/src/components/OwnershipDeepDive.jsx` | Reuse bounded evidence display patterns; its certification does not extend to new entities/lenses |
| Finance graph | `docs/POLITICAL_FINANCE_FLOW_GRAPH.md` | Source-specific semantics reusable. Name-only automatic resolution conflicts with current operating contract; audit execution paths and affected outputs before changing |
| Dashboard/API | `server/backend/main.py`, `dashboard/src/pages/Dashboard.jsx`, `dashboard/src/lib/api.js` | New tab added to existing path; Case Manager is not yet integrated here |
| Capability gate | `.federation/gui-capabilities.json` and extension-aware checker | Update together; never regenerate baseline merely to pass |

This inventory does not certify every source pipeline, full-suite regression,
packaged desktop runtime, iPhone behavior or deployed product.

## Dependency-ordered backlog

All owners below are MoneySweep. Acceptance requires evidence at the exact
candidate revision. OPEN tasks are required, not silently excluded.

| ID | Dependency | State | Deliverable and positive/negative acceptance |
| --- | --- | --- | --- |
| INV-001 | none | OPEN | Complete source/module/API/GUI inventory; distinguish fixtures, docs, real providers and unavailable sources |
| INV-002 | none | OPEN | Full baseline and dependency lock receipt; count pass/fail/skip and preserve failures |
| INV-003 | none | IMPLEMENTED_PENDING_RELEASE | Adopt 24-lens registry, fixed denominator and independent states; reject empty/missing/duplicate/unknown lenses and unsupported states |
| INV-004 | INV-003 | IMPLEMENTED_PENDING_RELEASE | Read-only visible registry, provenance, failure/retry; real API response and malformed/missing-input negatives |
| INV-005 | INV-001 | OPEN | MoneySweep-local workspace ADR and versioned contracts; preserve existing exports and record any actual external dependency |
| INV-006 | INV-001 | OPEN | Canonical evidence existence boundary; unknown, foreign-case and unauthorized references fail atomically |
| INV-007 | INV-006 | OPEN | Immutable source manifestations and extraction fragments; retain raw bytes, locators, hashes and parser version; detect tampering |
| INV-008 | INV-001 | OPEN | Identity audit and namesake candidate review; no name-only binding; preserve historical decisions and complete candidate sets |
| INV-009 | INV-008 | OPEN | Audited identity merge/split/supersession; downstream impact preview and replay; no destructive history edits |
| INV-010 | INV-007,INV-008 | OPEN | Typed assertions with valid/recorded time and uncertainty; reject reversed intervals and unsupported current-role inference |
| INV-011 | INV-006,INV-005 | OPEN | Authenticated case service integration; reject off-box, wrong-role and forged-actor requests; avoid widening clearance |
| INV-012 | INV-011 | OPEN | Discoverable case index/overview/evidence workflow; no API-only normal operation or dead controls |
| INV-013 | INV-012,INV-010 | OPEN | Claims and contradictory assertions; pending import default and explicit support/contradict/qualify/supersede |
| INV-014 | INV-013 | OPEN | Contradiction review and finding schema; mandatory identity/time/provenance/falsification gates; no acceptance with reversible material residue |
| INV-015 | INV-013 | OPEN | Leads, assignments and search ledger; exact bounds, negative searches and public-source exhaustion states; failure is not non-detection |
| INV-016 | INV-014 | OPEN | Immutable snapshots and redacted exports; replay exact IDs/hashes and reject unauthorized field leakage |
| INV-017 | INV-007 | OPEN | Acquisition run receipts, pagination and amendments; reconcile retained/excluded/quarantined records and report incomplete pages |
| INV-018 | INV-017,INV-008 | OPEN | LDA/PR lobbying lens; client/lobbyist IDs, periods, amendments/termination; disclosed agency is not a meeting |
| INV-019 | INV-017,INV-008 | OPEN | Contract/grant lenses; preserve IDs, ceilings/obligations/payments and subaward roles; no double counting |
| INV-020 | INV-017,INV-008 | OPEN | Campaign-finance lens; amendments/refunds/transfers/IE; no recipient merge from normalized name |
| INV-021 | INV-010 | OPEN | Family lineage lens; generation arithmetic, alternate paths, parentage contradictions and primary-record locators |
| INV-022 | INV-010 | OPEN | Corporate heritage/control lens; legal succession versus asset acquisition, historical control intervals |
| INV-023 | INV-010 | OPEN | Institutional/professional/nonprofit lenses; dated roles, boards and disclosed funding; membership is not contact |
| INV-024 | INV-010 | OPEN | Political/government/policy/conflict lenses; jurisdiction, applicable duty, roles and recusals; no misconduct inference from proximity |
| INV-025 | INV-010 | OPEN | Judicial/media/event/communication lenses; allegation versus finding and attendance versus interaction |
| INV-026 | INV-010 | OPEN | Property/financial/geographic/historical/cross-border lenses; authoritative anchors and temporal continuity; no address-only identity |
| INV-027 | INV-013 | OPEN | Evidence/counterevidence lens across all views; source-dependence and missing-page tests |
| INV-028 | INV-010,INV-012 | OPEN | Network/timeline/table views and path evidence; no direct edge invented from shared organization |
| INV-029 | INV-028 | OPEN | Temporal paths, three-way joins and snapshot comparison; all constituent edges, graph scope and method recorded |
| INV-030 | INV-029 | OPEN | Metrics with disputed-edge sensitivity; centrality cannot certify influence or coordination |
| INV-031 | INV-015,INV-017 | OPEN | Bounded research expansion and safe cancel/retry; per-lead source, hop, time and quota budgets; no unbounded recursive crawl |
| INV-032 | INV-016,INV-027 | OPEN | Source-backed report export; every claim opens evidence; gaps and contradictions survive export |
| INV-033 | INV-018,INV-021,INV-022,INV-023,INV-024,INV-025,INV-026 | OPEN | Domenech pilot; earlier claims enter pending verification, all applicable lenses accounted independently |
| INV-034 | INV-033,INV-032 | OPEN | Independent pilot verification and falsification; no requirement to find a Ben–Francisco bridge |
| INV-035 | INV-034 | OPEN | Exact-release manifest, desktop/mobile GUI, authorization/export regressions and data-preserving rollback rehearsal |

## Release gates and exclusions

Each tranche freezes its own exact source/code hashes, explicit tests and input
manifest. Record source acquisition separately from software implementation and
finding validity. Preserve passed artifacts after unrelated failures.

Full-lens readiness remains UNRESOLVED. No production deployment, federation
activation, skill promotion or canonical evidence mutation is part of this
slice. Other repositories remain untouched. Full development continues through
the backlog; closing INV-003/004 cannot close it by implication.

## Validation commands

- `python -m pytest -o addopts='' tests/test_investigation_lenses.py tests/test_case_manager_foundation.py tests/test_case_manager_phase1_service.py tests/test_case_manager_auth.py tests/test_case_manager_app_health.py tests/test_resolution_core_contracts.py tests/test_resolution_core_hardening.py -q`
- `python .federation/check_gui_parity_with_extensions.py`
- In `dashboard/`: `npm run test:gui-parity`, `npm run build`, `npm run lint`.

The targeted pytest command intentionally disables the whole-repository coverage
floor: it is a bounded regression check, not a full coverage certificate.
