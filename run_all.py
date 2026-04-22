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
                        help="Skip step 15 (download SBA loans, SLFRF, CDBG-DR)")
    parser.add_argument("--skip-unified-master", action="store_true",
                        help="Skip step 16 (build unified awards master across all datasets)")
    parser.add_argument("--skip-fec", action="store_true",
                        help="Skip step 17 (download FEC Schedule A contributions from PR)")
    parser.add_argument("--skip-lda", action="store_true",
                        help="Skip step 18 (download LDA lobbying filings for PR)")
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
    logger.info("[Step 1/23] Setting up directories...")
    try:
        from scripts.setup_directories import main as setup_dirs
        setup_dirs(root)
        steps["dirs"] = True
        logger.info("[Step 1/23] Done.\n")
    except Exception as e:
        logger.error(f"[Step 1/23] FAILED: {e}")
        steps["dirs"] = False
        return 1

    # ------------------------------------------------------------------
    # Step 2: Generate download instructions
    # ------------------------------------------------------------------
    logger.info("[Step 2/23] Generating download instructions...")
    try:
        from scripts.download_instructions import main as gen_instructions
        gen_instructions(root)
        steps["instructions"] = True
        logger.info("[Step 2/23] Done.\n")
    except Exception as e:
        logger.error(f"[Step 2/23] FAILED: {e}")
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
        logger.info("[Step 3/23] SKIPPED (--skip-download / --manual-only)\n")
    else:
        logger.info("[Step 3/23] Auto-downloading datasets...")
        try:
            from scripts.auto_download import download_all, print_download_summary
            dl_results = download_all(root, force=args.force_download)
            print_download_summary(dl_results, logger)
            download_count = sum(1 for r in dl_results if r["status"] in ("OK", "SKIPPED"))
            steps["download"] = True
            logger.info(f"[Step 3/23] Done ({download_count} files ready).\n")
        except ImportError:
            logger.warning("[Step 3/23] Auto-download unavailable (missing requests/lxml).")
            logger.warning("  Install: pip install requests lxml")
            logger.warning("  Or use --manual-only and download files manually.\n")
            steps["download"] = False
        except Exception as e:
            logger.error(f"[Step 3/23] FAILED: {e}")
            steps["download"] = False

    # ------------------------------------------------------------------
    # Step 4: Validate downloads
    # ------------------------------------------------------------------
    if args.skip_validation:
        logger.info("[Step 4/23] SKIPPED (--skip-validation)\n")
    else:
        logger.info("[Step 4/23] Validating downloaded files...")
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

            logger.info(f"[Step 4/23] Done (exit: {validation_result}).\n")
        except Exception as e:
            logger.error(f"[Step 4/23] FAILED: {e}")
            validation_result = 1

    # ------------------------------------------------------------------
    # Step 5: Normalize
    # ------------------------------------------------------------------
    if args.skip_normalize:
        logger.info("[Step 5/23] SKIPPED (--skip-normalize)\n")
    else:
        logger.info("[Step 5/23] Normalizing expansion inputs...")
        try:
            from scripts.normalize_expansion_inputs import normalize_all, print_report as norm_report
            results = normalize_all(root)
            norm_report(results, logger)
            normalize_count = sum(1 for r in results if r["status"] in ("OK", "WARN"))
            logger.info(f"[Step 5/23] Done ({normalize_count} files normalized).\n")
        except Exception as e:
            logger.error(f"[Step 5/23] FAILED: {e}")
            normalize_count = 0

    # ------------------------------------------------------------------
    # Step 5.5: Cross-file deduplication + master build
    # ------------------------------------------------------------------
    if args.skip_dedup:
        logger.info("[Step 5.5/23] SKIPPED (--skip-dedup)\n")
    else:
        logger.info("[Step 5.5/23] Building deduplicated master...")
        try:
            from scripts.deduplicate_master import main as build_master
            dedup_stats = build_master(root)
            if dedup_stats["master_rows"] > 0:
                logger.info(
                    f"[Step 5.5/23] Done — {dedup_stats['master_rows']:,} rows, "
                    f"{dedup_stats['duplicates_removed']:,} cross-file dupes removed.\n"
                )
            else:
                logger.info("[Step 5.5/23] Done (no normalized files found yet).\n")
        except Exception as e:
            logger.error(f"[Step 5.5/23] FAILED: {e}")
            dedup_stats = None

    # ------------------------------------------------------------------
    # Step 6: Validate coverage
    # ------------------------------------------------------------------
    if args.skip_coverage:
        logger.info("[Step 6/23] SKIPPED (--skip-coverage)\n")
    else:
        logger.info("[Step 6/23] Validating expansion coverage...")
        try:
            from scripts.validate_expansion_coverage import main as validate_coverage
            coverage_result = validate_coverage(root)
            logger.info(f"[Step 6/23] Done (exit: {coverage_result}).\n")
        except Exception as e:
            logger.error(f"[Step 6/23] FAILED: {e}")
            coverage_result = 1

    # ------------------------------------------------------------------
    # Step 7: SAM.gov UEI enrichment
    # ------------------------------------------------------------------
    if args.skip_enrichment:
        logger.info("[Step 7/23] SKIPPED (--skip-enrichment)\n")
    else:
        import os as _os
        from scripts.config import _load_dotenv, PROJECT_ROOT as _root
        has_key = bool(
            _os.environ.get("SAM_API_KEY", "").strip()
            or _load_dotenv(_root / ".env").get("SAM_API_KEY", "").strip()
        )
        if not has_key:
            logger.info("[Step 7/23] SKIPPED — SAM_API_KEY not set.")
            logger.info("  Set via: export SAM_API_KEY=your_key  or create a .env file.\n")
            enrichment_result = "NO_KEY — skipped"
        elif dedup_stats is None or dedup_stats.get("master_rows", 0) == 0:
            logger.info("[Step 7/23] SKIPPED — no master data (download files first)\n")
            enrichment_result = "SKIPPED — no master data"
        else:
            logger.info("[Step 7/23] Running SAM.gov UEI enrichment...")
            try:
                from scripts.sam_enrichment import run as run_enrichment
                summary = run_enrichment(root=root)
                enrichment_result = (
                    f"{summary.get('vendors_resolved', 0)}/{summary.get('vendors_attempted', 0)} vendors resolved "
                    f"({summary.get('coverage_pct', 0):.1f}%) — "
                    f"{'PASS' if summary.get('coverage_gate_pass') else 'BELOW GATE'}"
                )
                logger.info(f"[Step 7/23] Done.\n")
            except Exception as e:
                logger.error(f"[Step 7/23] FAILED: {e}")
                enrichment_result = f"FAILED: {e}"

    # ------------------------------------------------------------------
    # Step 8: Entity resolution (top 100 vendors → parent entity)
    # ------------------------------------------------------------------
    master_ready = dedup_stats is not None and dedup_stats.get("master_rows", 0) > 0
    if args.skip_entity_resolution:
        logger.info("[Step 8/23] SKIPPED (--skip-entity-resolution)\n")
    elif not master_ready:
        logger.info("[Step 8/23] SKIPPED — no master data yet\n")
    else:
        logger.info("[Step 8/23] Resolving top 100 vendor entities...")
        try:
            from scripts.entity_resolution import run as run_entity
            run_entity(root=root)
            logger.info("[Step 8/23] Done.\n")
        except Exception as e:
            logger.error(f"[Step 8/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 9: Dominance analysis
    # ------------------------------------------------------------------
    if args.skip_dominance:
        logger.info("[Step 9/23] SKIPPED (--skip-dominance)\n")
    elif not master_ready:
        logger.info("[Step 9/23] SKIPPED — no master data yet\n")
    else:
        logger.info("[Step 9/23] Computing dominance metrics...")
        try:
            from scripts.dominance_analysis import run as run_dominance
            summary_d = run_dominance(root=root)
            logger.info(
                f"[Step 9/23] Done — top vendor: {summary_d.get('top_vendor', '?')}, "
                f"${summary_d.get('top_vendor_obligation', 0):,.0f}\n"
            )
        except Exception as e:
            logger.error(f"[Step 9/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 10: Network graph
    # ------------------------------------------------------------------
    if args.skip_graph:
        logger.info("[Step 10/23] SKIPPED (--skip-graph)\n")
    elif not master_ready:
        logger.info("[Step 10/23] SKIPPED — no master data yet\n")
    else:
        logger.info("[Step 10/23] Building network graph...")
        try:
            from scripts.network_graph import run as run_graph
            summary_g = run_graph(root=root)
            logger.info(
                f"[Step 10/23] Done — {summary_g.get('total_nodes', 0)} nodes, "
                f"{summary_g.get('total_edges', 0)} edges → network.graphml\n"
            )
        except ImportError:
            logger.info("[Step 10/23] SKIPPED — networkx not installed (pip install networkx)\n")
        except Exception as e:
            logger.error(f"[Step 10/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 11: Download grants
    # ------------------------------------------------------------------
    if args.skip_grants:
        logger.info("[Step 11/23] SKIPPED (--skip-grants)\n")
    else:
        logger.info("[Step 11/23] Downloading federal grants (USASpending)...")
        try:
            from scripts.download_grants import run as run_grants
            g = run_grants(root=root)
            logger.info(f"[Step 11/23] Done — {g.get('total_rows', 0):,} grant records\n")
        except Exception as e:
            logger.error(f"[Step 11/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 12: Download subawards
    # ------------------------------------------------------------------
    if args.skip_subawards:
        logger.info("[Step 12/23] SKIPPED (--skip-subawards)\n")
    else:
        logger.info("[Step 12/23] Downloading subawards (USASpending)...")
        try:
            from scripts.download_subawards import run as run_subawards
            s = run_subawards(root=root)
            logger.info(f"[Step 12/23] Done — {s.get('total_rows', 0):,} subaward records\n")
        except Exception as e:
            logger.error(f"[Step 12/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 13: Download FEMA data
    # ------------------------------------------------------------------
    if args.skip_fema:
        logger.info("[Step 13/23] SKIPPED (--skip-fema)\n")
    else:
        logger.info("[Step 13/23] Downloading FEMA Public Assistance + HMGP...")
        try:
            from scripts.download_fema import run as run_fema
            f = run_fema(root=root)
            logger.info(f"[Step 13/23] Done — PA: {f.get('pa_rows', 0):,}, HMGP: {f.get('hmgp_rows', 0):,}\n")
        except Exception as e:
            logger.error(f"[Step 13/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 14: Download research grants
    # ------------------------------------------------------------------
    if args.skip_research:
        logger.info("[Step 14/23] SKIPPED (--skip-research)\n")
    else:
        logger.info("[Step 14/23] Downloading NIH + NSF research grants...")
        try:
            from scripts.download_research import run as run_research
            r = run_research(root=root)
            logger.info(f"[Step 14/23] Done — NIH: {r.get('nih_rows', 0):,}, NSF: {r.get('nsf_rows', 0):,}\n")
        except Exception as e:
            logger.error(f"[Step 14/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 15: Bulk downloads (SBA, SLFRF, CDBG-DR)
    # ------------------------------------------------------------------
    if args.skip_bulk_downloads:
        logger.info("[Step 15/23] SKIPPED (--skip-bulk-downloads)\n")
    else:
        logger.info("[Step 15/23] Downloading SBA loans, SLFRF, CDBG-DR...")
        for name, mod in [("SBA", "download_sba"), ("SLFRF", "download_slfrf"), ("CDBG-DR", "download_cdbg_dr")]:
            try:
                import importlib
                m = importlib.import_module(f"scripts.{mod}")
                result = m.run(root=root)
                logger.info(f"  {name}: {result.get('rows', result.get('total_rows', 0)):,} rows")
            except Exception as e:
                logger.error(f"  {name} FAILED: {e}")
        logger.info("[Step 15/23] Done.\n")

    # ------------------------------------------------------------------
    # Step 16: Build unified master
    # ------------------------------------------------------------------
    if args.skip_unified_master:
        logger.info("[Step 16/23] SKIPPED (--skip-unified-master)\n")
    else:
        logger.info("[Step 16/23] Building unified awards master (all datasets)...")
        try:
            from scripts.build_unified_master import run as run_unified
            u = run_unified(root=root)
            logger.info(
                f"[Step 16/23] Done — {u.get('total_rows', 0):,} total rows across "
                f"{len(u.get('by_dataset', {}))} datasets → pr_all_awards_master.csv\n"
            )
        except Exception as e:
            logger.error(f"[Step 16/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 17: Download FEC contributions
    # ------------------------------------------------------------------
    if args.skip_fec:
        logger.info("[Step 17/23] SKIPPED (--skip-fec)\n")
    else:
        logger.info("[Step 17/23] Downloading FEC Schedule A contributions from PR...")
        try:
            from scripts.download_fec import run as run_fec
            fec_result = run_fec(root=root, api_key=args.fec_api_key)
            logger.info(f"[Step 17/23] Done — {fec_result.get('rows', 0):,} contribution records\n")
        except Exception as e:
            logger.error(f"[Step 17/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 18: Download LDA lobbying filings
    # ------------------------------------------------------------------
    if args.skip_lda:
        logger.info("[Step 18/23] SKIPPED (--skip-lda)\n")
    else:
        logger.info("[Step 18/23] Downloading LDA lobbying filings for PR...")
        try:
            from scripts.download_lda import run as run_lda
            lda_result = run_lda(root=root, api_key=args.lda_api_key)
            logger.info(f"[Step 18/23] Done — {lda_result.get('rows', 0):,} filings\n")
        except Exception as e:
            logger.error(f"[Step 18/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 19: Cross-reference analyses (FEC + lobbying)
    # ------------------------------------------------------------------
    if args.skip_crossref:
        logger.info("[Step 19/23] SKIPPED (--skip-crossref)\n")
    else:
        logger.info("[Step 19/23] Running FEC and lobbying cross-reference analyses...")
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
        logger.info("[Step 19/23] Done.\n")

    # ------------------------------------------------------------------
    # Step 20: IRS 990 nonprofits via ProPublica
    # ------------------------------------------------------------------
    if args.skip_nonprofits:
        logger.info("[Step 20/23] SKIPPED (--skip-nonprofits)\n")
    else:
        logger.info("[Step 20/23] Downloading IRS 990 nonprofit data for PR...")
        try:
            from scripts.download_nonprofits import run as run_nonprofits
            np_result = run_nonprofits(root=root)
            logger.info(f"[Step 20/23] Done — {np_result.get('rows', 0):,} nonprofits\n")
        except Exception as e:
            logger.error(f"[Step 20/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 21: CMS Open Payments + Medicare provider data
    # ------------------------------------------------------------------
    if args.skip_cms:
        logger.info("[Step 21/23] SKIPPED (--skip-cms)\n")
    else:
        logger.info("[Step 21/23] Downloading CMS Open Payments and Medicare data for PR...")
        try:
            from scripts.download_cms import run as run_cms
            cms_result = run_cms(root=root)
            logger.info(
                f"[Step 21/23] Done — Open Payments: {cms_result.get('open_payments_rows', 0):,}, "
                f"Medicare: {cms_result.get('medicare_rows', 0):,}\n"
            )
        except Exception as e:
            logger.error(f"[Step 21/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 22: FDIC bank data
    # ------------------------------------------------------------------
    if args.skip_fdic:
        logger.info("[Step 22/23] SKIPPED (--skip-fdic)\n")
    else:
        logger.info("[Step 22/23] Downloading FDIC bank institution and financial data for PR...")
        try:
            from scripts.download_fdic import run as run_fdic
            fdic_result = run_fdic(root=root)
            logger.info(
                f"[Step 22/23] Done — {fdic_result.get('institution_rows', 0):,} institutions, "
                f"{fdic_result.get('financial_rows', 0):,} financial rows\n"
            )
        except Exception as e:
            logger.error(f"[Step 22/23] FAILED: {e}")

    # ------------------------------------------------------------------
    # Step 23: Entity profiles cross-reference
    # ------------------------------------------------------------------
    if args.skip_entity_profiles:
        logger.info("[Step 23/23] SKIPPED (--skip-entity-profiles)\n")
    else:
        logger.info("[Step 23/23] Building enriched entity profiles...")
        try:
            from scripts.analyze_entity_profiles import build_profiles
            ep_result = build_profiles(root=root)
            logger.info(
                f"[Step 23/23] Done — {ep_result.get('rows', 0):,} entities profiled, "
                f"{ep_result.get('np_matched', 0):,} nonprofits, "
                f"{ep_result.get('med_matched', 0):,} Medicare providers, "
                f"{ep_result.get('bank_matched', 0):,} banks\n"
            )
        except Exception as e:
            logger.error(f"[Step 23/23] FAILED: {e}")

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
