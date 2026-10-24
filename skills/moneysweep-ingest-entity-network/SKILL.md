---
name: moneysweep-ingest-entity-network
description: >-
  Ingest a frozen external ecosystem/network reference into MoneySweep as
  noncanonical source manifestations. Use for MII-style PDF/ZIP snapshots that
  need byte verification, row extraction, denominator reconciliation,
  contradiction preservation, source-vector binding, and fail-closed handoff to
  the canonical resolution core. Never promotes names, MII evidence classes,
  sector membership, or count equality to identity.
default_mode: read_only
allowed_modes: [read_only, offline_write]
command_ids: []
owner_repo: jotaele44/moneysweep-pr
---

# moneysweep-ingest-entity-network

Use this skill for evidence-gated ingestion of external entity/network reference
artifacts. It is the companion ingestion skill for the byte-frozen
`moneysweep-resolve-entities` contract; do not mutate that certified skill merely
to add a new source adapter.

## Boundary

This skill may create source manifestations, candidate rows, frozen manifests,
coverage/exhaustion ledgers, contradiction ledgers, and staging artifacts. It may
not create canonical entity identity or promote source relationships.

MII-style evidence classes such as `A/B/C` are source-local taxonomy. They are
not `resolution_core` evidence bases.

## Procedure

1. Freeze each supplied artifact: source filename, raw byte size, SHA-256, and
   source version.
2. For archives, freeze member path + uncompressed size + member SHA-256.
3. Verify expected bytes before parsing. Hash mismatch fails closed.
4. Inspect source structure before extraction; preserve RAW strings exactly.
5. Extract only rows actually exposed by the source.
6. Preserve duplicate/rendered manifestations separately from distinct
   source-card signatures.
7. Materialize name-only/registry candidates as
   `CANDIDATE_NOT_IDENTITY`; leave canonical IDs null.
8. Reconcile declared denominators against row-level materialization. Count
   inaccessible residue but never synthesize placeholder rows.
9. Preserve source contradictions and newly discovered ingestion contradictions
   as separate classes.
10. Bind declared source-exhaustion vectors to existing MoneySweep source IDs
    without treating registry presence or materialization as proof of equivalent
    scope.
11. Hand any later identity adjudication to the canonical
    `moneysweep.capital_control.resolution_core`.
12. Promote nothing until its own bounded evidence gates close.

## MII v0.3 adapter

The current implementation is
`moneysweep.entity_network.mii_v03` with CLI
`scripts/import_mii_v03_reference.py`.

The committed aggregate reference is under
`data/reference/entity_network/mii_v0_3/`. Exact row-level source extraction is
written to staging when the frozen PDF and ZIP are supplied locally.

## Required invariants

- source manifestation != canonical entity
- MII A/B/C != MoneySweep binding evidence
- NAME_ONLY != identity
- sector membership != identity
- count equality != identity
- visible manifestation count != unique entity count
- aggregate edge arithmetic != row-level edge availability
- missing source row != synthetic placeholder
- source binding != source exhaustion
- materialized source != complete source scope
- tied or contradictory evidence remains unresolved

## Stop conditions

Stop with an explicit blocker when:

- frozen PDF/ZIP hashes or archive-member payloads differ;
- parser structure drifts from the frozen source;
- declared arithmetic does not close;
- an inaccessible row is about to be synthesized;
- a name-only candidate is about to be promoted;
- a source-local evidence class is about to be mapped to binding identity
  evidence;
- row-level edges are not exposed by the supplied artifact;
- source-vector scope is narrower or different from the requested source family;
- contradictions remain inside a requested certification claim.

## Result envelope

Emit source hashes, archive member inventory, source/retained/residue counts,
candidate states, contradiction IDs, source-vector bindings, blocked scopes,
output hashes, and next safe action.
