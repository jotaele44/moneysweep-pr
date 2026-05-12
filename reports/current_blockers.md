# Current Blockers — R5 PR2

**Updated:** 2026-05-12

## Active blockers

### B1 — SAM full extract requires `SAM_API_KEY`
- **Impact:** entity resolution rate stuck at 0%; parent_uei_rate gate fails
- **Required:** `SAM_API_KEY` set in `.env`; run `scripts/sam_enrichment.py`
- **Unblocks:** entity_resolution gate, parent_uei gate, high_value_unresolved_zero gate
- **Workaround:** vendor_uei_index.csv (200 cached entries) present but sparse

### B2 — pr_fec_crossref.csv is header-only
- **Impact:** FEC crossref join not yet populated
- **Root cause:** crossref join depends on entities_resolved.csv being fully populated (PR3 dependency)
- **Mitigation:** removed from fec expected_outputs in source_registry.yaml; file moved to notes

### B3 — FEMA 178-PW, HUD DRGR manual exports not present
- **Impact:** 6 manual-export sources have no data files
- **Required:** manual drop to `data/manual/` directories per manual_export_registry.yaml
- **Scope:** PR6 handles ingestion once files confirmed present

## Resolved in PR2

- ~~entities_resolved.csv missing~~ → 107,459 rows written
- ~~alias_registry.json missing~~ → 105,323 entries written
- ~~per-source manifests missing for top-5~~ → 5 manifests written
