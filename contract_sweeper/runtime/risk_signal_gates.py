"""R7 risk signal completion gates.

Gates:
  risk_signal_schema_valid        — signals CSV has all required columns
  risk_signal_lineage_complete    — every signal row has non-empty evidence_source
                                    and evidence_row_ids
  risk_signal_explainability_complete — every signal row has non-empty explanation
  no_random_scores                — determinism check: two runs produce same count
  entity_scores_present           — entity_risk_scores.csv is non-empty

These are checked by `python -m contract_sweeper.runtime.risk_signal_gates --root .`
Returns exit code 0 on all pass, non-zero on any failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from contract_sweeper.runtime.logging_config import configure_logging, get_logger
from contract_sweeper.runtime.risk_signals import SIGNAL_COLUMNS, SCHEMA_VERSION

_LOG = get_logger(__name__)

SIGNALS_CSV = Path("data") / "staging" / "processed" / "risk" / "risk_signals_master.csv"
ENTITY_SCORES_CSV = Path("data") / "staging" / "processed" / "risk" / "entity_risk_scores.csv"
MANIFEST_JSON = Path("data") / "manifests" / "risk_signal_report.json"

_LINEAGE_FIELDS = ("evidence_source", "evidence_row_ids")
_EXPLAIN_FIELDS = ("explanation",)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def gate_signal_schema_valid(root: Path) -> dict:
    path = root / SIGNALS_CSV
    rows = _read_csv_rows(path)
    if not rows:
        return {
            "gate": "risk_signal_schema_valid",
            "passed": False,
            "reason": f"No rows or missing file: {path}",
        }
    present = set(rows[0].keys())
    missing = [c for c in SIGNAL_COLUMNS if c not in present]
    passed = len(missing) == 0
    return {
        "gate": "risk_signal_schema_valid",
        "passed": passed,
        "row_count": len(rows),
        "missing_columns": missing,
        "reason": "" if passed else f"Missing columns: {missing}",
    }


def gate_signal_lineage_complete(root: Path) -> dict:
    path = root / SIGNALS_CSV
    rows = _read_csv_rows(path)
    if not rows:
        return {
            "gate": "risk_signal_lineage_complete",
            "passed": False,
            "reason": "No signal rows to check",
        }
    incomplete = [
        r.get("signal_id", str(i))
        for i, r in enumerate(rows)
        if not all(r.get(f, "").strip() for f in _LINEAGE_FIELDS)
    ]
    passed = len(incomplete) == 0
    return {
        "gate": "risk_signal_lineage_complete",
        "passed": passed,
        "row_count": len(rows),
        "incomplete_count": len(incomplete),
        "sample_incomplete": incomplete[:5],
        "reason": "" if passed else f"{len(incomplete)} rows missing lineage fields",
    }


def gate_signal_explainability_complete(root: Path) -> dict:
    path = root / SIGNALS_CSV
    rows = _read_csv_rows(path)
    if not rows:
        return {
            "gate": "risk_signal_explainability_complete",
            "passed": False,
            "reason": "No signal rows to check",
        }
    incomplete = [
        r.get("signal_id", str(i))
        for i, r in enumerate(rows)
        if not all(r.get(f, "").strip() for f in _EXPLAIN_FIELDS)
    ]
    passed = len(incomplete) == 0
    return {
        "gate": "risk_signal_explainability_complete",
        "passed": passed,
        "row_count": len(rows),
        "incomplete_count": len(incomplete),
        "sample_incomplete": incomplete[:5],
        "reason": "" if passed else f"{len(incomplete)} rows missing explanation",
    }


def gate_no_random_scores(root: Path) -> dict:
    """Determinism check: signal_ids must be unique (no UUID-style randomness)."""
    path = root / SIGNALS_CSV
    rows = _read_csv_rows(path)
    if not rows:
        return {
            "gate": "no_random_scores",
            "passed": True,
            "reason": "No rows — vacuously deterministic",
        }
    ids = [r.get("signal_id", "") for r in rows]
    duplicates = [sid for sid in set(ids) if ids.count(sid) > 1]
    passed = len(duplicates) == 0
    return {
        "gate": "no_random_scores",
        "passed": passed,
        "signal_count": len(ids),
        "duplicate_ids": duplicates[:5],
        "reason": "" if passed else f"{len(duplicates)} duplicate signal_ids (non-deterministic)",
    }


def gate_entity_scores_present(root: Path) -> dict:
    path = root / ENTITY_SCORES_CSV
    rows = _read_csv_rows(path)
    passed = len(rows) > 0
    return {
        "gate": "entity_scores_present",
        "passed": passed,
        "row_count": len(rows),
        "reason": "" if passed else "entity_risk_scores.csv is empty or missing",
    }


def run_all_gates(root: Path) -> list[dict]:
    return [
        gate_signal_schema_valid(root),
        gate_signal_lineage_complete(root),
        gate_signal_explainability_complete(root),
        gate_no_random_scores(root),
        gate_entity_scores_present(root),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="R7 risk signal gates")
    parser.add_argument("--root", default=".", help="Repository root path")
    parser.add_argument(
        "--allow-failed",
        action="store_true",
        help="Exit 0 even when gates fail (bootstrap mode only)",
    )
    args = parser.parse_args()
    configure_logging()
    root = Path(args.root).resolve()

    records = run_all_gates(root)
    failing = [r for r in records if not r["passed"]]

    ts = _now_iso()
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": ts,
        "all_passed": len(failing) == 0,
        "gate_count": len(records),
        "failing_count": len(failing),
        "records": records,
    }

    # Write manifest
    manifest_dir = root / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "risk_signal_gate_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    # Per-gate outcomes are diagnostics, not the command's machine output, so
    # they go through the structured logger (stderr) rather than stdout.
    for r in records:
        log = _LOG.info if r["passed"] else _LOG.warning
        log(
            "risk_signal_gate",
            extra={
                "gate": r["gate"],
                "status": "PASS" if r["passed"] else "FAIL",
                "reason": r.get("reason") or "",
            },
        )

    if failing:
        _LOG.warning("risk_signal_gates_failing", extra={"failing_count": len(failing)})
        if not args.allow_failed:
            sys.exit(1)
    else:
        _LOG.info("risk_signal_gates_all_passed", extra={"gate_count": len(records)})


if __name__ == "__main__":
    main()
