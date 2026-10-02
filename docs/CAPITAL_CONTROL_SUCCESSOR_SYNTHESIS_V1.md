# Capital Control successor synthesis v1

## Control

- Sole control ledger: issue #526.
- Fresh branch: `codex/capital-control-successor-synthesis-v1`.
- Base main: `df78f15f7c36b98bc6ecfae37c7e775ec487ead3`.
- Certified canonical-core input: PR #520 at `5646ad6014959baf783b66c8dd497f1f518f207e`.
- CI-green bounded non-resolver input: PR #527 at `f484a226f73f7f366a88ad9e051bba0d0150da54`.
- Historical lineage source: PR #484 commit `85dc4744173ebd26c68f2b904265c6c91497d5ad`, frozen at `archive/pr-484-historical-partial-salvage-85dc474`, remains `PARTIAL_SALVAGE`; its resolver/domain implementation remains `SUPERSEDED / NONCANONICAL`.
- Live PR #484 observation: repaired head `39d06ec63aba3e212f19f96881e5185b03787881` on current main is a distinct rebased lineage. It does not replace the immutable historical source commit and is not an additional successor payload.
- This successor must remain **DRAFT**. Merge, ready-for-review transition, and production promotion are prohibited.

The immutable source commit SHAs, archive refs, live-versus-historical identity scope, and source blob map are recorded in `data/manifests/capital_control/capital_control_successor_synthesis_v1.json`.

## Integration result

The synthesis imports the exact PR #520 payload and the exact PR #527 bounded payload onto current main. No file path overlaps between PR #520 and PR #527.

The material overlaps between imported payloads and changes already present on current main are:

```text
moneysweep/capital_control/__init__.py
dashboard/src/lib/api.js
```

Those files were adjudicated as derived whole-file merges:

- preserve current-main ownership Deep Dive exports;
- add `resolution_core` as the canonical resolution package export;
- preserve all existing capital-control exports;
- introduce no second resolver.
- preserve PR #527 offline snapshot lookup behavior;
- preserve current-main API-key client behavior.

Every other PR #520 and PR #527 path reuses the exact source blob recorded in the synthesis manifest. The exact PR #527 `api.js` source bytes are retained at the manifest-recorded snapshot path so shallow CI can verify the immutable input independently of the derived active file.

## Historical source artifacts

The imported PR #527 manifest, document, and regression test remain exact source-input artifacts. Their statement that the canonical core was external to **PR #527's own base** remains historically true. The active successor state is governed by the successor synthesis manifest and this document, not by reinterpreting PR #527's historical receipt.

## Canonical architecture

```text
MoneySweep orchestration / discovery
                |
                v
moneysweep.capital_control.resolution_core
                |
                +-- identifier identity
                +-- event identity
                +-- entity identity
                +-- property/project identity
                +-- financial attribution
                +-- namespace occupancy
                +-- contradiction and SUPERSEDED preservation
                +-- dependency unlock gates
                +-- public-source denominator / FOIA gate
                +-- change detection
```

The legacy `moneysweep.capital_control.identity` module is a compatibility wrapper over `resolution_core`. Generic API, dashboard, snapshot, and discovery code may consume canonical outputs but may not perform independent identity, amendment, property, project, funding, or FOIA adjudication.

## Binding invariants

- Preserve RAW source manifestations exactly.
- Preserve normalized and canonical representations separately.
- Never promote identity through name-only, normalized-name-only, nearest-only, proximity-only, same-category, count-equality, or source-absence evidence.
- Preserve full candidate sets, contradictions, rejected candidates, and `SUPERSEDED` observations.
- Reject unsafe N:N joins and unintended financial multiplication.
- Require an authoritative property anchor before parcel selection.
- Require a stable-ID or authoritative bridge before cross-source federation.
- Require a project-specific binding before funding attribution.
- Require certified public-source exhaustion before FOIA eligibility.

## Required certification denominator

This branch begins as:

```text
CANDIDATE_REQUIRES_COMPLETE_RECERTIFICATION
```

It may reach a bounded implementation `PASS` only after all of the following close on the exact successor head:

1. all pre-existing regressions;
2. GOLDEN_001 Finca Zequeira;
3. GOLDEN_002 BPOP/SEC ownership preservation;
4. GOLDEN_003 TAMCOR;
5. GOLDEN_004 PRASA/Jacobs;
6. repository identity-surface audit;
7. RAW/source-manifestation conservation;
8. full candidate-set conservation;
9. contradiction and `SUPERSEDED` conservation;
10. namespace occupancy;
11. unsafe M:N prevention;
12. authoritative property-anchor gate;
13. stable-ID/authoritative federation gate;
14. project-specific funding-attribution gate;
15. public-source-denominator/FOIA gate;
16. all protected CI checks at terminal success;
17. zero unexplained regression residue.

Passing that denominator would certify only the exact successor commit. It would not authorize merge or production promotion under issue #526.
