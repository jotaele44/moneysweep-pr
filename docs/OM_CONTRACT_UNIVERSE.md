# Puerto Rico O&M Contract Universe

## Status

`NON_PRODUCTION_DIAGNOSTIC`. This subsystem must not claim that all Puerto Rico operations-and-maintenance contracts are present until every certification constraint is satisfied.

## Scope

The universe combines central-government, municipal, public-corporation, concession/P3, federal-prime, and federal-subaward contract records. The normalized taxonomy is stored in `registries/om_contract_taxonomy.yaml` and covers operations, preventive/corrective maintenance, facilities, assets, inspection/testing, IT systems, vegetation, water, power, roads, transit, ports/airports, and concessions.

## OCPR acquisition

Use the resumable materializer rather than the prototype one-shot scraper for full runs:

```bash
python3 scripts/materialize_ocpr_contracts_resumable.py --max-pages 5 --reset
python3 scripts/materialize_ocpr_contracts_resumable.py
```

The first command is a provisional smoke run. The second resumes from its signed-by-hash checkpoint. The canonical `pr_ocpr_contracts.csv` is replaced only after:

1. every page is fetched;
2. the observed registry total remains stable;
3. the work JSONL SHA-256 matches its checkpoint;
4. raw row count equals the OCPR-reported total; and
5. a completion receipt is written.

The live endpoint currently returns the page length in `recordsTotal` and the
full unfiltered registry size in `recordsFiltered`; the resumable materializer
uses `recordsFiltered` as the completion denominator and tests this contract to
prevent a bounded smoke from being promoted as a complete registry.

Interrupted, failed, or `--max-pages` runs remain under `data/staging/checkpoints/ocpr_contracts/` and cannot be mistaken for complete source materialization.

## Build diagnostic universe

```bash
python3 scripts/build_om_contract_universe.py
python3 scripts/validate_om_contract_universe.py
```

Generated artifacts:

- source materialization inventory;
- classified contract universe;
- agency, municipality, fiscal-year, category, contractor, and source matrices;
- deterministic duplicate fingerprints;
- explicit unresolved-gap ledger; and
- diagnostic summary.

## Certification gate

A complete-coverage claim is prohibited until all of the following are independently evidenced:

- OCPR full-registry completion receipt;
- all 78 municipalities accounted for;
- all registered public corporations and instrumentalities accounted for;
- central-government and P3/concession sources accounted for;
- federal prime and subaward paths accounted for;
- missing sources explicitly recorded;
- all duplicate clusters adjudicated;
- amendments, renewals, cancellations, and current status preserved; and
- source, agency, municipality, fiscal-year, sector, contractor, value, and expenditure matrices reconciled.

The structural validator intentionally reports certification as blocked. Promotion requires a later, evidence-bearing certification workflow; it is not inferred from successful code execution.
