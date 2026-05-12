# Next Actions

**Updated:** 2026-05-12  
**Current branch:** `claude/r5-pr2-top5-source-materialization`

## PR2.5 (in-progress)

- [x] Patch `parent_collapse.py` to load `usaspending_parent_index.csv`
- [x] Re-run `parent_collapse.py` with enriched index
- [x] Emit `data/processed/entities_resolved_top5.csv`
- [x] Emit `data/processed/alias_registry_top5.json`
- [x] Emit `data/review_queue/pr2_unresolved_entities.csv`
- [x] Write `reports/pr2_5_sam_parent_resolution_report.md`
- [x] Tests (PR2-specific): 11 passed
- [x] Secret scan: 0 findings
- [ ] USAspending background lookup complete (~7h ETA) → re-run `parent_collapse.py` → refresh stats
- [ ] Recalibrate `source_registry.yaml` parent_uei thresholds (B4)
- [ ] Commit + push + PR

## When USAspending lookup completes

```bash
# Re-run entity resolution with full USAspending enrichment
python3 scripts/parent_collapse.py

# Update top5 outputs
python3 -c "
import csv, json
from pathlib import Path
# [same emit script as PR2.5 step 4]
"
```

## PR3 (next, after PR2.5 gate)

1. Port `execution_chain_builder.py` from sibling Contract-Sweep
2. Emit `execution_chain_master.csv`, `execution_chain_per_asset.csv`, `execution_chain_per_municipality.csv`
3. Wire into `validation_gates.py` `execution_chain_linkage_rate` gate
4. Tests + secret scan + PR #53
