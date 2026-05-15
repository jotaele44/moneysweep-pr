# Next Actions

**Updated:** 2026-05-14
**Current branch:** `claude/r5-pr59-fsrs-subawards`

## PR #59 — Subaward linkage (complete)

- [x] Fix Python 3.9 `X | None` import failures across config + 68 scripts
- [x] Fix `download_subawards.py` pagination (`hasNext` key) + `MAX_PAGES` cap
- [x] Capture `prime_award_generated_internal_id` in subaward master
- [x] Repair subaward→prime join in `execution_chain_builder.py`
- [x] Re-run download (4,834 subawards), chain builder, influence graph
- [x] `execution_chain_linkage_rate` 0.5969 → 1.0 (PASS); `failed_gate_count` 114 → 112
- [x] Tests: 89 unit passed; secret scan: 0 findings
- [x] `reports/pr59_fsrs_subawards_report.md`

## PR #60 — EMMA bonds (next)

1. Run `python3 scripts/download_emma.py` → emit `pr_emma_bonds.csv`, `pr_emma_underwriters.csv`
2. Refresh influence graph bond-underwriter layer
3. Add per-source manifest; confirm `source_coverage_rate` advances
4. Tests + secret scan + PR

## Remaining required-source backfill (PR #60–65)

Priority order from `reports/backfill_plan.md`:

1. ~~`fsrs_subawards`~~ — done (PR #59, via USAspending subaward API)
2. `emma_bonds` — PR #60, no credentials
3. `oficina_contralor` — PR #61, no credentials
4. `pr_cabilderos` — PR #62, no credentials
5. `cor3` — PR #63, manual export (confirm drop-zone file)
6. `prasa` — PR #64, manual export (confirm drop-zone file)
7. `hud_drgr_authorized` — PR #65, grantee login (deferred if file absent)

Target after PR #60–62: `source_coverage_rate` 0.50 → ~0.79.
Target after PR #63–65: `source_coverage_rate` → ~1.00.
