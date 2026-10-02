# Guide Financial Avenue Coverage v1

## Certification state

**OPEN — not certified.**

This audit freezes the financial/investment/incentive avenues explicitly named in
Kevane Grant Thornton's *Doing business in Puerto Rico — Business guide 2021* and
projects the MoneySweep base registry onto that denominator. The base registry
denominator was first frozen at commit `6ccd83fbb0ef7ad33d692cc36b27a94433500fcd`
(158 sources) and has since been **extended in place, by exactly 3 sources**
(161), to close the three route gaps this audit previously reported — see
"2026-09-12 update" below. This is a deliberate refresh of the frozen
denominator, not a new dated snapshot; unrelated live-registry growth since
`6ccd83f` (e.g. `hacienda_sut_ivu`, `census_gov_finances`, ...) is **not** folded
in here because none of it binds to a guide avenue.

The guide itself says that it does **not** cover the subject exhaustively and that
its laws are current only through 2020-12-31. Therefore a future
`GUIDE_BOUNDED_100_PERCENT=PASS` must never be promoted to `ALL_PR_FINANCE=PASS`.

Frozen guide manifestation (unchanged):

- local filename: `doing-business-in-puerto-rico-guide-2021(1).pdf`
- byte size: `764432`
- SHA-256: `f43f8ca103f4d709d012c82ada082c1b175a02467b82c6ad9125a9159bf7a5a8`
- canonical denominator: `registries/guide_financial_avenues_v1.yaml`
- avenue count: **30**

## 2026-09-12 update: the three route gaps are closed

The three scrapers staged in the (now-emptied)
`registries/source_registry_overlays/guide_financial_avenues_v1.yaml` overlay
were run live against their authoritative public endpoints and promoted into
`registries/source_registry.yaml`:

| `source_id` | Rows materialized | Endpoint |
|---|---:|---|
| `ocif_guide_financial_classes` | 997 | `https://concesionarios.ocif.pr.gov/es/License/Index` |
| `ocs_insurer_registry` | 761 (41 current insurers + 720 annual-report observations, 2010-2025) | `https://www.ocs.pr.gov/consumidores/aseguradores-del-pais` + `https://www.ocs.pr.gov/regulados/informes-anuales` |
| `ftz_board_pr` | 44 (3 zones + site rows) | `https://ofis.trade.gov/Zones/Details/{103,239,115}` |

**A materialization bug was found and fixed during this pass.** The live OCS
"Informes Anuales" page has no per-report `<a href>` markup; the CMS instead
renders the year/insurer/PDF-anchor triples only as inline `<script>`
JS object-literal assignments (`temp_array['anio'] = '...'`) for a client-side
widget. The prior `parse_annual_reports` implementation scanned visible anchor
tags with a nearby-year heading heuristic, which no longer matched anything on
the live page — it silently returned one spurious row (a site-wide navigation
PDF whose filename happened to contain a year token) instead of failing
closed. `scripts/scrape_ocs_insurers.py` was rewritten to extract the embedded
CMS records directly; it now correctly recovers all 720 real observations and
still raises if the embedded record pattern disappears again.

## Set algebra

The avenue-level algebra is explicitly a **guide-universe projection**:

- `A` = all 30 frozen guide avenues.
- `B_GUIDE_PROJECTION` = guide avenues with at least one explicit source route in
  the 161-source base registry denominator.

This avoids mixing source taxonomy with avenue identity.

| Set | Count | Meaning |
|---|---:|---|
| A | 30 | Frozen guide denominator |
| B_GUIDE_PROJECTION | 30 | Guide avenues represented by a base-registry route |
| INTERSECTION | 30 | Avenues represented in both |
| A_ONLY | 0 | No base-registry source route |
| B_ONLY | 0 | Zero by construction inside the guide projection |
| UNION | 30 | Full guide denominator |
| SYMMETRIC_DIFFERENCE | 0 | — |

`A_ONLY = {}` (previously `{GFAV-004 international_financial_entities, GFAV-005
insurance_companies, GFAV-020 foreign_trade_zones}`, now all `AUTHORITATIVE_ROUTE`).

At the **source** level, every base-registry source is retained rather than thrown
away: 21 of 161 source IDs have an explicit guide binding and the remaining **140
are B_ONLY sources relative to this guide**. `B_ONLY` here does not mean irrelevant
or low quality; it means the source covers MoneySweep material outside this
bounded 2021 guide taxonomy.

