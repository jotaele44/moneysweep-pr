"""Phase 6.5 artifact freshness and entity-universe audit.

This diagnostic is intentionally read-only against pipeline inputs. It writes
audit artifacts that explain whether reports are being rebuilt from current
intermediates or replayed from stale/cached/staged outputs.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REPORT_SUMMARY = Path("data/reports/pr_report_summary.json")
REPORT_MARKDOWN = Path("data/reports/pr_investigative_report.md")
POWER_SUMMARY = Path("data/staging/processed/pr_power_network_summary.json")
PRIME_SUB_SUMMARY = Path("data/staging/processed/pr_prime_sub_summary.json")
GRAPH_SUMMARY = Path("data/staging/processed/graph/network_summary.json")
DOMINANCE_SUMMARY = Path("data/staging/processed/dominance_summary.json")
ALL_AWARDS_SUMMARY = Path("data/staging/processed/pr_all_awards_summary.json")

EXPECTED_REPORT_LAYER_COUNT = 10
REQUIRED_REPORT_LAYERS_FOR_PRODUCTION = 8
MIN_ENTITY_UNIVERSE_FOR_PRODUCTION = 100

PRODUCTION_GATE_FIELDS = [
    "unique_normalized_entity_count",
    "entity_resolution_rate",
    "parent_uei_coverage",
    "graph_node_coverage_pct",
    "fixture_or_synthetic_data_detected",
    "high_value_overcollapse_suspect_count",
    "report_layers_populated",
    "bond_actor_count",
    "self_pair_ratio",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_generated_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _mtime_utc(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() and path.is_file() else 0


def _csv_row_count(path: Path) -> int:
    if not path.exists() or path.suffix.lower() != ".csv":
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except OSError:
        return 0


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _normalize_name(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    suffixes = {"INC", "LLC", "CORP", "CORPORATION", "COMPANY", "CO", "LTD", "THE", "OF", "AND"}
    tokens = text.split()
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _extract_generated_at_from_report(report_text: str) -> str:
    match = re.search(r"Generated:\s*([^*]+)", report_text)
    return match.group(1).strip() if match else ""


def _extract_prime_sub_pairs_from_report(report_text: str) -> list[dict[str, Any]]:
    lines = report_text.splitlines()
    in_section = False
    rows: list[dict[str, Any]] = []
    for line in lines:
        if line.startswith("## 3. Prime-to-Subcontractor"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Prime", "-------"}:
            continue
        rows.append(
            {
                "prime": cells[0],
                "sub": cells[1],
                "flow": cells[2],
                "contracts": cells[3],
            }
        )
    return rows


def load_entity_lineage_lookup(root: Path) -> dict[str, dict[str, str]]:
    """Load UEI/parent lineage from entity_master and entity_hierarchy when available."""
    lookup: dict[str, dict[str, str]] = {}

    entity_master_path = root / "data" / "staging" / "processed" / "entity_master.csv"
    if entity_master_path.exists():
        try:
            df_entity = pd.read_csv(entity_master_path, dtype=str, low_memory=False).fillna("")
            for _, row in df_entity.iterrows():
                key = (
                    str(row.get("entity_key") or row.get("canonical_name_normalized") or "").strip()
                    or _normalize_name(row.get("canonical_name"))
                )
                if not key:
                    continue
                entry = lookup.setdefault(key, {"recipient_uei": "", "parent_uei": "", "parent_name": ""})
                recipient_uei = str(row.get("recipient_uei") or "").strip()
                parent_uei = str(row.get("parent_uei") or "").strip()
                parent_name = str(row.get("parent_name") or "").strip()
                if recipient_uei and not entry["recipient_uei"]:
                    entry["recipient_uei"] = recipient_uei
                if parent_uei and not entry["parent_uei"]:
                    entry["parent_uei"] = parent_uei
                if parent_name and not entry["parent_name"]:
                    entry["parent_name"] = parent_name
        except Exception:
            pass

    hierarchy_path = root / "data" / "staging" / "processed" / "enrichment" / "entity_hierarchy.csv"
    if hierarchy_path.exists():
        try:
            df_hierarchy = pd.read_csv(hierarchy_path, dtype=str, low_memory=False).fillna("")
            for _, row in df_hierarchy.iterrows():
                key = _normalize_name(row.get("vendor_name") or row.get("recipient_name"))
                if not key:
                    continue
                entry = lookup.setdefault(key, {"recipient_uei": "", "parent_uei": "", "parent_name": ""})
                recipient_uei = str(row.get("uei") or row.get("recipient_uei") or "").strip()
                parent_uei = str(row.get("parent_uei") or "").strip()
                parent_name = str(row.get("parent_name") or "").strip()
                if recipient_uei and not entry["recipient_uei"]:
                    entry["recipient_uei"] = recipient_uei
                if parent_uei and not entry["parent_uei"]:
                    entry["parent_uei"] = parent_uei
                if parent_name and not entry["parent_name"]:
                    entry["parent_name"] = parent_name
        except Exception:
            pass

    return lookup


def collect_entity_universe(
    report_summary: dict[str, Any],
    power_summary: dict[str, Any],
    lineage_lookup: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Collect entity rows visible from checked-in summaries."""

    rows: dict[str, dict[str, Any]] = {}
    awards = report_summary.get("awards", {})
    for rank, entity in enumerate(awards.get("top_entities", []) or [], 1):
        name = str(entity.get("name", "")).strip()
        if not name:
            continue
        key = _normalize_name(name)
        rows[key] = {
            "entity_key": key,
            "canonical_name": name,
            "seen_in_awards": True,
            "seen_in_power_network": False,
            "award_rank": rank,
            "power_rank": "",
            "total_obligated": round(_safe_float(entity.get("obligated")), 2),
            "influence_score": "",
            "source_presence": "",
            "parent_uei": "",
            "recipient_uei": "",
            "audit_note": "visible in report summary top_entities",
        }

    for entity in power_summary.get("top_entities", []) or []:
        name = str(entity.get("name", "")).strip()
        if not name:
            continue
        key = _normalize_name(name)
        row = rows.setdefault(
            key,
            {
                "entity_key": key,
                "canonical_name": name,
                "seen_in_awards": False,
                "seen_in_power_network": True,
                "award_rank": "",
                "power_rank": "",
                "total_obligated": "",
                "influence_score": "",
                "source_presence": "",
                "parent_uei": "",
                "recipient_uei": "",
                "audit_note": "visible in power summary only",
            },
        )
        row["seen_in_power_network"] = True
        row["power_rank"] = _safe_int(entity.get("rank"))
        row["influence_score"] = _safe_float(entity.get("influence_score"))
        row["source_presence"] = _safe_int(entity.get("source_presence"))
        if row["total_obligated"] in {"", 0}:
            row["total_obligated"] = round(_safe_float(entity.get("awards_total")), 2)
    lineage_lookup = lineage_lookup or {}
    for key, row in rows.items():
        lineage = lineage_lookup.get(key, {})
        if not lineage:
            continue
        if not str(row.get("recipient_uei") or "").strip():
            row["recipient_uei"] = lineage.get("recipient_uei", "")
        if not str(row.get("parent_uei") or "").strip():
            row["parent_uei"] = lineage.get("parent_uei", "")

    return sorted(rows.values(), key=lambda row: _safe_float(row.get("total_obligated")), reverse=True)


