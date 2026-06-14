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
- **Government-flow coverage expansion — 25 new sources** (`docs/GOVERNMENT_FLOW_COVERAGE.md`),
  taking the registry from 88 → **113** tracked sources (automatable 57 → **65**,
  queued/excluded 31 → **48**):
  - 8 federal API producers (reusing `contract_sweeper.runtime.base_downloader`):
    `usaspending_loans` (direct loans/guarantees), `usda_farm_subsidies`
    (FSA/RMA), `hud_cdbg_mit` (CDBG-Mitigation), `federal_audit_clearinghouse`
    (SF-SAC Single Audits), `sam_exclusions` (debarment), `fema_individual_assistance`
    (IHP), `opportunity_zones`, `opm_fedscope` (federal payroll).
  - 17 PR-territorial / federal manual dropzone readers via the new shared
    `contract_sweeper.runtime.dropzone_ingest` helper: `ocpr_contracts` (the
    canonical PR contract registry), `ddec_incentives`, `crim_property_tax`,
    `ases_plan_vital`, `loteria_pr`, `gaming_commission`, `ports_authority`,
    `act_tolls_concession`, `oatrh_payroll`, `ogpe_permits`, `dtop_vehicle_fees`,
    `tourism_room_tax`, `bde_loans`, `prpha_housing_subsidy`, `doj_settlements`,
    `equitable_sharing`, `irs_ctc_eitc_pr`.
  - New `contract_sweeper/runtime/dropzone_ingest.py` factors the
    `ingest_oce`/`ingest_donaciones` reader (cache → empty-dropzone →
    case-insensitive ES/EN column mapping → blank-key filter → dedupe) into one
    shared, tested helper.
  - All new sources are `required: false` and ship dry-run (producers degrade to
    a header-only CSV without network/keys); live materialization is deferred and
    documented in the runbook.
- **NGO political-donation coverage build-out** (`docs/NGO_DONATION_COVERAGE.md`):
  - `analyze_political_crossref.build_ngo_donation_crossref` — joins
    `ngos_master.csv` against federal FEC + PR CEE/OCE donation feeds, flags
    501(c)(4)/(5)/(6) as `likely_political`, and emits
    `data/staging/processed/ngos/ngo_political_donations.csv`. Auto-invoked from
    `ngo_integration.py` after `ngos_master.csv` is written. New `--ngo` flag on
    the crossref CLI.
  - New `scripts/download_fec_committees.py` — FEC committee master plus
    Schedule B (disbursements) and Schedule E (independent expenditures) so
    PACs, Super PACs, 527s, and party committees become first-class entities.
    New source `fec_committees` in the registry.
  - New `scripts/ingest_oce.py` — PR Oficina del Contralor Electoral
    dropzone reader writing `pr_oce_donations.csv` aligned column-for-column to
    `pr_donaciones.csv`. New source `contralor_electoral` in the registry
    (distinct from the existing `oficina_contralor` government-audit source).
    New source `ngo_integration_layer` declares the NGO master / funding /
    coverage outputs.
  - 990 political-activity signal: `download_nonprofits.py` now writes
    `lobbying_expenditure`, `political_expenditure`, `schedule_c_filed`, and a
    derived `politically_active` flag.
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
