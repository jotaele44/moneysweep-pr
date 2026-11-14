---
name: moneysweep-certify-public-finance-release
description: >-
  Certify a bounded MoneySweep public-finance release only after the frozen
  source revision, data-plane gates, consumer/rendered receipts, TheHub
  persisted consumer receipt, native/physical-device proof, and full-SAM
  identity proof all close. Read-only and fail-closed: it never publishes,
  promotes, merges, fabricates missing evidence, or treats an audit-only
  denominator as exhaustive.
default_mode: read_only
allowed_modes: [read_only]
command_ids: []
owner_repo: jotaele44/moneysweep-pr
---

# moneysweep-certify-public-finance-release

This is the terminal MoneySweep release-certification workflow. It aggregates
already-produced evidence; it does not acquire sources, build an export, publish
the Floot app, write TheHub receipts, or create native builds.

## When this fires
Use for "certify MoneySweep", "is the public-finance release fully certified",
"freeze the final MoneySweep release", or a final zero-residue certification
decision after component gates have run.

## When this does NOT fire (boundary)
- Source acquisition or coverage expansion -> `moneysweep-recover-source-coverage`.
- Building the producer export -> `moneysweep-build-federation-export`.
- Promotion readiness -> `moneysweep-assess-promotion-readiness`.
- Cross-producer package consumption / receipt persistence -> `thehub-pr`.
- Native build execution or physical-device testing -> external Floot/mobile
  execution evidence supplied to this skill.

## Required evidence planes
1. **Frozen source identity**
   - exact Git commit;
   - frozen source/data byte hashes;
   - source-registry denominator and required-source denominator;
   - current head equality for the certified release.
2. **Data plane**
   - release-audit gates all PASS;
   - stable-ID uniqueness, FK/evidence integrity, null semantics, cardinality,
     expected-absence separation, stale-status contradiction preservation.
3. **Identity / claim semantics**
   - RAW / NORMALIZED / CANDIDATE / CANONICAL separation;
   - name-only promotion prohibited;
   - CURRENT / SUPERSEDED / CONTRADICTED / UNRESOLVED states mapped only from
     explicit source state;
   - full SAM manifestation required for exhaustive vendor-identity
     certification. A bounded audit is never promoted to full-SAM proof.
4. **Consumer and rendered plane**
   - exact-ID consumer regressions;
   - desktop DOM receipt;
   - 393px and 430px rendered/touch receipt;
   - zero unintended page-level horizontal overflow.
5. **Federation plane**
   - current MoneySweep package bound to the frozen source revision;
   - package hashes/counts/provenance validated by TheHub;
   - persisted TheHub consumer receipt with deterministic package identity and
     idempotency semantics.
6. **Production plane**
   - published MoneySweep URL;
   - production API/dashboard/evidence smoke;
   - production backend logs inspected for the smoke window;
   - persistence behavior verified where applicable.
7. **Native plane**
   - exact native build manifestation;
   - build hash/version frozen;
   - physical-device investigation/evidence smoke.
8. **Residue arithmetic**
   - every declared required gate is PASS;
   - OPEN/BLOCKED/PROVISIONAL/AUDIT_ONLY dependencies remain visible;
   - full release certification requires zero material unresolved residue.

## Procedure
1. Resolve the candidate source revision first. Refuse mutable-main evidence
   without an exact revision binding.
2. Collect the gate receipts from every evidence plane above.
3. Classify each gate as
   `PASS | FAIL | OPEN | BLOCKED | PROVISIONAL | AUDIT_ONLY | UNRESOLVED`.
4. Recompute release residue. Do not collapse expected absence, zero result,
   source failure, not queried, stale, historical, or blocked external states.
5. Verify that source, web, federation, and native manifestations all bind to
   the declared release or explicitly document their relationship to it.
6. Emit `MONEYSWEEP PUBLIC-FINANCE RELEASE CERTIFIED` only when all declared
   required gates are PASS and material residue is zero.
7. Otherwise emit a bounded checkpoint with the exact blockers and the next
   safe action. Never soften a blocker into a narrative "mostly complete"
   conclusion.

## Hard stop conditions
- Full SAM manifestation absent while exhaustive vendor identity is claimed.
- TheHub current persisted consumer receipt absent.
- Production publication/smoke/log receipt absent when production is in scope.
- Native build or physical-device proof absent when native is in scope.
- Any current-head drift relative to the frozen release.
- Any fabricated contradiction/supersession/zero-result state.
- Any unresolved material relationship, source arithmetic, or provenance hash.

## Evidence & result envelope
Emit:
`{status, release_revision, denominators, passed_gates, open_gates, blockers,
manifestations, receipts, contradictions, residue, next_safe_action}`.

The certification decision is evidence aggregation only. It cannot mutate source
data, publish, merge, or create receipts.
