#!/usr/bin/env bash
# Persist bot-written files on an unprotected data branch instead of main.
#
# main here is protected by required checks (and, in moneysweep-pr, a required
# pull-request review), so a workflow's plain `git push` to main is always
# rejected. Federation handoff receipts still have to be durable before the
# sender is acknowledged, so this commits the given paths on a dedicated data
# branch and pushes that. The branch is created as an orphan on first use and
# only ever holds the listed paths.
#
# Usage:
#   scripts/persist_to_data_branch.sh restore BRANCH PATH...
#       Copy PATHs from origin/BRANCH into the working tree (no-op when the
#       branch or a path does not exist yet). Run before ingest so duplicate
#       detection sees receipts persisted by earlier runs.
#   scripts/persist_to_data_branch.sh push BRANCH MESSAGE PATH...
#       Commit the working-tree copies of PATHs onto BRANCH and push, retrying
#       when the branch moved. Exits non-zero if the push never lands, so the
#       caller's acknowledgment step does not run.
set -euo pipefail

mode="${1:?usage: persist_to_data_branch.sh restore|push BRANCH ...}"
branch="${2:?branch required}"
shift 2

remote_has_branch() {
  git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1
}

case "$mode" in
  restore)
    [ "$#" -gt 0 ] || { echo "restore needs at least one PATH" >&2; exit 2; }
    if ! remote_has_branch; then
      echo "No $branch branch yet; nothing to restore."
      exit 0
    fi
    git fetch --quiet --depth=1 origin "$branch"
    for path in "$@"; do
      if git cat-file -e "FETCH_HEAD:$path" 2>/dev/null; then
        git archive FETCH_HEAD -- "$path" | tar -x
        echo "Restored $path from $branch."
      fi
    done
    ;;
  push)
    message="${1:?message required}"
    shift
    [ "$#" -gt 0 ] || { echo "push needs at least one PATH" >&2; exit 2; }
    src="$(pwd)"
    work="$(mktemp -d)"
    trap 'git -C "$src" worktree remove --force "$work" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
    for attempt in 1 2 3 4; do
      git worktree remove --force "$work" >/dev/null 2>&1 || true
      rm -rf "$work"
      if remote_has_branch; then
        git fetch --quiet --depth=1 origin "$branch"
        git worktree add --quiet --detach "$work" FETCH_HEAD
      else
        git worktree add --quiet --detach "$work" HEAD
        git -C "$work" checkout --quiet --orphan "tmp-$branch-$attempt"
        git -C "$work" rm -rfq --cached . >/dev/null
        find "$work" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
      fi
      for path in "$@"; do
        if [ -e "$src/$path" ]; then
          mkdir -p "$work/$(dirname "$path")"
          rm -rf "${work:?}/$path"
          cp -R "$src/$path" "$work/$path"
          git -C "$work" add -- "$path"
        fi
      done
      if git -C "$work" diff --cached --quiet; then
        echo "$branch already has these files."
        exit 0
      fi
      git -C "$work" commit --quiet -m "$message"
      if git -C "$work" push --quiet origin "HEAD:refs/heads/$branch"; then
        echo "Pushed to $branch (attempt $attempt)."
        exit 0
      fi
      echo "$branch moved; retrying."
      sleep $((2 ** attempt))
    done
    echo "::error::Could not push to $branch after 4 attempts." >&2
    exit 1
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac
