---
name: moneysweep-resolve-entities
description: >-
  Orchestrate the canonical MoneySweep resolution core for identifier, event,
  entity, property/project, and financial-attribution resolution. Preserve RAW
  source manifestations, stable-ID namespace boundaries, full candidate sets,
  contradictions, and SUPERSEDED states. Never prove identity from names,
  normalization, proximity, nearest-neighbor, same category, counts, or source
  absence alone.
default_mode: read_only
allowed_modes: [read_only, offline_write]
command_ids: []
owner_repo: jotaele44/moneysweep-pr
---

# moneysweep-resolve-entities

This skill is the MoneySweep orchestration surface for the canonical implementation
at `moneysweep.capital_control.resolution_core`. MoneySweep does not maintain a
second matching engine. `scripts/entity_resolution.py` and existing alias/parent
scripts are adapters and discovery/orchestration surfaces only; final adjudication
must pass through `resolution_core`.

## Resolution layers
Keep these propositions separate even when they concern the same records:

- `IDENTIFIER_IDENTITY`: what an identifier denotes inside its authoritative namespace.
- `EVENT_IDENTITY`: whether two source manifestations describe the same event/instrument.
- `ENTITY_IDENTITY`: whether manifestations bind to the same legal/natural entity.
- `PROPERTY_PROJECT_IDENTITY`: permit/project/property/parcel binding.
- `FINANCIAL_ATTRIBUTION`: whether a financial instrument is bound to the exact project/property.

Support `1:1`, `1:N`, `N:1`, `N:N`, `0:1`, and `UNRESOLVED`. Never assume 1:1.

## Evidence order
Prefer, in order: stable ID; authoritative binding; certified geometry;
point-in-polygon plus an independent alias/ID; point-in-polygon; authoritative
alias plus spatial/temporal support; historical continuity plus corroboration;
proximity; unresolved. Hard evidence overrides heuristics. Tied top evidence is
`UNRESOLVED` and the complete candidate set is preserved.

## Prohibited sole identity proofs
The following are discovery only unless independently bound:
`NAME_ONLY`, `NORMALIZED_NAME_ONLY`, `COUNT_EQUALITY`, `NEAREST_ONLY`,
`PROXIMITY_ONLY`, `SAME_CATEGORY`, and `SOURCE_ABSENCE`.

## Namespace occupancy
Treat IDs as namespace-scoped, e.g. `CFI::2020-000358` and
`DDEC::2020-000358`. Before accepting an external field as a canonical ID, check
whether that identifier is already occupied in its authoritative namespace. A
conflicting RAW value is preserved exactly; it is never silently corrected.
Identifier identity and underlying event identity may have different states.

## Dependency gates
- Parcel work requires an authoritative property anchor/catastro or equivalent.
- Cross-source federation requires a stable-ID or authoritative bridge.
- Funding attribution requires a project-specific authoritative binding.
- FOIA eligibility requires every relevant public-source family to be exhausted,
  negatively closed, or demonstrably inaccessible with zero unexplained reachable
  residue.

## Procedure
1. Freeze source manifestations and preserve RAW strings before normalization.
2. Generate candidate identifiers/events/entities/properties without promotion.
3. Use `resolution_core` to adjudicate namespace occupancy and evidence priority.
4. Compute `INTERSECTION`, `A_ONLY`, `B_ONLY`, `UNION`, and
   `SYMMETRIC_DIFFERENCE` for proposed equivalence when material.
5. Preserve contradictions and displaced results as `SUPERSEDED` where appropriate.
6. Refuse unsafe M:N joins that would multiply records unless explicitly modeled.
7. Keep financial amount semantics distinct: project estimate, contract amount,
   max payable, grant authorized, obligation, disbursement, invoice, payment,
   cancellation, and balance.
8. After bounded source exhaustion, use change detection and reopen only affected
   downstream branches.

## Required outputs
Emit candidate sets, proposition type, cardinality, evidence basis, certification
state, namespace bindings, contradictions, blockers, source manifestations, and
next safe action. Preserve aliases and provenance; nothing is silently rewritten.

## Stop conditions
- tied top evidence;
- name/normalized-name/proximity-only proposed promotion;
- identifier already occupied by another subject in the same namespace;
- competing authoritative parents without adjudication;
- parcel selection before an authoritative property anchor;
- unsafe many-to-many join;
- funding attribution without project-specific binding;
- FOIA request while the public denominator has reachable residue.

## Promotion gates
No production promotion until legacy capital-control regressions plus all golden
corpora and invariants pass. `GOLDEN_001_FINCA_ZEQUEIRA` is mandatory; BPOP,
TAMCOR, and PRASA/Jacobs corpora must close before full resolution-core promotion.

## Evidence & result envelope
Emit `{status, proposition_type, cardinality, candidates, selected_id,
evidence_basis, source_manifestations, blockers, contradictions, superseded,
next_safe_action}`. Confidence is descriptive only; evidence state controls
certification.
