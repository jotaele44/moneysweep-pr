"""
Full pipeline orchestrator — Puerto Rico Federal Contracts Data Pipeline.

Usage:
  python3 run_all.py                    # Run all steps
  python3 run_all.py --only-setup       # Steps 1-2 only (dirs + instructions)
  python3 run_all.py --skip-validation
  python3 run_all.py --skip-normalize
  python3 run_all.py --skip-coverage
  python3 run_all.py --skip-enrichment
  python3 run_all.py --skip-entity-resolution
  python3 run_all.py --skip-dominance
  python3 run_all.py --skip-graph
  python3 run_all.py --skip-grants
  python3 run_all.py --skip-subawards
  python3 run_all.py --skip-fema
  python3 run_all.py --skip-research
  python3 run_all.py --skip-bulk-downloads
  python3 run_all.py --skip-unified-master
  python3 run_all.py --skip-fec
  python3 run_all.py --skip-lda
  python3 run_all.py --skip-crossref
  python3 run_all.py --skip-nonprofits
  python3 run_all.py --skip-cms
  python3 run_all.py --skip-fdic
  python3 run_all.py --skip-entity-profiles
  python3 run_all.py --skip-sec
  python3 run_all.py --skip-power-network
  python3 run_all.py --skip-emma
  python3 run_all.py --skip-ofac
  python3 run_all.py --skip-opencorporates
  python3 run_all.py --skip-prime-sub
  python3 run_all.py --skip-sf133
  python3 run_all.py --skip-cor3
  python3 run_all.py --skip-compras
  python3 run_all.py --skip-rfp-lobby
  python3 run_all.py --skip-municipal
  python3 run_all.py --skip-usace
  python3 run_all.py --skip-eqb
  python3 run_all.py --skip-msrb-trades
  python3 run_all.py --skip-bond-flow
  python3 run_all.py --skip-delivery
  python3 run_all.py --skip-report
  python3 run_all.py --skip-ed
  python3 run_all.py --skip-hhs
  python3 run_all.py --skip-doj-grants
  python3 run_all.py --skip-oia
  python3 run_all.py --skip-haf
  python3 run_all.py --skip-exim
  python3 run_all.py --skip-earmarks
  python3 run_all.py --skip-nfip
  python3 run_all.py --skip-lihtc
  python3 run_all.py --skip-nmtc
  python3 run_all.py --skip-act60
  python3 run_all.py --skip-rum-coverover
  python3 run_all.py --skip-fhlb
  python3 run_all.py --skip-prepa
  python3 run_all.py --skip-promesa
  python3 run_all.py --skip-report-builder
  python3 run_all.py --skip-cabilderos
  python3 run_all.py --skip-contralor
  python3 run_all.py --skip-active-contractors
  python3 run_all.py --skip-prasa
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
    parser.add_argument("--skip-sf133", action="store_true",
                        help="Skip step 6b (SF-133 federal budget execution from USASpending)")
    parser.add_argument("--skip-cor3", action="store_true",
                        help="Skip step 15b (COR3 PR recovery project tracker)")
    parser.add_argument("--skip-compras", action="store_true",
                        help="Skip step 15c (Compras PR procurement RFPs and awards)")
    parser.add_argument("--skip-rfp-lobby", action="store_true",
                        help="Skip step 18c (RFP × LDA lobbying cross-reference)")
    parser.add_argument("--skip-municipal", action="store_true",
                        help="Skip step 25b (PR municipal federal spending by geography)")
    parser.add_argument("--skip-usace", action="store_true",
                        help="Skip step 26b (USACE Section 404/10 permit data for PR)")
    parser.add_argument("--skip-eqb", action="store_true",
                        help="Skip step 26c (PR EQB environmental permit data via EPA ECHO)")
    parser.add_argument("--skip-msrb-trades", action="store_true",
                        help="Skip step 26d (MSRB RTRS secondary market trade data for PR CUSIPs)")
    parser.add_argument("--skip-bond-flow", action="store_true",
                        help="Skip step 26e (bond flow cross-reference: underwriters/dealers vs entity_master)")
    parser.add_argument("--skip-delivery", action="store_true",
                        help="Skip step 29b (contractor project delivery scorecard)")
    parser.add_argument("--skip-report", action="store_true",
                        help="Skip step 30 (generate investigative report from all outputs)")
    parser.add_argument("--skip-ed", action="store_true",
                        help="Skip step 6c (Department of Education grants)")
    parser.add_argument("--skip-hhs", action="store_true",
                        help="Skip step 6d (HHS HRSA + ACF grants)")
    parser.add_argument("--skip-doj-grants", action="store_true",
                        help="Skip step 6e (Department of Justice grants)")
    parser.add_argument("--skip-oia", action="store_true",
                        help="Skip step 6f (Office of Insular Affairs grants)")
    parser.add_argument("--skip-haf", action="store_true",
                        help="Skip step 6g (Homeowner Assistance Fund)")
    parser.add_argument("--skip-exim", action="store_true",
                        help="Skip step 6h (Ex-Im Bank loans)")
    parser.add_argument("--skip-earmarks", action="store_true",
                        help="Skip step 6i (congressional earmarks)")
    parser.add_argument("--skip-nfip", action="store_true",
                        help="Skip step 26f (NFIP flood insurance claims)")
    parser.add_argument("--skip-lihtc", action="store_true",
                        help="Skip step 26g (LIHTC low-income housing tax credits)")
    parser.add_argument("--skip-nmtc", action="store_true",
                        help="Skip step 26h (NMTC new markets tax credits)")
    parser.add_argument("--skip-act60", action="store_true",
                        help="Skip step 26i (PR Act 60 tax incentive decrees)")
    parser.add_argument("--skip-rum-coverover", action="store_true",
                        help="Skip step 26j (PR Rum Cover-Over federal excise tax transfers)")
    parser.add_argument("--skip-fhlb", action="store_true",
                        help="Skip step 26k (FHLB advances to PR member banks)")
    parser.add_argument("--skip-prepa", action="store_true",
                        help="Skip step 26l (PREPA / Luma / Genera major contracts)")
    parser.add_argument("--skip-promesa", action="store_true",
                        help="Skip step 26m (PROMESA Title III creditor data)")
    parser.add_argument("--skip-report-builder", action="store_true",
                        help="Skip step 6j (ingest FPDS Report Builder Excel files FY2018-FY2024)")
    parser.add_argument("--skip-cabilderos", action="store_true",
                        help="Skip step 26n (ingest PR Cabilderos state lobbyist registry)")
    parser.add_argument("--skip-contralor", action="store_true",
                        help="Skip step 26o (ingest PR Contralor audit data)")
    parser.add_argument("--skip-active-contractors", action="store_true",
                        help="Skip step 26p (ingest PR Active Contractor Listing)")
    parser.add_argument("--skip-prasa", action="store_true",
                        help="Skip step 26q (ingest PRASA contract data)")
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
    # Step 6b: SF-133 federal budget execution
    # ------------------------------------------------------------------
    if args.skip_sf133:
        logger.info("[Step 6b] SKIPPED (--skip-sf133)\n")
    else:
        logger.info("[Step 6b] Downloading SF-133 federal budget execution (USASpending)...")
        try:
            from scripts.download_sf133 import run as run_sf133
            sf_result = run_sf133(root=root)
            logger.info(
                f"[Step 6b] Done — {sf_result.get('rows', 0):,} account rows, "
                f"avg obligation rate {sf_result.get('avg_obligation_rate', 0):.1%}\n"
            )
        except Exception as e:
            logger.error(f"[Step 6b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6c: Department of Education grants
    # ------------------------------------------------------------------
    if args.skip_ed:
        logger.info("[Step 6c] SKIPPED (--skip-ed)\n")
    else:
        logger.info("[Step 6c] Downloading Department of Education grants for PR...")
        try:
            from scripts.download_ed import run as run_ed
            ed_result = run_ed(root=root)
            logger.info(f"[Step 6c] Done — {ed_result.get('master_rows', 0):,} ED grant rows\n")
        except Exception as e:
            logger.error(f"[Step 6c] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6d: HHS (HRSA + ACF) grants
    # ------------------------------------------------------------------
    if args.skip_hhs:
        logger.info("[Step 6d] SKIPPED (--skip-hhs)\n")
    else:
        logger.info("[Step 6d] Downloading HHS (HRSA + ACF) grants for PR...")
        try:
            from scripts.download_hhs import run as run_hhs
            hhs_result = run_hhs(root=root)
            logger.info(f"[Step 6d] Done — {hhs_result.get('master_rows', 0):,} HHS grant rows\n")
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
            from scripts.download_doj_grants import run as run_doj
            doj_result = run_doj(root=root)
            logger.info(f"[Step 6e] Done — {doj_result.get('master_rows', 0):,} DOJ grant rows\n")
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
            oia_result = run_oia(root=root)
            logger.info(f"[Step 6f] Done — {oia_result.get('master_rows', 0):,} OIA grant rows\n")
        except Exception as e:
            logger.error(f"[Step 6f] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6g: Homeowner Assistance Fund
    # ------------------------------------------------------------------
    if args.skip_haf:
        logger.info("[Step 6g] SKIPPED (--skip-haf)\n")
    else:
        logger.info("[Step 6g] Downloading HAF (Homeowner Assistance Fund) for PR...")
        try:
            from scripts.download_haf import run as run_haf
            haf_result = run_haf(root=root)
            logger.info(f"[Step 6g] Done — {haf_result.get('master_rows', 0):,} HAF rows\n")
        except Exception as e:
            logger.error(f"[Step 6g] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6h: Ex-Im Bank loans
    # ------------------------------------------------------------------
    if args.skip_exim:
        logger.info("[Step 6h] SKIPPED (--skip-exim)\n")
    else:
        logger.info("[Step 6h] Downloading Ex-Im Bank data for PR...")
        try:
            from scripts.download_exim import run as run_exim
            exim_result = run_exim(root=root)
            logger.info(f"[Step 6h] Done — {exim_result.get('master_rows', 0):,} Ex-Im rows\n")
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
            earmarks_result = run_earmarks(root=root)
            logger.info(f"[Step 6i] Done — {earmarks_result.get('rows', 0):,} earmark records\n")
        except Exception as e:
            logger.error(f"[Step 6i] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 6j: FPDS Report Builder Excel ingestion (FY2018-FY2024)
    # ------------------------------------------------------------------
    if args.skip_report_builder:
        logger.info("[Step 6j] SKIPPED (--skip-report-builder)\n")
    else:
        logger.info("[Step 6j] Ingesting FPDS Report Builder Excel files (FY2018–FY2024)...")
        try:
            from scripts.ingest_report_builder import run as run_report_builder
            rb_result = run_report_builder(root=root)
            logger.info(f"[Step 6j] Done — {rb_result.get('rows', 0):,} PR contract rows\n")
        except Exception as e:
            logger.error(f"[Step 6j] FAILED: {e}")

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
        logger.info("[Step 15/29] Downloading SBA loans, SLFRF, CDBG-DR, SBIR...")
        for name, mod in [
            ("SBA",     "download_sba"),
            ("SLFRF",   "download_slfrf"),
            ("CDBG-DR", "download_cdbg_dr"),
            ("SBIR",    "download_sbir"),
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
    # Step 15b: COR3 PR recovery project tracker
    # ------------------------------------------------------------------
    if args.skip_cor3:
        logger.info("[Step 15b] SKIPPED (--skip-cor3)\n")
    else:
        logger.info("[Step 15b] Downloading COR3 PR recovery project data...")
        try:
            from scripts.download_cor3 import run as run_cor3
            cor3_result = run_cor3(root=root)
            logger.info(
                f"[Step 15b] Done — {cor3_result.get('rows', 0):,} projects, "
                f"avg disbursement rate {cor3_result.get('avg_disbursement_rate', 0):.1%}\n"
            )
        except Exception as e:
            logger.error(f"[Step 15b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15c: Compras PR procurement RFPs and awards
    # ------------------------------------------------------------------
    if args.skip_compras:
        logger.info("[Step 15c] SKIPPED (--skip-compras)\n")
    else:
        logger.info("[Step 15c] Downloading Compras PR procurement data...")
        try:
            from scripts.download_compras import run as run_compras
            compras_result = run_compras(root=root)
            logger.info(
                f"[Step 15c] Done — {compras_result.get('rfp_rows', 0):,} RFPs, "
                f"{compras_result.get('award_rows', 0):,} awards\n"
            )
        except Exception as e:
            logger.error(f"[Step 15c] FAILED: {e}")

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
    # Step 18c: RFP × LDA lobbying cross-reference
    # ------------------------------------------------------------------
    if args.skip_rfp_lobby:
        logger.info("[Step 18c] SKIPPED (--skip-rfp-lobby)\n")
    else:
        logger.info("[Step 18c] Cross-referencing RFPs with LDA lobbying filings...")
        try:
            from scripts.analyze_rfp_lobby import run as run_rfp_lobby
            rfp_result = run_rfp_lobby(root=root)
            logger.info(
                f"[Step 18c] Done — {rfp_result.get('rows', 0):,} RFPs, "
                f"{rfp_result.get('flagged_rfps', 0):,} with prior lobbying\n"
            )
        except Exception as e:
            logger.error(f"[Step 18c] FAILED: {e}")

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
    # Step 25b: PR municipal federal spending by geography
    # ------------------------------------------------------------------
    if args.skip_municipal:
        logger.info("[Step 25b] SKIPPED (--skip-municipal)\n")
    else:
        logger.info("[Step 25b] Downloading PR municipal federal spending data...")
        try:
            from scripts.download_municipal import run as run_municipal
            muni_result = run_municipal(root=root)
            logger.info(
                f"[Step 25b] Done — {muni_result.get('rows', 0):,} municipality-year rows, "
                f"{muni_result.get('municipalities', 0):,} municipalities\n"
            )
        except Exception as e:
            logger.error(f"[Step 25b] FAILED: {e}")

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
    # Step 26d: MSRB RTRS secondary market trade data for PR CUSIPs
    # ------------------------------------------------------------------
    if args.skip_msrb_trades:
        logger.info("[Step 26d] SKIPPED (--skip-msrb-trades)\n")
    else:
        logger.info("[Step 26d] Downloading MSRB RTRS trade data for PR CUSIPs...")
        try:
            from scripts.download_msrb_trades import run as run_msrb_trades
            msrb_result = run_msrb_trades(root=root)
            logger.info(
                f"[Step 26d] Done — {msrb_result.get('rows', 0):,} trades, "
                f"{msrb_result.get('unique_dealers', 0):,} dealers\n"
            )
        except Exception as e:
            logger.error(f"[Step 26d] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26e: Bond flow cross-reference (underwriters/dealers vs entity_master)
    # ------------------------------------------------------------------
    if args.skip_bond_flow:
        logger.info("[Step 26e] SKIPPED (--skip-bond-flow)\n")
    else:
        logger.info("[Step 26e] Cross-referencing bond market participants with entity master...")
        try:
            from scripts.analyze_bond_flow import run as run_bond_flow
            bf_result = run_bond_flow(root=root)
            logger.info(
                f"[Step 26e] Done — {bf_result.get('rows', 0):,} entities, "
                f"{bf_result.get('dual_role_count', 0):,} dual-role (contractor + bond market)\n"
            )
        except Exception as e:
            logger.error(f"[Step 26e] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26f: NFIP flood insurance claims for PR
    # ------------------------------------------------------------------
    if args.skip_nfip:
        logger.info("[Step 26f] SKIPPED (--skip-nfip)\n")
    else:
        logger.info("[Step 26f] Downloading NFIP flood insurance claims for PR (OpenFEMA)...")
        try:
            from scripts.download_nfip import run as run_nfip
            nfip_result = run_nfip(root=root)
            logger.info(f"[Step 26f] Done — {nfip_result.get('rows', 0):,} claim records\n")
        except Exception as e:
            logger.error(f"[Step 26f] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26g: LIHTC low-income housing tax credit projects
    # ------------------------------------------------------------------
    if args.skip_lihtc:
        logger.info("[Step 26g] SKIPPED (--skip-lihtc)\n")
    else:
        logger.info("[Step 26g] Downloading LIHTC project data for PR (HUD User)...")
        try:
            from scripts.download_lihtc import run as run_lihtc
            lihtc_result = run_lihtc(root=root)
            logger.info(f"[Step 26g] Done — {lihtc_result.get('rows', 0):,} LIHTC projects\n")
        except Exception as e:
            logger.error(f"[Step 26g] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26h: NMTC new markets tax credit allocatees
    # ------------------------------------------------------------------
    if args.skip_nmtc:
        logger.info("[Step 26h] SKIPPED (--skip-nmtc)\n")
    else:
        logger.info("[Step 26h] Downloading NMTC allocatee data for PR (CDFI Fund)...")
        try:
            from scripts.download_nmtc import run as run_nmtc
            nmtc_result = run_nmtc(root=root)
            logger.info(f"[Step 26h] Done — {nmtc_result.get('rows', 0):,} NMTC allocatees\n")
        except Exception as e:
            logger.error(f"[Step 26h] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26i: PR Act 60 tax incentive decrees
    # ------------------------------------------------------------------
    if args.skip_act60:
        logger.info("[Step 26i] SKIPPED (--skip-act60)\n")
    else:
        logger.info("[Step 26i] Downloading Act 60 decree data for PR...")
        try:
            from scripts.download_act60 import run as run_act60
            act60_result = run_act60(root=root)
            logger.info(f"[Step 26i] Done — {act60_result.get('rows', 0):,} decrees\n")
        except Exception as e:
            logger.error(f"[Step 26i] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26j: PR Rum Cover-Over (federal excise tax transfers)
    # ------------------------------------------------------------------
    if args.skip_rum_coverover:
        logger.info("[Step 26j] SKIPPED (--skip-rum-coverover)\n")
    else:
        logger.info("[Step 26j] Downloading Rum Cover-Over data for PR...")
        try:
            from scripts.download_rum_coverover import run as run_rum
            rum_result = run_rum(root=root)
            logger.info(f"[Step 26j] Done — {rum_result.get('rows', 0):,} fiscal year rows\n")
        except Exception as e:
            logger.error(f"[Step 26j] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26k: FHLB advances to PR member banks
    # ------------------------------------------------------------------
    if args.skip_fhlb:
        logger.info("[Step 26k] SKIPPED (--skip-fhlb)\n")
    else:
        logger.info("[Step 26k] Downloading FHLB advance data for PR banks (FDIC SDI)...")
        try:
            from scripts.download_fhlb import run as run_fhlb
            fhlb_result = run_fhlb(root=root)
            logger.info(f"[Step 26k] Done — {fhlb_result.get('rows', 0):,} advance records\n")
        except Exception as e:
            logger.error(f"[Step 26k] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26l: PREPA / Luma / Genera major contracts
    # ------------------------------------------------------------------
    if args.skip_prepa:
        logger.info("[Step 26l] SKIPPED (--skip-prepa)\n")
    else:
        logger.info("[Step 26l] Downloading PREPA / Luma / Genera contract data...")
        try:
            from scripts.download_prepa_contracts import run as run_prepa
            prepa_result = run_prepa(root=root)
            logger.info(f"[Step 26l] Done — {prepa_result.get('rows', 0):,} contracts\n")
        except Exception as e:
            logger.error(f"[Step 26l] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26m: PROMESA Title III creditor data
    # ------------------------------------------------------------------
    if args.skip_promesa:
        logger.info("[Step 26m] SKIPPED (--skip-promesa)\n")
    else:
        logger.info("[Step 26m] Downloading PROMESA Title III creditor data...")
        try:
            from scripts.download_promesa_creditors import run as run_promesa
            promesa_result = run_promesa(root=root)
            logger.info(f"[Step 26m] Done — {promesa_result.get('rows', 0):,} creditor records\n")
        except Exception as e:
            logger.error(f"[Step 26m] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26n: PR Cabilderos (state-level lobbyist registry)
    # ------------------------------------------------------------------
    if args.skip_cabilderos:
        logger.info("[Step 26n] SKIPPED (--skip-cabilderos)\n")
    else:
        logger.info("[Step 26n] Ingesting PR Cabilderos (state lobbyist registry)...")
        try:
            from scripts.ingest_cabilderos import run as run_cabilderos
            cab_result = run_cabilderos(root=root)
            logger.info(f"[Step 26n] Done — {cab_result.get('rows', 0):,} cabildero records\n")
        except Exception as e:
            logger.error(f"[Step 26n] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26o: PR Contralor audit data
    # ------------------------------------------------------------------
    if args.skip_contralor:
        logger.info("[Step 26o] SKIPPED (--skip-contralor)\n")
    else:
        logger.info("[Step 26o] Ingesting PR Contralor (Comptroller's Office) audit data...")
        try:
            from scripts.ingest_contralor import run as run_contralor
            cont_result = run_contralor(root=root)
            logger.info(f"[Step 26o] Done — {cont_result.get('rows', 0):,} audit records\n")
        except Exception as e:
            logger.error(f"[Step 26o] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26p: PR Active Contractor Listing
    # ------------------------------------------------------------------
    if args.skip_active_contractors:
        logger.info("[Step 26p] SKIPPED (--skip-active-contractors)\n")
    else:
        logger.info("[Step 26p] Ingesting PR Active Contractor Listing...")
        try:
            from scripts.ingest_active_contractors import run as run_active_contractors
            ac_result = run_active_contractors(root=root)
            logger.info(f"[Step 26p] Done — {ac_result.get('rows', 0):,} contractor records\n")
        except Exception as e:
            logger.error(f"[Step 26p] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26q: PRASA contract data
    # ------------------------------------------------------------------
    if args.skip_prasa:
        logger.info("[Step 26q] SKIPPED (--skip-prasa)\n")
    else:
        logger.info("[Step 26q] Ingesting PRASA (Aqueduct & Sewer Authority) contract data...")
        try:
            from scripts.ingest_prasa import run as run_prasa
            prasa_result = run_prasa(root=root)
            logger.info(f"[Step 26q] Done — {prasa_result.get('rows', 0):,} PRASA contracts\n")
        except Exception as e:
            logger.error(f"[Step 26q] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26b: USACE Section 404/10 permits for PR
    # ------------------------------------------------------------------
    if args.skip_usace:
        logger.info("[Step 26b] SKIPPED (--skip-usace)\n")
    else:
        logger.info("[Step 26b] Downloading USACE permit data for PR (EPA ECHO)...")
        try:
            from scripts.download_usace_permits import run as run_usace
            usace_result = run_usace(root=root)
            logger.info(
                f"[Step 26b] Done — {usace_result.get('rows', 0):,} permits\n"
            )
        except Exception as e:
            logger.error(f"[Step 26b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 26c: PR EQB environmental permits via EPA ECHO
    # ------------------------------------------------------------------
    if args.skip_eqb:
        logger.info("[Step 26c] SKIPPED (--skip-eqb)\n")
    else:
        logger.info("[Step 26c] Downloading PR EQB environmental permit data (EPA ECHO)...")
        try:
            from scripts.download_eqb import run as run_eqb
            eqb_result = run_eqb(root=root)
            logger.info(
                f"[Step 26c] Done — {eqb_result.get('rows', 0):,} facilities, "
                f"{eqb_result.get('with_violations', 0):,} with violations\n"
            )
        except Exception as e:
            logger.error(f"[Step 26c] FAILED: {e}")

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
    # Step 29b: Contractor project delivery scorecard
    # ------------------------------------------------------------------
    if args.skip_delivery:
        logger.info("[Step 29b] SKIPPED (--skip-delivery)\n")
    else:
        logger.info("[Step 29b] Scoring contractor project delivery performance...")
        try:
            from scripts.analyze_project_delivery import run as run_delivery
            delivery_result = run_delivery(root=root)
            logger.info(
                f"[Step 29b] Done — {delivery_result.get('rows', 0):,} entities scored, "
                f"{delivery_result.get('high_risk_count', 0):,} high-risk\n"
            )
        except Exception as e:
            logger.error(f"[Step 29b] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 30: Generate investigative report
    # ------------------------------------------------------------------
    if args.skip_report:
        logger.info("[Step 30] SKIPPED (--skip-report)\n")
    else:
        logger.info("[Step 30] Generating investigative report from all pipeline outputs...")
        try:
            from scripts.generate_report import run as run_report
            rpt = run_report(root=root, force=True)
            logger.info(
                f"[Step 30] Done — {rpt.get('data_layers', 0)}/8 data layers → "
                f"{rpt.get('report_path', '')}\n"
            )
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
