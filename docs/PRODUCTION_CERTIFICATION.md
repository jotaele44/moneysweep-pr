# Production certification

`moneysweep-pr` is production-certified only when the fail-closed certification report emitted by `tools.certify_production.py` has `certification_state: CERTIFIED` and `production_eligible: true` for one exact frozen scope, and explicit production activation has separately passed.

The certificate is a bounded claim over a frozen repository revision, evidence corpus, source registry identity, and implementation identity. Historical audit evidence remains evidence for its historical denominator; it is never silently promoted to a newer denominator.

The report separates:

- **certification scope** — exact evidence/corpus/source universe being certified;
- **audit implementation** — exact code and configuration used to evaluate that scope.

## Current source population

The current reconciled registry contains **164 sources: 16 required, 116 automatable, 48 excluded/manual/deferred**. Historical `162 / 16 / 113 / 49` evidence remains an older preserved scope and must not be rewritten in place.

The 162→164 source-ID transition is explicit: `A_ONLY=∅`, `B_ONLY={pr_fomb, pr_fomb_special_reports}`, and the required-source symmetric difference is empty. Runtime and certification use the same effective registry plane: root JSON + direct JSON extensions + direct JSON overrides.

## Evidence hierarchy

Keep these concepts separate:

```text
REPORTED_PRESENT
!= BYTE_PRESENT
!= ACQUISITION_SUCCESS
!= FULLY_MATERIALIZED
!= COVERAGE_PASS
!= FRESH
!= SOURCE_CERTIFIABLE
```

Readiness/status files are observations about the environment that generated them. They cannot manufacture bytes in a later Git checkout, operator corpus, CAS mount, or certification scope.

For `usaspending_prime`, the current Git manifestation lacks the required unified-master build corpus. `tools/audit_unified_master_inputs.py` audits a concrete evidence root and returns `READY_TO_BUILD` only when every required input byte validates. `READY_TO_BUILD` is pre-build state only and never grants production eligibility.

## Automatable execution

The current 116-source automatable population partitions into **104 keyless + 12 credential-gated** sources. `tools/build_keyless_execution_waves.py` derives restartable keyless waves from the generated recovery matrix:

1. `W1_SCHEDULE_INDEPENDENT` — scheduled keyless producers.
2. `W2_OPERATOR_TRIGGERED` — automatable manual/on-drop invocations. Operator-triggered execution is not the same as manual-export source authority.
3. `W3_DEPENDENCY_GATED` — dependency producers; ordering remains unresolved until upstream receipts pass.

Readiness and reported output counts are discovery/planning fields only. G5 credit requires source-bound execution evidence plus valid outputs under the current source definition.

## Current required-source residue

Machine-readable state is maintained in `reports/required_source_closure_20260914.json`.

- `usaspending_prime` — `BLOCKED_INPUT_CORPUS`: authoritative unified-master build input bytes must be mounted/recovered, audited, built, and receipted.
- `hud_drgr_authorized` — authorized operator export required; supporting HUD/CDBG-DR material is not automatically equivalent.
- `prasa` — current authoritative procurement export/dropzone evidence incomplete.
- `campaign_finance_entities` — upstream FEC/OCE products required before entity derivation.
- `campaign_finance_materialization_gate` — blocking validator remains open until its complete upstream denominator passes.

A zero-row file, substitute source, similarly named dataset, historical report count, or passing structural adapter test does not satisfy materialization.

## Gate DAG

| Gate | Required condition |
|---|---|
| G0_SCOPE_FREEZE | Exact scope SHA, implementation SHA, registry definition, corpus identity, and checkout binding frozen. |
| G1_CONTROL_PLANE_RECONCILIATION | Current readiness, source-status, recovery, completeness, federation, and registry identities reconcile without inheriting obsolete denominators. |
| G2_STRICT_PREFLIGHT | Strict pipeline preflight actually executes with zero structural errors. |
| G3_REQUIRED_SOURCE_MATERIALIZATION | All 16 current required sources are fully materialized from valid current-scope bytes. |
| G4_FULL_SOURCE_CLASSIFICATION | Every registered source has exactly one recognized state. |
| G5_AUTOMATABLE_EXECUTION | Every one of the 116 automatable sources has bound execution evidence and valid outputs. |
| G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS | Every in-scope source meets its executable validation/coverage contract. |
| G7_ENTITY_RESOLUTION | No blocking identity-review residue remains inside promoted relationships. |
| G8_PROVENANCE_AND_LINEAGE | A scope-bound authoritative corpus replay proves zero orphan/unresolved promoted lineage. |
| G9_CANONICAL_MASTER_INVARIANTS | Canonical products are rebuilt from that corpus and all invariants pass. |
| G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS | Applicable current sources are explicitly fresh or validly freshness-exempt. |
| G11_PRODUCTION_EXPORT_AND_FEDERATION | Same-scope federation export and downstream compatibility replay pass. |
| G12_RELEASE_CERTIFICATION | G0-G11 pass and explicit production activation authorization is authenticated and scope-bound. |

Anything other than `PASS` blocks certification. Unknown or missing evidence fails closed.

## Run the audit on one checkout

```bash
python -m tools.certify_production \
  --scope-sha "$(git rev-parse HEAD)" \
  --implementation-sha "$(git rev-parse HEAD)" \
  --run-preflight \
  --output reports/production_certification.json
```

`--require-certified` remains a strict release gate and exits non-zero unless the certifier's full release conditions pass. It must not be reinterpreted as pre-activation eligibility unless a separately implemented and documented technical-eligibility command exists.

## Identity and lineage rules

Production identity may not be proven by name-only matching, normalized-name equality, count equality, proximity, or determinism. Stable identifiers and authoritative bindings outrank heuristics. Tied top candidates remain unresolved. One-to-many, many-to-one, many-to-many, zero-to-one, and unresolved states must be preserved rather than coerced into one-to-one matches.

Every promoted row must retain source manifestation and lineage sufficient to reproduce the claim. Different hashes prove byte difference only. Historical receipts remain valid for their frozen definitions/corpus; changed source definitions require new bindings.

## Promotion separation

GitHub Actions startup/infrastructure failure may be bypassed for a code merge only under the documented standing rule when it is the sole remaining blocker. It never waives source evidence, identity, corpus authority, validation contracts, freshness, canonical invariants, federation, or activation.

The certifier never rewrites status files, federation state, historical evidence, or authorization flags merely to produce a green result. `CERTIFIED` is possible only after genuine evidence closure and separately explicit activation authorization.
