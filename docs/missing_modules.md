# Missing Modules — Canonical vs Present

Generated alongside `repo_audit.md`. Sourced from the R5 mission spec.

| Canonical module | Status |
|---|---|
| `contract_sweeper/runtime/source_registry.py` | present (R5 PR1) |
| `contract_sweeper/runtime/schema_registry.py` | present (R5 PR1) |
| `contract_sweeper/runtime/manifest_runtime.py` | present (R5 PR1) |
| `contract_sweeper/runtime/validation_gates.py` | present (R5 PR1) |
| `contract_sweeper/runtime/name_normalization.py` | present (R5 PR1) |
| `contract_sweeper/runtime/linkage_confidence.py` | present (R5 PR1) |
| `contract_sweeper/runtime/file_hash_runtime.py` | present (R5 PR1) |
| `contract_sweeper/runtime/retry_runtime.py` | present (R5 PR1) |
| `contract_sweeper/runtime/pagination_runtime.py` | present (R5 PR1) |
| `scripts/scan_for_secrets.py` | present (R5 PR1) |
| `scripts/alias_registry_builder.py` | missing — port in PR2/PR3 |
| `scripts/parent_collapse.py` | missing — port in PR2/PR3 |
| `scripts/execution_chain_builder.py` | missing — port in PR3 |
| `scripts/influence_graph_builder.py` | missing — port in PR4 |
| `scripts/quarantine_stale_outputs.py` | missing — port in PR5 |
| `scripts/contract_cradle_harden.py` | missing — orchestrator, build after PR3 |
| `scripts/gap_analysis.py` | missing — PR5 |
| `scripts/assets_master_builder.py` | missing — PR4 |
| `scripts/financial_flows_builder.py` | missing — PR2/PR3 |

## Notes
- Modules marked "present (R5 PR1)" land in this PR. They cover registry-driven foundation only.
- Modules marked "missing — port in PRx" are scoped to future PRs as enumerated in `prioritized_patch_plan.md`.
- Sibling implementations live in `/Users/jotaele/Documents/Coding/Contract-Sweep/scripts/`. They are the port source.