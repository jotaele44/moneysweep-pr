# Secret Handling Policy

This repository must not store real secrets in tracked files. Source recovery is paused, and the production path remains diagnostic, so credentials must not be used to bypass the R4.9Z pause lock.

## Required Practices

1. Keep API keys, bearer tokens, passwords, private keys, and service credentials out of tracked files.
2. Use GitHub Actions secrets only for explicitly manual workflows that require operator confirmation.
3. Do not print environment variables in CI logs.
4. Do not echo secrets, tokens, headers, signed URLs, cookies, or credential-derived values.
5. Use redacted excerpts in audit outputs.
6. Treat `.env` files as local-only files unless a checked-in file is clearly an example with placeholder values.
7. Rotate any credential that is ever committed or exposed in a log.

## CI Rules

Push and pull request CI must remain secret-free. CI workflows may run only safe checks while source recovery is paused:

```bash
python -m compileall contract_sweeper tests
pytest -q
python scripts/run_production_status_gate.py --root .
python scripts/run_repo_quality_audit_r49z_b.py --root .
```

CI must not run:

- source download scripts;
- endpoint retry scripts;
- source ingestion scripts;
- source staging jobs;
- master rebuild jobs;
- graph rebuild jobs;
- risk engine jobs;
- report generation jobs.

## Manual Workflows

Manual workflows that require secrets must stay `workflow_dispatch` only and must require explicit operator confirmation. They must not be converted to push, pull request, schedule, or automatic triggers while source recovery remains paused.

The existing `HigherGov fetch` workflow is a manual source-acquisition workflow, not CI. It must not be used as evidence that production inputs are staged, and it must not start downstream phases.

## Audit Output Rules

Secret scanning outputs must record only:

- file path;
- line number;
- pattern class;
- redacted excerpt;
- recommended action.

Audit outputs must never include a full credential, token, private key, signed URL, cookie, authorization header, or unredacted secret-like assignment.

## Pause-Lock Rules

Credential availability does not unfreeze source recovery by itself. R4.9G remains blocked unless R4.9F reports `unfreeze_candidates > 0` after a real source file or access change is validated.

R5 through R10 remain blocked until source coverage and downstream gates explicitly support progression.

