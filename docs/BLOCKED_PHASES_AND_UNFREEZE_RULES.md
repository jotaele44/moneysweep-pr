# Blocked Phases And Unfreeze Rules

The repo is paused after R4.9Z with source recovery locked. These rules preserve that state until external source coverage changes.

## Invariants

- Production status remains `NON_PRODUCTION_DIAGNOSTIC`.
- Phase 7/8 remains blocked.
- Retry suppression remains active while `unfreeze_candidates` is `0`.
- Downstream blockers remain active for R5 through R10.
- No synthetic production rows are allowed.
- No stale, fixture, cached, or diagnostic artifacts may be promoted to production inputs.

## Blocked Phase Matrix

| Phase | Status | Reason | Unfreeze rule |
| --- | --- | --- | --- |
| R4.9G retry | blocked | No unfreeze candidates exist. | Start only if R4.9F reports `unfreeze_candidates > 0` after a real source/access change. |
| R5 entity resolution | blocked | Physical source coverage is unavailable and the master is incomplete. | Start only after restored source coverage supports a diagnostic rebuild and explicit downstream gate review. |
| R6 execution chains | blocked | There is no rebuilt production master. | Start only after R5 is unblocked and a rebuilt master exists. |
| R7 financial backbone | blocked | Source and master coverage are incomplete. | Start only after upstream source/master gates pass. |
| R8 graph rebuild | blocked | Source and master coverage are incomplete. | Start only after upstream source/master gates pass and Phase 7/8 block is cleared. |
| R9 risk engine | blocked | Graph/data inputs are incomplete. | Start only after graph/data gates pass. |
| R10 reports | blocked | Production gates have not passed. | Start only after all production gates pass. |

## Allowed Tracks While Blocked

Allowed work:

- external source acquisition outside the repo;
- documentation and operator clarity;
- CI workflow hardening that runs only safe checks;
- dependency and secret policy audit;
- test marker and categorization work.

Forbidden work:

- source download retries;
- endpoint retries;
- source ingestion;
- production staging;
- master rebuild;
- graph rebuild;
- risk engine execution;
- report generation as production evidence.

## Unfreeze Sequence

1. External operator delivers a required source file, restores a missing physical validated source, or fixes access/export conditions outside the repo.
2. Operator places the file into the approved dropzone or target path.
3. Operator validates filename, required columns, nonzero rows, SHA256, and manifest.
4. Operator runs R4.9F watch.
5. If R4.9F reports `unfreeze_candidates > 0`, R4.9G can be scoped to the validated candidate set.
6. If R4.9F still reports `0`, stop and keep source recovery paused.
7. R5 and later phases remain blocked until physical source coverage and diagnostic rebuild evidence justify a separate unfreeze decision.

