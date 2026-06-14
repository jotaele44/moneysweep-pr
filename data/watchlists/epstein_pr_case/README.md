# Watchlist — `epstein_pr_case`

**Status: flagged reference only. NOT a public-money source. NOT a materialization target.**

## What this is

Bank-wire records extracted from the Jeffrey Epstein Puerto Rico case PDFs
(`EP_PR_CASE`, document `EFTA01382148.pdf`). The CSVs here record wire transfers
involving `JEFFREY E EPSTEIN` and associated shell entities (`GREAT ST JIM LLC`,
`NAUTILUS INC`, `CYPRESS INC`, `MAPLE INC`, `LAUREL INC`, `LSJE LLC`,
`MICHELLE'S TRANSPORT CO. LLC`) routed through FirstBank Puerto Rico and Banco
Popular de Puerto Rico in 2019.

| File | Contents |
|---|---|
| `EP_PR_PRBank_Wire_Ledger_ALL.csv` | Per-transaction wire ledger (date, amount, bank, entity) |
| `EP_PR_PRBank_Summary_ByEntity.csv` | Totals by entity |
| `EP_PR_PRBank_Summary_ByAccount.csv` | Totals by destination account |
| `EP_PR_PRBank_Summary_ByYear.csv` | Totals by year |

## Why it lives here and not in the source registry

These are private criminal-case financial records on a named individual — **out
of scope** for Contract-Sweeper, which is a Puerto Rico *public-money* (procurement,
grants, recovery, fiscal-control, influence) intelligence producer. They were
previously co-mingled with the legitimate `follow_the_money` source inputs under
`data/raw/follow_the_money/`; they have been separated here so they are never
ingested or materialized as a public-money source.

## Purpose: cross-reference flag

They are retained **only** as a watchlist: if Contract-Sweeper later acquires
public-money data (a contract, grant, donation, or wire) that connects to any of
these entities, banks, or transactions, that overlap should be flagged for human
review. The queryable flag list is generated to
`registries/watchlists/epstein_pr_case.json` by
`scripts/build_watchlist_flags.py`; use `scripts/watchlist.py` (`match()`,
`flagged_entities()`) to test incoming names against it.

## Rules

- Do **not** add these files (or this watchlist) to `registries/source_registry.yaml`.
- Do **not** materialize them into `data/staging/processed/`, `data/canonical_v1/`,
  or any federation export.
- Treat them as evidence/reference, not as a money-flow dataset.