def build_artifact_lineage(root: Path, report_summary: dict[str, Any], report_text: str) -> list[dict[str, Any]]:
    artifact_paths = [
        REPORT_MARKDOWN,
        REPORT_SUMMARY,
        POWER_SUMMARY,
        PRIME_SUB_SUMMARY,
        GRAPH_SUMMARY,
        DOMINANCE_SUMMARY,
        ALL_AWARDS_SUMMARY,
        Path("data/staging/processed/pr_power_network.csv"),
        Path("data/staging/processed/pr_prime_sub_relationships.csv"),
        Path("data/staging/processed/entity_master.csv"),
        Path("data/staging/processed/pr_bond_flow.csv"),
        Path("data/staging/processed/pr_emma_bonds.csv"),
        Path("data/staging/processed/pr_emma_underwriters.csv"),
        Path("data/staging/processed/graph/entity_edges.csv"),
        Path("data/staging/processed/graph/top_nodes.csv"),
        Path("data/staging/processed/graph/network.graphml"),
    ]
    report_generated_at = str(report_summary.get("generated_at") or _extract_generated_at_from_report(report_text))
    rows: list[dict[str, Any]] = []
    for rel in artifact_paths:
        path = root / rel
        payload = _read_json(path) if path.suffix == ".json" else {}
        generated_at = str(payload.get("generated_at") or (report_generated_at if rel == REPORT_MARKDOWN else ""))
        embedded_paths = []
        if payload:
            embedded_paths = [
                str(value)
                for value in re.findall(r"/[^\"']+", json.dumps(payload))
                if "Contract-Sweeper" in value
            ]
        rows.append(
            {
                "artifact_path": str(rel),
                "exists": path.exists(),
                "size_bytes": _file_size(path),
                "mtime_utc": _mtime_utc(path),
                "sha256": _sha256(path),
                "generated_at": generated_at,
                "row_count": _csv_row_count(path),
                "embedded_absolute_paths": "|".join(sorted(set(embedded_paths))),
                "lineage_issue": _lineage_issue(path, embedded_paths),
            }
        )
    return rows


