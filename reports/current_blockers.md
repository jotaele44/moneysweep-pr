# Current Blockers — R5 PR2.5

**Updated:** 2026-06-14

## Active blockers

### B1 — SAM API rate-limited (1,000 req/day)
- **Impact:** SAM full extract for 2,334 UEIs takes 2.3+ days
- **Status:** SAM_API_KEY available; partial run attempted; rate limit reached
- **Workaround:** USAspending parent lookup; recalibrate expectations for PR government award sources
- **Expected:** 5–15% parent resolution; large contractors (AECOM, Fluor, Parsons) should resolve

### B2 — pr_fec_crossref.csv is header-only
- **Impact:** FEC crossref join not yet populated
- **Root cause:** crossref join depends on entities_resolved.csv being fully populated (PR3 dependency)
- **Mitigation:** removed from fec expected_outputs in source_registry.yaml; file moved to notes

### B3 — FEMA 178-PW, HUD DRGR manual exports not present
- **Impact:** 6 manual-export sources have no data files
- **Required:** manual drop to `data/manual/` directories per manual_export_registry.yaml
- **Scope:** PR6 handles ingestion once files confirmed present

### B4 — parent_uei gate threshold needs recalibration (structural)
- **Impact:** `parent_uei_rate ≥ 0.90` gate will never pass for PR government award sources
- **Root cause:** Top-20 entities by obligation are all PR government agencies; no corporate parent expected
- **Fix:** Recalibrate per-source threshold in `source_registry.yaml`: `usaspending_prime → 0.05`, `fema_pa → 0.05`; retain `0.90` for FSRS/FPDS corporate-prime sources
- **Scope:** PR3 registry patch

## Resolved — SBA recovery source implementation

- ~~B5: SBA Disaster Loan workbook identified but not materialized~~ → registry
  entries added (`manual_export_registry.yaml`, `source_registry.yaml`),
  `SBARecoveryLoan` schema already matched the importer's record shape,
  `scripts/import_sba_disaster_loans.py` now also writes a municipality rollup
  (`sba_recovery_loans_pr_municipality_rollup.csv`), and
  `tests/test_import_sba_disaster_loans.py` covers header-detection,
  normalization, schema conformance, and relationship-key presence. `openpyxl`
  (missing dependency the importer needed) added to requirements + lockfile.
  Status is `not_materialized` in `reports/source_registry_status.csv` (correct
  — no operator has dropped `sba_disaster_loans_pr.xlsx` into
  `data/manual/sba_disaster_loans/` yet; the pipeline plumbing is what's done).
  `COMPARES_WITH_COR3_PROJECTS` relationship deferred — see
  `docs/SBA_RECOVERY_SOURCE_REFRESH.md`.

## Resolved in PR2

- ~~entities_resolved.csv missing~~ → 107,459 rows written
- ~~alias_registry.json missing~~ → 105,323 entries written
- ~~per-source manifests missing for top-5~~ → 5 manifests written

## Resolved in PR2.5

- ~~parent_collapse.py not loading USAspending index~~ → patched, usaspending_parent_index.csv now in candidates list
- ~~entities_resolved_top5.csv missing~~ → written to data/processed/
- ~~alias_registry_top5.json missing~~ → written to data/processed/
- ~~pr2_unresolved_entities.csv missing~~ → 3,818 rows in data/review_queue/
