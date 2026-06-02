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

Outputs (under ``reports/``, deterministic / byte-identical on re-run):
  - ``source_recovery_matrix.csv``     — per-source readiness row
  - ``source_recovery_matrix.md``      — roll-up by path_type
  - ``materialization_readiness.json`` — headline readiness summary (the gate number)

Read-only triage: no network, no writes outside ``reports/``, no registry edits.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.query.adapters import ADAPTER_REGISTRY, ENTITY_ADAPTER_REGISTRY
from contract_sweeper.runtime.source_registry import load_source_registry
from scripts.pipeline_preflight import STRUCTURAL_STATUSES, classify_source_readiness

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = REPO_ROOT / "reports" / "source_recovery_matrix.csv"
OUT_MD = REPO_ROOT / "reports" / "source_recovery_matrix.md"
OUT_JSON = REPO_ROOT / "reports" / "materialization_readiness.json"

ADAPTER_SOURCE_IDS = set(ADAPTER_REGISTRY) | set(ENTITY_ADAPTER_REGISTRY)

# PR-gov HTML/PDF / custom surfaces whose producer is a placeholder, not a real
# fetcher. Queued for a dedicated scraping-adapter design pass (out of scope of
# the automatable fill). Curated domain knowledge — kept explicit on purpose.
SCRAPER_NEEDED = {
    "compras_pr", "aafaf", "hacienda", "cofina", "prepa_luma_genera",
    "cor3", "prasa", "p3_authority",
    "pr_act_60_decrees", "promesa_creditors", "rum_cover_over",
    "municipal_finance", "pr_pensions", "eqb_epa_icis",
    "pr_cabilderos", "donaciones_pr", "follow_the_money",
    "emma_bonds", "msrb_rtrs_trades",
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
        "Materialize via `python -m contract_sweeper.query --source <id>` (set key if gated).",
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
    "manual_export", "scraper_needed", "deferred_stub",
    "semantic_duplicate", "broken_producer",
)


def _outputs_present(expected_outputs: list[str]) -> tuple[int, int]:
    present = sum(1 for p in expected_outputs if p and (REPO_ROOT / p).exists())
    return len(expected_outputs), present


def _is_deferred(src: dict) -> bool:
    if (src.get("producer_script") or "") == DEFERRED_PRODUCER:
        return True
    notes = (src.get("notes") or "").lower()
    return any(marker in notes for marker in DEFERRED_NOTE_MARKERS)


def _classify(src: dict) -> str:
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
    preflight = classify_source_readiness(REPO_ROOT, src)["readiness_status"]
    if sid not in ADAPTER_SOURCE_IDS and preflight in STRUCTURAL_STATUSES:
        return "broken_producer"
    if sid in ADAPTER_SOURCE_IDS:
        return "api_adapter"
    return "api_producer"


def build_rows() -> list[dict]:
    sources = load_source_registry(REPO_ROOT).get("sources", [])
    rows: list[dict] = []
    for src in sources:
        sid = src.get("source_id", "")
        auth = (src.get("authentication") or "").strip()
        expected = list(src.get("expected_outputs") or [])
        total, present = _outputs_present(expected)
        min_rows = (src.get("validation_threshold") or {}).get("min_rows", 1)
        path_type = _classify(src)
        automatable, action = PATH_TYPES[path_type]
        needs_key = auth.split("api_key:", 1)[1] if auth.startswith("api_key:") else ""
        has_adapter = sid in ADAPTER_SOURCE_IDS
        preflight = classify_source_readiness(REPO_ROOT, src)["readiness_status"]
        producer_importable = preflight not in STRUCTURAL_STATUSES
        # Structurally ready = automatable, has a working entrypoint, and declares outputs.
        ready = bool(automatable and (has_adapter or producer_importable) and total > 0)
        rows.append({
            "source_id": sid,
            "required": bool(src.get("required", False)),
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
        })
    rows.sort(key=lambda r: (not r["automatable"], r["path_type"], r["source_id"]))
    return rows


def build_summary(rows: list[dict]) -> dict:
    automatable = [r for r in rows if r["automatable"]]
    queued = Counter(r["path_type"] for r in rows if not r["automatable"])
    needs_key = sorted({r["needs_key"] for r in automatable if r["needs_key"]})
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
        "outputs": [
            "reports/source_recovery_matrix.csv",
            "reports/source_recovery_matrix.md",
            "reports/materialization_readiness.json",
        ],
    }


def _write_csv(rows: list[dict]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
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
        lines.append(
            f"| `{pt}` | {PATH_TYPES[pt][0]} | {counts[pt]} | {PATH_TYPES[pt][1]} |"
        )
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
        for m in members:
            lines.append(f"- `{m}`")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = build_rows()
    summary = build_summary(rows)
    _write_csv(rows)
    _write_md(rows, summary)
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(REPO_ROOT)} ({len(rows)} rows)")
    print(f"wrote {OUT_MD.relative_to(REPO_ROOT)}")
    print(f"wrote {OUT_JSON.relative_to(REPO_ROOT)}")
    print(
        f"  automatable_ready={summary['automatable_ready']}/"
        f"{summary['automatable_total']}  queued={summary['queued_excluded_total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
