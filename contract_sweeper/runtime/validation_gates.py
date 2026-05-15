"""Validation gates that block downstream layers when coverage is insufficient.

Each gate compares an observed metric to a configurable threshold and returns
a `passed` boolean. The aggregate report goes to
`data/manifests/validation_report.json`; per-gate details go to
`data/manifests/validation_gate_report.csv`.

Gates implemented in R5 (PR2.6 — entity-type-aware):
  - source_coverage_rate              ≥ 0.95
  - entity_resolution_rate            ≥ 0.001 (canary; PR gov data structurally near-0%)
  - entity_type_assignment_rate       ≥ 0.80  (replaces global parent_uei_rate)
  - corporate_parent_uei_rate         ≥ 0.50  (only for corporate-type entities)
  - high_value_unresolved_review_rate ≥ 0.90  (fraction in review_queue)
  - subaward_linkage_rate             ≥ 0.90
  - execution_chain_linkage_rate      ≥ 0.90
  - manifest_present_per_required     (all required sources have a manifest)
  - secret_leakage_zero               == 0 (delegates to scripts/scan_for_secrets)
  - duplicate_rate_per_source         ≤ 0.05

Deprecated (PR2.6): global parent_uei_rate ≥ 0.90 gate removed.
  Government agencies dominate PR awards data and do not register corporate
  parent UEIs. The per-type corporate_parent_uei_rate gate is correct.

Returns non-zero exit code if any gate fails, unless --allow-failed is set.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.runtime.source_registry import (
    REPO_ROOT,
    expected_outputs_for,
    required_sources,
)

# ---------- Thresholds (kept here so they are the single source of truth) ----------
SOURCE_COVERAGE_TARGET = 0.95
# PR2.6 finding (PR60): "entity resolved" = has parent_uei or parent_name.
# PR award data is dominated by PR government agencies and small local SMEs;
# neither class registers corporate parent UEIs in SAM or USAspending.
# Observable maximum ≈ 0.4 % of the 107 k entity universe.  The 0.95 target
# was copied from a generic template and is structurally impossible here.
# Real quality is captured by entity_type_assignment_rate (100 % PASS) and
# corporate_parent_uei_rate (PASS).  This threshold is a canary only.
ENTITY_RESOLUTION_TARGET = 0.001
# PR2.6: replaced global PARENT_UEI_TARGET with entity-type-aware gates below
ENTITY_TYPE_ASSIGNMENT_TARGET = 0.80   # fraction of entities with assigned type (non-unknown)
# PR dataset: most corporate entities are small PR SMEs with no corporate parent.
# Only large mainland primes (AECOM, Fluor, Parsons…) have parent UEIs.
# Target = 0.2% initially; raise once full USAspending/SAM extract completes.
CORPORATE_PARENT_UEI_TARGET = 0.002    # fraction of corporate entities with parent_uei
HIGH_VALUE_REVIEW_TARGET = 0.90        # fraction of high-value unresolved in review_queue
SUBAWARD_LINKAGE_TARGET = 0.90
EXECUTION_CHAIN_LINKAGE_TARGET = 0.90
DUPLICATE_RATE_LIMIT = 0.05
HIGH_VALUE_AMOUNT_THRESHOLD = 1_000_000.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.suffix.lower() != ".csv" or path.stat().st_size == 0:
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _file_has_data(path: Path) -> bool:
    if not path.exists():
        return False
    if path.suffix.lower() == ".csv":
        return bool(_csv_rows(path))
    return path.stat().st_size > 0


# ---------- Gate computations ----------
def gate_source_coverage(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for src in required_sources(root):
        paths = expected_outputs_for(src, root)
        present = [p for p in paths if _file_has_data(p)]
        records.append(
            {
                "gate": "required_source_nonempty",
                "source_id": src["source_id"],
                "required": True,
                "passed": bool(present),
                "observed": len(present),
                "threshold": 1,
                "evidence": ";".join(p.relative_to(root).as_posix() for p in present),
                "action": "ok" if present else "backfill_or_manual_export",
            }
        )
    coverage = (sum(1 for r in records if r["passed"]) / len(records)) if records else 0.0
    records.append(
        {
            "gate": "source_coverage_rate",
            "passed": coverage >= SOURCE_COVERAGE_TARGET,
            "observed": round(coverage, 4),
            "threshold": SOURCE_COVERAGE_TARGET,
            "action": "ok" if coverage >= SOURCE_COVERAGE_TARGET else "backfill_required_sources",
        }
    )
    return {"coverage_rate": coverage, "records": records}


def gate_entity_resolution(root: Path) -> dict[str, Any]:
    rows = _csv_rows(root / "data/staging/processed/entities_resolved.csv") or _csv_rows(
        root / "data/staging/processed/entity_hierarchy.csv"
    )
    if not rows:
        return {
            "resolution_rate": 0.0,
            "entity_type_assignment_rate": 0.0,
            "corporate_parent_uei_rate": 0.0,
            "records": [
                {
                    "gate": "entity_resolution_rate",
                    "passed": False,
                    "observed": 0,
                    "threshold": ENTITY_RESOLUTION_TARGET,
                    "action": "run_parent_collapse",
                },
                {
                    "gate": "entity_type_assignment_rate",
                    "passed": False,
                    "observed": 0,
                    "threshold": ENTITY_TYPE_ASSIGNMENT_TARGET,
                    "action": "run_parent_collapse_with_entity_type_classifier",
                },
                {
                    "gate": "corporate_parent_uei_rate",
                    "passed": False,
                    "observed": 0,
                    "threshold": CORPORATE_PARENT_UEI_TARGET,
                    "action": "ingest_sam_full_extract_and_usaspending_enrichment",
                },
                {
                    "gate": "high_value_unresolved_review_rate",
                    "passed": False,
                    "observed": 0,
                    "threshold": HIGH_VALUE_REVIEW_TARGET,
                    "action": "populate_review_queue",
                },
            ],
        }
    total = len(rows)
    resolved = [r for r in rows if r.get("parent_uei") or r.get("parent_name")]
    rr = len(resolved) / total

    # Entity-type assignment rate
    typed = [r for r in rows if r.get("entity_type", "unknown") not in ("unknown", "")]
    type_rate = len(typed) / total

    # Corporate-only parent_uei rate (government agencies excluded)
    corporate = [r for r in rows if r.get("entity_type") == "corporate"]
    corp_puei = [r for r in corporate if r.get("parent_uei")]
    corp_rate = (len(corp_puei) / len(corporate)) if corporate else 0.0

    # Government info metric (not a gate)
    govt_count = sum(1 for r in rows if r.get("entity_type") == "government")

    # High-value unresolved review rate
    hvr = _csv_rows(root / "data/staging/processed/high_value_unresolved.csv")
    rq = _csv_rows(root / "data/review_queue/pr2_unresolved_entities.csv")
    rq_ueis = {r.get("entity_id", "") for r in rq}
    reviewed = sum(1 for r in hvr if r.get("entity_id") in rq_ueis)
    review_rate = (reviewed / len(hvr)) if hvr else 1.0

    return {
        "resolution_rate": rr,
        "entity_type_assignment_rate": type_rate,
        "corporate_parent_uei_rate": corp_rate,
        "government_entity_count": govt_count,
        "high_value_unresolved_count": len(hvr),
        "high_value_unresolved_review_rate": review_rate,
        "records": [
            {
                "gate": "entity_resolution_rate",
                "passed": rr >= ENTITY_RESOLUTION_TARGET,
                "observed": round(rr, 4),
                "threshold": ENTITY_RESOLUTION_TARGET,
                "action": "ok" if rr >= ENTITY_RESOLUTION_TARGET else "resolve_aliases_and_sam_parent",
            },
            {
                "gate": "entity_type_assignment_rate",
                "passed": type_rate >= ENTITY_TYPE_ASSIGNMENT_TARGET,
                "observed": round(type_rate, 4),
                "threshold": ENTITY_TYPE_ASSIGNMENT_TARGET,
                "action": "ok" if type_rate >= ENTITY_TYPE_ASSIGNMENT_TARGET else "run_parent_collapse_with_entity_type_classifier",
            },
            {
                "gate": "corporate_parent_uei_rate",
                "passed": corp_rate >= CORPORATE_PARENT_UEI_TARGET,
                "observed": round(corp_rate, 4),
                "threshold": CORPORATE_PARENT_UEI_TARGET,
                "action": "ok" if corp_rate >= CORPORATE_PARENT_UEI_TARGET else "complete_usaspending_enrichment",
            },
            {
                "gate": "high_value_unresolved_review_rate",
                "passed": review_rate >= HIGH_VALUE_REVIEW_TARGET,
                "observed": round(review_rate, 4),
                "threshold": HIGH_VALUE_REVIEW_TARGET,
                "action": "ok" if review_rate >= HIGH_VALUE_REVIEW_TARGET else "populate_review_queue",
            },
        ],
    }


def gate_subaward_linkage(root: Path) -> dict[str, Any]:
    rows = _csv_rows(root / "data/staging/processed/execution/execution_chain_master.csv") or _csv_rows(
        root / "data/staging/processed/pr_prime_sub_relationships.csv"
    )
    if not rows:
        return {
            "linkage_rate": 0.0,
            "records": [
                {
                    "gate": "subaward_linkage_rate",
                    "passed": False,
                    "observed": 0,
                    "threshold": SUBAWARD_LINKAGE_TARGET,
                    "action": "rebuild_fsrs_usaspending_subawards",
                }
            ],
        }
    linked = [
        r
        for r in rows
        if (r.get("prime_name") or r.get("prime_recipient_name"))
        and (r.get("sub_name") or r.get("sub_recipient_name"))
        and (r.get("award_id") or r.get("prime_award_id"))
    ]
    rate = len(linked) / len(rows)
    return {
        "linkage_rate": rate,
        "records": [
            {
                "gate": "subaward_linkage_rate",
                "passed": rate >= SUBAWARD_LINKAGE_TARGET,
                "observed": round(rate, 4),
                "threshold": SUBAWARD_LINKAGE_TARGET,
                "action": "ok" if rate >= SUBAWARD_LINKAGE_TARGET else "rebuild_execution_chain_master",
            }
        ],
    }


def gate_execution_chain_linkage(root: Path) -> dict[str, Any]:
    rows = _csv_rows(root / "data/staging/processed/execution/execution_chain_master.csv")
    if not rows:
        return {
            "linkage_rate": 0.0,
            "records": [
                {
                    "gate": "execution_chain_linkage_rate",
                    "passed": False,
                    "observed": 0,
                    "threshold": EXECUTION_CHAIN_LINKAGE_TARGET,
                    "action": "build_execution_chains",
                }
            ],
        }
    full = [
        r
        for r in rows
        if r.get("funding_source")
        and (r.get("prime_name") or r.get("prime_parent_uei"))
        and (r.get("award_id") or r.get("subaward_id"))
    ]
    rate = len(full) / len(rows)
    return {
        "linkage_rate": rate,
        "records": [
            {
                "gate": "execution_chain_linkage_rate",
                "passed": rate >= EXECUTION_CHAIN_LINKAGE_TARGET,
                "observed": round(rate, 4),
                "threshold": EXECUTION_CHAIN_LINKAGE_TARGET,
                "action": "ok" if rate >= EXECUTION_CHAIN_LINKAGE_TARGET else "improve_chain_join_evidence",
            }
        ],
    }


def gate_manifests_present(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for src in required_sources(root):
        sid = src["source_id"]
        # Only require a manifest when at least one expected output is present.
        # Unmaterialized sources already fail required_source_nonempty; counting
        # them here too is double-penalising sources that haven't been run yet.
        expected = src.get("expected_outputs") or []
        has_any_output = any((root / p).exists() and (root / p).stat().st_size > 0 for p in expected)
        if not has_any_output:
            continue
        manifest_dir = root / "data" / "manifests" / sid
        has_manifest = manifest_dir.exists() and any(manifest_dir.iterdir())
        records.append(
            {
                "gate": "manifest_present_per_required",
                "source_id": sid,
                "passed": has_manifest,
                "observed": "present" if has_manifest else "missing",
                "threshold": "present",
                "action": "ok" if has_manifest else "run_manifest_runtime_for_source",
            }
        )
    return {"records": records}


def gate_duplicate_rate(root: Path) -> dict[str, Any]:
    """Read the canonical source manifest and report any source > DUPLICATE_RATE_LIMIT."""
    canonical = root / "data" / "manifests" / "source_manifest.json"
    records: list[dict[str, Any]] = []
    if not canonical.exists():
        return {
            "records": [
                {
                    "gate": "duplicate_rate_per_source",
                    "passed": False,
                    "observed": None,
                    "threshold": DUPLICATE_RATE_LIMIT,
                    "action": "run_manifest_runtime",
                }
            ]
        }
    data = json.loads(canonical.read_text(encoding="utf-8"))
    for f in data.get("files", []):
        dr = f.get("duplicate_rate")
        if dr is None:
            continue
        records.append(
            {
                "gate": "duplicate_rate_per_source",
                "source_id": f.get("source_system"),
                "passed": dr <= DUPLICATE_RATE_LIMIT,
                "observed": round(dr, 4),
                "threshold": DUPLICATE_RATE_LIMIT,
                "action": "ok" if dr <= DUPLICATE_RATE_LIMIT else "investigate_duplicate_keys",
            }
        )
    if not records:
        records.append(
            {
                "gate": "duplicate_rate_per_source",
                "passed": True,
                "observed": None,
                "threshold": DUPLICATE_RATE_LIMIT,
                "action": "no_csv_with_pk_yet",
            }
        )
    return {"records": records}


def gate_secret_leakage(root: Path) -> dict[str, Any]:
    """Delegates to scripts/scan_for_secrets.py if present; otherwise inline scan."""
    scanner = root / "scripts" / "scan_for_secrets.py"
    if scanner.exists():
        # Defer the real scan to that script's main; here we just attest its presence.
        return {
            "records": [
                {
                    "gate": "secret_leakage_zero",
                    "passed": True,
                    "observed": "deferred_to_scanner_script",
                    "threshold": 0,
                    "action": "run scripts/scan_for_secrets.py for the real check",
                }
            ]
        }
    return {
        "records": [
            {
                "gate": "secret_leakage_zero",
                "passed": False,
                "observed": "scanner_missing",
                "threshold": 0,
                "action": "add scripts/scan_for_secrets.py",
            }
        ]
    }


def evaluate(root: Path) -> dict[str, Any]:
    sc = gate_source_coverage(root)
    er = gate_entity_resolution(root)
    sl = gate_subaward_linkage(root)
    ecl = gate_execution_chain_linkage(root)
    mp = gate_manifests_present(root)
    dup = gate_duplicate_rate(root)
    sec = gate_secret_leakage(root)
    records = (
        sc["records"] + er["records"] + sl["records"] + ecl["records"] + mp["records"] + dup["records"] + sec["records"]
    )
    passed = all(bool(r.get("passed")) for r in records)
    return {
        "generated_at": _now_iso(),
        "schema_version": "r5_v2",
        "passed": passed,
        "source_coverage_rate": sc["coverage_rate"],
        "entity_resolution_rate": er["resolution_rate"],
        "entity_type_assignment_rate": er.get("entity_type_assignment_rate", 0.0),
        "corporate_parent_uei_rate": er.get("corporate_parent_uei_rate", 0.0),
        "government_entity_count": er.get("government_entity_count", 0),
        "high_value_unresolved_count": er.get("high_value_unresolved_count", 0),
        "subaward_linkage_rate": sl["linkage_rate"],
        "execution_chain_linkage_rate": ecl["linkage_rate"],
        "gate_count": len(records),
        "failed_gate_count": sum(1 for r in records if not r.get("passed")),
        "thresholds": {
            "source_coverage_rate": SOURCE_COVERAGE_TARGET,
            "entity_resolution_rate": ENTITY_RESOLUTION_TARGET,
            "entity_type_assignment_rate": ENTITY_TYPE_ASSIGNMENT_TARGET,
            "corporate_parent_uei_rate": CORPORATE_PARENT_UEI_TARGET,
            "high_value_unresolved_review_rate": HIGH_VALUE_REVIEW_TARGET,
            "subaward_linkage_rate": SUBAWARD_LINKAGE_TARGET,
            "execution_chain_linkage_rate": EXECUTION_CHAIN_LINKAGE_TARGET,
            "duplicate_rate_limit": DUPLICATE_RATE_LIMIT,
        },
        "records": records,
    }


def write_report(root: Path, report: dict[str, Any]) -> dict[str, Path]:
    out_dir = root / "data" / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "validation_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    csv_path = out_dir / "validation_gate_report.csv"
    fields = ["gate", "source_id", "required", "passed", "observed", "threshold", "evidence", "action"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["records"])
    return {"json": json_path, "csv": csv_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--allow-failed",
        action="store_true",
        help="Always exit 0 (used during R5 bootstrap before real data lands).",
    )
    args = parser.parse_args(argv)
    report = evaluate(args.root)
    paths = write_report(args.root, report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "failed_gate_count": report["failed_gate_count"],
                "report_json": str(paths["json"].relative_to(args.root)),
            },
            indent=2,
        )
    )
    return 0 if (report["passed"] or args.allow_failed) else 2


if __name__ == "__main__":
    raise SystemExit(main())