The executable audit is `scripts/audit_guide_financial_avenues.py`. It fails closed
unless the frozen base-source snapshot (`reports/guide_financial_avenue_source_audit_v1.csv`,
locked by count + SHA-256 in `registries/guide_financial_avenue_bindings_v1.yaml`)
and `reports/source_registry_status.csv` both account for exactly the same 161
unique source IDs, then emits one row per source and one row per guide avenue.

## Base route assessment

### Stronger existing routes

- **Commercial banking:** `fdic`, `fhlb`.
- **Capital markets:** `sec_edgar`, `sec_13f_nport`.
- **Economic Development Bank financing:** `bde_loans` (manual-export dependent).
- **Public-private partnerships:** `p3_authority` plus materialized
  `act_transition_ppp`. `docs/PPP_REGISTRY.md` currently records six known
  concessions as canonical; blocked PRASA document surfaces remain separate.
- **Qualified Opportunity Zones:** `opportunity_zones` plus DDEC/Act 60 support.
- **International financial entities:** `ocif_guide_financial_classes` — official
  OCIF concessionaire registry, filtered to the guide-relevant license classes
  (ENTIDAD FINANCIERA INTERNACIONAL, ENTIDAD BANCARIA INTERNACIONAL, FONDO DE
  CAPITAL PRIVADO LEY 185-2014, EXEMPT REPORTING ADVISORS, INVESTMENT ADVISOR).
- **Insurance companies:** `ocs_insurer_registry` — official OCS domestic-insurer
  current listing plus a 2010-2025 per-insurer annual-report index.
- **Foreign-trade zones:** `ftz_board_pr` — U.S. FTZ Board OFIS zone/site records
  for the frozen discovery denominator, Puerto Rico Zones 7, 61 and 163.

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

`ocif_guide_financial_classes` does **not** currently retain the OCIF
"INVESTMENT COMPANIES" license class (only "INVESTMENT ADVISOR" is scraped), so
it does not by itself close the registered investment-company denominator for
GFAV-007/011/013; those remain `proposed_overlay_bindings` in
`registries/guide_financial_avenue_bindings_v1.yaml` for a future pass.

## Remaining zero-residue blockers

| Residue | State | Closure requirement |
|---|---|---|
| OCIF new route | **CLOSED (2026-09-12)** | Live-materialized (997 rows); route bound as `AUTHORITATIVE_ROUTE` |
| OCS new route | **CLOSED (2026-09-12)** | Live-materialized (761 rows: 41 current + 720 annual, 2010-2025); route bound as `AUTHORITATIVE_ROUTE` |
| FTZ Board new route | **CLOSED (2026-09-12)** | Live-materialized (44 rows, exact 7/61/163 closure); route bound as `AUTHORITATIVE_ROUTE` |
| REIT denominator | UNRESOLVED | Authoritative Puerto Rico REIT election/registration denominator or explicit negative closure |
| Registered investment-company denominator | UNRESOLVED | Exact local statutory class/source binding; adviser/broker/fund categories must not be collapsed; OCIF's "INVESTMENT COMPANIES" class is not yet scraped |
| Act 60 incentive categories | OPEN | Authoritative beneficiary/decree materialization; exclude seed fallback; classify all 23 incentive-category lanes without omission |
| Existing source materialization | OPEN | Every guide-bound route needed for the claim must have a frozen manifestation, not merely registered code |
| Identity | OPEN | Stable IDs/authoritative bindings; no normalized-name-only promotion |
| Temporal | OPEN | Preserve report/effective/approval years and historical observations; no current/historical conflation |
| Provenance | OPEN | Freeze retrieval UTC, locator/query, raw bytes where obtainable, SHA-256, schema fingerprint and record count |
| Arithmetic | OPEN | Source/retained/excluded counts close; no unexplained loss, duplication or multiplication |

Closing the three route gaps resolves **route representation only** (now 30/30
for the guide projection). It does **not** by itself satisfy the frozen source
manifestation, identity, temporal, provenance, or arithmetic residue rows above,
which is why `GUIDE_BOUNDED_100_PERCENT` stays `OPEN`.

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
