"""
Full pipeline orchestrator — Puerto Rico Federal Contracts Data Pipeline (~65 steps).

Usage:
  python3 run_all.py                    # Run all steps
  python3 run_all.py --only-setup       # Steps 1-2 only (dirs + instructions)

Core pipeline flags:
  --skip-validation          Step 4   download validation
  --skip-normalize           Step 5   normalization
  --skip-coverage            Step 6   coverage validation
  --skip-dedup               Step 5.5 cross-file dedup + master build
  --skip-enrichment          Step 7   SAM.gov UEI enrichment
  --skip-entity-resolution   Step 8   top-100 vendor entity resolution
  --skip-dominance           Step 9   HHI / market share dominance
  --skip-graph               Step 10  network graph export
  --skip-grants              Step 11  USASpending federal grants
  --skip-subawards           Step 12  USASpending subawards
  --skip-fema                Step 13  FEMA PA + HMGP
  --skip-research            Step 14  NIH + NSF research grants
  --skip-bulk-downloads      Step 15  SBA / SLFRF / CDBG-DR / SBIR / DOE / DOT / USDA / HUD-CPD
  --skip-unified-master      Step 16  unified awards master
  --skip-fec                 Step 17  FEC Schedule A contributions
  --skip-lda                 Step 18  LDA lobbying filings
  --skip-lda-enrich          Step 18b LDA entity enrichment
  --skip-crossref            Step 19  FEC + lobbying crossref
  --skip-nonprofits          Step 20  IRS 990 nonprofits
  --skip-cms                 Step 21  CMS Open Payments + Medicare
  --skip-fdic                Step 22  FDIC bank data
  --skip-entity-profiles     Step 23  entity profiles crossref
  --skip-sec                 Step 24  SEC EDGAR financials
  --skip-power-network       Step 25  integrated power/influence network
  --skip-emma                Step 26  MSRB EMMA municipal bonds
  --skip-ofac                Step 27  OFAC SDN sanctions crossref
  --skip-opencorporates      Step 28  OpenCorporates PR registry
  --skip-prime-sub           Step 29  prime-to-sub relationships

Supplemental federal downloads (steps 6b–6j):
  --skip-sf133               Step 6b  SF-133 budget execution
  --skip-ed                  Step 6c  Dept of Education grants
  --skip-hhs                 Step 6d  HHS/HRSA/ACF grants
  --skip-doj-grants          Step 6e  DOJ grants
  --skip-oia                 Step 6f  Office of Insular Affairs grants
  --skip-haf                 Step 6g  Homeowner Assistance Fund
  --skip-exim                Step 6h  Ex-Im Bank
  --skip-earmarks            Step 6i  Congressional earmarks
  --skip-report-builder      Step 6j  FPDS Report Builder FY2018-2024

Step 15 sequential additions:
  --skip-fsrs                Step 15a FSRS prime-to-sub reporting
  --skip-cor3                Step 15b COR3 PR recovery project tracker
  --skip-compras             Step 15c comprashpr.com RFP/award scrape

FEMA PA financial backbone (steps 15d–15g):
  --skip-fema-pa-projects    Step 15d OpenFEMA PA v2 projects
  --skip-fema-pa-portal      Step 15e FEMA PA portal 178-PW ingest
  --skip-fema-pa-linkage     Step 15f FEMA PA PW → contracts/assets linkage
  --skip-fema-pa-validation  Step 15g FEMA PA coverage validation

HUD DRGR financial backbone (steps 15h–15n):
  --skip-drgr-public         Step 15h HUD DRGR public report download
  --skip-drgr-exports        Step 15i HUD DRGR authorized export ingest
  --skip-drgr-normalize      Step 15j normalize DRGR grants/projects/activities
  --skip-drgr-linkage        Step 15k DRGR responsible orgs → contracts
  --skip-drgr-assets         Step 15l DRGR activities → assets/municipalities
  --skip-drgr-validation     Step 15m DRGR coverage + entity-resolution report
  --skip-drgr-amounts        Step 15n DRGR budget/drawdown reconciliation

Financial flows master (step 15o):
  --skip-financial-flows     Step 15o build financial_flows_master.parquet

RFP-lobby crossref (step 17b):
  --skip-rfp-lobby           Step 17b RFP timing vs LDA lobbying

Municipal finance (step 25b):
  --skip-municipal           Step 25b PR municipal fiscal health

Bond market + PR-specific sources (steps 26b–26q):
  --skip-msrb-trades         Step 26b MSRB RTRS secondary market trades
  --skip-bond-flow           Step 26c bond flow entity crossref
  --skip-usace               Step 26d USACE Section 404/10 permits
  --skip-eqb                 Step 26e PR EQB / EPA ICIS permits
  --skip-nfip                Step 26f NFIP flood insurance claims
  --skip-lihtc               Step 26g LIHTC housing tax credit projects
  --skip-nmtc                Step 26h NMTC new markets tax credits
  --skip-act60               Step 26i PR Act 60 tax incentive decrees
  --skip-rum-coverover       Step 26j rum cover-over revenue
  --skip-fhlb                Step 26k FHLB advances to PR banks
  --skip-prepa               Step 26l PREPA/Luma/Genera contracts
  --skip-promesa             Step 26m PROMESA Title III creditors
  --skip-cabilderos          Step 26n PR cabilderos (state lobbyists)
  --skip-contralor           Step 26o PR Comptroller audit/contract data
  --skip-active-contractors  Step 26p PR active contractor registry
  --skip-prasa               Step 26q PRASA contracts

Project delivery + final report:
  --skip-delivery            Step 28b contractor delivery scorecard
  --skip-report              Step 30  generate PR investigation report
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path for all imports
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_pandas() -> bool:
    """Check pandas is installed. Print helpful message if not."""
    try:
        import pandas  # noqa: F401
        return True
    except ImportError:
        print("ERROR: pandas is not installed.")
        print("Run: pip install -r requirements.txt")
        return False


def setup_pipeline_logging(logs_dir: Path) -> logging.Logger:
    """Configure root pipeline logger: stdout + timestamped log file."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"pipeline_{timestamp}.log"

    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def print_banner(logger: logging.Logger) -> None:
    logger.info("=" * 70)
    logger.info("  Puerto Rico Federal Contracts Data Pipeline")
    logger.info("  Full Contract Data Acquisition & Staging Pipeline (2000-2025) + UEI Enrichment")
    logger.info("=" * 70)
    logger.info("")


def print_summary(
    logger: logging.Logger,
    elapsed: float,
    steps: dict,
    download_count: int,
    validation_result: int,
    normalize_count: int,
    coverage_result: int,
    root: Path,
    dedup_stats: dict = None,
    enrichment_result: str = None,
) -> int:
    """Print final pipeline summary (Section 10 success metrics). Returns exit code."""
    # Gather coverage info if available
    covered_years = "N/A"
    gap_2007 = "N/A"
    timeline = "N/A"

    try:
        from scripts.validate_expansion_coverage import build_coverage_matrix, COVERAGE_YEARS as CY

        matrix = build_coverage_matrix(root)
        if any(i["exists"] for i in matrix.values()):
            all_fy = set()
            for info in matrix.values():
                all_fy.update(info.get("fiscal_years", set()))
            covered = [y for y in CY if y in all_fy]
            missing = [y for y in CY if y not in all_fy]
            covered_years = f"{len(covered)}/26 years (2000-2025)"
            if missing:
                covered_years += f" — GAPS: {missing}"

            from scripts.validate_expansion_coverage import check_2007_gap
            gap_2007 = "OK" if check_2007_gap(matrix) else "CRITICAL: MISSING"

            gaps = []
            for i in range(len(CY) - 1):
                y, yn = CY[i], CY[i + 1]
                y_cov = y in all_fy
                yn_cov = yn in all_fy
                if y_cov and not yn_cov:
                    gaps.append(yn)
            timeline = "OK" if not gaps else f"GAPS: {gaps}"
    except Exception:
        pass

    # Determine overall status
    all_ok = (
        steps.get("dirs", False)
        and steps.get("instructions", False)
        and validation_result in (None, 0, 2)
        and (normalize_count is None or normalize_count > 0)
        and coverage_result in (None, 0)
    )

    partial = (
        steps.get("dirs", False)
        and steps.get("instructions", False)
        and not all_ok
    )

    status = "SUCCESS" if all_ok else ("PARTIAL" if partial else "FAILED")

    logger.info("")
    logger.info("=" * 70)
    logger.info("  PIPELINE SUMMARY")
    logger.info("=" * 70)
    logger.info(f"  Directories:           {'OK' if steps.get('dirs') else 'FAILED'}")
    logger.info(
        f"  Download instructions: {'OK — see data/staging/expansion/DOWNLOAD_INSTRUCTIONS.md' if steps.get('instructions') else 'FAILED'}"
    )

    if download_count is None:
        logger.info("  Auto-downloaded:       SKIPPED")
    else:
        logger.info(f"  Auto-downloaded:       {download_count}/13 files ready")

    if validation_result is None:
        logger.info("  Files validated:       SKIPPED")
    elif validation_result == 0:
        logger.info("  Files validated:       ALL PASS")
    elif validation_result == 2:
        logger.info("  Files validated:       PASS with warnings")
    else:
        logger.info("  Files validated:       FAIL — see data/logs/validation_report.log")

    if normalize_count is None:
        logger.info("  Files normalized:      SKIPPED")
    else:
        from scripts.config import DOWNLOAD_MANIFEST as DM
        logger.info(f"  Files normalized:      {normalize_count}/{len(DM)}")

    logger.info(f"  Year coverage:         {covered_years}")
    logger.info(f"  2007 gap status:       {gap_2007}")
    logger.info(f"  Timeline continuity:   {timeline}")
    logger.info(f"  Expected record range: ~5,000–15,000+ (from ~1,500 baseline)")

    if dedup_stats is not None:
        logger.info(
            f"  Master (deduped):      {dedup_stats.get('master_rows', 0):,} rows "
            f"({dedup_stats.get('duplicates_removed', 0):,} cross-file dupes removed)"
        )

    if enrichment_result is None:
        logger.info("  UEI enrichment:        SKIPPED")
    else:
        logger.info(f"  UEI enrichment:        {enrichment_result}")

    logger.info(f"  Pipeline status:       {status}")
    logger.info(f"  Elapsed time:          {elapsed:.1f}s")
    logger.info("=" * 70)

    return 0 if all_ok or partial else 1


