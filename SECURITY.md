# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue or PR for
a suspected vulnerability.

- Preferred: open a private [GitHub Security Advisory](https://github.com/jotaele44/Contract-Sweeper/security/advisories/new)
  for this repository.
- Or email the maintainer: **jorge.gonzalez44@upr.edu** (subject line prefixed
  `[SECURITY]`).

Include enough detail to reproduce: affected file/version, impact, and a minimal
proof of concept if possible. We aim to acknowledge reports within a few days.

## Scope

This policy covers the Contract-Sweeper source code and its CI/CD configuration.
The pipeline ingests **public records**; please report concerns such as:

- credential/secret handling (env-var usage, accidental secret commits),
- code execution paths that run external commands or fetch remote data,
- dependency vulnerabilities not yet surfaced by the `pip-audit` workflow.

Note that the public datasets the pipeline processes are not themselves in scope;
they are governed by their originating sources.

## Supported versions

The project is pre-release (`NON_PRODUCTION_DIAGNOSTIC`); security fixes are applied
to `main`.

## Automated tooling

- Secret scanning runs in pre-commit (`gitleaks`) and CI (`scripts/scan_for_secrets.py`).
- `pip-audit` scans the locked dependency set weekly (`.github/workflows/pip-audit.yml`).
- Dependabot proposes dependency and GitHub Actions updates weekly.
