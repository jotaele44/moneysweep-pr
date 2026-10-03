<!-- Rendered from thehub-pr/federation-templates/baseline/CLAUDE.md.
     Edit the template there and re-render (tools/render_federation_templates.py);
     do not hand-edit this file — template-drift.yml fails the build if you do. -->

# Working in this repository

**Documentation is part of the change.** If your change makes any document that
describes this repository untrue, update that document in the same change. This is
enforced rather than advisory: CI runs `tools/check_docs_sync.py` on every pull
request, and a Stop hook in `.claude/settings.json` runs it before you finish.

- Before you finish, run `python3 tools/check_docs_sync.py --base origin/main`.
- `.federation/docs-sync.json` says which docs cover which paths. When the checker
  names a doc, read it and update whatever your change made untrue.
- If a doc genuinely needs no change, say why in a commit message line:
  `Docs-Impact: none - <reason>`. The reason is read by reviewers; "n/a" is not one.
- A reference to a path that no longer exists is a contradiction, not a style issue.
  Fix the reference instead of waiving it.
- Files with a "Rendered from" header are generated from templates in the federation
  hub. Change the template and re-render; never hand-edit the copy.

The full policy is in [`CONTRIBUTING.md`](CONTRIBUTING.md).
