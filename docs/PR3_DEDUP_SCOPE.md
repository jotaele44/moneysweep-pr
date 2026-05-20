# PR3 — Entity Deduplication Scope

**Status:** SCOPE-ONLY — no implementation in this PR.
**Gate:** This document must be reviewed and accepted before any PR3 implementation
branch (Batch 121+) is opened.
**Authored:** 2026-05-20 (Batch 111–120)

---

## 0. Purpose & boundaries

PR3 collapses the ~105k normalized-name alias clusters into a deduplicated set of
**canonical entities**, so that downstream financial-flow and influence-graph outputs
key on one stable identity per real-world organization instead of many spelling
variants.

This is **entity-level** deduplication. It is distinct from the existing row-level
`scripts/deduplicate_master.py` (which drops cross-file duplicate award *rows*) and
must not modify it.

**In scope:** survivorship resolution across alias clusters; conflict adjudication;
canonical-ID assignment; provenance carry-through; merge auditing.

**Out of scope:** new source ingestion; schema redesign of award masters; graph
algorithm changes beyond re-keying nodes; any change to validation-gate thresholds
except those explicitly enumerated in §9.

---

## 1. Inputs of record

| Artifact | Role |
|---|---|
| `data/staging/processed/enrichment/alias_registry.json` | 105,323 candidate alias clusters (normalized-name based) |
| `data/staging/processed/entities_resolved.csv` | resolved entities with `entity_id`, `entity_uei`, `parent_uei`, `resolution_method`, `match_confidence` |
| `data/staging/processed/enrichment/entity_hierarchy.csv` | vendor → parent resolution from USAspending |
| `data/review_queue/suspect_entity_collapses.csv` | flagged over-collapse candidates |
| `data/exports/entity_collapse_diagnostics.csv` | collapse-quality diagnostics |

The `alias_registry.json` header carries the binding caveat:
> *"Alias clusters are normalized-name candidates, not verified legal identity."*

PR3 must treat normalized-name equality as a **hypothesis**, never as proof of
identity. Survivorship rules below exist precisely to adjudicate that hypothesis.

---

## 2. Canonical entity survivorship rules (T112)

When two or more records are candidates for the same canonical entity, the surviving
canonical record is chosen by this **ordered** rule set. First decisive rule wins.

1. **Verified identifier beats inferred.** A record with a non-empty `entity_uei`
   (or `parent_uei`) outranks any record without one. Two records with *different*
   non-empty UEIs are **never** merged — they are distinct entities (see §3).
2. **Higher resolution confidence wins.** Compare `match_confidence`; the higher
   value supplies the canonical `entity_name`, `entity_type`, and `parent_*` fields.
3. **Resolution method precedence**, when confidence ties:
   `sam_enrichment` > `usaspending` > `sam_index` > `cache` > `summary_only_unresolved`.
4. **Greater financial materiality wins**, when still tied: higher `total_obligation`,
   then higher `record_count`.
5. **Deterministic tiebreak:** lexicographically smallest `normalized_name`. No rule
   may depend on input row order, dict iteration order, or wall-clock time.

The **canonical entity ID** is assigned, not inherited: a stable `canonical_entity_id`
is minted (deterministic hash of the surviving `entity_uei` if present, else of the
surviving `normalized_name`). Original `entity_id` values are preserved as members.

A **confidence score** is emitted per canonical entity = the surviving record's
`match_confidence`, downgraded one band if the merge group contains any
`summary_only_unresolved` member.

---

## 3. Alias conflict policy (T113)

A *conflict* is any merge group where members disagree on a field that affects
identity.

- **UEI conflict** — two distinct non-empty `entity_uei` values in one normalized-name
  cluster: **do not merge.** Split the cluster by UEI; route the residual
  no-UEI members to the review queue. Never silently pick one UEI.
- **Parent conflict** — members agree on entity but disagree on `parent_uei`/`parent_name`:
  keep the parent with the highest-confidence supporting record; record the rejected
  parent(s) in the merge audit; flag for review if confidences are within 0.10.