def _lineage_issue(path: Path, embedded_paths: list[str]) -> str:
    if not path.exists():
        return "missing_artifact"
    if any(p.startswith("/home/user/Contract-Sweeper") for p in embedded_paths):
        return "embedded_path_points_to_different_workspace"
    if path.suffix == ".json" and path.name.endswith("_summary.json"):
        return "summary_present"
    return ""


def collect_source_refresh_range(root: Path) -> dict[str, Any]:
    source_files = [
        p for p in (root / "data").rglob("*")
        if p.is_file()
        and "/data/staging/processed/" not in str(p)
        and "/data/reports/" not in str(p)
        and p.name != ".gitkeep"
    ]
    if not source_files:
        return {"source_file_count": 0, "oldest_source_mtime_utc": "", "newest_source_mtime_utc": ""}
    mtimes = [datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) for p in source_files]
    return {
        "source_file_count": len(source_files),
        "oldest_source_mtime_utc": min(mtimes).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "newest_source_mtime_utc": max(mtimes).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_cache_reuse_audit(root: Path, lineage_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    generate_report = (root / "scripts" / "generate_report.py").read_text(encoding="utf-8")
    build_unified = (root / "scripts" / "build_unified_master.py").read_text(encoding="utf-8")
    run_all = (root / "run_all.py").read_text(encoding="utf-8")

    report_cached_guard = "Report exists" in generate_report and "CACHED" in generate_report
    unified_cached_guard = "already exists" in build_unified and "--force" in build_unified
    skip_download_present = "--skip-download" in run_all
    report_force_forwarded_legacy = "gen_report" in run_all and "force=True" in run_all
    report_force_forwarded_guard = (
        "_call_step(" in run_all
        and "force_recompute=force_recompute_outputs" in run_all
        and "run_report" in run_all
        and "force_recompute_outputs = bool(skip_download)" in run_all
    )
    report_force_forwarded = report_force_forwarded_legacy or report_force_forwarded_guard

    existing_artifacts = [row for row in lineage_rows if row["exists"]]
    cached_like = [
        row
        for row in lineage_rows
        if row["exists"]
        and (
            row["lineage_issue"] in {"summary_present", "embedded_path_points_to_different_workspace"}
            or str(row.get("generated_at", "")).strip() != ""
        )
    ]
    cache_hit_ratio = round(len(cached_like) / max(len(existing_artifacts), 1), 4)

    rows = [
        {
            "stage": "report_generation",
            "cache_guard_detected": report_cached_guard,
            "cache_hit_ratio": cache_hit_ratio,
            "report_regeneration_status": "cached_without_force" if report_cached_guard else "unknown",
            "downstream_recompute_count": 0 if report_cached_guard and not report_force_forwarded else 1,
            "finding": "generate_report.py returns CACHED when report exists unless --force is supplied",
        },
        {
            "stage": "unified_master",
            "cache_guard_detected": unified_cached_guard,
            "cache_hit_ratio": cache_hit_ratio,
            "report_regeneration_status": "not_applicable",
            "downstream_recompute_count": 0 if unified_cached_guard else 1,
            "finding": "build_unified_master.py skips existing pr_all_awards_master.csv unless --force is supplied",
        },
        {
            "stage": "run_all_skip_download",
            "cache_guard_detected": skip_download_present,
            "cache_hit_ratio": cache_hit_ratio,
            "report_regeneration_status": "forced_recompute_enabled" if report_force_forwarded else "suspect_cached_exports",
            "downstream_recompute_count": 1 if report_force_forwarded else 0,
            "finding": (
                "run_all.py --skip-download now forwards force-recompute to report/export layers"
                if report_force_forwarded
                else "run_all.py --skip-download can leave report/export layers cached because downstream force rebuild is not enforced"
            ),
        },
    ]
    return rows


def build_collapse_diagnostics(entity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in entity_rows:
        amount = _safe_float(row.get("total_obligated"))
        missing_parent = not str(row.get("parent_uei") or "").strip()
        missing_uei = not str(row.get("recipient_uei") or "").strip()
        suspect = bool(amount >= 1_000_000 and (missing_parent or missing_uei))
        rows.append(
            {
                "entity_key": row["entity_key"],
                "canonical_name": row["canonical_name"],
                "total_obligated": amount,
                "parent_uei": row.get("parent_uei", ""),
                "recipient_uei": row.get("recipient_uei", ""),
                "parent_uei_missing": missing_parent,
                "recipient_uei_missing": missing_uei,
                "high_value_overcollapse_suspect": suspect,
                "collapse_reason": "high value entity lacks parent UEI/recipient UEI lineage" if suspect else "",
            }
        )
    return rows


def compute_prime_sub_shape(report_text: str, prime_sub_summary: dict[str, Any]) -> dict[str, Any]:
    pairs = _extract_prime_sub_pairs_from_report(report_text)
    if not pairs:
        pairs = [
            {"prime": row.get("prime_recipient", ""), "sub": row.get("sub_recipient", "")}
            for row in prime_sub_summary.get("top_pairs", []) or []
        ]

    normalized_pairs = [(_normalize_name(row.get("prime")), _normalize_name(row.get("sub"))) for row in pairs]
    normalized_pairs = [(p, s) for p, s in normalized_pairs if p and s]
    self_pairs = [(p, s) for p, s in normalized_pairs if p == s]
    pair_set = set(normalized_pairs)
    reciprocal_pairs = [
        (p, s)
        for p, s in pair_set
        if p != s and (s, p) in pair_set
    ]
    prime_count = _safe_int(prime_sub_summary.get("prime_count"))
    sub_count = _safe_int(prime_sub_summary.get("sub_count"))
    pair_count = _safe_int(prime_sub_summary.get("pair_count"))
    dense_denominator = max(prime_count * sub_count, 1)

    return {
        "visible_pair_count": len(normalized_pairs),
        "summary_pair_count": pair_count,
        "unique_primes": prime_count,
        "unique_subs": sub_count,
        "self_pair_count": len(self_pairs),
        "self_pair_ratio": round(len(self_pairs) / max(len(normalized_pairs), 1), 4),
        "reciprocal_pair_count": len(reciprocal_pairs),
        "reciprocal_pair_ratio": round(len(reciprocal_pairs) / max(len(pair_set), 1), 4),
        "dense_matrix_score": round(pair_count / dense_denominator, 4),
        "edge_reuse_ratio": round(pair_count / max(prime_count + sub_count, 1), 4),
    }


def detect_fixture_or_synthetic(
    root: Path,
    report_summary: dict[str, Any],
    prime_sub_summary: dict[str, Any],
    prime_sub_shape: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if _safe_int(report_summary.get("awards", {}).get("unique_entities")) == 18:
        reasons.append("report unique_entities is exactly 18")
    if _safe_int(report_summary.get("power_network", {}).get("total_ranked")) == 18:
        reasons.append("power network total_ranked is exactly 18")
    if _safe_int(prime_sub_summary.get("prime_count")) == 18 and _safe_int(prime_sub_summary.get("sub_count")) == 18:
        reasons.append("prime and sub universes are both exactly 18")
    if prime_sub_shape.get("dense_matrix_score", 0) >= 0.75:
        reasons.append("prime-sub pair matrix is implausibly dense")
    if "PRIME-SUB-" in json.dumps(prime_sub_summary):
        reasons.append("prime_award_ids use generated PRIME-SUB-* pattern")

    code_hits = []
    for script in (root / "scripts").glob("*.py"):
        text = script.read_text(encoding="utf-8", errors="replace").lower()
        if any(token in text for token in ["seed", "fallback", "synthetic", "sample data"]):
            code_hits.append(script.name)
    if code_hits:
        reasons.append(f"fixture/fallback/seed code tokens found in scripts: {', '.join(sorted(code_hits)[:10])}")
    return bool(reasons), reasons


def build_graph_blockers(
    gate: dict[str, Any],
    source_refresh: dict[str, Any],
    prime_sub_shape: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers = []
    checks = {
        "unique_normalized_entity_count": gate["unique_normalized_entity_count"] >= MIN_ENTITY_UNIVERSE_FOR_PRODUCTION,
        "entity_resolution_rate": gate["entity_resolution_rate"] >= 0.95,
        "parent_uei_coverage": gate["parent_uei_coverage"] >= 0.90,
        "graph_node_coverage_pct": gate["graph_node_coverage_pct"] >= 0.90,
        "fixture_or_synthetic_data_detected": gate["fixture_or_synthetic_data_detected"] is False,
        "high_value_overcollapse_suspect_count": gate["high_value_overcollapse_suspect_count"] == 0,
        "report_layers_populated": gate["report_layers_populated"] >= REQUIRED_REPORT_LAYERS_FOR_PRODUCTION,
        "bond_actor_count": gate["bond_actor_count"] > 0,
        "self_pair_ratio": gate["self_pair_ratio"] < 0.05,
    }
    for metric, ok in checks.items():
        if not ok:
            blockers.append(
                {
                    "metric": metric,
                    "observed_value": gate.get(metric),
                    "required_gate": _gate_requirement(metric),
                    "severity": "BLOCKER",
                    "recommended_action": _recommended_action(metric),
                }
            )
    blockers.append(
        {
            "metric": "source_refresh_timestamp_range",
            "observed_value": f"{source_refresh.get('oldest_source_mtime_utc')} to {source_refresh.get('newest_source_mtime_utc')}",
            "required_gate": "source freshness must be traceable to current ingest run",
            "severity": "INFO",
            "recommended_action": "compare source mtimes and manifests against the run timestamp before graph rebuild",
        }
    )
    blockers.append(
        {
            "metric": "dense_matrix_score",
            "observed_value": prime_sub_shape.get("dense_matrix_score"),
            "required_gate": "manual review when prime-sub matrix is implausibly dense",
            "severity": "WARN",
            "recommended_action": "inspect FSRS ingestion and prevent synthetic dense edge expansion",
        }
    )
    return blockers


def _gate_requirement(metric: str) -> str:
    requirements = {
        "unique_normalized_entity_count": ">= 100",
        "entity_resolution_rate": ">= 0.95",
        "parent_uei_coverage": ">= 0.90",
        "graph_node_coverage_pct": ">= 0.90",
        "fixture_or_synthetic_data_detected": "False",
        "high_value_overcollapse_suspect_count": "0",
        "report_layers_populated": ">= 8",
        "bond_actor_count": "> 0",
        "self_pair_ratio": "< 0.05",
    }
    return requirements.get(metric, "")


def _recommended_action(metric: str) -> str:
    actions = {
        "unique_normalized_entity_count": "disable graph/risk outputs and rebuild the entity universe from source records",
        "entity_resolution_rate": "run deterministic entity resolution with review queue before downstream graphing",
        "parent_uei_coverage": "fix SAM/UEI enrichment and parent collapse before graph rebuild",
        "graph_node_coverage_pct": "audit graph inclusion filters and input artifact lineage",
        "fixture_or_synthetic_data_detected": "remove fixture/demo fallback data from production pipeline paths",
        "high_value_overcollapse_suspect_count": "review high-value entities missing UEI lineage",
        "report_layers_populated": "populate at least 8 report layers before production export",
        "bond_actor_count": "ingest and link EMMA/MSRB/COFINA/PROMESA bond actors",
        "self_pair_ratio": "fix prime-sub join logic and block self-pair edges except verified legal self-awards",
    }
    return actions.get(metric, "review metric")


def run_audit(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"
    report_summary = _read_json(root / REPORT_SUMMARY)
    power_summary = _read_json(root / POWER_SUMMARY)
    prime_sub_summary = _read_json(root / PRIME_SUB_SUMMARY)
    graph_summary = _read_json(root / GRAPH_SUMMARY)
    dominance_summary = _read_json(root / DOMINANCE_SUMMARY)
    report_text = (root / REPORT_MARKDOWN).read_text(encoding="utf-8", errors="replace") if (root / REPORT_MARKDOWN).exists() else ""

    lineage_lookup = load_entity_lineage_lookup(root)
    entity_rows = collect_entity_universe(report_summary, power_summary, lineage_lookup=lineage_lookup)
    collapse_rows = build_collapse_diagnostics(entity_rows)
    lineage_rows = build_artifact_lineage(root, report_summary, report_text)
    cache_rows = build_cache_reuse_audit(root, lineage_rows)
    source_refresh = collect_source_refresh_range(root)
    prime_sub_shape = compute_prime_sub_shape(report_text, prime_sub_summary)
    fixture_detected, fixture_reasons = detect_fixture_or_synthetic(root, report_summary, prime_sub_summary, prime_sub_shape)

    report_generated = _parse_generated_at(str(report_summary.get("generated_at") or _extract_generated_at_from_report(report_text)))
    artifact_generation_delta_hours = round((_utc_now() - report_generated).total_seconds() / 3600, 2) if report_generated else None
    cache_hit_ratio = cache_rows[0]["cache_hit_ratio"] if cache_rows else 0.0
    report_layers_populated = _safe_int(report_summary.get("data_layers"))
    unique_entities = len({row["entity_key"] for row in entity_rows})
    parent_uei_coverage = (
        round(
            sum(1 for row in entity_rows if str(row.get("parent_uei") or "").strip() != "")
            / max(unique_entities, 1),
            4,
        )
        if unique_entities
        else 0.0
    )
    entity_resolution_rate = (
        round(
            sum(1 for row in entity_rows if str(row.get("recipient_uei") or "").strip() != "")
            / max(unique_entities, 1),
            4,
        )
        if unique_entities
        else 0.0
    )
    high_value_overcollapse_suspect_count = sum(1 for row in collapse_rows if row["high_value_overcollapse_suspect"])
    graph_vendor_nodes = _safe_int(graph_summary.get("vendor_nodes"))
    graph_node_coverage_pct = round(graph_vendor_nodes / max(unique_entities, 1), 4)
    bond_actor_count = _safe_int(report_summary.get("power_network", {}).get("bond_actors_count"))

    gate = {
        "unique_normalized_entity_count": unique_entities,
        "entity_resolution_rate": entity_resolution_rate,
        "parent_uei_coverage": parent_uei_coverage,
        "graph_node_coverage_pct": graph_node_coverage_pct,
        "fixture_or_synthetic_data_detected": fixture_detected,
        "high_value_overcollapse_suspect_count": high_value_overcollapse_suspect_count,
        "report_layers_populated": report_layers_populated,
        "bond_actor_count": bond_actor_count,
        "self_pair_ratio": prime_sub_shape["self_pair_ratio"],
    }
    graph_build_allowed = (
        gate["unique_normalized_entity_count"] >= 100
        and gate["entity_resolution_rate"] >= 0.95
        and gate["parent_uei_coverage"] >= 0.90
        and gate["graph_node_coverage_pct"] >= 0.90
        and gate["fixture_or_synthetic_data_detected"] is False
        and gate["high_value_overcollapse_suspect_count"] == 0
        and gate["report_layers_populated"] >= 8
        and gate["bond_actor_count"] > 0
        and gate["self_pair_ratio"] < 0.05
    )

    graph_blockers = build_graph_blockers(gate, source_refresh, prime_sub_shape)
    suspect_collapses = [row for row in collapse_rows if row["high_value_overcollapse_suspect"]]
    stage_index = {str(row.get("stage")): row for row in cache_rows}
    report_stage = stage_index.get("report_generation", {})
    run_all_stage = stage_index.get("run_all_skip_download", {})

    summary = {
        "audit_generated_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "PRODUCTION_READY" if graph_build_allowed else "NON_PRODUCTION_DIAGNOSTIC",
        "graph_build_allowed": graph_build_allowed,
        "risk_engine_allowed": graph_build_allowed,
        "required_action": "skip graph rebuild and skip risk engine" if not graph_build_allowed else "graph/risk gate may proceed",
        "artifact_generation_delta_hours": artifact_generation_delta_hours,
        "cache_hit_ratio": cache_hit_ratio,
        "report_regeneration_status": (
            run_all_stage.get("report_regeneration_status")
            or report_stage.get("report_regeneration_status")
            or "unknown"
        ),
        "downstream_recompute_count": int(
            run_all_stage.get("downstream_recompute_count")
            or report_stage.get("downstream_recompute_count")
            or 0
        ),
        "source_refresh_timestamp_range": source_refresh,
        "artifact_lineage_chain": lineage_rows,
        "top_n_truncation_suspected": unique_entities <= 20 and _safe_int(report_summary.get("awards", {}).get("unique_entities")) == unique_entities,
        "fixture_or_synthetic_data_detected": fixture_detected,
        "fixture_or_synthetic_reasons": fixture_reasons,
        "prime_sub_shape": prime_sub_shape,
        "production_gate": gate,
        "production_gate_fields": PRODUCTION_GATE_FIELDS,
        "blocker_count": sum(1 for row in graph_blockers if row["severity"] == "BLOCKER"),
        "blockers": graph_blockers,
        "observed_summaries": {
            "report_generated_at": report_summary.get("generated_at", ""),
            "report_layers_populated": report_layers_populated,
            "dominance_unique_vendors": dominance_summary.get("unique_vendors", ""),
            "power_total_entities": power_summary.get("total_entities", ""),
            "graph_vendor_nodes": graph_summary.get("vendor_nodes", ""),
            "graph_parent_entity_nodes": graph_summary.get("parent_entity_nodes", ""),
            "bond_actor_count": bond_actor_count,
        },
    }

    _write_json(exports_dir / "output_validation_audit.json", summary)
    _write_csv(
        exports_dir / "entity_universe_audit.csv",
        entity_rows,
        [
            "entity_key",
            "canonical_name",
            "seen_in_awards",
            "seen_in_power_network",
            "award_rank",
            "power_rank",
            "total_obligated",
            "influence_score",
            "source_presence",
            "parent_uei",
            "recipient_uei",
            "audit_note",
        ],
    )
    _write_csv(
        exports_dir / "entity_collapse_diagnostics.csv",
        collapse_rows,
        [
            "entity_key",
            "canonical_name",
            "total_obligated",
            "parent_uei",
            "recipient_uei",
            "parent_uei_missing",
            "recipient_uei_missing",
            "high_value_overcollapse_suspect",
            "collapse_reason",
        ],
    )
    _write_csv(
        exports_dir / "artifact_lineage_audit.csv",
        lineage_rows,
        [
            "artifact_path",
            "exists",
            "size_bytes",
            "mtime_utc",
            "sha256",
            "generated_at",
            "row_count",
            "embedded_absolute_paths",
            "lineage_issue",
        ],
    )
    _write_csv(
        exports_dir / "cache_reuse_audit.csv",
        cache_rows,
        [
            "stage",
            "cache_guard_detected",
            "cache_hit_ratio",
            "report_regeneration_status",
            "downstream_recompute_count",
            "finding",
        ],
    )
    _write_csv(
        review_dir / "suspect_entity_collapses.csv",
        suspect_collapses,
        [
            "entity_key",
            "canonical_name",
            "total_obligated",
            "parent_uei",
            "recipient_uei",
            "parent_uei_missing",
            "recipient_uei_missing",
            "high_value_overcollapse_suspect",
            "collapse_reason",
        ],
    )
    _write_csv(
        review_dir / "graph_coverage_blockers.csv",
        graph_blockers,
        ["metric", "observed_value", "required_gate", "severity", "recommended_action"],
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 6.5 artifact and entity-universe audit")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="Project root to audit")
    args = parser.parse_args()
    summary = run_audit(Path(args.root))
    print(f"status: {summary['status']}")
    print(f"graph_build_allowed: {summary['graph_build_allowed']}")
    print(f"risk_engine_allowed: {summary['risk_engine_allowed']}")
    print(f"blocker_count: {summary['blocker_count']}")
    print("outputs: data/exports/output_validation_audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
