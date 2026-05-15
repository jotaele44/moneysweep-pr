# docs/ — Document Index

This directory contains 26 reference documents accumulated across R4 and R5/R7
development phases. Documents are categorized by currency below.

---

## Current / Active

These documents reflect the current R5/R7 governed platform and are worth reading.

| File | Topic |
|---|---|
| [CI_TESTING_STRATEGY.md](CI_TESTING_STRATEGY.md) | CI testing approach — marker taxonomy, gate integration |
| [CI_WORKFLOW_README.md](CI_WORKFLOW_README.md) | CI workflow structure — job descriptions, step order |
| [CLAIM_LANGUAGE_POLICY.md](CLAIM_LANGUAGE_POLICY.md) | Language policy for claims in outputs and reports |
| [DEPENDENCY_SECURITY_AUDIT.md](DEPENDENCY_SECURITY_AUDIT.md) | Third-party dependency security assessment |
| [NGO_INTEGRATION.md](NGO_INTEGRATION.md) | NGO beneficiary source integration guide |
| [NORTH_STAR_PRODUCT_SPEC.md](NORTH_STAR_PRODUCT_SPEC.md) | Long-range product goals and investigative use cases |
| [OUTPUT_CONTRACTS.md](OUTPUT_CONTRACTS.md) | Output schema contracts — column names, types, guarantees |
| [PRODUCTION_GATES.md](PRODUCTION_GATES.md) | Gate specifications — thresholds, failure conditions |
| [REFERENCE_ARCHITECTURES.md](REFERENCE_ARCHITECTURES.md) | Comparable pipeline architectures and design precedents |
| [SECRET_HANDLING_POLICY.md](SECRET_HANDLING_POLICY.md) | API key and credential handling policy |
| [SOURCE_RECOVERY_RUNBOOK.md](SOURCE_RECOVERY_RUNBOOK.md) | Runbook for recovering a blocked or missing source |
| [TESTING_STRATEGY.md](TESTING_STRATEGY.md) | Testing philosophy, fixture patterns, isolation rules |
| [source_inventory.csv](source_inventory.csv) | Source inventory data (14 registered sources) |

---

## R4-Era / Stale

These documents were written during the R4.x backfill-orchestration phase (r47–r49z),
which concluded when R5 locked 14/14 gates. They are preserved for historical context
but do not reflect current system state.

Archive target: `archive/docs_r4/` (planned, not yet executed).

| File | Original Purpose |
|---|---|
| [BLOCKED_PHASES_AND_UNFREEZE_RULES.md](BLOCKED_PHASES_AND_UNFREEZE_RULES.md) | Phase-7/8 freeze rules (now superseded by R5 gate) |
| [EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md](EXTERNAL_BLOCKER_FREEZE_STATUS_R4_9E.md) | R4.9E external blocker freeze status snapshot |
| [OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md](OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md) | R4.9Z operator action list (completed) |
| [PROJECT_STATE_AFTER_R4_9Z.md](PROJECT_STATE_AFTER_R4_9Z.md) | R4.9Z state snapshot (superseded by HANDOFF.md) |
| [REPO_QUALITY_STATUS_AFTER_R4_9Z.md](REPO_QUALITY_STATUS_AFTER_R4_9Z.md) | R4.9Z repo quality status (superseded by CI) |
| [SOURCE_DELIVERY_HANDOFF_R4_9E.md](SOURCE_DELIVERY_HANDOFF_R4_9E.md) | R4.9E source delivery handoff notes |
| [SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md](SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md) | R4.9Z source recovery pause status |
| [WHEN_TO_RESUME_R4_9G.md](WHEN_TO_RESUME_R4_9G.md) | R4.9G unfreeze trigger conditions (resolved) |
| [broken_imports.md](broken_imports.md) | R4-era broken import analysis (resolved) |
| [execution_roadmap.md](execution_roadmap.md) | R4 execution roadmap (phase completed) |
| [missing_modules.md](missing_modules.md) | R4-era missing module analysis (resolved) |
| [placeholder_detection.md](placeholder_detection.md) | R4 placeholder detection analysis (resolved) |
| [prioritized_patch_plan.md](prioritized_patch_plan.md) | R4 patch plan (executed) |
| [repo_audit.md](repo_audit.md) | R4 repo audit snapshot (superseded by module_inventory.csv) |

---

## How to Use This Index

- For current architecture and setup, start with [../ARCHITECTURE.md](../ARCHITECTURE.md)
  and [../SETUP.md](../SETUP.md) at the repo root.
- For investigative output contracts and signal definitions, see `OUTPUT_CONTRACTS.md`
  and `PRODUCTION_GATES.md`.
- R4-era documents should not be relied on for current system behavior — check
  `registries/source_registry.yaml` and CI gate output instead.
