"""Support helpers for the pipeline orchestrator (extracted from run_all.py).

Behaviour-preserving move of the orchestrator's small building blocks:
the archived-source skip finder, the pandas check, logging setup, and the
banner/summary printers. run_all.py imports these unchanged.
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import json
import logging
import sys
from datetime import datetime
from pathlib import Path


def archived_producer_modules(root: Path) -> set:
    """Module basenames whose registry producer_script lives under archive/."""
    registry = root / "registries" / "source_registry.json"
    try:
        sources = json.loads(registry.read_text(encoding="utf-8")).get("sources", [])
    except (OSError, ValueError):
        return set()
    return {
        Path(s["producer_script"]).stem
        for s in sources
        if str(s.get("producer_script", "")).startswith("archive/")
    }


class _ArchivedSourceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Supplies skip-stubs for `scripts.<producer>` modules kept archived."""

    def __init__(self, archived: set, logger: logging.Logger) -> None:
        self._archived = archived
        self._logger = logger

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("scripts."):
            return None
        if fullname.split(".")[-1] not in self._archived:
            return None
        return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        name = module.__name__.split(".")[-1]
        logger = self._logger

        def run(*_args, **_kwargs):
            logger.info(f"  SKIPPED — source archived, not wired ({name})")
            return {"rows": 0, "skipped": True, "archived": True}

        module.run = run


def install_archived_source_skip(root: Path, logger: logging.Logger) -> set:
    """Register the archived-source finder; return the archived module set."""
    archived = archived_producer_modules(root)
    if archived:
        sys.meta_path.insert(0, _ArchivedSourceFinder(archived, logger))
    return archived


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
    logger.info("  Expected record range: ~5,000–15,000+ (from ~1,500 baseline)")

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
