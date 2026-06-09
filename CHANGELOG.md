# Changelog

All notable changes to Contract-Sweeper are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it leaves its current `NON_PRODUCTION_DIAGNOSTIC` status.

## Scope note — two independently-versioned contracts

This project has **not** yet cut a tagged software release (the pipeline is paused
pending source delivery). Two machine-readable **contracts** are versioned on their
own tracks and are the things downstream consumers actually pin against. Keep them
separate — they share a constant name only, never a lineage:

| Contract | Version | Source of truth |
|----------|---------|-----------------|
| Federation export (`contract-sweeper-export`, consumed by `spiderweb-pr` query-hub) | `1.2.0` | `scripts/build_export_package.py:EXPORT_CONTRACT_VERSION` |
| Finance-lane report (`contract_sweeper_finance_lane_report.json`) | `1.0.0` | `readiness/contract_sweeper_finance_lane.py:EXPORT_CONTRACT_VERSION` |

A bump to the **federation export** version is what the release-tagging workflow
(`.github/workflows/release-tag.yml`) keys off of — see `docs/federation_readiness.md`
§"Cross-repo release & handshake procedure".

## [Unreleased]

### Added
- Build-execution roadmap hardening (`docs/BUILD_EXECUTION_SEQUENCE.md`, Waves A–M):
  - **Quality-gate spine** (now blocking): `ruff` lint + format, `mypy` (pinned 1.11.2),
    `pytest` with a `--cov-fail-under` floor, and a `requirements.lock` drift check.
  - **Critical-path test coverage** for previously-untested runtime helpers, security-
    sensitive pipeline modules, and query adapters.
  - **Cross-repo contract hardening**: a draft-07 schema for the finance-lane report,
    a federation conformance-fixture freshness guard, and single-source pinning of each
    contract version.
  - **Supply-chain automation**: `dependabot.yml`, a lockfile-drift gate, and a scheduled
    `pip-audit`.
  - **Governance scaffolding**: `LICENSE` (MIT), `CONTRIBUTING.md`, `CODEOWNERS`,
    a PR template, `CODE_OF_CONDUCT.md`, and `SECURITY.md`.
  - **Release & versioning** (this entry): this `CHANGELOG.md`, a release-tagging workflow
    keyed to federation `export_contract_version` bumps, and the cross-repo release/handshake
    procedure in `docs/federation_readiness.md`.

### Changed
- Narrowed an over-broad `except Exception` in `contract_sweeper/runtime/validation_gates.py`
  to `(OSError, UnicodeDecodeError, csv.Error)` so unrelated bugs are no longer swallowed (#221).

### Notes
- Status remains `NON_PRODUCTION_DIAGNOSTIC`; no end-to-end production run is gated on
  this changelog. Entries here track engineering/governance changes to the repository, not
  data outputs.

[Unreleased]: https://github.com/jotaele44/contract-sweeper/commits/main