- **Entity-type conflict** — members disagree on `entity_type` (e.g. `government`
  vs `contractor`): **do not merge**; this is a strong signal the normalized-name
  collision is spurious. Route to review queue.
- **Name-only clusters** (`status: candidate_alias_cluster`, no UEI on any member):
  merge **only** if normalized names are exactly equal AND no type/parent conflict.
  Fuzzy/near-match merging of name-only clusters is **forbidden** in PR3.
- **Sentinel names** — clusters whose `normalized_name` is a non-entity placeholder
  (`MULTIPLE RECIPIENTS`, `MISCELLANEOUS`, `REDACTED`, empty): never merged into a
  real entity; passed through untouched and excluded from graph collapse.

Every conflict produces a row in the **unresolved conflict queue** (§8 / Batch 128),
never a silent decision.

---

## 4. Parent-child collapse guardrails (T114)

Parent–child relationships (`parent_uei` → child entity) must survive dedup as
*edges*, not by collapsing the child into the parent.

- A child entity is **never** merged into its parent. They remain two canonical
  entities linked by a `parent_of` relationship.
- A merge group may not span a known parent/child pair: if grouping would unify a
  parent UEI with a child UEI, abort that merge and flag it.
- **Over-collapse ceiling:** any candidate merge group with
  `collapsed_group_size` above a configured threshold (default 25, see §9) is held
  for review before being applied. The existing `suspect_entity_collapses.csv`
  high-value flags (e.g. *Hospital Damas Inc*, *Municipality of San Juan*) are the
  reference cases this guardrail must catch.
- Government-tier entities (municipalities, agencies) are merged only on exact
  normalized-name equality — never via parent inference.

---

## 5. Provenance preservation contract (T115)

Dedup must be **lossless with respect to origin**. For every canonical entity the
output must retain:

- `member_entity_ids` — every pre-merge `entity_id` folded in.
- `member_normalized_names` — every contributing normalized name / alias.
- `source_files` — union of all members' `source_files` (comma-joined, deduped).
- `source_systems` — union of `source_system` tags (e.g. `awards|fec|lda`).
- `original_entity_names` — every distinct raw/`entity_name` string observed.
- `original_uei_set` — every non-empty UEI seen (normally size 0 or 1 post-§3).
- `resolution_methods` — union of contributing `resolution_method` values.

No source identifier may be dropped. Award rows themselves are **not** rewritten by
PR3; they are re-pointed to `canonical_entity_id` via a crosswalk
(`entity_id` → `canonical_entity_id`), preserving each row's original `entity_id`.

---

## 6. Row-loss / merge audit requirements (T116)

PR3 must emit a **merge audit** that makes every collapse reproducible and reversible.

- **Row-count invariant:** `count(input award rows) == count(output award rows)`.
  Entity dedup reduces the *entity* count, never the *award-row* count. A violation
  is a hard failure.
- **Entity-count accounting:** the audit records
  `entities_in`, `canonical_entities_out`, `groups_merged`, `members_per_group`
  distribution, and `unmerged_singletons`.
- **Per-merge record:** one audit row per canonical entity with `>1` member:
  `canonical_entity_id`, ordered `member_entity_ids`, the rule number from §2 that
  decided survivorship, the survivor, and any rejected field values.
- **Crosswalk completeness:** every input `entity_id` appears exactly once in the
  `entity_id → canonical_entity_id` crosswalk. No orphans, no duplicates.
- The audit is a first-class output artifact, not a log line.

---

## 7. Graph collapse validation criteria (T117)

When the influence graph is re-keyed onto canonical entities:

- **Node accounting:** `nodes_out == count(distinct canonical_entity_id referenced)`.
  Report `nodes_in`, `nodes_out`, `nodes_collapsed`.
