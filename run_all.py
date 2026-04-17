"""
Full pipeline orchestrator — Puerto Rico Federal Contracts Data Pipeline (Section 9).

Usage:
  python3 run_all.py                  # Run all steps
  python3 run_all.py --only-setup     # Steps 1-2 only (dirs + instructions)
  python3 run_all.py --skip-validation
  python3 run_all.py --skip-normalize
  python3 run_all.py --skip-coverage
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
    logger.info("[Step 1/7] Setting up directories...")
    try:
        from scripts.setup_directories import main as setup_dirs
        setup_dirs(root)
        steps["dirs"] = True
        logger.info("[Step 1/7] Done.\n")
    except Exception as e:
        logger.error(f"[Step 1/7] FAILED: {e}")
        steps["dirs"] = False
        return 1

    # ------------------------------------------------------------------
    # Step 2: Generate download instructions
    # ------------------------------------------------------------------
    logger.info("[Step 2/7] Generating download instructions...")
    try:
        from scripts.download_instructions import main as gen_instructions
        gen_instructions(root)
        steps["instructions"] = True
        logger.info("[Step 2/7] Done.\n")
    except Exception as e:
        logger.error(f"[Step 2/7] FAILED: {e}")
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
        logger.info("[Step 3/7] SKIPPED (--skip-download / --manual-only)\n")
    else:
        logger.info("[Step 3/7] Auto-downloading datasets...")
        try:
            from scripts.auto_download import download_all, print_download_summary
            dl_results = download_all(root, force=args.force_download)
            print_download_summary(dl_results, logger)
            download_count = sum(1 for r in dl_results if r["status"] in ("OK", "SKIPPED"))
            steps["download"] = True
            logger.info(f"[Step 3/7] Done ({download_count} files ready).\n")
        except ImportError:
            logger.warning("[Step 3/7] Auto-download unavailable (missing requests/lxml).")
            logger.warning("  Install: pip install requests lxml")
            logger.warning("  Or use --manual-only and download files manually.\n")
            steps["download"] = False
        except Exception as e:
            logger.error(f"[Step 3/7] FAILED: {e}")
            steps["download"] = False

    # ------------------------------------------------------------------
    # Step 4: Validate downloads
    # ------------------------------------------------------------------
    if args.skip_validation:
        logger.info("[Step 4/7] SKIPPED (--skip-validation)\n")
    else:
        logger.info("[Step 4/7] Validating downloaded files...")
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

            logger.info(f"[Step 4/7] Done (exit: {validation_result}).\n")
        except Exception as e:
            logger.error(f"[Step 4/7] FAILED: {e}")
            validation_result = 1

    # ------------------------------------------------------------------
    # Step 5: Normalize
    # ------------------------------------------------------------------
    if args.skip_normalize:
        logger.info("[Step 5/7] SKIPPED (--skip-normalize)\n")
    else:
        logger.info("[Step 5/7] Normalizing expansion inputs...")
        try:
            from scripts.normalize_expansion_inputs import normalize_all, print_report as norm_report
            results = normalize_all(root)
            norm_report(results, logger)
            normalize_count = sum(1 for r in results if r["status"] in ("OK", "WARN"))
            logger.info(f"[Step 5/7] Done ({normalize_count} files normalized).\n")
        except Exception as e:
            logger.error(f"[Step 5/7] FAILED: {e}")
            normalize_count = 0

    # ------------------------------------------------------------------
    # Step 5.5: Cross-file deduplication + master build
    # ------------------------------------------------------------------
    if args.skip_dedup:
        logger.info("[Step 5.5/7] SKIPPED (--skip-dedup)\n")
    else:
        logger.info("[Step 5.5/7] Building deduplicated master...")
        try:
            from scripts.deduplicate_master import main as build_master
            dedup_stats = build_master(root)
            if dedup_stats["master_rows"] > 0:
                logger.info(
                    f"[Step 5.5/7] Done — {dedup_stats['master_rows']:,} rows, "
                    f"{dedup_stats['duplicates_removed']:,} cross-file dupes removed.\n"
                )
            else:
                logger.info("[Step 5.5/7] Done (no normalized files found yet).\n")
        except Exception as e:
            logger.error(f"[Step 5.5/7] FAILED: {e}")
            dedup_stats = None

    # ------------------------------------------------------------------
    # Step 6: Validate coverage
    # ------------------------------------------------------------------
    if args.skip_coverage:
        logger.info("[Step 6/7] SKIPPED (--skip-coverage)\n")
    else:
        logger.info("[Step 6/7] Validating expansion coverage...")
        try:
            from scripts.validate_expansion_coverage import main as validate_coverage
            coverage_result = validate_coverage(root)
            logger.info(f"[Step 6/7] Done (exit: {coverage_result}).\n")
        except Exception as e:
            logger.error(f"[Step 6/7] FAILED: {e}")
            coverage_result = 1

    # ------------------------------------------------------------------
    # Step 7: SAM.gov UEI enrichment
    # ------------------------------------------------------------------
    if args.skip_enrichment:
        logger.info("[Step 7/7] SKIPPED (--skip-enrichment)\n")
    else:
        import os as _os
        from scripts.config import _load_dotenv, PROJECT_ROOT as _root
        has_key = bool(
            _os.environ.get("SAM_API_KEY", "").strip()
            or _load_dotenv(_root / ".env").get("SAM_API_KEY", "").strip()
        )
        if not has_key:
            logger.info("[Step 7/7] SKIPPED — SAM_API_KEY not set.")
            logger.info("  Set via: export SAM_API_KEY=your_key  or create a .env file.\n")
            enrichment_result = "NO_KEY — skipped"
        elif dedup_stats is None or dedup_stats.get("master_rows", 0) == 0:
            logger.info("[Step 7/7] SKIPPED — no master data (download files first)\n")
            enrichment_result = "SKIPPED — no master data"
        else:
            logger.info("[Step 7/7] Running SAM.gov UEI enrichment...")
            try:
                from scripts.sam_enrichment import run as run_enrichment
                summary = run_enrichment(root=root)
                enrichment_result = (
                    f"{summary.get('vendors_resolved', 0)}/{summary.get('vendors_attempted', 0)} vendors resolved "
                    f"({summary.get('coverage_pct', 0):.1f}%) — "
                    f"{'PASS' if summary.get('coverage_gate_pass') else 'BELOW GATE'}"
                )
                logger.info(f"[Step 7/7] Done.\n")
            except Exception as e:
                logger.error(f"[Step 7/7] FAILED: {e}")
                enrichment_result = f"FAILED: {e}"

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
