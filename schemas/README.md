# schemas/

JSON Schema definitions for canonical outputs and internal/derived tables.

## Two schema classes

| Prefix | Class | Purpose |
|---|---|---|
| `contract_sweeper_*.schema.json` | **Exported canonical contract** | Read by downstream consumers — most importantly `spiderweb-pr`'s federation adapter. Version changes here are a cross-repo coordination event. |
| _(no prefix)_ | Internal / derived | Schemas for tables this repo produces but doesn't export across the federation boundary. Free to evolve without cross-repo sign-off. |

The audit (Phase 3, Audit #8 in `reports/codebase_audit.md`) flagged the
prefix convention as load-bearing but undocumented. This file is the policy
document.

## The exported set (`contract_sweeper_*`)

```
contract_sweeper_entity.schema.json
contract_sweeper_export_manifest.schema.json
contract_sweeper_funding_award.schema.json
contract_sweeper_relationship.schema.json
contract_sweeper_source.schema.json
contract_sweeper_transaction.schema.json
```

These six files define the public surface area Contract-Sweeper publishes for
federated consumption. The README at repo root cites a "Contract-Finance"
export contract (currently v1.2.0); these schemas are how that contract is
expressed in machine-readable form.

### Editing rules for exported schemas

1. **Bump the schema version** when changing field shapes, types, or
   required-flag values. Patch bumps for additions, minor bumps for required
   relaxations, major bumps for breaking removals or renames.
2. **Coordinate with `spiderweb-pr`** before changing exported schemas — the
   downstream adapter pins specific shapes. Open a PR in both repos in lockstep.
3. **Add a regression fixture** under `tests/` whenever you add or rename a
   field, to lock down the contract.

## The internal set (everything else)

The other 21 schemas (`agency_master`, `entity_aliases`, `graph_edges`,
`influence_edges`, `municipality_crosswalk`, …) describe tables this repo
produces for its own use. They're free to evolve in single PRs without
cross-repo sign-off.

## Versioning by directory

The `schemas/canonical_v1/` directory holds the v1-frozen exported schemas
for compatibility while v2 is in development. When you cut v2:

1. Copy the v1 exported schemas to `schemas/canonical_v1/` (if not already).
2. Bump the schemas in `schemas/` to v2 shape.
3. Update `spiderweb-pr`'s adapter to read whichever version it pins.

## Naming convention quick reference

| Pattern | Means |
|---|---|
| `<name>.schema.json` | JSON Schema file (the `.schema` suffix is the marker). |
| `contract_sweeper_<name>.schema.json` | Member of the exported canonical contract. Treat as a public API surface. |
| `schemas/canonical_v1/<name>.schema.json` | Frozen v1 snapshot for downstream-pin compatibility. |
