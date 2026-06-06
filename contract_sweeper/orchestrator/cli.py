"""Command-line interface for the pipeline orchestrator (extracted from run_all.py).

`build_arg_parser()` is a verbatim move of run_all.main()'s argparse block so the
flag surface is identical; run_all.py calls it and then parse_args().
"""
from __future__ import annotations

import argparse


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Puerto Rico Federal Contracts Data Pipeline"
    )
    parser.add_argument(
        "--only-setup",
        action="store_true",
        help="Run only steps 1-2 (create dirs + generate instructions), then exit",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip step 3 (auto-download)",
    )
    parser.add_argument(
        "--manual-only",
        action="store_true",
        help="Alias for --skip-download",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download even if files already exist",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip step 4 (download validation)",
    )
    parser.add_argument(
        "--skip-normalize",
        action="store_true",
        help="Skip step 5 (normalization)",
    )
    parser.add_argument(
        "--skip-coverage",
        action="store_true",
        help="Skip step 6 (coverage validation)",
    )
    parser.add_argument(
        "--skip-dedup",
        action="store_true",
        help="Skip step 5.5 (cross-file deduplication and master build)",
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip step 7 (SAM.gov UEI enrichment)",
    )
    parser.add_argument(
        "--skip-entity-resolution",
        action="store_true",
        help="Skip step 8 (entity resolution — top 100 vendors → parent entity)",
    )
    parser.add_argument(
        "--skip-dominance",
        action="store_true",
        help="Skip step 9 (dominance analysis — HHI, market share, trends)",
    )
    parser.add_argument(
        "--skip-graph",
        action="store_true",
        help="Skip step 10 (network graph — vendor-agency GraphML export)",
    )
    parser.add_argument("--skip-grants", action="store_true",
                        help="Skip step 11 (download federal grants from USASpending)")
    parser.add_argument("--skip-subawards", action="store_true",
                        help="Skip step 12 (download subawards from USASpending)")
    parser.add_argument("--skip-fema", action="store_true",
                        help="Skip step 13 (download FEMA Public Assistance + HMGP)")
    parser.add_argument("--skip-research", action="store_true",
                        help="Skip step 14 (download NIH + NSF research grants)")
    parser.add_argument("--skip-bulk-downloads", action="store_true",
                        help="Skip step 15 (download SBA loans, SLFRF, CDBG-DR, SBIR)")
    parser.add_argument("--skip-unified-master", action="store_true",
                        help="Skip step 16 (build unified awards master across all datasets)")
    parser.add_argument("--skip-fec", action="store_true",
                        help="Skip step 17 (download FEC Schedule A contributions from PR)")
    parser.add_argument("--skip-lda", action="store_true",
                        help="Skip step 18 (download LDA lobbying filings for PR)")
    parser.add_argument("--skip-lda-enrich", action="store_true",
                        help="Skip step 18b (LDA enrichment of award recipients by client name)")
    parser.add_argument("--skip-crossref", action="store_true",
                        help="Skip step 19 (FEC + lobbying cross-reference analyses)")
    parser.add_argument("--lda-api-key", dest="lda_api_key", default=None,
                        help="LDA API token (default: LDA_API_KEY env var)")
    parser.add_argument("--fec-api-key", dest="fec_api_key", default=None,
                        help="FEC API key (default: FEC_API_KEY env var or DEMO_KEY)")
    parser.add_argument("--skip-nonprofits", action="store_true",
                        help="Skip step 20 (IRS 990 nonprofit data via ProPublica)")
    parser.add_argument("--skip-cms", action="store_true",
                        help="Skip step 21 (CMS Open Payments + Medicare provider data)")
    parser.add_argument("--skip-fdic", action="store_true",
                        help="Skip step 22 (FDIC bank institution and financial data)")
    parser.add_argument("--skip-entity-profiles", action="store_true",
                        help="Skip step 23 (entity profiles cross-reference)")
    parser.add_argument("--skip-sec", action="store_true",
                        help="Skip step 24 (SEC EDGAR PR-significant company financials)")
    parser.add_argument("--skip-power-network", action="store_true",
                        help="Skip step 25 (integrated influence/power network analysis)")
    parser.add_argument("--skip-emma", action="store_true",
                        help="Skip step 26 (MSRB EMMA Puerto Rico municipal bond data)")
    parser.add_argument("--skip-ofac", action="store_true",
                        help="Skip step 27 (OFAC SDN sanctions list crossref)")
    parser.add_argument("--skip-opencorporates", action="store_true",
                        help="Skip step 28 (OpenCorporates PR business registry)")
    parser.add_argument("--skip-prime-sub", action="store_true",
                        help="Skip step 29 (prime-to-subcontractor relationship analysis)")
    parser.add_argument("--oc-api-token", dest="oc_api_token", default=None,
                        help="OpenCorporates API token (default: OPENCORPORATES_API_TOKEN env var)")
    # Insertion A — supplemental federal downloads + Report Builder
    parser.add_argument("--skip-sf133", action="store_true",
                        help="Skip step 6b (SF-133 budget execution data)")
    parser.add_argument("--skip-ed", action="store_true",
                        help="Skip step 6c (Dept of Education grants)")
    parser.add_argument("--skip-hhs", action="store_true",
                        help="Skip step 6d (HHS/HRSA/ACF grants)")
    parser.add_argument("--skip-doj-grants", action="store_true",
                        help="Skip step 6e (DOJ grants)")
    parser.add_argument("--skip-oia", action="store_true",
                        help="Skip step 6f (Office of Insular Affairs grants)")
    parser.add_argument("--skip-haf", action="store_true",
                        help="Skip step 6g (Homeowner Assistance Fund)")
    parser.add_argument("--skip-exim", action="store_true",
                        help="Skip step 6h (Ex-Im Bank loans/guarantees)")
    parser.add_argument("--skip-earmarks", action="store_true",
                        help="Skip step 6i (Congressional earmarks)")
    parser.add_argument("--skip-report-builder", action="store_true",
                        help="Skip step 6j (FPDS Report Builder FY2018-2024 ingestion)")
    # Insertion B — step 15 sequential additions
    parser.add_argument("--skip-fsrs", action="store_true",
                        help="Skip step 15a (FSRS prime-to-sub reporting)")
    parser.add_argument("--skip-cor3", action="store_true",
                        help="Skip step 15b (COR3 PR recovery project tracker)")
    parser.add_argument("--skip-compras", action="store_true",
                        help="Skip step 15c (comprashpr.com RFP/award scrape)")
    # Insertion C — FEMA PA backbone + HUD DRGR backbone + financial flows
    parser.add_argument("--skip-fema-pa-projects", action="store_true",
                        help="Skip step 15d (OpenFEMA PA v2 projects for PR)")
    parser.add_argument("--skip-fema-pa-portal", action="store_true",
                        help="Skip step 15e (FEMA PA portal 178-PW export ingest)")
    parser.add_argument("--skip-fema-pa-linkage", action="store_true",
                        help="Skip step 15f (link FEMA PA PWs to contracts/assets)")
    parser.add_argument("--skip-fema-pa-validation", action="store_true",
                        help="Skip step 15g (validate FEMA PA coverage + v1/v2 diff)")
    parser.add_argument("--skip-drgr-public", action="store_true",
                        help="Skip step 15h (HUD DRGR public financial report download)")
    parser.add_argument("--skip-drgr-exports", action="store_true",
                        help="Skip step 15i (HUD DRGR authorized local export ingest)")
    parser.add_argument("--skip-drgr-normalize", action="store_true",
                        help="Skip step 15j (normalize HUD DRGR grants/projects/activities)")
    parser.add_argument("--skip-drgr-linkage", action="store_true",
                        help="Skip step 15k (link DRGR responsible orgs to contracts)")
    parser.add_argument("--skip-drgr-assets", action="store_true",
                        help="Skip step 15l (link DRGR activities to assets/municipalities)")
    parser.add_argument("--skip-drgr-validation", action="store_true",
                        help="Skip step 15m (HUD DRGR coverage and entity-resolution report)")
    parser.add_argument("--skip-drgr-amounts", action="store_true",
                        help="Skip step 15n (HUD DRGR budget/drawdown/obligation reconciliation)")
    parser.add_argument("--skip-financial-flows", action="store_true",
                        help="Skip step 15o (build financial flows master parquet)")
    # Insertion D — RFP-lobby crossref
    parser.add_argument("--skip-rfp-lobby", action="store_true",
                        help="Skip step 17b (analyze RFP timing vs LDA lobbying)")
    # Insertion E — PR municipal finance
    parser.add_argument("--skip-municipal", action="store_true",
                        help="Skip step 25b (PR municipal fiscal health data)")
    # Insertion F — bond market + PR-specific sources
    parser.add_argument("--skip-msrb-trades", action="store_true",
                        help="Skip step 26b (MSRB RTRS secondary market trade data)")
    parser.add_argument("--skip-bond-flow", action="store_true",
                        help="Skip step 26c (bond flow: underwriters/dealers vs entity crossref)")
    parser.add_argument("--skip-usace", action="store_true",
                        help="Skip step 26d (USACE Section 404/10 permit data)")
    parser.add_argument("--skip-eqb", action="store_true",
                        help="Skip step 26e (PR EQB / EPA ICIS environmental permits)")
    parser.add_argument("--skip-nfip", action="store_true",
                        help="Skip step 26f (NFIP flood insurance claims for PR)")
    parser.add_argument("--skip-lihtc", action="store_true",
                        help="Skip step 26g (LIHTC low-income housing tax credit projects)")
    parser.add_argument("--skip-nmtc", action="store_true",
                        help="Skip step 26h (NMTC new markets tax credit allocations)")
    parser.add_argument("--skip-act60", action="store_true",
                        help="Skip step 26i (PR Act 60 tax incentive decrees)")
    parser.add_argument("--skip-rum-coverover", action="store_true",
                        help="Skip step 26j (rum cover-over excise tax revenue)")
    parser.add_argument("--skip-fhlb", action="store_true",
                        help="Skip step 26k (FHLB advances to PR banks)")
    parser.add_argument("--skip-prepa", action="store_true",
                        help="Skip step 26l (PREPA/Luma/Genera contract data)")
    parser.add_argument("--skip-promesa", action="store_true",
                        help="Skip step 26m (PROMESA Title III creditor data)")
    parser.add_argument("--skip-cabilderos", action="store_true",
                        help="Skip step 26n (PR state lobbyist registry — cabilderos)")
    parser.add_argument("--skip-contralor", action="store_true",
                        help="Skip step 26o (PR Comptroller audit/contract data)")
    parser.add_argument("--skip-active-contractors", action="store_true",
                        help="Skip step 26p (PR active contractor registry)")
    parser.add_argument("--skip-prasa", action="store_true",
                        help="Skip step 26q (PRASA aqueduct/sewer authority contracts)")
    # Insertion G — project delivery scorecard
    parser.add_argument("--skip-delivery", action="store_true",
                        help="Skip step 28b (contractor project delivery scorecard)")
    # Insertion H — final report
    parser.add_argument("--skip-report", action="store_true",
                        help="Skip step 30 (generate PR investigation report)")
    # Tier 1 — federal entitlements + PR government financials
    parser.add_argument("--skip-medicaid-fmap", action="store_true",
                        help="Skip step 21b (Medicaid FMAP rates + CMS-64 PR expenditure)")
    parser.add_argument("--skip-ssa", action="store_true",
                        help="Skip step 21c (SSA OASDI/SSI/SSDI benefit data for PR)")
    parser.add_argument("--skip-medicare-parts", action="store_true",
                        help="Skip step 21d (Medicare Part A + Part D for PR)")
    parser.add_argument("--skip-va", action="store_true",
                        help="Skip step 21e (VA benefits + VAMC contracts for PR)")
    parser.add_argument("--skip-snap-nap", action="store_true",
                        help="Skip step 21f (USDA FNS NAP nutrition assistance block grant)")
    parser.add_argument("--skip-aafaf", action="store_true",
                        help="Skip step 25c (AAFAF PR government budget execution)")
    parser.add_argument("--skip-pr-pensions", action="store_true",
                        help="Skip step 25d (PR pension funds ERS/TRS/JRS)")
    # Tier 2 — Federal agency gaps + enforcement + compliance
    parser.add_argument("--skip-epa", action="store_true",
                        help="Skip step 6k (EPA grants for PR via USASpending)")
    parser.add_argument("--skip-usace-civil", action="store_true",
                        help="Skip step 6l (USACE civil works contracts for PR)")
    parser.add_argument("--skip-nih", action="store_true",
                        help="Skip step 6m (NIH research grants via NIH Reporter API)")
    parser.add_argument("--skip-fcc", action="store_true",
                        help="Skip step 26r (FCC USF E-Rate/broadband/rural-health subsidies)")
    parser.add_argument("--skip-dol", action="store_true",
                        help="Skip step 26s (DOL WHD + OSHA enforcement data for PR)")
    parser.add_argument("--skip-sec-holdings", action="store_true",
                        help="Skip step 26t (SEC 13F/N-PORT PR bond holdings)")
    parser.add_argument("--skip-gao-ig", action="store_true",
                        help="Skip step 26u (GAO + HUD/FEMA/HHS IG audit reports)")
    parser.add_argument("--skip-p3", action="store_true",
                        help="Skip step 26v (PR P3 Authority public-private partnership contracts)")
    # Tier 3 — Remaining coverage gaps
    parser.add_argument("--skip-medicare-advantage", action="store_true",
                        help="Skip step 21g (CMS Medicare Advantage plan payments for PR)")
    parser.add_argument("--skip-chip", action="store_true",
                        help="Skip step 21h (CMS CHIP children's health insurance for PR)")
    parser.add_argument("--skip-wic", action="store_true",
                        help="Skip step 21i (USDA WIC women/infants/children nutrition for PR)")
    parser.add_argument("--skip-wioa", action="store_true",
                        help="Skip step 21j (DOL WIOA workforce development grants for PR)")
    parser.add_argument("--skip-hud-hcv", action="store_true",
                        help="Skip step 21k (HUD Section 8 / Housing Choice Voucher for PR)")
    parser.add_argument("--skip-ncua", action="store_true",
                        help="Skip step 22b (NCUA credit union call report data for PR)")
    parser.add_argument("--skip-hacienda", action="store_true",
                        help="Skip step 25e (PR Hacienda monthly tax revenues)")
    parser.add_argument("--skip-cofina", action="store_true",
                        help="Skip step 25f (COFINA SUT revenue bond allocation)")
    parser.add_argument("--strict-preflight", action="store_true",
                        help="Abort before the pipeline if the readiness preflight "
                             "finds structural errors (missing keys never abort)")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip the registry readiness preflight")
    return parser
