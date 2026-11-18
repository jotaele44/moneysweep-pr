# Puerto Rico Data Center Intelligence — governed integration candidate

Status: **AUDIT_ONLY / CERTIFICATION WITHHELD**. This document is additive, does not assert deployment of a pipeline or source completeness, and grants no authority to merge.

## Scope and frozen baseline
- MoneySweep owns records about permits, projects, organizations, contracts, and payments.
- Spiderweb owns spatial-geometry verification and `Cell_ID` assignments. Preserve 1:N/N:N relationships; municipality, nearest-neighbor, and name-only matches are discovery, not identity.
- AguaYLuz contributes typed utility/environmental observations with their own source lineage; it is not a federation admin.
- TheHub alone governs cross-repository LOCKSTEP and federation promotion.
- Mucaro skill promotion requires independently reviewed implementation and exact-head replay.
- Wave 8 observed source heads, **not equivalence proofs**: MoneySweep `c478c3a00d87d51e062df40f9be126d089416822`, Spiderweb `f0adae4d1093261b25b4121b0ae0a9f592bebf0b`, AguaYLuz `58cd9529e387661e8af9445961c82d1c2233f7a3`, TheHub `4577763aeba0e387a360285ba4f79f96d2e6f426`, Mucaro `621e722e3412df711e41c7afa27859751b8abb61`.

## Evidence contract
Each immutable observation carries raw source namespace and record ID, retrieval UTC, source URL, byte SHA-256 where original bytes were acquired, producer and head SHA, evidence class, project type, and claim state. `observation_id` is never automatically a project or facility identity. Preserve raw, normalized, and canonical fields separately. Group multiple versions and contradictory observations without silent overwrite. A claim requiring source bytes remains BLOCKED until they are acquired.

## Change detection
Maintain versioned, frozen per-source snapshots including scope, request, retrieval timestamp, response code, schema and count, source-provided update metadata, raw payload hashes, and ObjectID inventory. Distinguish byte, logical, schema, identity, temporal, and geometry changes. Different bytes do not automatically mean different records; equal ObjectIDs do not prove stable attributes. Compare complete and comparable snapshot populations; otherwise return BLOCKED or UNRESOLVED. Scheduled public-source monitoring is separate from production raw-byte acquisition.

## Current blockers
Contemporary authoritative Puerto Rico permit-feature populations not acquired; no complete denominator; no verified planned-new-build facility identities; Spiderweb and AguaYLuz bindings not independently reproduced; no exact-head federation CI, reviewer approval, qualified merge, postmerge replay, TheHub LOCKSTEP or Mucaro promotion. The identified AEP 1120-36 notice is existing-facility modernization, not a confirmed new build.

## Pre-merge gates
1. Acquire and hash source-original bytes; enumerate and close source exclusions.
2. Prove count/row/ID conservation, temporal consistency, null/duplicate/tie/N:N behavior, and negative regressions.
3. Reconcile authority and geometry identities with independent evidence; unresolved candidates stay candidates.
4. Review and test source parser, UI, security, source change monitor, and failure modes on exact head.
5. Require independent approval; only then permit qualified merge, exact merged-head CI, Spiderweb/AguaYLuz consumer replay, TheHub LOCKSTEP, and immutable final receipts.
6. Promote reviewed Mucaro skill only after those gates and zero material unresolved residue in the declared scope.

## Wave 8 archive contradiction
A previous reply stated ZIP SHA-256 `b477af2ea635d0aba06b87b132e332574a60839feac000f616bb46ee3a512058`. Actual current container bytes of `PR_Data_Center_Intelligence_Wave8.zip` hash `e1e72e329978b4dbe7fec99eea25b1aa6e838a8333c4b80574b01d57041c110d`. Six internal members all match their listed sizes and SHA-256, and 21/21 local integration tests replayed successfully. The outer-hash contradiction remains OPEN until its original manifestation is independently recovered; no retroactive byte-equivalence claim.

**Final verdict: CANDIDATE / AUDIT_ONLY. DATA_CENTER_INTELLIGENCE_CERTIFIED = WITHHELD.**
