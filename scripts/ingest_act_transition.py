"""Promote extracted ACT/ACUDEN transition contracts to canonical processed CSVs.

This is the registry ``producer_script`` for two manual-export sources:

  - ``act_transition_contracts`` → ``data/staging/processed/pr_act_transition_contracts.csv``
  - ``acuden_2024_transition``   → ``data/staging/processed/pr_acuden_transition.csv``

It closes the gap between the PDF extractor (``scripts/extract_act_acuden_pdfs.py``,
which writes per-PDF 6-column CSVs under ``data/staging/raw/``) and the canonical
``data/staging/processed/`` outputs the registry declares. Once an operator drops
the source PDF in the manual drop dir, running this producer materializes the
declared output (≥1 row ⇒ ``fully_materialized`` in gap analysis).

No network. Materialization still requires the operator-supplied PDF; with no PDF
present the producer is a clean no-op (writes nothing, reports ``EMPTY``).

Usage:
  python3 scripts/ingest_act_transition.py                 # both sources
  python3 scripts/ingest_act_transition.py --source act
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging

# Source metadata mirrored locally so this module imports WITHOUT pulling in
# pdfplumber (the readiness preflight imports every producer module — it must
# not require the heavy PDF stack). The extractor is imported lazily, only when
# we actually run an extraction. Keep these in sync with
# scripts/extract_act_acuden_pdfs.py::SOURCES.
SOURCE_META = {
    "act": {"label": "act_transition_contracts", "output_dir": "data/staging/raw/act_transition"},
    "acuden": {"label": "acuden_2024_transition", "output_dir": "data/staging/raw/acuden_2024"},
}

# source_key -> registry expected_output
PROCESSED_OUTPUTS = {
    "act": "data/staging/processed/pr_act_transition_contracts.csv",
    "acuden": "data/staging/processed/pr_acuden_transition.csv",
}

# Canonical processed schema: extractor's 6 columns + a provenance tag.
CANONICAL_COLUMNS = [
    "source_dataset",
    "contractor_name",
    "contract_number",
    "start_date",
    "end_date",
    "amount",
    "service_type",
]


def promote_rows(rows: list[dict], source_key: str) -> list[dict]:
    """Map extractor rows to the canonical processed schema. Pure — no I/O.

    Drops rows with neither a contractor nor a contract number, tags each row
    with its source dataset, and deduplicates on (contract_number,
    contractor_name).
    """
    label = SOURCE_META[source_key]["label"]
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        contractor = (row.get("contractor_name") or "").strip()
        contract = (row.get("contract_number") or "").strip()
        if not contractor and not contract:
            continue
        key = (contract, contractor)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "source_dataset": label,
                "contractor_name": contractor,
                "contract_number": contract,
                "start_date": (row.get("start_date") or "").strip(),
                "end_date": (row.get("end_date") or "").strip(),
                "amount": (row.get("amount") or "").strip(),
                "service_type": (row.get("service_type") or "").strip(),
            }
        )
    return out


def _read_staged_rows(root: Path, source_key: str) -> list[dict]:
    out_dir = root / SOURCE_META[source_key]["output_dir"]
    if not out_dir.exists():
        return []
    rows: list[dict] = []
    for csv_path in sorted(out_dir.glob("*.csv")):
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def _write_processed(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def materialize_source(root: Path, source_key: str, input_dir: Path | None, logger) -> dict:
    """Extract (if a PDF is present) then promote one source to its processed CSV."""
    # Lazy import — keeps module import (and the readiness preflight) free of pdfplumber.
    from contract_sweeper.runtime.alias_overrides import load_overrides
    from scripts.extract_act_acuden_pdfs import extract_source

    overrides = load_overrides()
    extract_source(
        source_key, root, overrides, dry_run=False, input_override=input_dir, logger=logger
    )
    staged = _read_staged_rows(root, source_key)
    promoted = promote_rows(staged, source_key)
    out_path = root / PROCESSED_OUTPUTS[source_key]
    if not promoted:
        logger.info(f"  [{source_key}] no rows to promote (drop a PDF first) — EMPTY")
        return {"source": source_key, "status": "EMPTY", "rows": 0, "output": str(out_path)}
    _write_processed(promoted, out_path)
    logger.info(f"  [{source_key}] {len(promoted)} rows → {PROCESSED_OUTPUTS[source_key]}")
    return {"source": source_key, "status": "OK", "rows": len(promoted), "output": str(out_path)}


def run(root: Path | None = None, source: str = "all", input_dir: Path | None = None) -> dict:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("ingest_act_transition")
    keys = list(PROCESSED_OUTPUTS) if source == "all" else [source]
    if input_dir is not None and source == "all":
        raise ValueError("--input-dir requires --source act or --source acuden")
    results = [materialize_source(root, k, input_dir, logger) for k in keys]
    total = sum(r["rows"] for r in results)
    return {"status": "OK" if total else "EMPTY", "rows": total, "sources": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["act", "acuden", "all"], default="all")
    parser.add_argument("--input-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    result = run(source=args.source, input_dir=args.input_dir)
    return 0 if result["rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
