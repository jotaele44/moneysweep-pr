# MoneySweep HUD DRGR Pursuit Receipt

- Run: `20260906T183741Z_hud_drgr_pursuit`
- Result: `PARTIAL_UNRESOLVED`
- Repo head at run: `74b10245f925bfd9b9ea07b2ce986981d5d65525`
- Origin main at run: `74b10245f925bfd9b9ea07b2ce986981d5d65525`
- Lumen: `LUMEN_UNAVAILABLE_OR_UNHEALTHY; bounded local inspection used`

## Evidence Arithmetic

- Total known HUD/DRGR-shaped paths inspected: `9`
- Classified records: `9`
- Authorized candidates: `0`

## Gate Results

- `scripts/audit_hud_drgr_authorized_sources.py`: `PASS`, blocker preserved
- `scripts/ingest_hud_drgr_exports.py --force`: `PASS`, `0` activities, `0` projects, `0` drawdowns, `0` appropriations
- `scripts/validate_export.py --package data/exports/canonical_v1_federation --mode test`: `PASS` after Hub-package validator drift repair
- Focused pytest: `PASS`, `30 passed`

## Blocker Classification

`hud_drgr_authorized` remains `PARTIAL_UNRESOLVED`. Public CDBG-DR/CDBG-DR-MIT, HCV, and zero-row DRGR-shaped artifacts are documentary/supporting evidence only and are not promoted to an authorized DRGR activity/project/drawdown export.

## Worktree Residue

Dirty state at receipt write is expected generated/edited audit work to be committed with this gate:

```text
M .claude/skillpacks/BINDING.json
 M .claude/skillpacks/MANIFEST.json
 M scripts/validate_export.py
 M tests/test_export_manifest.py
?? reports/live-readiness/20260906T183741Z_hud_drgr_pursuit/
?? scripts/audit_hud_drgr_authorized_sources.py
?? tests/test_audit_hud_drgr_authorized_sources.py
```
