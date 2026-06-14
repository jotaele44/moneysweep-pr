# Government-Flow Coverage Expansion (25 sources)

This expansion closes 25 previously-uncovered **government-involved financial
flows** touching Puerto Rico, taking the source registry from 88 → **113**
tracked definitions. It complements the existing federal-award, grant,
disaster-recovery, health/social, financial-sector, bond, lobbying, and
political-finance coverage.

All new sources are `required: false` and ship in **dry-run** mode: producers
degrade to a header-only CSV when network egress or an API key is absent, so the
registry validator and CI stay green. **Live materialization is deferred** to a
networked/credentialed run (see `docs/MATERIALIZATION_RUNBOOK.md`).

## What was added

### Tranche 1 — federal API producers (automatable)

Reuse `contract_sweeper.runtime.base_downloader` (`HttpConfig`, `build_session`,
`http_get_json` / `http_post_json`, `paginate`). All became `api_producer` +
`ready` in `reports/materialization_readiness.json`.

| source_id | Flow | Endpoint | Output |
|---|---|---|---|
| `usaspending_loans` | Federal direct loans & loan guarantees (assistance type 07/08) | api.usaspending.gov | `pr_federal_loans.csv` |
| `usda_farm_subsidies` | USDA FSA direct payments + RMA crop insurance (types 06/10) | api.usaspending.gov | `pr_usda_farm_subsidies.csv` |
| `hud_cdbg_mit` | HUD CDBG-Mitigation (CFDA 14.272) | api.usaspending.gov | `pr_cdbg_mit.csv` |
| `federal_audit_clearinghouse` | Single Audits (SF-SAC) of PR auditees | api.fac.gov (`FAC_API_KEY`) | `pr_single_audits.csv` |
| `sam_exclusions` | SAM.gov debarment/exclusions | api.sam.gov (`SAM_API_KEY`) | `sam_exclusions.csv` |
| `fema_individual_assistance` | FEMA IHP household disaster aid | OpenFEMA | `pr_fema_ia.csv` |
| `opportunity_zones` | QOZ designated tracts (capital-gains incentive) | CDFI Fund (`OZ_DATA_URL`) | `pr_opportunity_zones.csv` |
| `opm_fedscope` | Federal civilian payroll in PR | OPM FedScope (`FEDSCOPE_DATA_URL`) | `pr_federal_payroll.csv` |

### Tranches 2-3 — manual dropzone readers (queued/manual)

Delegate to the shared `contract_sweeper.runtime.dropzone_ingest.ingest_dropzone`
helper. Each registers `authentication: manual_export` + a `manual_drop_dir`; an
operator drops CSV/Excel exports there and runs `scripts/ingest_<id>.py`.

| source_id | Flow | Dropzone |
|---|---|---|
| `ocpr_contracts` | **Canonical PR contract registry** (every PR govt contract; distinct from `oficina_contralor` audits) | `data/raw/OCPR_Contracts/` |
| `ddec_incentives` | Act 60/20/22 tax-incentive decrees | `data/raw/DDEC_Incentives/` |
| `crim_property_tax` | Municipal property-tax assessments & collections | `data/raw/CRIM/` |
| `ases_plan_vital` | Plan Vital Medicaid managed-care contracts & capitation | `data/raw/ASES/` |
| `loteria_pr` | Lottery revenue / prizes / commissions | `data/raw/Loteria/` |
| `gaming_commission` | Casino/slot licensing & gaming tax | `data/raw/Gaming/` |
| `ports_authority` | Port/airport concession fees & leases | `data/raw/Ports/` |
| `act_tolls_concession` | Toll revenue & Metropistas/Autopistas concession | `data/raw/ACT_Tolls/` |
| `oatrh_payroll` | Central-government payroll / salaries | `data/raw/OATRH_Payroll/` |
| `ogpe_permits` | Construction-permit fees & green incentives | `data/raw/OGPe/` |
| `dtop_vehicle_fees` | Vehicle-registration (marbete) & license fees | `data/raw/DTOP/` |
| `tourism_room_tax` | Hotel-occupancy tax & co-op marketing | `data/raw/Tourism/` |
| `bde_loans` | Economic Development Bank territorial loans | `data/raw/BDE/` |
| `prpha_housing_subsidy` | Public-housing operating subsidies & RAD | `data/raw/PRPHA/` |
| `doj_settlements` | DOJ/USAO-PR civil settlements & FCA recoveries | `data/raw/DOJ_Settlements/` |
| `equitable_sharing` | DOJ/Treasury asset-forfeiture payouts | `data/raw/Equitable_Sharing/` |
| `irs_ctc_eitc_pr` | IRS Child Tax Credit / EITC to PR families | `data/raw/IRS_CTC_EITC/` |

## Readiness impact

`reports/materialization_readiness.json` after this change:

- `total_sources`: 88 → **113**
- `automatable_total` / `automatable_ready`: 57 → **65** (the 8 API producers)
- `queued_excluded_total`: 31 → **48** (`manual_export` 11 → 28)
- `automatable_not_ready`: still `[]`

## Future vectors (not in this expansion)

1. Promote the `scraper→manual_export` PR surfaces (OCPR registry, Loteria,
   OATRH, OGPe) to live scraping adapters.
2. Entity-resolve recipients/payees (e.g. `ocpr_contracts.contractor_name`,
   `doj_settlements.defendant_name`) against `entities_resolved.csv` and the
   awards master.
3. Replace the best-effort `opportunity_zones` / `opm_fedscope` fetchers with
   pinned authoritative bulk-file ingests.
4. Cross-link `ddec_incentives` (Act 60 decrees) and `sam_exclusions` into the
   risk-signal layer.
