"""R1 cache/staleness audit built on artifact lineage rows."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.validation.artifact_lineage import (
    LINEAGE_FIELDS,
    build_artifact_lineage_rows,
)
from contract_sweeper.validation.production_status import (
    STATUS_VALIDATED,
    load_current_status,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _has_manifest_for_source(source_path: Path) -> bool:
    candidates = (
        source_path.with_suffix(source_path.suffix + ".manifest.json"),
        source_path.parent / "manifest.json",
        source_path.parent / "_manifest.json",
    )
    return any(path.exists() for path in candidates)


def _detect_skip_download_recompute_guard(run_all_text: str) -> bool:
    return (
        "force_recompute_outputs = bool(skip_download)" in run_all_text
        and "_call_step(" in run_all_text
        and "force_recompute=force_recompute_outputs" in run_all_text
    )


def _detect_top_n_truncation(report_summary: dict[str, Any], power_summary: dict[str, Any], prime_sub_summary: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    unique_entities = _safe_int(report_summary.get("awards", {}).get("unique_entities"))
    total_ranked = _safe_int(report_summary.get("power_network", {}).get("total_ranked") or power_summary.get("total_entities"))
    prime_count = _safe_int(prime_sub_summary.get("prime_count"))
    sub_count = _safe_int(prime_sub_summary.get("sub_count"))
    top_entities_len = len(report_summary.get("awards", {}).get("top_entities", []) or [])

    if unique_entities and unique_entities <= 20:
        reasons.append(f"unique_entities is constrained to {unique_entities}")
    if total_ranked and total_ranked <= 20:
        reasons.append(f"power network ranked universe is constrained to {total_ranked}")
    if unique_entities and prime_count == unique_entities and sub_count == unique_entities:
        reasons.append("prime/sub counts exactly mirror entity universe")
    if unique_entities and top_entities_len == unique_entities:
        reasons.append("report top_entities list spans the full constrained universe")

    return bool(reasons), reasons


def _detect_fixture_demo_replay(report_summary: dict[str, Any], power_summary: dict[str, Any], prime_sub_summary: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    unique_entities = _safe_int(report_summary.get("awards", {}).get("unique_entities"))
    total_ranked = _safe_int(report_summary.get("power_network", {}).get("total_ranked") or power_summary.get("total_entities"))
    prime_count = _safe_int(prime_sub_summary.get("prime_count"))
    sub_count = _safe_int(prime_sub_summary.get("sub_count"))
    pair_count = _safe_int(prime_sub_summary.get("pair_count"))

    if unique_entities == 18:
        reasons.append("report unique_entities remains fixed at 18")
    if total_ranked == 18:
        reasons.append("power network total_ranked remains fixed at 18")
    if prime_count == 18 and sub_count == 18:
        reasons.append("prime/sub universes remain fixed at 18")
    if prime_count > 0 and sub_count > 0:
        dense_score = pair_count / max(prime_count * sub_count, 1)
        if dense_score >= 0.75:
            reasons.append("prime/sub matrix appears implausibly dense")

    return bool(reasons), reasons


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run_audit(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    report_summary = _read_json(root / "data/reports/pr_report_summary.json")
    power_summary = _read_json(root / "data/staging/processed/pr_power_network_summary.json")
    prime_sub_summary = _read_json(root / "data/staging/processed/pr_prime_sub_summary.json")
    production_status = load_current_status(root)

    lineage_rows = build_artifact_lineage_rows(root)
    _write_csv(exports_dir / "artifact_lineage_audit.csv", lineage_rows, list(LINEAGE_FIELDS))

    run_all_text = (root / "run_all.py").read_text(encoding="utf-8", errors="replace")
    skip_download_recompute_guard = _detect_skip_download_recompute_guard(run_all_text)
    topn_suspected, topn_reasons = _detect_top_n_truncation(report_summary, power_summary, prime_sub_summary)
    fixture_suspected, fixture_reasons = _detect_fixture_demo_replay(report_summary, power_summary, prime_sub_summary)

    cache_rows: list[dict[str, Any]] = []
    stale_count = 0
    cache_hit_count = 0
    missing_manifest_count = 0

    for row in lineage_rows:
        source_inputs = [Path(p) for p in str(row.get("source_inputs", "")).split("|") if p]
        missing_for_artifact = 0
        for rel in source_inputs:
            src = root / rel
            if not _has_manifest_for_source(src):
                missing_for_artifact += 1
        missing_manifest_count += missing_for_artifact

        stale = bool(row.get("stale_candidate"))
        cache_hit = bool(row.get("cache_hit"))
        stale_count += int(stale)
        cache_hit_count += int(cache_hit)

        finding_parts: list[str] = []
        if cache_hit:
            finding_parts.append("cache guard likely replayed existing artifact")
        if stale:
            finding_parts.append("artifact is older than one or more declared source inputs")
        if missing_for_artifact > 0:
            finding_parts.append(f"{missing_for_artifact} source inputs missing manifest metadata")
        if row.get("source_row_count", 0) == 0:
            finding_parts.append("declared source inputs are missing or empty")
        if topn_suspected:
            finding_parts.append("top-N truncation signature detected")
        if fixture_suspected:
            finding_parts.append("fixture/demo replay signature detected")

        cache_rows.append(
            {
                "artifact_path": row.get("artifact_path", ""),
                "artifact_type": row.get("artifact_type", ""),
                "producer_script": row.get("producer_script", ""),
                "producer_phase": row.get("producer_phase", ""),
                "cache_hit": cache_hit,
                "was_recomputed": bool(row.get("was_recomputed")),
                "stale_candidate": stale,
                "missing_manifest_count": missing_for_artifact,
                "skip_download_recompute_guard": skip_download_recompute_guard,
                "top_n_truncation_suspected": topn_suspected,
                "fixture_or_demo_replay_suspected": fixture_suspected,
                "finding": "; ".join(finding_parts) if finding_parts else "no immediate cache risk detected",
            }
        )

    _write_csv(
        exports_dir / "cache_reuse_audit.csv",
        cache_rows,
        [
            "artifact_path",
            "artifact_type",
            "producer_script",
            "producer_phase",
            "cache_hit",
            "was_recomputed",
            "stale_candidate",
            "missing_manifest_count",
            "skip_download_recompute_guard",
            "top_n_truncation_suspected",
            "fixture_or_demo_replay_suspected",
            "finding",
        ],
    )

    report_rows = [row for row in lineage_rows if str(row.get("artifact_path", "")).startswith("data/reports/")]
    reports_recomputed = bool(report_rows) and all(bool(row.get("was_recomputed")) for row in report_rows)
    stale_artifacts_labeled = stale_count > 0 and production_status.get("production_status") != STATUS_VALIDATED
    gate_passed = bool(reports_recomputed or stale_artifacts_labeled)

    phase_7_8_blocked = bool((not gate_passed) or production_status.get("production_status") != STATUS_VALIDATED)
    report_regeneration_status = (
        "reports_recomputed"
        if reports_recomputed
        else ("stale_labeled_non_production" if stale_artifacts_labeled else "cached_or_unverified")
    )

    rebuild_status = {
        "generated_at": _utc_now(),
        "reports_recomputed": reports_recomputed,
        "report_regeneration_status": report_regeneration_status,
        "downstream_recompute_count": sum(1 for row in lineage_rows if bool(row.get("was_recomputed"))),
        "stale_artifact_count": stale_count,
        "cache_hit_count": cache_hit_count,
        "missing_manifest_detected": missing_manifest_count > 0,
        "missing_manifest_count": missing_manifest_count,
        "top_n_truncation_suspected": topn_suspected,
        "top_n_truncation_reasons": topn_reasons,
        "fixture_or_demo_replay_suspected": fixture_suspected,
        "fixture_or_demo_replay_reasons": fixture_reasons,
        "skip_download_recompute_guard": skip_download_recompute_guard,
        "stale_artifacts_labeled": stale_artifacts_labeled,
        "r1_gate_passed": gate_passed,
        "phase_7_8_blocked": phase_7_8_blocked,
        "phase_7_8_block_reason": (
            "R1 gate failed or production status is not fully validated"
            if phase_7_8_blocked
            else "R1 gate passed and production status is validated"
        ),
        "artifact_lineage_output": "data/exports/artifact_lineage_audit.csv",
        "cache_reuse_output": "data/exports/cache_reuse_audit.csv",
    }

    _write_json(exports_dir / "rebuild_status.json", rebuild_status)
    return rebuild_status