def main() -> int:
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
    args = parser.parse_args()

    root = PROJECT_ROOT
    logs_dir = root / "data" / "logs"

    # Bootstrap: create logs dir before setting up logger
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_pipeline_logging(logs_dir)
    print_banner(logger)

    start_time = time.time()
    steps = {}
    download_count = None
    validation_result = None
    normalize_count = None
    coverage_result = None
    dedup_stats = None
    enrichment_result = None

    # ------------------------------------------------------------------
    # Dependency check
    # ------------------------------------------------------------------
    if not check_pandas():
        return 1

    from scripts.config import DOWNLOAD_MANIFEST, EXPANSION_DIR

    # ------------------------------------------------------------------
    # Step 1: Setup directories
    # ------------------------------------------------------------------
    logger.info("[Step 1/29] Setting up directories...")
    try:
        from scripts.setup_directories import main as setup_dirs
        setup_dirs(root)
        steps["dirs"] = True
        logger.info("[Step 1/29] Done.\n")
    except Exception as e:
        logger.error(f"[Step 1/29] FAILED: {e}")
        steps["dirs"] = False
        return 1

    # ------------------------------------------------------------------
    # Step 2: Generate download instructions
    # ------------------------------------------------------------------
    logger.info("[Step 2/29] Generating download instructions...")
    try:
        from scripts.download_instructions import main as gen_instructions
        gen_instructions(root)
        steps["instructions"] = True
        logger.info("[Step 2/29] Done.\n")
    except Exception as e:
        logger.error(f"[Step 2/29] FAILED: {e}")
        steps["instructions"] = False
        return 1

    if args.only_setup:
        logger.info("--only-setup flag set. Stopping after steps 1-2.")
        elapsed = time.time() - start_time
        return print_summary(logger, elapsed, steps, None, None, None, None, root,
                             dedup_stats=None, enrichment_result=None)

    # ------------------------------------------------------------------
    # Step 3: Auto-download datasets
    # ------------------------------------------------------------------
    skip_download = args.skip_download or args.manual_only
    if skip_download:
        logger.info("[Step 3/29] SKIPPED (--skip-download / --manual-only)\n")
    else:
        logger.info("[Step 3/29] Auto-downloading datasets...")
        try:
            from scripts.auto_download import download_all, print_download_summary
            dl_results = download_all(root, force=args.force_download)
            print_download_summary(dl_results, logger)
            download_count = sum(1 for r in dl_results if r["status"] in ("OK", "SKIPPED"))
            # Attempt HigherGov API fetch if HIGHERGOV_API_KEY is available (falls back to .env)
            try:
                import os as _os
                from scripts.config import _load_dotenv, PROJECT_ROOT as _root
                hg_key = _os.environ.get("HIGHERGOV_API_KEY", "").strip() or _load_dotenv(_root / ".env").get("HIGHERGOV_API_KEY", "").strip()
                if hg_key:
                    logger.info("[Step 3.1] HIGHERGOV_API_KEY found — fetching HigherGov exports...")
                    try:
                        from scripts.fetch_highergov_api import main as _fetch_hg
                        res = _fetch_hg()
                        if res == 0:
                            logger.info("[Step 3.1] HigherGov fetch completed successfully.")
                        else:
                            logger.warning(f"[Step 3.1] HigherGov fetch exited with code {res}.")
                    except Exception as e:
                        logger.error(f"[Step 3.1] HigherGov fetch failed: {e}")
                else:
                    logger.info("[Step 3.1] HIGHERGOV_API_KEY not set — skipping HigherGov fetch.")
            except Exception:
                logger.debug("Failed to run HigherGov fetch pre-check; continuing.")

            steps["download"] = True
            logger.info(f"[Step 3/29] Done ({download_count} files ready).\n")
        except ImportError:
            logger.warning("[Step 3/29] Auto-download unavailable (missing requests/lxml).")
            logger.warning("  Install: pip install requests lxml")
            logger.warning("  Or use --manual-only and download files manually.\n")
            steps["download"] = False
        except Exception as e:
            logger.error(f"[Step 3/29] FAILED: {e}")
            steps["download"] = False

    # ------------------------------------------------------------------
    # Step 4: Validate downloads
    # ------------------------------------------------------------------
    if args.skip_validation:
        logger.info("[Step 4/29] SKIPPED (--skip-validation)\n")
    else:
        logger.info("[Step 4/29] Validating downloaded files...")
        try:
            from scripts.validate_downloads import validate_all, print_report
            results = validate_all(root)
            print_report(results, logger)

            missing_files = [r for r in results if not r["exists"]]
            if missing_files:
                logger.info("")
                logger.info(
                    f"  {len(missing_files)} of {len(DOWNLOAD_MANIFEST)} files not yet downloaded."
                )
                logger.info(
                    "  For remaining files, see: data/staging/expansion/DOWNLOAD_INSTRUCTIONS.md"
                )
                logger.info("")
                validation_result = 1
            else:
                has_fail = any(r["status"] == "FAIL" for r in results)
                has_warn = any(r["status"] == "WARN" for r in results)
                validation_result = 1 if has_fail else (2 if has_warn else 0)

            logger.info(f"[Step 4/29] Done (exit: {validation_result}).\n")
        except Exception as e:
            logger.error(f"[Step 4/29] FAILED: {e}")
            validation_result = 1

    # ------------------------------------------------------------------
    # Step 4.1: FDIC Mapper (deterministic normalization)
    # ------------------------------------------------------------------
    if args.skip_normalize:
        logger.info("[Step 4.1/29] SKIPPED (--skip-normalize)\n")
    else:
        try:
            fdic_inst_path = (root / "data" / "staging" / "processed" / "pr_fdic_institutions.csv")
            fdic_fin_path = (root / "data" / "staging" / "processed" / "pr_fdic_financials.csv")
            
            fdic_mapped = 0
            if fdic_inst_path.exists():
                import pandas as pd
                from scripts.fdic_mapper import map_fdic_resource
                df = pd.read_csv(fdic_inst_path, low_memory=False)
                _, report = map_fdic_resource(df, "institutions")
                logger.info(f"[Step 4.1a] FDIC institutions: {report}")
                if report.get("threshold_met"):
                    fdic_mapped += 1
                else:
                    logger.warning(f"[Step 4.1a] FDIC institutions validation below threshold: {report.get('failed_dates')} {report.get('failed_amounts')}")
            
            if fdic_fin_path.exists():
                import pandas as pd
                from scripts.fdic_mapper import map_fdic_resource
                df = pd.read_csv(fdic_fin_path, low_memory=False)
                _, report = map_fdic_resource(df, "financials")
                logger.info(f"[Step 4.1b] FDIC financials: {report}")
                if report.get("threshold_met"):
                    fdic_mapped += 1
                else:
                    logger.warning(f"[Step 4.1b] FDIC financials validation below threshold: {report.get('failed_dates')} {report.get('failed_amounts')}")
            
            logger.info(f"[Step 4.1/29] Done ({fdic_mapped} FDIC datasets validated).\n")
        except Exception as e:
            logger.error(f"[Step 4.1/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 4.2: EMMA Mapper (deterministic normalization)
    # ------------------------------------------------------------------
    if args.skip_normalize:
        logger.info("[Step 4.2/29] SKIPPED (--skip-normalize)\n")
    else:
        try:
            emma_bonds_path = (root / "data" / "staging" / "processed" / "pr_emma_bonds.csv")
            emma_uw_path = (root / "data" / "staging" / "processed" / "pr_emma_underwriters.csv")
            
            emma_mapped = 0
            if emma_bonds_path.exists():
                import pandas as pd
                from scripts.emma_mapper import map_emma_resource
                df = pd.read_csv(emma_bonds_path)
                _, report = map_emma_resource(df, "bonds")
                logger.info(f"[Step 4.2a] EMMA bonds: {report}")
                if report.get("threshold_met"):
                    emma_mapped += 1
                else:
                    logger.warning(f"[Step 4.2a] EMMA bonds validation below threshold: {report.get('failed_dates')} {report.get('failed_amounts')}")
            
            if emma_uw_path.exists():
                import pandas as pd
                from scripts.emma_mapper import map_emma_resource
                df = pd.read_csv(emma_uw_path)
                _, report = map_emma_resource(df, "underwriters")
                logger.info(f"[Step 4.2b] EMMA underwriters: {report}")
                if report.get("threshold_met"):
                    emma_mapped += 1
                else:
                    logger.warning(f"[Step 4.2b] EMMA underwriters validation below threshold: {report.get('failed_dates')} {report.get('failed_amounts')}")
            
            logger.info(f"[Step 4.2/29] Done ({emma_mapped} EMMA datasets validated).\n")
        except Exception as e:
            logger.error(f"[Step 4.2/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 4.3: CMS Mapper (deterministic normalization)
    # ------------------------------------------------------------------
    if args.skip_normalize:
        logger.info("[Step 4.3/29] SKIPPED (--skip-normalize)\n")
    else:
        try:
            cms_op_path = (root / "data" / "staging" / "processed" / "pr_cms_open_payments.csv")
            cms_med_path = (root / "data" / "staging" / "processed" / "pr_cms_medicare_providers.csv")
            
            cms_mapped = 0
            if cms_op_path.exists():
                import pandas as pd
                from scripts.cms_mapper import map_cms_resource
                df = pd.read_csv(cms_op_path)
                _, report = map_cms_resource(df, "open_payments")
                logger.info(f"[Step 4.3a] CMS open_payments: {report}")
                if report.get("threshold_met"):
                    cms_mapped += 1
                else:
                    logger.warning(f"[Step 4.3a] CMS open_payments validation below threshold: {report.get('issues')}")
            
            if cms_med_path.exists():
                import pandas as pd
                from scripts.cms_mapper import map_cms_resource
                df = pd.read_csv(cms_med_path)
                _, report = map_cms_resource(df, "medicare")
                logger.info(f"[Step 4.3b] CMS medicare: {report}")
                if report.get("threshold_met"):
                    cms_mapped += 1
                else:
                    logger.warning(f"[Step 4.3b] CMS medicare validation below threshold: {report.get('issues')}")
            
            logger.info(f"[Step 4.3/29] Done ({cms_mapped} CMS datasets validated).\n")
        except Exception as e:
            logger.error(f"[Step 4.3/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 5: Normalize
    # ------------------------------------------------------------------
    if args.skip_normalize:
        logger.info("[Step 5/29] SKIPPED (--skip-normalize)\n")
    else:
        logger.info("[Step 5/29] Normalizing expansion inputs...")
        try:
            from scripts.normalize_expansion_inputs import normalize_all, print_report as norm_report
            results = normalize_all(root)
            norm_report(results, logger)
            normalize_count = sum(1 for r in results if r["status"] in ("OK", "WARN"))
            logger.info(f"[Step 5/29] Done ({normalize_count} files normalized).\n")
        except Exception as e:
            logger.error(f"[Step 5/29] FAILED: {e}")
            normalize_count = 0

    # ------------------------------------------------------------------
    # Step 5.5: Cross-file deduplication + master build
    # ------------------------------------------------------------------
    if args.skip_dedup:
        logger.info("[Step 5.5/29] SKIPPED (--skip-dedup)\n")
    else:
        logger.info("[Step 5.5/29] Building deduplicated master...")
        try:
            from scripts.deduplicate_master import main as build_master
            dedup_stats = build_master(root)
            if dedup_stats["master_rows"] > 0:
                logger.info(
                    f"[Step 5.5/29] Done — {dedup_stats['master_rows']:,} rows, "
                    f"{dedup_stats['duplicates_removed']:,} cross-file dupes removed.\n"
                )
            else:
                logger.info("[Step 5.5/29] Done (no normalized files found yet).\n")
        except Exception as e:
            logger.error(f"[Step 5.5/29] FAILED: {e}")
            dedup_stats = None

    # ------------------------------------------------------------------
    # Step 6: Validate coverage
    # ------------------------------------------------------------------
    if args.skip_coverage:
        logger.info("[Step 6/29] SKIPPED (--skip-coverage)\n")
    else:
        logger.info("[Step 6/29] Validating expansion coverage...")
        try:
            from scripts.validate_expansion_coverage import main as validate_coverage
            coverage_result = validate_coverage(root)
            logger.info(f"[Step 6/29] Done (exit: {coverage_result}).\n")
        except Exception as e:
            logger.error(f"[Step 6/29] FAILED: {e}")
            coverage_result = 1

    # ------------------------------------------------------------------
    # Step 6b: SF-133 budget execution data
    # ------------------------------------------------------------------
    if args.skip_sf133:
        logger.info("[Step 6b] SKIPPED (--skip-sf133)\n")
    else:
        logger.info("[Step 6b] Downloading SF-133 budget execution data...")
        try:
            from scripts.download_sf133 import run as run_sf133
            result = run_sf133(root=root)
            logger.info(f"[Step 6b] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6c: Department of Education grants
    # ------------------------------------------------------------------
    if args.skip_ed:
        logger.info("[Step 6c] SKIPPED (--skip-ed)\n")
    else:
        logger.info("[Step 6c] Downloading Dept of Education grants for PR...")
        try:
            from scripts.download_ed import run as run_ed
            result = run_ed(root=root)
            logger.info(f"[Step 6c] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6c] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6d: HHS / HRSA / ACF grants
    # ------------------------------------------------------------------
    if args.skip_hhs:
        logger.info("[Step 6d] SKIPPED (--skip-hhs)\n")
    else:
        logger.info("[Step 6d] Downloading HHS/HRSA/ACF grants for PR...")
        try:
            from scripts.download_hhs import run as run_hhs
            result = run_hhs(root=root)
            logger.info(f"[Step 6d] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6d] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6e: DOJ grants
    # ------------------------------------------------------------------
    if args.skip_doj_grants:
        logger.info("[Step 6e] SKIPPED (--skip-doj-grants)\n")
    else:
        logger.info("[Step 6e] Downloading DOJ grants for PR...")
        try:
            from scripts.download_doj_grants import run as run_doj_grants
            result = run_doj_grants(root=root)
            logger.info(f"[Step 6e] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6e] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6f: Office of Insular Affairs grants
    # ------------------------------------------------------------------
    if args.skip_oia:
        logger.info("[Step 6f] SKIPPED (--skip-oia)\n")
    else:
        logger.info("[Step 6f] Downloading OIA grants for PR...")
        try:
            from scripts.download_oia import run as run_oia
            result = run_oia(root=root)
            logger.info(f"[Step 6f] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6f] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6g: Homeowner Assistance Fund
    # ------------------------------------------------------------------
    if args.skip_haf:
        logger.info("[Step 6g] SKIPPED (--skip-haf)\n")
    else:
        logger.info("[Step 6g] Downloading Homeowner Assistance Fund data for PR...")
        try:
            from scripts.download_haf import run as run_haf
            result = run_haf(root=root)
            logger.info(f"[Step 6g] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6g] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6h: Ex-Im Bank
    # ------------------------------------------------------------------
    if args.skip_exim:
        logger.info("[Step 6h] SKIPPED (--skip-exim)\n")
    else:
        logger.info("[Step 6h] Downloading Ex-Im Bank loans/guarantees for PR...")
        try:
            from scripts.download_exim import run as run_exim
            result = run_exim(root=root)
            logger.info(f"[Step 6h] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6h] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6i: Congressional earmarks
    # ------------------------------------------------------------------
    if args.skip_earmarks:
        logger.info("[Step 6i] SKIPPED (--skip-earmarks)\n")
    else:
        logger.info("[Step 6i] Downloading congressional earmarks for PR...")
        try:
            from scripts.download_earmarks import run as run_earmarks
            result = run_earmarks(root=root)
            logger.info(f"[Step 6i] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6i] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6j: FPDS Report Builder ingestion (FY2018-2024)
    # ------------------------------------------------------------------
    if args.skip_report_builder:
        logger.info("[Step 6j] SKIPPED (--skip-report-builder)\n")
    else:
        logger.info("[Step 6j] Ingesting FPDS Report Builder files (FY2018-2024)...")
        try:
            from scripts.ingest_report_builder import run as run_report_builder
            result = run_report_builder(root=root)
            logger.info(f"[Step 6j] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6j] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6k: EPA grants for PR (USASpending)
    # ------------------------------------------------------------------
    if args.skip_epa:
        logger.info("[Step 6k] SKIPPED (--skip-epa)\n")
    else:
        logger.info("[Step 6k] Downloading EPA grants and cooperative agreements for PR...")
        try:
            from scripts.download_epa import run as run_epa
            result = run_epa(root=root)
            logger.info(f"[Step 6k] Done — {result.get('rows', result.get('master_rows', 0)):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6k] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6l: USACE civil works contracts for PR (USASpending)
    # ------------------------------------------------------------------
    if args.skip_usace_civil:
        logger.info("[Step 6l] SKIPPED (--skip-usace-civil)\n")
    else:
        logger.info("[Step 6l] Downloading USACE civil works contracts and grants for PR...")
        try:
            from scripts.download_usace_civil import run as run_usace_civil
            result = run_usace_civil(root=root)
            logger.info(f"[Step 6l] Done — {result.get('rows', result.get('master_rows', 0)):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6l] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6m: NIH research grants to PR (NIH Reporter API)
    # ------------------------------------------------------------------
    if args.skip_nih:
        logger.info("[Step 6m] SKIPPED (--skip-nih)\n")
    else:
        logger.info("[Step 6m] Downloading NIH research grants to PR institutions...")
        try:
            from scripts.download_nih import run as run_nih
            result = run_nih(root=root)
            logger.info(f"[Step 6m] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 6m] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 7: SAM.gov UEI enrichment
    # ------------------------------------------------------------------
    if args.skip_enrichment:
        logger.info("[Step 7/29] SKIPPED (--skip-enrichment)\n")
    else:
        import os as _os
        from scripts.config import _load_dotenv, PROJECT_ROOT as _root
        has_key = bool(
            _os.environ.get("SAM_API_KEY", "").strip()
            or _load_dotenv(_root / ".env").get("SAM_API_KEY", "").strip()
        )
        if not has_key:
            logger.info("[Step 7/29] SKIPPED — SAM_API_KEY not set.")
            logger.info("  Set via: export SAM_API_KEY=your_key  or create a .env file.\n")
            enrichment_result = "NO_KEY — skipped"
        elif dedup_stats is None or dedup_stats.get("master_rows", 0) == 0:
            logger.info("[Step 7/29] SKIPPED — no master data (download files first)\n")
            enrichment_result = "SKIPPED — no master data"
        else:
            logger.info("[Step 7/29] Running SAM.gov UEI enrichment...")
            try:
                from scripts.sam_enrichment import run as run_enrichment
                summary = run_enrichment(root=root)
                enrichment_result = (
                    f"{summary.get('vendors_resolved', 0)}/{summary.get('vendors_attempted', 0)} vendors resolved "
                    f"({summary.get('coverage_pct', 0):.1f}%) — "
                    f"{'PASS' if summary.get('coverage_gate_pass') else 'BELOW GATE'}"
                )
                logger.info(f"[Step 7/29] Done.\n")
            except Exception as e:
                logger.error(f"[Step 7/29] FAILED: {e}")
                enrichment_result = f"FAILED: {e}"

    # ------------------------------------------------------------------
    # Step 8: Entity resolution (top 100 vendors → parent entity)
    # ------------------------------------------------------------------
    master_ready = dedup_stats is not None and dedup_stats.get("master_rows", 0) > 0
    if args.skip_entity_resolution:
        logger.info("[Step 8/29] SKIPPED (--skip-entity-resolution)\n")
    elif not master_ready:
        logger.info("[Step 8/29] SKIPPED — no master data yet\n")
    else:
        logger.info("[Step 8/29] Resolving top 100 vendor entities...")
        try:
            from scripts.entity_resolution import run as run_entity
            run_entity(root=root)
            logger.info("[Step 8/29] Done.\n")
        except Exception as e:
            logger.error(f"[Step 8/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 9: Dominance analysis
    # ------------------------------------------------------------------
    if args.skip_dominance:
        logger.info("[Step 9/29] SKIPPED (--skip-dominance)\n")
    elif not master_ready:
        logger.info("[Step 9/29] SKIPPED — no master data yet\n")
    else:
        logger.info("[Step 9/29] Computing dominance metrics...")
        try:
            from scripts.dominance_analysis import run as run_dominance
            summary_d = run_dominance(root=root)
            logger.info(
                f"[Step 9/29] Done — top vendor: {summary_d.get('top_vendor', '?')}, "
                f"${summary_d.get('top_vendor_obligation', 0):,.0f}\n"
            )
        except Exception as e:
            logger.error(f"[Step 9/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 10: Network graph
    # ------------------------------------------------------------------
    if args.skip_graph:
        logger.info("[Step 10/29] SKIPPED (--skip-graph)\n")
    elif not master_ready:
        logger.info("[Step 10/29] SKIPPED — no master data yet\n")
    else:
        logger.info("[Step 10/29] Building network graph...")
        try:
            from scripts.network_graph import run as run_graph
            summary_g = run_graph(root=root)
            logger.info(
                f"[Step 10/29] Done — {summary_g.get('total_nodes', 0)} nodes, "
                f"{summary_g.get('total_edges', 0)} edges → network.graphml\n"
            )
        except ImportError:
            logger.info("[Step 10/29] SKIPPED — networkx not installed (pip install networkx)\n")
        except Exception as e:
            logger.error(f"[Step 10/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 11: Download grants
    # ------------------------------------------------------------------
    if args.skip_grants:
        logger.info("[Step 11/29] SKIPPED (--skip-grants)\n")
    else:
        logger.info("[Step 11/29] Downloading federal grants (USASpending)...")
        try:
            from scripts.download_grants import run as run_grants
            g = run_grants(root=root)
            logger.info(f"[Step 11/29] Done — {g.get('master_rows', g.get('total_rows', 0)):,} grant records\n")
        except Exception as e:
            logger.error(f"[Step 11/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 12: Download subawards
    # ------------------------------------------------------------------
    if args.skip_subawards:
        logger.info("[Step 12/29] SKIPPED (--skip-subawards)\n")
    else:
        logger.info("[Step 12/29] Downloading subawards (USASpending)...")
        try:
            from scripts.download_subawards import run as run_subawards
            s = run_subawards(root=root)
            logger.info(f"[Step 12/29] Done — {s.get('master_rows', s.get('total_rows', 0)):,} subaward records\n")
        except Exception as e:
            logger.error(f"[Step 12/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 13: Download FEMA data
    # ------------------------------------------------------------------
    if args.skip_fema:
        logger.info("[Step 13/29] SKIPPED (--skip-fema)\n")
    else:
        logger.info("[Step 13/29] Downloading FEMA Public Assistance + HMGP...")
        try:
            from scripts.download_fema import run as run_fema
            f = run_fema(root=root)
            logger.info(f"[Step 13/29] Done — PA: {f.get('pa_rows', 0):,}, HMGP: {f.get('hmgp_rows', 0):,}\n")
        except Exception as e:
            logger.error(f"[Step 13/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 14: Download research grants
    # ------------------------------------------------------------------
    if args.skip_research:
        logger.info("[Step 14/29] SKIPPED (--skip-research)\n")
    else:
        logger.info("[Step 14/29] Downloading NIH + NSF research grants...")
        try:
            from scripts.download_research import run as run_research
            r = run_research(root=root)
            logger.info(f"[Step 14/29] Done — NIH: {r.get('nih_rows', 0):,}, NSF: {r.get('nsf_rows', 0):,}\n")
        except Exception as e:
            logger.error(f"[Step 14/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15: Bulk downloads (SBA, SLFRF, CDBG-DR)
    # ------------------------------------------------------------------
    if args.skip_bulk_downloads:
        logger.info("[Step 15/29] SKIPPED (--skip-bulk-downloads)\n")
    else:
        logger.info("[Step 15/29] Downloading SBA loans, SLFRF, CDBG-DR, SBIR, DOE, DOT, USDA, HUD-CPD...")
        for name, mod in [
            ("SBA",     "download_sba"),
            ("SLFRF",   "download_slfrf"),
            ("CDBG-DR", "download_cdbg_dr"),
            ("SBIR",    "download_sbir"),
            ("DOE",     "download_doe"),
            ("DOT",     "download_dot"),
            ("USDA",    "download_usda"),
            ("HUD-CPD", "download_hud"),
        ]:
            try:
                import importlib
                m = importlib.import_module(f"scripts.{mod}")
                result = m.run(root=root)
                logger.info(f"  {name}: {result.get('rows', result.get('total_rows', 0)):,} rows")
            except Exception as e:
                logger.error(f"  {name} FAILED: {e}")
        logger.info("[Step 15/29] Done.\n")

    # ------------------------------------------------------------------
    # Step 15a: FSRS prime-to-sub reporting
    # ------------------------------------------------------------------
    if args.skip_fsrs:
        logger.info("[Step 15a] SKIPPED (--skip-fsrs)\n")
    else:
        logger.info("[Step 15a] Downloading FSRS prime-to-sub reporting data...")
        try:
            from scripts.download_fsrs import run as run_fsrs
            result = run_fsrs(root=root)
            logger.info(f"[Step 15a] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 15a] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15b: COR3 PR recovery project tracker
    # ------------------------------------------------------------------
    if args.skip_cor3:
        logger.info("[Step 15b] SKIPPED (--skip-cor3)\n")
    else:
        logger.info("[Step 15b] Downloading COR3 PR recovery project data...")
        try:
            from scripts.download_cor3 import run as run_cor3
            result = run_cor3(root=root)
            logger.info(f"[Step 15b] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 15b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15c: PR Compras RFP/award scrape
    # ------------------------------------------------------------------
    if args.skip_compras:
        logger.info("[Step 15c] SKIPPED (--skip-compras)\n")
    else:
        logger.info("[Step 15c] Scraping comprashpr.com RFPs and contract awards...")
        try:
            from scripts.download_compras import run as run_compras
            result = run_compras(root=root)
            logger.info(f"[Step 15c] Done — {result.get('rows', result.get('award_rows', 0)):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 15c] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15d: OpenFEMA PA v2 projects for PR
    # ------------------------------------------------------------------
    if args.skip_fema_pa_projects:
        logger.info("[Step 15d] SKIPPED (--skip-fema-pa-projects)\n")
    else:
        logger.info("[Step 15d] Downloading OpenFEMA PA v2 project records for PR...")
        try:
            from scripts.download_openfema_pa_projects import run as run_fema_pa_proj
            result = run_fema_pa_proj(root=root)
            logger.info(f"[Step 15d] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 15d] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15e: FEMA PA portal 178-PW export ingest
    # ------------------------------------------------------------------
    if args.skip_fema_pa_portal:
        logger.info("[Step 15e] SKIPPED (--skip-fema-pa-portal)\n")
    else:
        logger.info("[Step 15e] Ingesting FEMA PA portal 178-PW authorized export...")
        try:
            from scripts.ingest_fema_pa_portal_exports import run as run_fema_pa_portal
            result = run_fema_pa_portal(root=root)
            logger.info(f"[Step 15e] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 15e] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15f: Link FEMA PA PWs to contracts/assets
    # ------------------------------------------------------------------
    if args.skip_fema_pa_linkage:
        logger.info("[Step 15f] SKIPPED (--skip-fema-pa-linkage)\n")
    else:
        logger.info("[Step 15f] Linking FEMA PA project worksheets to contracts and assets...")
        try:
            from scripts.link_fema_pa_to_contracts import run as run_fema_pa_link
            result = run_fema_pa_link(root=root)
            logger.info(f"[Step 15f] Done — {result.get('linkage_rows', 0):,} linkage rows\n")
        except Exception as e:
            logger.error(f"[Step 15f] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15g: Validate FEMA PA coverage
    # ------------------------------------------------------------------
    if args.skip_fema_pa_validation:
        logger.info("[Step 15g] SKIPPED (--skip-fema-pa-validation)\n")
    else:
        logger.info("[Step 15g] Validating FEMA PA coverage and v1/v2 diff...")
        try:
            from scripts.validate_fema_pa_coverage import run as run_fema_pa_val
            result = run_fema_pa_val(root=root)
            logger.info(f"[Step 15g] Done — status: {result.get('status', '?')}\n")
        except Exception as e:
            logger.error(f"[Step 15g] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15h: HUD DRGR public financial report download
    # ------------------------------------------------------------------
    if args.skip_drgr_public:
        logger.info("[Step 15h] SKIPPED (--skip-drgr-public)\n")
    else:
        logger.info("[Step 15h] Downloading HUD DRGR public financial reports...")
        try:
            from scripts.download_hud_drgr_public import run as run_drgr_pub
            result = run_drgr_pub(root=root)
            logger.info(f"[Step 15h] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 15h] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15i: HUD DRGR authorized local export ingest
    # ------------------------------------------------------------------
    if args.skip_drgr_exports:
        logger.info("[Step 15i] SKIPPED (--skip-drgr-exports)\n")
    else:
        logger.info("[Step 15i] Ingesting authorized HUD DRGR local export files...")
        try:
            from scripts.ingest_hud_drgr_exports import run as run_drgr_ingest
            result = run_drgr_ingest(root=root)
            logger.info(f"[Step 15i] Done — {result.get('activity_rows', result.get('rows', 0)):,} activity rows\n")
        except Exception as e:
            logger.error(f"[Step 15i] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15j: Normalize HUD DRGR grants/projects/activities
    # ------------------------------------------------------------------
    if args.skip_drgr_normalize:
        logger.info("[Step 15j] SKIPPED (--skip-drgr-normalize)\n")
    else:
        logger.info("[Step 15j] Normalizing HUD DRGR grants, projects, and activities...")
        try:
            from scripts.normalize_hud_drgr import run as run_drgr_norm
            result = run_drgr_norm(root=root)
            logger.info(f"[Step 15j] Done — {result.get('project_rows', 0):,} projects, {result.get('org_rows', 0):,} orgs\n")
        except Exception as e:
            logger.error(f"[Step 15j] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15k: Link DRGR responsible orgs to contracts
    # ------------------------------------------------------------------
    if args.skip_drgr_linkage:
        logger.info("[Step 15k] SKIPPED (--skip-drgr-linkage)\n")
    else:
        logger.info("[Step 15k] Linking HUD DRGR responsible orgs to contract entities...")
        try:
            from scripts.link_hud_drgr_to_contracts import run as run_drgr_link
            result = run_drgr_link(root=root)
            logger.info(f"[Step 15k] Done — {result.get('linkage_rows', 0):,} linkage rows\n")
        except Exception as e:
            logger.error(f"[Step 15k] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15l: Link DRGR activities to assets/municipalities
    # ------------------------------------------------------------------
    if args.skip_drgr_assets:
        logger.info("[Step 15l] SKIPPED (--skip-drgr-assets)\n")
    else:
        logger.info("[Step 15l] Linking HUD DRGR activities to physical assets and municipalities...")
        try:
            from scripts.link_hud_drgr_to_assets import run as run_drgr_assets
            result = run_drgr_assets(root=root)
            logger.info(f"[Step 15l] Done — {result.get('linkage_rows', 0):,} rows, "
                        f"{result.get('municipalities_matched', 0):,} municipalities\n")
        except Exception as e:
            logger.error(f"[Step 15l] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15m: HUD DRGR coverage and entity-resolution report
    # ------------------------------------------------------------------
    if args.skip_drgr_validation:
        logger.info("[Step 15m] SKIPPED (--skip-drgr-validation)\n")
    else:
        logger.info("[Step 15m] Running HUD DRGR coverage and entity-resolution validation...")
        try:
            from scripts.validate_hud_drgr_coverage import run as run_drgr_cov
            result = run_drgr_cov(root=root)
            logger.info(f"[Step 15m] Done — status: {result.get('status', '?')}\n")
        except Exception as e:
            logger.error(f"[Step 15m] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15n: HUD DRGR budget/drawdown/obligation reconciliation
    # ------------------------------------------------------------------
    if args.skip_drgr_amounts:
        logger.info("[Step 15n] SKIPPED (--skip-drgr-amounts)\n")
    else:
        logger.info("[Step 15n] Reconciling HUD DRGR budget, drawdown, and obligation amounts...")
        try:
            from scripts.validate_hud_drgr_amounts import run as run_drgr_amts
            result = run_drgr_amts(root=root)
            logger.info(f"[Step 15n] Done — status: {result.get('status', '?')}\n")
        except Exception as e:
            logger.error(f"[Step 15n] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15o: Build financial flows master
    # ------------------------------------------------------------------
    if args.skip_financial_flows:
        logger.info("[Step 15o] SKIPPED (--skip-financial-flows)\n")
    else:
        logger.info("[Step 15o] Building financial flows master (FEMA + HUD + procurement)...")
        try:
            from scripts.build_financial_flows_master import run as run_fin_flows
            result = run_fin_flows(root=root)
            logger.info(f"[Step 15o] Done — {result.get('rows', 0):,} flow records\n")
        except Exception as e:
            logger.error(f"[Step 15o] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 16: Build unified master
    # ------------------------------------------------------------------
    if args.skip_unified_master:
        logger.info("[Step 16/29] SKIPPED (--skip-unified-master)\n")
    else:
        logger.info("[Step 16/29] Building unified awards master (all datasets)...")
        try:
            from scripts.build_unified_master import run as run_unified
            u = run_unified(root=root)
            logger.info(
                f"[Step 16/29] Done — {u.get('total_rows', 0):,} total rows across "
                f"{len(u.get('by_dataset', {}))} datasets → pr_all_awards_master.csv\n"
            )
        except Exception as e:
            logger.error(f"[Step 16/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 17: Download FEC contributions
    # ------------------------------------------------------------------
    if args.skip_fec:
        logger.info("[Step 17/29] SKIPPED (--skip-fec)\n")
    else:
        logger.info("[Step 17/29] Downloading FEC Schedule A contributions from PR...")
        try:
            from scripts.download_fec import run as run_fec
            fec_result = run_fec(root=root, api_key=args.fec_api_key)
            logger.info(f"[Step 17/29] Done — {fec_result.get('rows', 0):,} contribution records\n")
        except Exception as e:
            logger.error(f"[Step 17/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 17b: Analyze RFP timing vs LDA lobbying
    # ------------------------------------------------------------------
    if args.skip_rfp_lobby:
        logger.info("[Step 17b] SKIPPED (--skip-rfp-lobby)\n")
    else:
        logger.info("[Step 17b] Analyzing PR procurement RFP timing vs LDA lobbying...")
        try:
            from scripts.analyze_rfp_lobby import run as run_rfp_lobby
            result = run_rfp_lobby(root=root)
            logger.info(f"[Step 17b] Done — {result.get('rows', 0):,} RFP-lobby crossref rows\n")
        except Exception as e:
            logger.error(f"[Step 17b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 18: Download LDA lobbying filings
    # ------------------------------------------------------------------
    if args.skip_lda:
        logger.info("[Step 18/29] SKIPPED (--skip-lda)\n")
    else:
        logger.info("[Step 18/29] Downloading LDA lobbying filings for PR...")
        try:
            from scripts.download_lda import run as run_lda
            lda_result = run_lda(root=root, api_key=args.lda_api_key)
            logger.info(f"[Step 18/29] Done — {lda_result.get('rows', 0):,} filings\n")
        except Exception as e:
            logger.error(f"[Step 18/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 18b: LDA entity enrichment (award recipients → lobbying lookup)
    # ------------------------------------------------------------------
    if args.skip_lda_enrich:
        logger.info("[Step 18b/29] SKIPPED (--skip-lda-enrich)\n")
    else:
        logger.info("[Step 18b/29] Enriching award recipients with LDA lobbying data...")
        try:
            from scripts.lda_enrich import run as run_lda_enrich
            enrich_result = run_lda_enrich(root=root, api_key=args.lda_api_key)
            logger.info(
                f"[Step 18b/29] Done — {enrich_result.get('entities_queried', 0):,} queried, "
                f"{enrich_result.get('entities_matched', 0):,} with LDA filings, "
                f"${enrich_result.get('total_spend', 0):,.0f} lobbying spend\n"
            )
        except Exception as e:
            logger.error(f"[Step 18b/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 19: Cross-reference analyses (FEC + lobbying)
    # ------------------------------------------------------------------
    if args.skip_crossref:
        logger.info("[Step 19/29] SKIPPED (--skip-crossref)\n")
    else:
        logger.info("[Step 19/29] Running FEC and lobbying cross-reference analyses...")
        for label, mod, fn in [
            ("FEC crossref",      "analyze_fec_crossref",      "build_crossref"),
            ("Lobbying crossref", "analyze_lobbying_crossref", "build_crossref"),
        ]:
            try:
                import importlib
                m  = importlib.import_module(f"scripts.{mod}")
                cr = getattr(m, fn)(root=root)
                logger.info(f"  {label}: {cr.get('rows', 0):,} matched entities")
            except Exception as e:
                logger.error(f"  {label} FAILED: {e}")
        logger.info("[Step 19/29] Done.\n")

    # ------------------------------------------------------------------
    # Step 20: IRS 990 nonprofits via ProPublica
    # ------------------------------------------------------------------
    if args.skip_nonprofits:
        logger.info("[Step 20/29] SKIPPED (--skip-nonprofits)\n")
    else:
        logger.info("[Step 20/29] Downloading IRS 990 nonprofit data for PR...")
        try:
            from scripts.download_nonprofits import run as run_nonprofits
            np_result = run_nonprofits(root=root)
            logger.info(f"[Step 20/29] Done — {np_result.get('rows', 0):,} nonprofits\n")
        except Exception as e:
            logger.error(f"[Step 20/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21: CMS Open Payments + Medicare provider data
    # ------------------------------------------------------------------
    if args.skip_cms:
        logger.info("[Step 21/29] SKIPPED (--skip-cms)\n")
    else:
        logger.info("[Step 21/29] Downloading CMS Open Payments and Medicare data for PR...")
        try:
            from scripts.download_cms import run as run_cms
            cms_result = run_cms(root=root)
            logger.info(
                f"[Step 21/29] Done — Open Payments: {cms_result.get('open_payments_rows', 0):,}, "
                f"Medicare: {cms_result.get('medicare_rows', 0):,}\n"
            )
        except Exception as e:
            logger.error(f"[Step 21/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21b: Medicaid FMAP rates + CMS-64 PR expenditure
    # ------------------------------------------------------------------
    if args.skip_medicaid_fmap:
        logger.info("[Step 21b] SKIPPED (--skip-medicaid-fmap)\n")
    else:
        logger.info("[Step 21b] Downloading Medicaid FMAP rates and PR CMS-64 expenditure data...")
        try:
            from scripts.download_medicaid_fmap import run as run_medicaid_fmap
            result = run_medicaid_fmap(root=root)
            logger.info(f"[Step 21b] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 21b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21c: SSA OASDI/SSI/SSDI benefit data
    # ------------------------------------------------------------------
    if args.skip_ssa:
        logger.info("[Step 21c] SKIPPED (--skip-ssa)\n")
    else:
        logger.info("[Step 21c] Downloading SSA OASDI/SSI/SSDI benefit data for PR...")
        try:
            from scripts.download_ssa import run as run_ssa
            result = run_ssa(root=root)
            logger.info(f"[Step 21c] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 21c] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21d: Medicare Part A + Part D
    # ------------------------------------------------------------------
    if args.skip_medicare_parts:
        logger.info("[Step 21d] SKIPPED (--skip-medicare-parts)\n")
    else:
        logger.info("[Step 21d] Downloading Medicare Part A and Part D data for PR...")
        try:
            from scripts.download_medicare_parts import run as run_medicare_parts
            result = run_medicare_parts(root=root)
            logger.info(f"[Step 21d] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 21d] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21e: VA benefits + VAMC contracts
    # ------------------------------------------------------------------
    if args.skip_va:
        logger.info("[Step 21e] SKIPPED (--skip-va)\n")
    else:
        logger.info("[Step 21e] Downloading VA benefit payments and VAMC contract data for PR...")
        try:
            from scripts.download_va import run as run_va
            result = run_va(root=root)
            logger.info(f"[Step 21e] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 21e] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21f: USDA FNS NAP nutrition assistance block grant
    # ------------------------------------------------------------------
    if args.skip_snap_nap:
        logger.info("[Step 21f] SKIPPED (--skip-snap-nap)\n")
    else:
        logger.info("[Step 21f] Downloading USDA FNS NAP nutrition assistance data for PR...")
        try:
            from scripts.download_snap_nap import run as run_snap_nap
            result = run_snap_nap(root=root)
            logger.info(f"[Step 21f] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 21f] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 22: FDIC bank data
    # ------------------------------------------------------------------
    if args.skip_fdic:
        logger.info("[Step 22/29] SKIPPED (--skip-fdic)\n")
    else:
        logger.info("[Step 22/29] Downloading FDIC bank institution and financial data for PR...")
        try:
            from scripts.download_fdic import run as run_fdic
            fdic_result = run_fdic(root=root)
            logger.info(
                f"[Step 22/29] Done — {fdic_result.get('institution_rows', 0):,} institutions, "
                f"{fdic_result.get('financial_rows', 0):,} financial rows\n"
            )
        except Exception as e:
            logger.error(f"[Step 22/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 23: Entity profiles cross-reference
    # ------------------------------------------------------------------
    if args.skip_entity_profiles:
        logger.info("[Step 23/29] SKIPPED (--skip-entity-profiles)\n")
    else:
        logger.info("[Step 23/29] Building enriched entity profiles...")
        try:
            from scripts.analyze_entity_profiles import build_profiles
            ep_result = build_profiles(root=root)
            logger.info(
                f"[Step 23/29] Done — {ep_result.get('rows', 0):,} entities profiled, "
                f"{ep_result.get('np_matched', 0):,} nonprofits, "
                f"{ep_result.get('med_matched', 0):,} Medicare providers, "
                f"{ep_result.get('bank_matched', 0):,} banks\n"
            )
        except Exception as e:
            logger.error(f"[Step 23/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 24: SEC EDGAR PR-significant company financials
    # ------------------------------------------------------------------
    if args.skip_sec:
        logger.info("[Step 24/29] SKIPPED (--skip-sec)\n")
    else:
        logger.info("[Step 24/29] Downloading SEC EDGAR data for PR-significant companies...")
        try:
            from scripts.download_sec import run as run_sec
            sec_result = run_sec(root=root)
            logger.info(
                f"[Step 24/29] Done — {sec_result.get('company_rows', 0):,} companies, "
                f"{sec_result.get('financial_rows', 0):,} annual financial rows\n"
            )
        except Exception as e:
            logger.error(f"[Step 24/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 25: Integrated power network analysis
    # ------------------------------------------------------------------
    if args.skip_power_network:
        logger.info("[Step 25/29] SKIPPED (--skip-power-network)\n")
    else:
        logger.info("[Step 25/29] Building integrated PR power/influence network...")
        try:
            from scripts.analyze_power_network import build_power_network
            pn_result = build_power_network(root=root)
            logger.info(
                f"[Step 25/29] Done — {pn_result.get('rows', 0):,} entities ranked, "
                f"{pn_result.get('full_loop', 0):,} full-loop entities "
                f"(awards + FEC + lobbying)\n"
            )
        except Exception as e:
            logger.error(f"[Step 25/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 25b: PR municipal fiscal health data
    # ------------------------------------------------------------------
    if args.skip_municipal:
        logger.info("[Step 25b] SKIPPED (--skip-municipal)\n")
    else:
        logger.info("[Step 25b] Downloading PR municipal fiscal health data...")
        try:
            from scripts.download_municipal import run as run_municipal
            result = run_municipal(root=root)
            logger.info(f"[Step 25b] Done — {result.get('rows', 0):,} municipality rows\n")
        except Exception as e:
            logger.error(f"[Step 25b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 25c: AAFAF PR government budget execution
    # ------------------------------------------------------------------
    if args.skip_aafaf:
        logger.info("[Step 25c] SKIPPED (--skip-aafaf)\n")
    else:
        logger.info("[Step 25c] Downloading AAFAF PR government budget execution data...")
        try:
            from scripts.download_aafaf import run as run_aafaf
            result = run_aafaf(root=root)
            logger.info(f"[Step 25c] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 25c] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 25d: PR pension funds (ERS, TRS, JRS)
    # ------------------------------------------------------------------
    if args.skip_pr_pensions:
        logger.info("[Step 25d] SKIPPED (--skip-pr-pensions)\n")
    else:
        logger.info("[Step 25d] Downloading PR pension fund data (ERS/TRS/JRS)...")
        try:
            from scripts.download_pr_pensions import run as run_pr_pensions
            result = run_pr_pensions(root=root)
            logger.info(f"[Step 25d] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 25d] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26: MSRB EMMA municipal bond data
    # ------------------------------------------------------------------
    if args.skip_emma:
        logger.info("[Step 26/29] SKIPPED (--skip-emma)\n")
    else:
        logger.info("[Step 26/29] Downloading PR municipal bond data from MSRB EMMA...")
        try:
            from scripts.download_emma import run as run_emma
            emma_result = run_emma(root=root)
            logger.info(
                f"[Step 26/29] Done — {emma_result.get('bond_rows', 0):,} bonds, "
                f"{emma_result.get('underwriter_rows', 0):,} underwriters, "
                f"${emma_result.get('total_par', 0):,.0f} total par\n"
            )
        except Exception as e:
            logger.error(f"[Step 26/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26b: MSRB RTRS secondary market trade data
    # ------------------------------------------------------------------
    if args.skip_msrb_trades:
        logger.info("[Step 26b] SKIPPED (--skip-msrb-trades)\n")
    else:
        logger.info("[Step 26b] Downloading MSRB RTRS secondary market trade data for PR CUSIPs...")
        try:
            from scripts.download_msrb_trades import run as run_msrb_trades
            result = run_msrb_trades(root=root)
            logger.info(f"[Step 26b] Done — {result.get('rows', 0):,} trade records\n")
        except Exception as e:
            logger.error(f"[Step 26b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26c: Bond flow crossref (underwriters/dealers vs entity master)
    # ------------------------------------------------------------------
    if args.skip_bond_flow:
        logger.info("[Step 26c] SKIPPED (--skip-bond-flow)\n")
    else:
        logger.info("[Step 26c] Analyzing bond flow: underwriters and dealers vs entity master...")
        try:
            from scripts.analyze_bond_flow import run as run_bond_flow
            result = run_bond_flow(root=root)
            logger.info(f"[Step 26c] Done — {result.get('rows', 0):,} entities, "
                        f"{result.get('dual_role', 0):,} dual-role (bond + federal)\n")
        except Exception as e:
            logger.error(f"[Step 26c] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26d: USACE Section 404/10 permit data
    # ------------------------------------------------------------------
    if args.skip_usace:
        logger.info("[Step 26d] SKIPPED (--skip-usace)\n")
    else:
        logger.info("[Step 26d] Downloading USACE Section 404/10 permit data for PR...")
        try:
            from scripts.download_usace_permits import run as run_usace
            result = run_usace(root=root)
            logger.info(f"[Step 26d] Done — {result.get('rows', 0):,} permits\n")
        except Exception as e:
            logger.error(f"[Step 26d] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26e: PR EQB / EPA ICIS environmental permits
    # ------------------------------------------------------------------
    if args.skip_eqb:
        logger.info("[Step 26e] SKIPPED (--skip-eqb)\n")
    else:
        logger.info("[Step 26e] Downloading PR EQB / EPA ICIS environmental permit data...")
        try:
            from scripts.download_eqb import run as run_eqb
            result = run_eqb(root=root)
            logger.info(f"[Step 26e] Done — {result.get('rows', 0):,} permit records\n")
        except Exception as e:
            logger.error(f"[Step 26e] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26f: NFIP flood insurance claims
    # ------------------------------------------------------------------
    if args.skip_nfip:
        logger.info("[Step 26f] SKIPPED (--skip-nfip)\n")
    else:
        logger.info("[Step 26f] Downloading NFIP flood insurance claims for PR...")
        try:
            from scripts.download_nfip import run as run_nfip
            result = run_nfip(root=root)
            logger.info(f"[Step 26f] Done — {result.get('rows', 0):,} claims\n")
        except Exception as e:
            logger.error(f"[Step 26f] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26g: LIHTC low-income housing tax credit projects
    # ------------------------------------------------------------------
    if args.skip_lihtc:
        logger.info("[Step 26g] SKIPPED (--skip-lihtc)\n")
    else:
        logger.info("[Step 26g] Downloading LIHTC low-income housing tax credit data for PR...")
        try:
            from scripts.download_lihtc import run as run_lihtc
            result = run_lihtc(root=root)
            logger.info(f"[Step 26g] Done — {result.get('rows', 0):,} LIHTC projects\n")
        except Exception as e:
            logger.error(f"[Step 26g] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26h: NMTC new markets tax credit allocations
    # ------------------------------------------------------------------
    if args.skip_nmtc:
        logger.info("[Step 26h] SKIPPED (--skip-nmtc)\n")
    else:
        logger.info("[Step 26h] Downloading NMTC new markets tax credit allocations for PR...")
        try:
            from scripts.download_nmtc import run as run_nmtc
            result = run_nmtc(root=root)
            logger.info(f"[Step 26h] Done — {result.get('rows', 0):,} NMTC allocations\n")
        except Exception as e:
            logger.error(f"[Step 26h] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26i: PR Act 60 tax incentive decrees
    # ------------------------------------------------------------------
    if args.skip_act60:
        logger.info("[Step 26i] SKIPPED (--skip-act60)\n")
    else:
        logger.info("[Step 26i] Downloading PR Act 60 tax incentive decree data...")
        try:
            from scripts.download_act60 import run as run_act60
            result = run_act60(root=root)
            logger.info(f"[Step 26i] Done — {result.get('rows', 0):,} decrees\n")
        except Exception as e:
            logger.error(f"[Step 26i] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26j: Rum cover-over excise tax revenue
    # ------------------------------------------------------------------
    if args.skip_rum_coverover:
        logger.info("[Step 26j] SKIPPED (--skip-rum-coverover)\n")
    else:
        logger.info("[Step 26j] Downloading rum cover-over excise tax revenue data...")
        try:
            from scripts.download_rum_coverover import run as run_rum
            result = run_rum(root=root)
            logger.info(f"[Step 26j] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26j] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26k: FHLB advances to PR banks
    # ------------------------------------------------------------------
    if args.skip_fhlb:
        logger.info("[Step 26k] SKIPPED (--skip-fhlb)\n")
    else:
        logger.info("[Step 26k] Downloading FHLB advances to PR financial institutions...")
        try:
            from scripts.download_fhlb import run as run_fhlb
            result = run_fhlb(root=root)
            logger.info(f"[Step 26k] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26k] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26l: PREPA / Luma / Genera contract data
    # ------------------------------------------------------------------
    if args.skip_prepa:
        logger.info("[Step 26l] SKIPPED (--skip-prepa)\n")
    else:
        logger.info("[Step 26l] Downloading PREPA/Luma/Genera contract data...")
        try:
            from scripts.download_prepa_contracts import run as run_prepa
            result = run_prepa(root=root)
            logger.info(f"[Step 26l] Done — {result.get('rows', 0):,} contracts\n")
        except Exception as e:
            logger.error(f"[Step 26l] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26m: PROMESA Title III creditor data
    # ------------------------------------------------------------------
    if args.skip_promesa:
        logger.info("[Step 26m] SKIPPED (--skip-promesa)\n")
    else:
        logger.info("[Step 26m] Downloading PROMESA Title III creditor and recovery data...")
        try:
            from scripts.download_promesa_creditors import run as run_promesa
            result = run_promesa(root=root)
            logger.info(f"[Step 26m] Done — {result.get('rows', 0):,} creditor records\n")
        except Exception as e:
            logger.error(f"[Step 26m] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26n: PR cabilderos (state lobbyist registry) — ingest-first/fetch-fallback
    # ------------------------------------------------------------------
    if args.skip_cabilderos:
        logger.info("[Step 26n] SKIPPED (--skip-cabilderos)\n")
    else:
        logger.info("[Step 26n] Loading PR cabilderos (state lobbyist registry)...")
        _cab_result = {"rows": 0}
        try:
            from scripts.ingest_cabilderos import run as run_ingest_cab
            _cab_result = run_ingest_cab(root=root)
        except Exception as e:
            logger.warning(f"[Step 26n] ingest_cabilderos failed: {e}")
        if _cab_result.get("rows", 0) == 0:
            try:
                from scripts.download_cabilderos import run as run_fetch_cab
                _cab_result = run_fetch_cab(root=root)
            except Exception as e:
                logger.error(f"[Step 26n] download_cabilderos FAILED: {e}")
        logger.info(f"[Step 26n] Done — {_cab_result.get('rows', 0):,} cabildero records\n")

    # ------------------------------------------------------------------
    # Step 26o: PR Contralor audit/contract data — ingest-first/fetch-fallback
    # ------------------------------------------------------------------
    if args.skip_contralor:
        logger.info("[Step 26o] SKIPPED (--skip-contralor)\n")
    else:
        logger.info("[Step 26o] Loading PR Comptroller audit and contract data...")
        _con_result = {"rows": 0}
        try:
            from scripts.ingest_contralor import run as run_ingest_con
            _con_result = run_ingest_con(root=root)
        except Exception as e:
            logger.warning(f"[Step 26o] ingest_contralor failed: {e}")
        if _con_result.get("rows", 0) == 0:
            try:
                from scripts.download_contralor import run as run_fetch_con
                _con_result = run_fetch_con(root=root)
            except Exception as e:
                logger.error(f"[Step 26o] download_contralor FAILED: {e}")
        logger.info(f"[Step 26o] Done — {_con_result.get('rows', 0):,} audit/contract records\n")

    # ------------------------------------------------------------------
    # Step 26p: PR active contractor registry — ingest-first/fetch-fallback
    # ------------------------------------------------------------------
    if args.skip_active_contractors:
        logger.info("[Step 26p] SKIPPED (--skip-active-contractors)\n")
    else:
        logger.info("[Step 26p] Loading PR active contractor registry...")
        _ac_result = {"rows": 0}
        try:
            from scripts.ingest_active_contractors import run as run_ingest_ac
            _ac_result = run_ingest_ac(root=root)
        except Exception as e:
            logger.warning(f"[Step 26p] ingest_active_contractors failed: {e}")
        if _ac_result.get("rows", 0) == 0:
            try:
                from scripts.download_active_contractors import run as run_fetch_ac
                _ac_result = run_fetch_ac(root=root)
            except Exception as e:
                logger.error(f"[Step 26p] download_active_contractors FAILED: {e}")
        logger.info(f"[Step 26p] Done — {_ac_result.get('rows', 0):,} contractor records\n")

    # ------------------------------------------------------------------
    # Step 26q: PRASA contracts — ingest-first/fetch-fallback
    # ------------------------------------------------------------------
    if args.skip_prasa:
        logger.info("[Step 26q] SKIPPED (--skip-prasa)\n")
    else:
        logger.info("[Step 26q] Loading PRASA aqueduct/sewer authority contract data...")
        _prasa_result = {"rows": 0}
        try:
            from scripts.ingest_prasa import run as run_ingest_prasa
            _prasa_result = run_ingest_prasa(root=root)
        except Exception as e:
            logger.warning(f"[Step 26q] ingest_prasa failed: {e}")
        if _prasa_result.get("rows", 0) == 0:
            try:
                from scripts.download_prasa import run as run_fetch_prasa
                _prasa_result = run_fetch_prasa(root=root)
            except Exception as e:
                logger.error(f"[Step 26q] download_prasa FAILED: {e}")
        logger.info(f"[Step 26q] Done — {_prasa_result.get('rows', 0):,} PRASA contract records\n")

    # ------------------------------------------------------------------
    # Step 26r: FCC USF broadband / E-Rate / Rural Health Care subsidies
    # ------------------------------------------------------------------
    if args.skip_fcc:
        logger.info("[Step 26r] SKIPPED (--skip-fcc)\n")
    else:
        logger.info("[Step 26r] Downloading FCC USF (E-Rate, Rural Health Care, High Cost) data for PR...")
        try:
            from scripts.download_fcc import run as run_fcc
            result = run_fcc(root=root)
            logger.info(f"[Step 26r] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26r] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26s: DOL WHD + OSHA enforcement data
    # ------------------------------------------------------------------
    if args.skip_dol:
        logger.info("[Step 26s] SKIPPED (--skip-dol)\n")
    else:
        logger.info("[Step 26s] Downloading DOL wage-hour and OSHA enforcement data for PR...")
        try:
            from scripts.download_dol import run as run_dol
            result = run_dol(root=root)
            logger.info(f"[Step 26s] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26s] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26t: SEC 13F / N-PORT PR bond holdings
    # ------------------------------------------------------------------
    if args.skip_sec_holdings:
        logger.info("[Step 26t] SKIPPED (--skip-sec-holdings)\n")
    else:
        logger.info("[Step 26t] Downloading SEC 13F/N-PORT institutional PR bond holdings...")
        try:
            from scripts.download_sec_holdings import run as run_sec_holdings
            result = run_sec_holdings(root=root)
            logger.info(f"[Step 26t] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26t] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26u: GAO + HUD/FEMA/HHS IG audit reports covering PR
    # ------------------------------------------------------------------
    if args.skip_gao_ig:
        logger.info("[Step 26u] SKIPPED (--skip-gao-ig)\n")
    else:
        logger.info("[Step 26u] Downloading GAO and Inspector General audit reports covering PR...")
        try:
            from scripts.download_gao_ig import run as run_gao_ig
            result = run_gao_ig(root=root)
            logger.info(f"[Step 26u] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26u] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26v: PR P3 Authority public-private partnership contracts
    # ------------------------------------------------------------------
    if args.skip_p3:
        logger.info("[Step 26v] SKIPPED (--skip-p3)\n")
    else:
        logger.info("[Step 26v] Downloading PR P3 Authority public-private partnership contracts...")
        try:
            from scripts.download_p3 import run as run_p3
            result = run_p3(root=root)
            logger.info(f"[Step 26v] Done — {result.get('rows', 0):,} rows\n")
        except Exception as e:
            logger.error(f"[Step 26v] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 27: OFAC SDN sanctions crossref
    # ------------------------------------------------------------------
    if args.skip_ofac:
        logger.info("[Step 27/29] SKIPPED (--skip-ofac)\n")
    else:
        logger.info("[Step 27/29] Downloading OFAC SDN list and crossreffing against awards...")
        try:
            from scripts.download_ofac import run as run_ofac
            ofac_result = run_ofac(root=root)
            logger.info(
                f"[Step 27/29] Done — {ofac_result.get('sdn_rows', 0):,} SDN entries, "
                f"{ofac_result.get('match_rows', 0):,} awards master matches\n"
            )
        except Exception as e:
            logger.error(f"[Step 27/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 28: OpenCorporates PR business registry
    # ------------------------------------------------------------------
    if args.skip_opencorporates:
        logger.info("[Step 28/29] SKIPPED (--skip-opencorporates)\n")
    else:
        logger.info("[Step 28/29] Downloading PR business entities from OpenCorporates...")
        try:
            from scripts.download_opencorporates import run as run_oc
            oc_result = run_oc(root=root, api_token=args.oc_api_token)
            logger.info(
                f"[Step 28/29] Done — {oc_result.get('company_rows', 0):,} companies, "
                f"{oc_result.get('officer_rows', 0):,} officer records\n"
            )
        except Exception as e:
            logger.error(f"[Step 28/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 28b: Contractor project delivery scorecard
    # ------------------------------------------------------------------
    if args.skip_delivery:
        logger.info("[Step 28b] SKIPPED (--skip-delivery)\n")
    else:
        logger.info("[Step 28b] Building contractor project delivery scorecard...")
        try:
            from scripts.analyze_project_delivery import run as run_delivery
            result = run_delivery(root=root)
            logger.info(f"[Step 28b] Done — {result.get('rows', 0):,} entities scored\n")
        except Exception as e:
            logger.error(f"[Step 28b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 29: Prime-to-subcontractor relationship analysis
    # ------------------------------------------------------------------
    if args.skip_prime_sub:
        logger.info("[Step 29/29] SKIPPED (--skip-prime-sub)\n")
    else:
        logger.info("[Step 29/29] Analyzing prime-to-subcontractor relationships...")
        try:
            from scripts.analyze_prime_sub import build_prime_sub
            ps_result = build_prime_sub(root=root)
            logger.info(
                f"[Step 29/29] Done — {ps_result.get('rows', 0):,} prime-sub pairs, "
                f"{ps_result.get('prime_count', 0):,} primes, "
                f"{ps_result.get('sub_count', 0):,} subs, "
                f"${ps_result.get('total_flow', 0):,.0f} total flow\n"
            )
        except Exception as e:
            logger.error(f"[Step 29/29] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 30: Generate PR investigation report
    # ------------------------------------------------------------------
    if args.skip_report:
        logger.info("[Step 30] SKIPPED (--skip-report)\n")
    else:
        logger.info("[Step 30] Generating PR investigation report...")
        try:
            from scripts.generate_report import run as run_report
            result = run_report(root=root)
            logger.info(f"[Step 30] Done — report written to {result.get('path', 'data/output/')}\n")
        except Exception as e:
            logger.error(f"[Step 30] FAILED: {e}")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    elapsed = time.time() - start_time
    return print_summary(
        logger, elapsed, steps, download_count, validation_result,
        normalize_count, coverage_result, root,
        dedup_stats=dedup_stats, enrichment_result=enrichment_result,
    )


if __name__ == "__main__":
    sys.exit(main())
