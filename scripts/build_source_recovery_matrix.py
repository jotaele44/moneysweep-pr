"""Source materialization readiness classifier.

Classifies every registered source by its **materialization path** and decides
whether it is *automatable* — i.e. can materialize with no human-supplied file
and no unbuilt code, given network egress (and an API key where required).

The target for "fill all sources to 100%" is the **automatable** set. Sources
that are not automatable are explicitly *queued* with a documented reason:
``manual_export`` (operator file), ``scraper_needed`` (PR-gov HTML/PDF surface
with no real fetcher yet), ``deferred_stub`` (intentionally unimplemented), or
``semantic_duplicate`` (covered by a sibling source).

Inputs (no network):
  - the live source registry (incl. extensions) via ``load_source_registry``
  - the live query-adapter registries (``ADAPTER_REGISTRY`` + ``ENTITY_ADAPTER_REGISTRY``)
  - per-source producer health via ``pipeline_preflight.classify_source_readiness``

Outputs (under ``reports/`` by default, deterministic / byte-identical on re-run):
  - ``source_recovery_matrix.csv``     — per-source readiness row
  - ``source_recovery_matrix.md``      — roll-up by path_type
  - ``materialization_readiness.json`` — headline readiness summary (the gate number)

The existing executable identity accepts optional ``--root`` and ``--out``
arguments for TheHub's typed GUI action contract. ``--check`` regenerates into
an isolated temporary directory and byte-compares the declared outputs, so a
validation run cannot overwrite the reference artifacts.

Read-only triage: no network, no registry edits.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.query.adapters import ADAPTER_REGISTRY, ENTITY_ADAPTER_REGISTRY
from moneysweep.runtime.source_registry import load_source_registry
from moneysweep.update_controller.policy import (
    REQUIRED_DAG,
    TERMINAL_PATH_TYPES,
    infer_trigger_type,
)
from scripts.pipeline_preflight import STRUCTURAL_STATUSES, classify_source_readiness

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = REPO_ROOT / "reports" / "source_recovery_matrix.csv"
OUT_MD = REPO_ROOT / "reports" / "source_recovery_matrix.md"
OUT_JSON = REPO_ROOT / "reports" / "materialization_readiness.json"
OUTPUT_NAMES = (
    "source_recovery_matrix.csv",
    "source_recovery_matrix.md",
    "materialization_readiness.json",
)

ADAPTER_SOURCE_IDS = set(ADAPTER_REGISTRY) | set(ENTITY_ADAPTER_REGISTRY)

# PR-gov HTML/PDF / custom surfaces with no real fetcher yet.
# Only genuine stubs remain here; sources with real scraping implementations
# have been promoted to api_producer so they appear in the automatable set.
# Curated domain knowledge — kept explicit on purpose.
SCRAPER_NEEDED = {
    "pr_act_154_excise",  # download_coverage_gap_intake.py — intentional deferred stub
}

# Sources fully covered by a sibling source; they never materialize independently.
SEMANTIC_DUPLICATES = {
    "fpds_report_builder": "usaspending_prime",
    "fsrs_subawards": "usaspending_subawards",
    "congressional_earmarks": "usaspending_grants_gov",
}

DEFERRED_PRODUCER = "scripts/download_nara_nextgen.py"
DEFERRED_NOTE_MARKERS = ("intentionally not implemented", "deferred")

# path_type -> automatable + recommended action.
PATH_TYPES = {
    "api_adapter": (
        True,
        "Materialize via `python -m moneysweep.query --source <id>` (set key if gated).",
    ),
    "api_producer": (
        True,
        "Run producer under strict preflight; public API path, set key if gated.",
    ),
    "manual_export": (
        False,
        "Operator delivers file to the dropzone; see manual_export_registry.yaml + runbook.",
    ),
    "scraper_needed": (
        False,
        "Queued: needs a scraping adapter for the PR-gov HTML/PDF surface.",
    ),
    "deferred_stub": (
        False,
        "Intentionally unimplemented; remains not_materialized by design.",
    ),
    "semantic_duplicate": (
        False,
        "No action; covered by sibling source.",
    ),
    "broken_producer": (
        False,
        "Repair: producer fails import / has no callable entrypoint / is missing.",
    ),
}

QUEUED_PATH_TYPES = (
    "manual_export",
    "scraper_needed",
    "deferred_stub",
    "semantic_duplicate",
    "broken_producer",
)


def _outputs_present(expected_outputs: list[str], root: Path | None = None) -> tuple[int, int]:
    """Declared outputs present on disk OR recorded in the committed staging
    manifest — the same clean-checkout fallback as gap_analysis_builder, so the
    committed matrix regenerates byte-identically in CI where the gitignored
    masters are absent."""
    from scripts.gap_analysis_builder import _staging_manifest

    root = root or REPO_ROOT
    manifest = _staging_manifest(root)
    present = sum(
        1
        for p in expected_outputs
        if p and ((root / p).exists() or manifest.get(p, {}).get("row_count", 0) >= 1)
    )
    return len(expected_outputs), present


def _is_deferred(src: dict) -> bool:
    if (src.get("producer_script") or "") == DEFERRED_PRODUCER:
        return True
    notes = (src.get("notes") or "").lower()
    return any(marker in notes for marker in DEFERRED_NOTE_MARKERS)


def _classify(src: dict, root: Path | None = None) -> str:
    """Return the path_type for a source (priority-ordered)."""
    sid = src.get("source_id", "")
    auth = (src.get("authentication") or "").strip()
    if _is_deferred(src):
        return "deferred_stub"
    if sid in SEMANTIC_DUPLICATES:
        return "semantic_duplicate"
    if auth == "manual_export" or src.get("manual_drop_dir"):
        return "manual_export"
    if sid in SCRAPER_NEEDED:
        return "scraper_needed"
    # Structural producer defect (import error / missing callable / missing script).
    preflight = classify_source_readiness(root or REPO_ROOT, src)["readiness_status"]
    if sid not in ADAPTER_SOURCE_IDS and preflight in STRUCTURAL_STATUSES:
        return "broken_producer"
    if sid in ADAPTER_SOURCE_IDS:
        return "api_adapter"
    return "api_producer"


def build_registry_snapshot(sources: list[dict]) -> dict:
    """Deterministic count + source-id hash computed from the live registry (spec §16)."""
    source_ids = sorted(src["source_id"] for src in sources)
    digest = hashlib.sha256(("\n".join(source_ids) + "\n").encode("utf-8")).hexdigest()
    return {
        "source_count": len(source_ids),
        "source_ids_sha256": digest,
    }


def build_rows(root: Path | None = None) -> list[dict]:
    """Readiness rows for every registered source.

    ``root`` defaults to this repo checkout; callers reporting against another
    tree must pass it so registry, outputs, and preflight all read from the same
    tree.
    """
    root = root or REPO_ROOT
    sources = load_source_registry(root).get("sources", [])
    rows: list[dict] = []
    for src in sources:
        sid = src.get("source_id", "")
        auth = (src.get("authentication") or "").strip()
        cadence = str(src.get("update_cadence") or "").strip().lower()
        expected = list(src.get("expected_outputs") or [])
        total, present = _outputs_present(expected, root)
        min_rows = (src.get("validation_threshold") or {}).get("min_rows", 1)
        path_type = _classify(src, root)
        automatable, action = PATH_TYPES[path_type]
        needs_key = auth.split("api_key:", 1)[1] if auth.startswith("api_key:") else ""
        has_adapter = sid in ADAPTER_SOURCE_IDS
        preflight = classify_source_readiness(root, src)["readiness_status"]
        producer_importable = preflight not in STRUCTURAL_STATUSES
        ready = bool(automatable and (has_adapter or producer_importable) and total > 0)
        dag_parents = list(REQUIRED_DAG.get(sid, []))
        trigger_type = (
            infer_trigger_type(path_type, cadence, dag_parents, path_type == "manual_export")
            or "disabled"
        )
        rows.append(
            {
                "source_id": sid,
                "required": bool(src.get("required", False)),
                "family": src.get("family", ""),
                "update_cadence": cadence,
                "authentication": auth,
                "required_secret": needs_key,
                "trigger_type": trigger_type,
                "terminal": path_type in TERMINAL_PATH_TYPES,
                "path_type": path_type,
                "automatable": automatable,
                "ready": ready,
                "needs_key": needs_key,
                "has_adapter": has_adapter,
                "producer_importable": producer_importable,
                "producer_script": src.get("producer_script", ""),
                "expected_outputs_count": total,
                "outputs_present_count": present,
                "min_rows": min_rows,
                "dropzone_path": src.get("manual_drop_dir", "") or "",
                "recommended_action": action,
            }
        )
    rows.sort(key=lambda r: (not r["automatable"], r["path_type"], r["source_id"]))
    return rows


def build_summary(rows: list[dict], root: Path | None = None) -> dict:
    root = root or REPO_ROOT
    automatable = [r for r in rows if r["automatable"]]
    queued = Counter(r["path_type"] for r in rows if not r["automatable"])
    needs_key = sorted({r["needs_key"] for r in automatable if r["needs_key"]})
    snapshot = build_registry_snapshot([{"source_id": r["source_id"]} for r in rows])
    reg = load_source_registry(root)
    return {
        "schema_version": "r5_readiness_v1",
        "total_sources": len(rows),
        "automatable_total": len(automatable),
        "automatable_ready": sum(1 for r in automatable if r["ready"]),
        "automatable_not_ready": sorted(r["source_id"] for r in automatable if not r["ready"]),
        "automatable_needs_key_count": sum(1 for r in automatable if r["needs_key"]),
        "automatable_required_keys": needs_key,
        "queued_excluded": {k: queued.get(k, 0) for k in QUEUED_PATH_TYPES},
        "queued_excluded_total": sum(queued.values()),
        "source_count_provenance": {
            "computed_from_live_registry": True,
            "registry_schema_version": str(reg.get("schema_version") or ""),
            "source_ids_sha256": snapshot["source_ids_sha256"],
            "historical_counts_are_non_authoritative": True,
        },
        "outputs": [
            "reports/source_recovery_matrix.csv",
            "reports/source_recovery_matrix.md",
            "reports/materialization_readiness.json",
        ],
    }


def _write_csv(rows: list[dict]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_md(rows: list[dict], summary: dict) -> None:
    counts = Counter(r["path_type"] for r in rows)
    lines = ["# Source Materialization Readiness", ""]
    lines.append(f"Total sources: **{summary['total_sources']}**")
    lines.append(
        f"Automatable: **{summary['automatable_total']}** "
        f"(ready: **{summary['automatable_ready']}**, "
        f"need API key at run time: {summary['automatable_needs_key_count']})"
    )
    lines.append(f"Queued / excluded: **{summary['queued_excluded_total']}**")
    lines.append("")
    lines.append("## Path types")
    lines.append("")
    lines.append("| path_type | automatable | count | recommended_action |")
    lines.append("| --- | --- | --- | --- |")
    for pt in sorted(counts, key=lambda b: (not PATH_TYPES[b][0], -counts[b], b)):
        lines.append(f"| `{pt}` | {PATH_TYPES[pt][0]} | {counts[pt]} | {PATH_TYPES[pt][1]} |")
    lines.append("")
    if summary["automatable_required_keys"]:
        lines.append(
            "API keys needed for full automatable materialization: "
            + ", ".join(f"`{k}`" for k in summary["automatable_required_keys"])
        )
        lines.append("")
    for pt in sorted(counts):
        members = sorted(r["source_id"] for r in rows if r["path_type"] == pt)
        lines.append(f"## {pt} ({len(members)})")
        lines.append("")
        for member in members:
            lines.append(f"- `{member}`")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def _set_outputs(out: Path) -> None:
    global OUT_CSV, OUT_MD, OUT_JSON
    OUT_CSV = out / OUTPUT_NAMES[0]
    OUT_MD = out / OUTPUT_NAMES[1]
    OUT_JSON = out / OUTPUT_NAMES[2]


def _build(root: Path, out: Path) -> dict:
    _set_outputs(out)
    rows = build_rows(root)
    summary = build_summary(rows, root)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(rows)
    _write_md(rows, summary)
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PASS",
        "row_count": len(rows),
        "automatable_ready": summary["automatable_ready"],
        "automatable_total": summary["automatable_total"],
        "queued_excluded_total": summary["queued_excluded_total"],
        "outputs": [str(out / name) for name in OUTPUT_NAMES],
    }


def _check(root: Path, expected_out: Path) -> dict:
    global OUT_CSV, OUT_MD, OUT_JSON
    original_outputs = (OUT_CSV, OUT_MD, OUT_JSON)
    try:
        with tempfile.TemporaryDirectory(prefix="moneysweep-source-recovery-") as tmp:
            generated = Path(tmp)
            result = _build(root, generated)
            mismatches: list[str] = []
            for name in OUTPUT_NAMES:
                expected = expected_out / name
                candidate = generated / name
                if not expected.is_file():
                    mismatches.append(f"missing expected output: {expected}")
                elif expected.read_bytes() != candidate.read_bytes():
                    mismatches.append(f"byte mismatch: {expected}")
            result["status"] = "PASS" if not mismatches else "FAIL"
            result["mismatches"] = mismatches
            result["outputs"] = [str(expected_out / name) for name in OUTPUT_NAMES]
            return result
    finally:
        OUT_CSV, OUT_MD, OUT_JSON = original_outputs


def _parse_args(argv: list[str]) -> tuple[Path, Path, bool, bool]:
    """Parse the small typed contract without creating a second CLI framework surface."""
    root = REPO_ROOT
    out = REPO_ROOT / "reports"
    check = False
    json_output = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in {"--root", "--out"}:
            if index + 1 >= len(argv):
                raise ValueError(f"{token} requires a path")
            value = Path(argv[index + 1]).expanduser().resolve()
            if token == "--root":
                root = value
            else:
                out = value
            index += 2
            continue
        if token == "--check":
            check = True
        elif token == "--json":
            json_output = True
        else:
            raise ValueError(f"unknown argument: {token}")
        index += 1
    return root, out, check, json_output


def main(argv: list[str] | None = None) -> int:
    try:
        root, out, check, json_output = _parse_args(list(sys.argv[1:] if argv is None else argv))
        result = _check(root, out) if check else _build(root, out)
    except Exception as exc:  # fail closed for manager/CI callers
        result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        json_output = "--json" in (sys.argv[1:] if argv is None else argv)

    if json_output:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
