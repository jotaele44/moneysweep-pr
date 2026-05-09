# When To Resume R4.9G

R4.9G is blocked in the current repo state. It must not run because R4.9F reports `unfreeze_candidates: 0` and all 21 source delivery blockers remain unresolved.

## Resume Trigger

R4.9G may be considered only after one of these material external changes is visible:

- R4.9F reports `unfreeze_candidates > 0`; or
- at least one required source file is visibly delivered into an approved path listed in `data/review_queue/source_delivery_checklist_r4_9e.csv` or `data/review_queue/physical_validated_files_still_missing_r4_9c.csv`.

An intent to retry is not enough. A source file, access change, or endpoint/export fix must exist first.

## What To Run First

After a material source/access change, run only:

```bash
python scripts/run_source_delivery_watch_r49f.py --root .
python scripts/run_source_recovery_pause_lock_r49z.py --root .
```

If the watch still reports `unfreeze_candidates: 0`, stop. Do not run R4.9G.

## R4.9G Gate

R4.9G can start only when all of these are true:

- at least one delivered source is in an approved path;
- its schema check passes;
- its row count is nonzero;
- its SHA256 has been computed;
- its validated manifest has been written or updated;
- R4.9F reports `unfreeze_candidates > 0`;
- the retry is scoped only to validated unfreeze candidates;
- downstream phase blockers remain active unless explicitly cleared later.

## Non-Triggers

Do not resume R4.9G for any of these:

- merged documentation-only PRs;
- CI workflow changes;
- dependency or secret policy audits;
- test categorization;
- stale diagnostic output files;
- cached report files;
- untracked local source-looking files that have not been validated through the approved delivery paths;
- manual interest in retrying without a delivered source/access change.

## After R4.9G

Even if R4.9G becomes eligible and succeeds for one source, R5 remains blocked until physical source coverage is restored enough to support a diagnostic rebuild and downstream gate review. R4.9G is an unfreeze gate, not a blanket release for R5 through R10.

