"""Fail-closed audit for USAspending unified-master build inputs.

This tool audits an evidence root only. Historical readiness/status reports are
observations and can never manufacture missing input bytes. It does not build the
master, grant source materialization credit, or mutate production reports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACTS = "data/staging/processed/pr_contracts_master.csv"
CANONICAL = [
    "pr_grants_master.csv",
    "pr_subawards_master.csv",
    "pr_fema_pa_master.csv",
    "pr_fema_hmgp_master.csv",
    "pr_research_master.csv",
    "pr_sba_loans_master.csv",
    "pr_slfrf_master.csv",
    "pr_cdbg_dr_master.csv",
    "pr_dot_master.csv",
    "pr_usda_master.csv",
    "pr_doe_master.csv",
    "pr_hud_master.csv",
    "pr_sbir_master.csv",
    "pr_epa_master.csv",
    "pr_usace_civil_master.csv",
    "pr_wioa_grants.csv",
]
OPTIONAL = {"data/staging/processed/pr_hud_master.csv"}
EXPANSIONS = [
    "data/staging/expansion/expansion_idv_indirect_pr.csv",
    "data/staging/expansion/expansion_dod_upr_2001_2015.csv",
    "data/staging/expansion/expansion_dod_upr_2016_2025.csv",
    "data/staging/expansion/expansion_reconstruction_2017_2025.csv",
]
OUTPUT = "data/staging/processed/pr_all_awards_master.csv"


class AuditError(ValueError):
    pass


def _safe(root: Path, rel: str) -> Path:
    if not rel or "\\" in rel or "\x00" in rel:
        raise AuditError("unsafe_path")
    p = PurePosixPath(rel)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise AuditError("unsafe_path")
    current = root.resolve()
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise AuditError("symlink_path")
    resolved = current.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise AuditError("path_escape")
    return resolved


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inspect(root: Path, rel: str, *, required: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"path": rel, "required": required, "byte_present": False}
    try:
        path = _safe(root, rel)
        if not path.is_file():
            result["state"] = "MISSING"
            return result
        before = path.stat()
        result.update(byte_present=True, bytes=before.st_size, sha256=_sha(path))
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh, strict=True)
                header = next(reader, None)
                if not header or len(set(header)) != len(header) or any(h == "" for h in header):
                    raise AuditError("invalid_csv_header")
                rows = 0
                for row in reader:
                    if len(row) != len(header):
                        raise AuditError("csv_row_width_mismatch")
                    rows += 1
            result.update(rows=rows, columns_raw=header)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise AuditError("file_changed_during_audit")
        result["state"] = "BYTE_VALIDATED"
    except (OSError, UnicodeError, csv.Error, AuditError) as exc:
        result["state"] = "INVALID"
        result["error"] = str(exc)
    return result


def _reported_presence(status_csv: Path | None) -> dict[str, str]:
    if status_csv is None or not status_csv.is_file():
        return {}
    output: dict[str, str] = {}
    with status_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            sid = str(row.get("source_id", "")).strip()
            if sid:
                output[sid] = str(row.get("pipeline_status", "")).strip()
    return output


def audit(root: Path, status_csv: Path | None = None) -> dict[str, Any]:
    required = [CONTRACTS] + [f"data/staging/processed/{x}" for x in CANONICAL] + EXPANSIONS
    rows = [_inspect(root, rel, required=rel not in OPTIONAL) for rel in required]
    if len({r["path"] for r in rows}) != len(rows):
        raise AuditError("duplicate_input_contract")
    missing_required = [r["path"] for r in rows if r["required"] and r["state"] != "BYTE_VALIDATED"]
    invalid = [r["path"] for r in rows if r["state"] == "INVALID"]
    reports = _reported_presence(status_csv)
    output = _inspect(root, OUTPUT, required=False)
    state = "READY_TO_BUILD" if not missing_required and not invalid else "BLOCKED_INPUT_CORPUS"
    return {
        "schema_version": "moneysweep.unified_master_input_audit/v1",
        "source_id": "usaspending_prime",
        "claim_scope": "evidence_root_byte_manifestation_only",
        "state": state,
        "production_eligible": False,
        "builder_contract": {
            "required_input_count": sum(r["required"] for r in rows),
            "optional_input_count": sum(not r["required"] for r in rows),
            "declared_output": OUTPUT,
            "require_all_inputs": True,
        },
        "inputs": rows,
        "output": output,
        "reported_source_status": reports.get("usaspending_prime"),
        "reported_presence_is_byte_evidence": False,
        "missing_required": missing_required,
        "invalid_inputs": invalid,
        "blockers": (["required_input_bytes_missing"] if missing_required else [])
        + (["invalid_input_bytes"] if invalid else []),
        "closure_requirements": [
            "Recover or mount every required authoritative input byte under a frozen evidence root.",
            "Validate schema and row integrity before the build.",
            "Run build_unified_master.py with require_all_inputs=True.",
            "Hash all build inputs and outputs and bind them to the current source definition receipt.",
            "Do not infer byte presence from historical/local readiness or source status reports.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--status-csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root.resolve(), args.status_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"state": report["state"], "missing_required": len(report["missing_required"])}, sort_keys=True))
    return 0 if report["state"] == "READY_TO_BUILD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
