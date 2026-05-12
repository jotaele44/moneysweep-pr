# Next Actions

**Updated:** 2026-05-12  
**Current branch:** `claude/r5-pr2-top5-source-materialization`

## PR2 remaining (in-flight)

- [x] Port `alias_registry_builder.py` + `parent_collapse.py`
- [x] Create `scripts/write_source_manifests.py`
- [x] Run entity resolution → `entities_resolved.csv` (107k rows)
- [x] Write 5 per-source manifests
- [x] Create `reports/` directory
- [ ] Add 3 test files (`test_write_source_manifests`, `test_parent_collapse`, `test_alias_registry_builder`)
- [ ] Commit + push + PR

## PR3 (next)

1. Port `execution_chain_builder.py` from sibling
2. Emit `execution_chain_master.csv`, `execution_chain_per_asset.csv`, `execution_chain_per_municipality.csv`
3. Check `subaward_linkage_rate` gate with real data

## Immediate actions to unblock SAM resolution (B1)

```bash
# Set SAM API key
echo "SAM_API_KEY=your_key" >> .env

# Run full SAM extract (takes ~20 min for full PR entity list)
python3 scripts/sam_enrichment.py

# Re-run parent_collapse after SAM extract
python3 scripts/parent_collapse.py
```
