# Registries

The four registries here drive source materialization, schema validation,
endpoint resolution, and manual-export tracking. They exist in two formats:

| Registry | YAML (source of truth) | JSON (runtime wire format) |
|---|---|---|
| Source registry | `source_registry.yaml` | `source_registry.json` |
| Schema registry | `schema_registry.yaml` | `schema_registry.json` |
| Endpoint candidates | `endpoint_candidates.yaml` | `endpoint_candidates.json` |
| Manual export registry | `manual_export_registry.yaml` | `manual_export_registry.json` |

## YAML is the source of truth

**Edit the `.yaml` files.** YAML is the human-editable canonical form: comments,
multi-line strings, anchors, the lot.

**JSON files are regenerated, never hand-edited.** Runtime modules under
`contract_sweeper.runtime.*` read JSON because it's faster and stdlib-only;
they never touch YAML. JSON files are an output artifact.

## Regenerating JSON after a YAML edit

```bash
python3 scripts/regenerate_registry_json.py
git add registries/*.json
```

Run the regenerator after every YAML edit. The CI check
[`registry-sync.yml`](../.github/workflows/registry-sync.yml) will fail the PR
if you forget — it re-runs the regenerator in a clean checkout and asserts
`git diff --exit-code` on `registries/*.json`.

The matching pre-commit hook (`mirrors-pre-commit/local — regenerate-registry-json`
in [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)) runs the regenerator
automatically when you stage a YAML change, so the local workflow is "edit
YAML, commit, JSON regenerates as part of the commit."

## Why two formats?

- **YAML for humans:** registries are policy data — source IDs, expected outputs,
  schema columns, endpoint URLs, notes. YAML's comment support and multi-line
  strings make policy edits readable in PRs.
- **JSON for runtime:** `contract_sweeper.runtime.source_registry`, `schema_registry`,
  etc. read JSON via the stdlib without an extra dependency, and JSON parses
  faster than YAML on every startup.

When the two formats drift, the runtime reads stale policy. The Phase-2 audit
caught two registries already drifted (`schema_registry.json` was missing
`alias_overrides` schema and `override_hits` column; `endpoint_candidates.json`
had empty URLs for `act_transition_contracts` and `acuden_2024_transition`).
The guardrail makes that class of drift impossible to commit.

## Adding a new registry

1. Create `registries/<name>.yaml`.
2. Add `("<name>.yaml", "<name>.json")` to `REGISTRY_PAIRS` in
   `scripts/regenerate_registry_json.py`.
3. Run `python3 scripts/regenerate_registry_json.py` and commit both files.
4. The runtime module that reads it should point at the `.json`, not the `.yaml`.
