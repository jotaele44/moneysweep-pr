"""Build risk signals master from R5 data shapes.

Calls contract_sweeper.runtime.risk_signals.compute_signals() and writes:
  data/staging/processed/risk/risk_signals_master.csv
  data/staging/processed/risk/entity_risk_scores.csv
  data/staging/processed/risk/project_risk_scores.csv
  data/staging/processed/risk/municipality_risk_scores.csv
  data/manifests/risk_signal_report.json

Usage:
  python3 scripts/build_risk_signals.py
  python3 scripts/build_risk_signals.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from contract_sweeper.runtime.risk_signals import (
    SIGNAL_COLUMNS,
    ENTITY_SCORE_COLUMNS,
    PROJECT_SCORE_COLUMNS,
    MUNICIPALITY_SCORE_COLUMNS,
    compute_signals,
)
from scripts.config import setup_logging

logger = setup_logging(__name__)

RISK_OUT = Path("data") / "staging" / "processed" / "risk"
MANIFESTS_OUT = Path("data") / "manifests"


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def run(root: Path) -> dict:
    logger.info("Computing risk signals from R5 data (root=%s)", root)
    result = compute_signals(root)

    signals            = result["signals"]
    entity_scores      = result["entity_scores"]
    project_scores     = result["project_scores"]
    municipality_scores = result["municipality_scores"]
    metadata           = result["metadata"]

    out_base = root / RISK_OUT

    n_sig  = _write_csv(out_base / "risk_signals_master.csv",   signals,            SIGNAL_COLUMNS)
    n_ent  = _write_csv(out_base / "entity_risk_scores.csv",    entity_scores,      ENTITY_SCORE_COLUMNS)
    n_proj = _write_csv(out_base / "project_risk_scores.csv",   project_scores,     PROJECT_SCORE_COLUMNS)
    n_muni = _write_csv(out_base / "municipality_risk_scores.csv", municipality_scores, MUNICIPALITY_SCORE_COLUMNS)

    logger.info(
        "  Signals: %d | Entities: %d | Projects: %d | Municipalities: %d",
        n_sig, n_ent, n_proj, n_muni,
    )

    manifest = {**metadata, "output_rows": {
        "risk_signals_master":      n_sig,
        "entity_risk_scores":       n_ent,
        "project_risk_scores":      n_proj,
        "municipality_risk_scores": n_muni,
    }}

    manifest_dir = root / MANIFESTS_OUT
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "risk_signal_report.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("  Manifest: %s", manifest_path)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build risk signals master")
    parser.add_argument("--root", default=".", help="Repository root path")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    run(root)


if __name__ == "__main__":
    main()
