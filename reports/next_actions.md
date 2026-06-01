# Next Actions

**Updated:** 2026-06-01
**Active vector:** `MATERIALIZATION_READINESS_LOCKED_AWAITING_EGRESS_FILL`

## Done (this cycle — merged #144)

- [x] Restored the strict-preflight gate (deferred NARA stubs no longer abort it;
      84 sources, 0 structural errors) via `scripts/download_nara_nextgen.py`.
- [x] Materialization readiness gate — `scripts/build_source_recovery_matrix.py`
      now classifies every source from the live registry + adapter registries +
      preflight. Headline: `reports/materialization_readiness.json`.
- [x] `tests/test_materialization_readiness.py` (the gate) + `docs/MATERIALIZATION_RUNBOOK.md`.
- [x] Full suite green: 1229 passed, 5 skipped.

## Readiness snapshot

- 84 sources → **54 automatable, all structurally ready**; 0 broken producers.
- 5 automatable sources need a run-time key: SAM, LDA, FEC, OpenCorporates, HigherGov.
- 30 queued/excluded: 20 `scraper_needed`, 5 `manual_export`, 3 `semantic_duplicate`, 2 `deferred_stub`.

## Next command — `FILL_AUTOMATABLE_SOURCES_IN_EGRESS_ENABLED_ENVIRONMENT`

Run the fill per `docs/MATERIALIZATION_RUNBOOK.md` **in an environment with
outbound HTTPS** (the web sandbox blocks egress — HTTP 403 — so no producer or
adapter can fetch data there):

1. `pip install -r requirements.txt`
2. Set the 5 keys in `.env`.
3. `python3 run_all.py --only-setup --strict-preflight` (expect 0 structural errors).
4. Materialize: `python -m contract_sweeper.query --source <id>` (35 adapter
   sources) and/or `python3 run_all.py --strict-preflight`.
5. `python3 scripts/gap_analysis_builder.py && python3 scripts/build_source_recovery_matrix.py`.
6. Verify `automatable_ready == automatable_total` and each automatable source
   `fully_materialized`.

## Future work (separate egress-enabled PRs)

- Build the 20 `scraper_needed` PR-gov HTML/PDF scraping adapters.
- Integrate the manual datasets (ACT, ACUDEN, PRASA, cabilderos, DCAA) via the
  dropzones in `registries/manual_export_registry.yaml`.
