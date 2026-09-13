# PR #484 non-resolver salvage v1

## Control

- Control ledger: issue #526.
- Source lineage: PR #484 at `85dc4744173ebd26c68f2b904265c6c91497d5ad`.
- Fresh base after change detection: current `main` at `df78f15f7c36b98bc6ecfae37c7e775ec487ead3`.
- Canonical resolver: `moneysweep.capital_control.resolution_core`.
- Frozen canonical-core source: PR #520 at `5646ad6014959baf783b66c8dd497f1f518f207e`.
- Merge and production promotion remain prohibited.

This branch does not merge or cherry-pick PR #484. It independently reconstructs only adjudicated non-resolver behavior on current main.

## Canonical-core materialization boundary

The certified `resolution_core` remains external to current main because PR #520 is intentionally frozen, draft, and unmerged. Therefore this salvage branch does not claim repository-wide canonical-core integration or complete GOLDEN_001–004 recertification.

Its current promotion state is:

`BLOCKED_PENDING_CANONICAL_CORE_INTEGRATION_AND_COMPLETE_RECERTIFICATION`

The non-resolver snapshot change can be tested independently, but the branch cannot inherit PR #520's certification and cannot become merge-eligible merely because its local and protected CI checks pass.

## Implemented

### Exact-query offline snapshot resolution

The dashboard client now checks the complete request path, including query parameters, before falling back to the unfiltered route key. The snapshot generator materializes a bounded exact-query example for `/contracts?status=ACTIVE` through the existing canonical backend route.

This is presentation/offline-export behavior. It does not adjudicate identity, amendments, ownership, projects, properties, or financial attribution.

## Reused from current canonical implementation

The following PR #484 concepts were already independently implemented and tested on current main, so they are reused rather than duplicated:

- temporal holding observations;
- RAW reported-holder preservation;
- legal holder, investor family, and ultimate parent as separate identity levels;
- whole-row current-position selection;
- tied-top failure closure;
- set comparison accounting;
- bounded issuer certification and regression controls;
- ownership-tab reachability and accessibility;
- typed holding-observation schema contracts.

## Dependency-gated, not implemented

A general multi-issuer comparison UI is deliberately deferred. It may be added only when the canonical issuer outputs being compared are independently certified, semantically compatible, and expose stable identity levels under equivalent source denominators. The UI must not synthesize a comparison universe or inherit certification between issuers.

## Superseded implementation

PR #484's generic `server/backend/main.py` capital-control engine remains `SUPERSEDED / NONCANONICAL`. Amendment adjudication, identity-level rollups, schema validation, and domain comparisons must remain in `capital_control` and `resolution_core`, with dedicated API projections consuming those outputs.

## Recertification

Every delta on this branch requires the complete denominator from issue #526:

1. all existing regressions;
2. GOLDEN_001 Finca Zequeira;
3. GOLDEN_002 BPOP;
4. GOLDEN_003 TAMCOR;
5. GOLDEN_004 PRASA/Jacobs;
6. identity-surface audit;
7. RAW/source conservation;
8. candidate and contradiction/SUPERSEDED conservation;
9. namespace occupancy and unsafe M:N gates;
10. property, federation, funding, and FOIA dependency gates;
11. all protected CI at terminal success;
12. zero unexplained residue.

Until the canonical core is integrated onto a successor branch and that complete denominator closes, this PR must remain draft, unmerged, and non-promoted.
