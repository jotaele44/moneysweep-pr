# Guide Financial Avenue Coverage v1

## Certification state

**OPEN — not certified.**

This audit freezes the financial/investment/incentive avenues explicitly named in
Kevane Grant Thornton's *Doing business in Puerto Rico — Business guide 2021* and
projects the frozen MoneySweep base registry at commit
`6ccd83fbb0ef7ad33d692cc36b27a94433500fcd` onto that denominator.

The guide itself says that it does **not** cover the subject exhaustively and that
its laws are current only through 2020-12-31. Therefore a future
`GUIDE_BOUNDED_100_PERCENT=PASS` must never be promoted to `ALL_PR_FINANCE=PASS`.

Frozen guide manifestation:

- local filename: `doing-business-in-puerto-rico-guide-2021(1).pdf`
- byte size: `764432`
- SHA-256: `f43f8ca103f4d709d012c82ada082c1b175a02467b82c6ad9125a9159bf7a5a8`
- canonical denominator: `registries/guide_financial_avenues_v1.yaml`
- avenue count: **30**

## Set algebra

The avenue-level algebra is explicitly a **guide-universe projection**:

- `A` = all 30 frozen guide avenues.
- `B_GUIDE_PROJECTION` = guide avenues with at least one explicit source route in
  the 158-source frozen MoneySweep base registry.

This avoids mixing source taxonomy with avenue identity.

| Set | Count | Meaning |
|---|---:|---|
| A | 30 | Frozen guide denominator |
| B_GUIDE_PROJECTION | 27 | Guide avenues represented by a base-registry route |
| INTERSECTION | 27 | Avenues represented in both |
| A_ONLY | 3 | No base-registry source route |
| B_ONLY | 0 | Zero by construction inside the guide projection |
| UNION | 30 | Full guide denominator |
| SYMMETRIC_DIFFERENCE | 3 | Same three base route gaps |

`A_ONLY = {GFAV-004 international_financial_entities, GFAV-005 insurance_companies,
GFAV-020 foreign_trade_zones}`.

At the **source** level, every base-registry source is retained rather than thrown
away: 18 of 158 source IDs have an explicit guide binding and the remaining **140
are B_ONLY sources relative to this guide**. `B_ONLY` here does not mean irrelevant
or low quality; it means the source covers MoneySweep material outside this
bounded 2021 guide taxonomy.

The executable audit is `scripts/audit_guide_financial_avenues.py`. It fails closed
unless the live base registry and `reports/source_registry_status.csv` both contain
exactly the same 158 unique source IDs, then emits one row per source and one row
per guide avenue.

## Base route assessment

### Stronger existing routes

- **Commercial banking:** `fdic`, `fhlb`.
- **Capital markets:** `sec_edgar`, `sec_13f_nport`.
- **Economic Development Bank financing:** `bde_loans` (manual-export dependent).
- **Public-private partnerships:** `p3_authority` plus materialized
  `act_transition_ppp`. `docs/PPP_REGISTRY.md` currently records six known
  concessions as canonical; blocked PRASA document surfaces remain separate.
- **Qualified Opportunity Zones:** `opportunity_zones` plus DDEC/Act 60 support.

### Existing partial/supporting routes

`pr_act_60_decrees` and `ddec_incentives` are the principal source routes for most
Act 60 incentive categories. They are **not sufficient for certification** today:

1. `ddec_incentives` is an operator-delivered manual export.
2. `scripts/download_act60.py` falls back to `KNOWN_ACT60_DATA` and writes rows with
   `source_url=known_seed_data` when live acquisition fails. Those rows are
   explicitly **NONCANONICAL** for this audit and cannot satisfy a denominator,
   current-beneficiary, or identity gate.
3. A generic Act 60 row does not prove every guide incentive category is present;
   the raw `incentive_type`/decree semantics must be classified and the category
   denominator must close independently.

`sec_edgar`/`sec_13f_nport` are discovery/support for REITs and registered
investment companies, but they do not prove the Puerto Rico tax-election or local
registration denominator described by the guide. Those bindings remain
`CANDIDATE_NOT_IDENTITY`.

