"""Build reports/source_audit_matrix.csv from canonical inputs.

Static (Phase-1) audit: cross-references three signals per source_id:
  1. source_registry_status.csv — declared producer / output / status
  2. scripts/ tree — whether the producer script file exists
  3. run_all.py — whether the producer is imported into the pipeline
  4. data/staging/processed/ — whether declared outputs exist on disk

No network calls. No module execution. Re-runnable.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "reports" / "source_registry_status.csv"
RUN_ALL = REPO_ROOT / "run_all.py"
SCRIPTS_DIR = REPO_ROOT / "scripts"
PROCESSED_DIR = REPO_ROOT / "data" / "staging" / "processed"
OUT = REPO_ROOT / "reports" / "source_audit_matrix.csv"

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+scripts\.([a-zA-Z_][a-zA-Z0-9_]*)")


def wired_modules() -> set[str]:
    mods: set[str] = set()
    for line in RUN_ALL.read_text().splitlines():
        m = IMPORT_RE.match(line)
        if m:
            mods.add(m.group(1))
    return mods


def find_outputs_on_disk(declared: str) -> list[str]:
    """For each ';'-separated declared output path, return the ones that exist."""
    found = []
    for raw in declared.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        path = REPO_ROOT / raw
        if path.exists():
            found.append(raw)
            continue
        if raw.endswith("/"):
            if path.is_dir() and any(path.iterdir()):
                found.append(raw)
            continue
        stem = path.stem
        parent = path.parent
        if parent.is_dir():
            for cand in parent.glob(f"{stem}*"):
                if cand.is_file():
                    found.append(str(cand.relative_to(REPO_ROOT)))
    return sorted(set(found))


def classify(row: dict, script_exists: bool, wired: bool, declared_outputs: list[str], outputs_on_disk: list[str]) -> tuple[str, str]:
    declared = row["pipeline_status"]
    auth = row["authentication"]
    n_declared = len(declared_outputs)
    n_present = len(outputs_on_disk)

    if declared == "fully_materialized":
        if n_present == 0 and not wired:
            return "DECLARED_GREEN_UNWIRED_NO_OUTPUT", "Registry claims materialized, producer NOT in run_all.py, no outputs on disk — unverifiable claim"
        if n_present == 0:
            return "DECLARED_GREEN_NO_OUTPUT_ON_DISK", "Registry claims materialized but no output files present in clone"
        if n_present < n_declared:
            return "DECLARED_GREEN_PARTIAL_ON_DISK", f"Registry claims materialized; only {n_present}/{n_declared} declared outputs on disk"
        return "DECLARED_GREEN_VERIFIED", ""

    if declared == "partially_materialized":
        if n_present == 0:
            return "DECLARED_PARTIAL_NO_OUTPUT_ON_DISK", "Registry claims partial but no output files present in clone"
        return "DECLARED_PARTIAL_VERIFIED", ""

    if auth.startswith("api_key"):
        return "BLOCKED_NEEDS_API_KEY", f"Requires {auth.split(':',1)[1]}"
    if auth == "manual_export":
        return "BLOCKED_MANUAL_EXPORT", "Producer requires operator-supplied export drop"
    if not script_exists:
        return "BLOCKED_NO_PRODUCER_SCRIPT", "Producer script declared in registry does not exist on disk"
    if not wired:
        return "BLOCKED_NOT_WIRED", "Producer script exists but is not imported by run_all.py"
    return "READY_NOT_MATERIALIZED", "Producer wired and unblocked; never executed in this clone"


def main() -> None:
    wired = wired_modules()

    with REGISTRY.open() as f:
        reg_rows = list(csv.DictReader(f))

    out_rows = []
    for row in reg_rows:
        producer = row["producer_script"]
        script_path = REPO_ROOT / producer
        script_exists = script_path.is_file()
        module_name = Path(producer).stem if producer.startswith("scripts/") else ""
        is_wired = module_name in wired

        declared_outputs = [p.strip() for p in row["expected_outputs"].split(";") if p.strip()]
        outputs_on_disk = find_outputs_on_disk(row["expected_outputs"])
        status, audit_note = classify(row, script_exists, is_wired, declared_outputs, outputs_on_disk)

        out_rows.append({
            "source_id": row["source_id"],
            "family": row["family"],
            "required": row["required"],
            "authentication": row["authentication"],
            "producer_script": producer,
            "producer_script_exists": script_exists,
            "producer_wired_in_run_all": is_wired,
            "declared_status": row["pipeline_status"],
            "expected_outputs": row["expected_outputs"],
            "outputs_on_disk_count": len(outputs_on_disk),
            "outputs_on_disk": ";".join(outputs_on_disk),
            "audit_status": status,
            "audit_note": audit_note,
            "registry_blocker_notes": row["blocker_notes"],
        })

    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    counts: dict[str, int] = {}
    for r in out_rows:
        counts[r["audit_status"]] = counts.get(r["audit_status"], 0) + 1
    print(f"Wrote {OUT.relative_to(REPO_ROOT)} ({len(out_rows)} rows)")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {status}")


if __name__ == "__main__":
    main()
