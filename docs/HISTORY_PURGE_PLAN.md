# Git history purge plan (#222)

_Status: **documented, not yet executed.** Tasks 66–67 of
`docs/BUILD_EXECUTION_SEQUENCE.md` (the size guard + this plan) are done; tasks
68 (the purge) and 69 (post-purge verification) are deliberately deferred to a
maintainer-coordinated window because they **rewrite published history and
force-push**, which every collaborator must re-clone around._

This is the companion to `RECOMMENDATIONS.md` #1 ("Remove ~89 MB of data blobs
committed to git history").

## What is in history

The large blobs were already removed from the working tree and `data/**` is now
deny-all in `.gitignore` (RECOMMENDATIONS.md #2), so **nothing new is being
added**. But the blobs still live in the object database and bloat every full
clone. Confirmed with:

```bash
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '/^blob/ && $3 > 500000 {print $3, $4}' | sort -rn
```

The offenders to strip (path globs; sizes are uncompressed):

| Size | Path |
|------|------|
| 56 MB | `data/raw/Follow the Money/funding_flows_sf133.csv` |
| 24 MB | `data/staging/processed/partial/contracts_master_partial_diagnostic_r4_9g.csv` |
| 5.3 MB | `data/raw/FEC/efile-2026-05-05T06_41_38.csv` |
| 1.3 MB | `data/staging/processed/partial/entities_partial_diagnostic_r4_9g.csv` |
| <1 MB ea. | `data/raw/Vigentes*` and `data/raw/torres_rosa_consultation/*.pdf` (and other `data/raw/**` PDFs) |

> Note: a fresh checkout in an ephemeral/partial clone may report a small `.git`
> because text blobs pack well and some environments use blobless clones. Verify
> the real cost in a **full** clone (`git clone --no-single-branch`) before and
> after the purge — see "Verification" below.

## Why a guard comes first (already landed)

`.github/workflows/size-guard.yml` blocks any PR that adds or grows a tracked
file past 5 MiB. Landing the guard **before** the purge means the problem cannot
recur the moment history is clean. This is task 66; the purge is task 68.

## The purge procedure (task 68 — requires a coordinated window)

> **Do not run this unattended.** It rewrites every commit SHA after the first
> touch of these paths and requires a force-push plus a re-clone by all
> collaborators. Schedule a window, freeze merges, and announce it.

1. **Announce & freeze.** Pause merges to `main`; tell all collaborators a
   re-clone is coming and to push/stash any in-flight work first.

2. **Back up.** Create a throwaway mirror so the rewrite is reversible:
   ```bash
   git clone --mirror git@github.com:jotaele44/moneysweep-pr.git cs-backup.git
   ```

3. **Rewrite history** with [`git-filter-repo`](https://github.com/newren/git-filter-repo)
   (preferred over BFG/`filter-branch`). Strip the specific large paths while
   keeping the small, intentionally-committed fixtures under `data/`:
   ```bash
   git clone git@github.com:jotaele44/moneysweep-pr.git cs-purge
   cd cs-purge
   git filter-repo \
     --path "data/raw/Follow the Money/funding_flows_sf133.csv" \
     --path "data/staging/processed/partial/contracts_master_partial_diagnostic_r4_9g.csv" \
     --path "data/staging/processed/partial/entities_partial_diagnostic_r4_9g.csv" \
     --path "data/raw/FEC/efile-2026-05-05T06_41_38.csv" \
     --path-glob "data/raw/Vigentes*" \
     --path-glob "data/raw/torres_rosa_consultation/*" \
     --invert-paths
   ```
   `--invert-paths` removes exactly the listed paths from **all** history and
   leaves everything else (including allowlisted fixtures) intact. Re-run the
   inventory command above to confirm the blobs are gone.

4. **Repack & measure** (see Verification).

5. **Force-push** the rewritten refs:
   ```bash
   git push --force --all
   git push --force --tags
   ```

6. **Re-clone.** Every collaborator deletes their local clone and clones fresh.
   Old clones still contain the blobs and must not be pushed from.

## Verification (task 69 — depends on 68)

After the force-push:

```bash
# Clone size, fresh and full
git clone --no-single-branch git@github.com:jotaele44/moneysweep-pr.git cs-verify
du -sh cs-verify/.git

# The offenders must be absent from all history
cd cs-verify
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '/^blob/ && $3 > 5000000 {print $3, $4}' | sort -rn   # expect: empty
```

Then:

- Record the before/after `.git` size here and in `RECOMMENDATIONS.md` #1, and
  flip task 69 to `[done]` in `docs/BUILD_EXECUTION_SEQUENCE.md`.
- Confirm CI is green on a fresh clone (the rewrite changes SHAs; any
  SHA-pinned references — e.g. `.git-blame-ignore-revs`, the Wave-C format commit
  — must be re-resolved against the rewritten history).

## Rollback

If anything looks wrong after the force-push, restore from the mirror created in
step 2:

```bash
cd cs-backup.git
git push --force --mirror git@github.com:jotaele44/moneysweep-pr.git
```