## A_ONLY attack

Three additive source overlays are staged under
`registries/source_registry_overlays/guide_financial_avenues_v1.yaml`:

1. `ocif_guide_financial_classes` — official OCIF concessionaire registry.
   Guide-relevant classes include international financial/banking entities,
   private-equity funds under Ley 185-2014, exempt reporting advisers and
   investment advisers. The OCIF public portal exposes license type, institution,
   status, approval date, license number, NMLS/CRD and export controls.
2. `ocs_insurer_registry` — official Office of the Commissioner of Insurance
   domestic-insurer list plus the annual financial-report index. Current OCS
   annual reports include explicit reinsurance entities such as `Popular Re, Inc.`
   and `Popular Life Re`, providing a temporal regulatory observation distinct
   from an Act 60 incentive decree.
3. `ftz_board_pr` — U.S. Foreign-Trade Zones Board OFIS public zone/site records.
   The discovery denominator is frozen to Puerto Rico Zones **7, 61 and 163** and
   the producer verifies those zone numbers from their authoritative detail pages
   before retention.

If these three overlays are eventually merged, **route representation** would
become 30/30 for the guide projection. That is not certification: the new sources
must first materialize and pass their own schema, count, duplicate, null,
temporal, identity and provenance gates.

## Remaining zero-residue blockers

| Residue | State | Closure requirement |
|---|---|---|
| OCIF new route | OPEN | Live materialization; all requested classes exhaustively paged; count marker closes; stable license IDs preserved |
| OCS new route | OPEN | Live current-insurer + annual-report materialization; duplicates/adjudication; temporal observations frozen |
| FTZ Board new route | OPEN | Live three-zone fetch; exact 7/61/163 closure; site/subzone semantics preserved |
| REIT denominator | UNRESOLVED | Authoritative Puerto Rico REIT election/registration denominator or explicit negative closure |
| Registered investment-company denominator | UNRESOLVED | Exact local statutory class/source binding; adviser/broker/fund categories must not be collapsed |
| Act 60 incentive categories | OPEN | Authoritative beneficiary/decree materialization; exclude seed fallback; classify all 23 incentive-category lanes without omission |
| Existing source materialization | OPEN | Every guide-bound route needed for the claim must have a frozen manifestation, not merely registered code |
| Identity | OPEN | Stable IDs/authoritative bindings; no normalized-name-only promotion |
| Temporal | OPEN | Preserve report/effective/approval years and historical observations; no current/historical conflation |
| Provenance | OPEN | Freeze retrieval UTC, locator/query, raw bytes where obtainable, SHA-256, schema fingerprint and record count |
| Arithmetic | OPEN | Source/retained/excluded counts close; no unexplained loss, duplication or multiplication |

## Certification gate

`GUIDE_BOUNDED_100_PERCENT` may become `PASS` only when:

- all 30 avenues are fully classified;
- every required authoritative source manifestation is frozen;
- every avenue has explicit inclusion/exclusion semantics;
- all null/duplicate/tie/identity/temporal contradictions are adjudicated;
- all row-count and join arithmetic closes;
- source and schema provenance is frozen;
- no `CANDIDATE_NOT_IDENTITY`, seed-only, unmaterialized or unresolved residue
  remains inside the claim.

Until then, **script success, route coverage, and a 30/30 registry mapping are not
certification**.

## Public authority locators used for the new routes

- OCIF concessionaires: `https://concesionarios.ocif.pr.gov/es/License/Index`
- OCS domestic insurers: `https://www.ocs.pr.gov/consumidores/aseguradores-del-pais`
- OCS insurer annual reports: `https://www.ocs.pr.gov/regulados/informes-anuales`
- FTZ Board public information: `https://ofis.trade.gov/`
- FTZ 7 detail: `https://ofis.trade.gov/Zones/Details/103`
- FTZ 61 detail: `https://ofis.trade.gov/Zones/Details/239`
- FTZ 163 detail: `https://ofis.trade.gov/Zones/Details/115`
