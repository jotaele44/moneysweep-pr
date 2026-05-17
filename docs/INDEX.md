# docs/ — Document Index

This directory contains 14 reference documents relevant to the current R5/R7 platform.

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

## How to Use This Index

- For current architecture and setup, start with [../ARCHITECTURE.md](../ARCHITECTURE.md)
  and [../SETUP.md](../SETUP.md) at the repo root.
- For investigative output contracts and signal definitions, see `OUTPUT_CONTRACTS.md`
  and `PRODUCTION_GATES.md`.
- R4-era documents should not be relied on for current system behavior — check
  `registries/source_registry.yaml` and CI gate output instead.
