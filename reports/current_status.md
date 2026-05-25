# Current Status — Post-PR97 Normalization

**Updated:** 2026-05-23
**Branch:** `claude/post-pr97-status-normalization`
**Phase:** Required-source backfill gate (strict preflight confirmed)

---

## Pipeline state summary

| Item | Status |
|---|---|
| Source registry wiring | COMPLETE — all 82 producer_script paths point to scripts/ |
| PR #97 (pipeline readiness preflight) | MERGED to main (commit cd85605) |
| Strict preflight result | PASS — 0 structural errors, 5 missing_key_limited (non-fatal) |
| Full test suite (2026-05-23) | 713 passed, 4 pre-existing failures, 2 skipped |
| Preflight-specific tests | 5/5 passed |
| Production status | NON_PRODUCTION_DIAGNOSTIC |
| Pause lock | ACTIVE |

---

## Strict preflight result (2026-05-23)

```
python3 run_all.py --only-setup --strict-preflight
```

- **82 sources checked**
- **77 ready** (import OK, no key required or key present)
- **5 missing_key_limited** (non-fatal — sources skip or run limited):
  - `sam_entities` → SAM_API_KEY not set
  - `highergov_supplemental` → HIGHERGOV_API_KEY not set
  - `lda` → LDA_API_KEY not set
  - `fec` → FEC_API_KEY not set
  - `opencorporates` → OPENCORPORATES_API_TOKEN not set
- **0 structural errors**
- **Result: PASS** — strict mode did not abort

---

## Test result (2026-05-23)

```
python3 -m pytest -q --ignore=.claude
713 passed, 4 failed, 2 skipped
```

4 pre-existing failures on main (not introduced by this branch):
- `test_r48b_executes_with_explicit_terminal_statuses` — order-dependent; passes in isolation
- `test_r48d_runs_targeted_retry_and_writes_outputs` — pre-existing on main
- `test_r48d_schema_alignment_report_records_deterministic_mappings` — pre-existing on main
- `test_status_csv_regenerates_identically` — order-dependent; passes in isolation

---

## Production blockers (unchanged)

- **Materialization incomplete** — required sources not yet fully materialized (see backfill order below)
- **Manual exports pending** — cor3, hud_drgr_authorized, prasa, oficina_contralor require operator-supplied files
- **PR3 deduplication** — blocked until PR2.5/PR2.6 branch reconciled against latest main
- **Source intake taxonomy** — uploaded PR contract, lobbying, PRASA, and contractor-reference datasets pending classification

---

## Required-source backfill order (next execution)

Run required-source producers only (`required=True`); do not run optional sources in this pass. Gate: strict preflight must pass before each run.

| Source | Current status | Notes |
|---|---|---|
| `usaspending_prime` | partially_materialized | No API key required |
| `emma_bonds` | partially_materialized | No API key required |
| `pr_cabilderos` | partially_materialized | No API key required |
| `fsrs_subawards` | not_materialized | No API key required |
| `cor3` | not_materialized | Manual export required |
| `hud_drgr_authorized` | not_materialized | Manual export required |
| `prasa` | not_materialized | Manual export required |
| `oficina_contralor` | not_materialized | Manual export required |
| `sam_entities` | not_materialized | Requires SAM_API_KEY |

Already fully materialized (required): `usaspending_subawards`, `fema_pa_openfema_v2`,
`hud_cdbg_dr_public`, `lda`, `fec`.

**Next command:** `BACKFILL_REQUIRED_SOURCES_ONLY_AFTER_STRICT_PREFLIGHT`

---

## Deferred patches

- **Materialization vocabulary** — `gap_analysis_builder.py` uses `fully_materialized` / `partially_materialized` / `not_materialized` / `below_threshold` / `no_outputs_declared`. Proposed additions (`full_materialized`, `partial_materialized`, `seed_only`, `manual_required`, `failed_api_query`) diverge from existing vocabulary; defer to a dedicated PR to avoid breaking existing tests.
