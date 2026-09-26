# Production certification

`moneysweep-pr` is production-certified only when the fail-closed certification report emitted by `tools.certify_production.py` has `certification_state: CERTIFIED` and `production_eligible: true` for one exact Git commit.

The certificate is a bounded claim over a frozen repository revision and the source universe represented by the registry digest in that report. Historical audit evidence remains evidence for its historical denominator; it is never silently promoted to a newer denominator.

The report separates two identities:

- **certification scope** — the exact Git commit whose evidence corpus is being certified;
- **audit implementation** — the exact Git commit containing the certifier and certification configuration.

On pull requests CI checks these out separately: the PR base/current `main` is the immutable evidence scope, while the PR head is the audit implementation. A PR therefore cannot certify edited status files while claiming an older `main` SHA.

## Run the audit on one checkout

```bash
python -m tools.certify_production \
  --scope-sha "$(git rev-parse HEAD)" \
  --implementation-sha "$(git rev-parse HEAD)" \
  --run-preflight \
  --output reports/production_certification.json
```

To use the certifier as a hard release gate:

```bash
python -m tools.certify_production \
  --scope-sha "$(git rev-parse HEAD)" \
  --implementation-sha "$(git rev-parse HEAD)" \
  --run-preflight \
  --require-certified
```

The second command exits non-zero unless every mandatory gate passes.

## Gate DAG

| Gate | Required condition |
|---|---|
| G0_SCOPE_FREEZE | Exact scope SHA, implementation SHA, checkout binding, and source denominator frozen. |
| G1_CONTROL_PLANE_RECONCILIATION | Readiness, source-status, recovery, completeness, federation, and registry digest reconcile. |
| G2_STRICT_PREFLIGHT | Strict pipeline preflight executes with zero structural errors. |
| G3_REQUIRED_SOURCE_MATERIALIZATION | All 16 current required sources are fully materialized. |
| G4_FULL_SOURCE_CLASSIFICATION | Every registered source has exactly one recognized materialization state. |
| G5_AUTOMATABLE_EXECUTION | Every automatable source is materially executed and represented in freshness state. |
| G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS | Every in-scope source meets an explicit validated coverage contract. |
| G7_ENTITY_RESOLUTION | No unresolved identity-review residue remains inside the certified claim. |
| G8_PROVENANCE_AND_LINEAGE | A current-denominator audit proves zero orphan/unresolved promoted lineage. |
| G9_CANONICAL_MASTER_INVARIANTS | Canonical master/graph receipt is explicitly `CERTIFIED`. |
| G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS | Every enabled automatable source is explicitly fresh for the frozen claim. |
| G11_PRODUCTION_EXPORT_AND_FEDERATION | Production export and downstream federation live-execution gates pass. |
| G12_RELEASE_CERTIFICATION | G0-G11 pass and production activation is explicitly authorized. |

States are `PASS`, `FAIL`, `BLOCKED`, or `OPEN`. Anything other than `PASS` blocks the final certificate. Unknown or missing evidence fails closed.

## Current required-source residue at the 2026-08-28 main snapshot

The current registry contains 16 required sources. Eight are fully materialized, one is partial, and seven are not materialized. The residue is:

- `usaspending_prime` — partial;
- `cor3` — not materialized;
- `hud_drgr_authorized` — not materialized and requires the authorized DRGR export;
- `prasa` — not materialized and requires an authoritative PRASA operator export;
- `oficina_contralor` — not materialized;
- `pr_cabilderos` — not materialized and requires authoritative OEG evidence;
- `campaign_finance_entities` — not materialized;
- `campaign_finance_materialization_gate` — not materialized.

A zero-row file, a substitute source, a similarly named dataset, or a passing structural adapter test does not satisfy materialization.

## Identity and lineage rules

Production identity may not be proven by name-only matching, normalized-name equality, count equality, proximity, or determinism. Stable identifiers and authoritative bindings outrank heuristics. Tied top candidates remain unresolved. One-to-many, many-to-one, many-to-many, zero-to-one, and unresolved states must be preserved rather than coerced into one-to-one matches.

Every promoted row must retain source manifestation and lineage sufficient to reproduce the claim. Different file hashes prove byte difference only. Historical lineage receipts remain valid for their frozen corpus, but a changed source denominator requires a new audit.

## Promotion separation

Technical certification and production activation are separate controls. The certifier never rewrites `federation.json`, historical status reports, or authorization flags merely to produce a green result. `CERTIFIED` is possible only after the evidence gates pass and an explicit production-activation authorization exists.