- **Edge preservation:** no edge may be dropped. Edges between two members of the
  same merge group become self-loops → these are **removed and counted**, not left
  dangling. All other edges are re-pointed to canonical endpoints; parallel edges
  created by collapse are merged with summed weights and counted.
- **Edge-weight conservation:** total edge weight after collapse (excluding removed
  self-loops) must equal total before, within floating-point tolerance.
- **No new nodes:** graph collapse may only reduce or preserve node count.
- A graph-collapse diagnostics report mirrors `entity_collapse_diagnostics.csv`.
- Regression test: re-running collapse on already-canonical input is a no-op.

---

## 8. Unresolved conflict queue

All §3 conflicts and all §4 over-collapse holds are written to a single reviewable
artifact (CSV) with: cluster key, conflict type, member identifiers, competing
values, financial materiality, and a `disposition` column (`pending` by default).
PR3 makes **no** automated decision on queued items.

---

## 9. Allowed / forbidden files for implementation (T119)

The Batch 121+ implementation PR is restricted to the following.

**ALLOWED — new files:**
- `scripts/dedup_entities.py` — the PR3 entity-dedup entrypoint.
- `contract_sweeper/dedup/` — new package for survivorship/conflict/audit logic.
- `config/dedup_config.*` — dedup config schema (Batch 122).
- `tests/test_pr3_dedup*.py` — targeted PR3 tests.
- New output artifacts under `data/staging/processed/dedup/` and
  `data/review_queue/` (conflict queue, merge audit).
- `reports/pr3_dedup_report.md` / diagnostics CSVs.

**ALLOWED — modify (integration only, Batch 131):**
- `scripts/build_unified_master.py` — to invoke dedup and emit `canonical_entity_id`.
- `scripts/alias_registry_builder.py` — loader hardening only (Batch 123); no
  change to cluster semantics.
- `reports/current_status.json` — status updates.
- `contract_sweeper/runtime/validation_gates.py` — **only** to add PR3 metrics;
  existing thresholds unchanged except the new `entity_overcollapse_ceiling`
  (default 25) and `dedup_rowcount_invariant` gate.

**FORBIDDEN — must not be touched by PR3:**
- `scripts/deduplicate_master.py` — row-level dedup; unrelated and protected.
- `scripts/entity_resolution.py` — resolution stays upstream of dedup.
- Any award-master schema (`pr_*_master.csv` column sets).
- Any source-registry / schema-registry file under `registries/`.
- `archive/**`, HigherGov modules, and any handoff artifact.
- Recalibration of validation-gate thresholds not listed above.

---

## 10. Rollback plan (T118)

- All PR3 work lands on `claude/pr3-dedup-impl` (Batch 121); `main` is never
  committed to directly.
- Dedup is **additive**: it writes new artifacts and a crosswalk. The original
  `entities_resolved.csv` and award masters are not overwritten, so reverting the
  merge commit fully restores prior behavior with no data migration.
- A `--dry-run` mode (Batch 121) produces the merge audit and conflict queue
  **without** writing canonical outputs — required green before any non-dry run.
- If a production rebuild surfaces a bad collapse: revert the PR3 merge commit;
  downstream builds fall back to pre-dedup `entity_id` keying automatically because
  the crosswalk is the only new dependency.
- The merge audit (§6) is the recovery key — every collapse is individually
  reversible from it.

---

## 11. Acceptance checklist for this scope PR

- [ ] Survivorship rule order (§2) accepted.
- [ ] UEI/parent/type conflict policy (§3) accepted.
- [ ] Over-collapse ceiling default (25) confirmed or amended (§4, §9).
- [ ] Provenance field list (§5) accepted.
- [ ] Row-count invariant + merge-audit requirements (§6) accepted.
- [ ] Graph collapse validation criteria (§7) accepted.
- [ ] Allowed/forbidden file list (§9) accepted.
- [ ] Rollback plan (§10) accepted.

On acceptance, Batch 121 opens `claude/pr3-dedup-impl` from `main`.
