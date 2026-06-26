"""R1 artifact lineage helpers.

Builds machine-readable lineage records that connect report/graph/dominance
artifacts to producer scripts and expected source inputs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_path: str
    artifact_type: str
    producer_script: str
    producer_phase: str
    source_inputs: tuple[str, ...]


ARTIFACT_SPECS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec(
        artifact_path="data/reports/pr_investigative_report.md",
        artifact_type="report_markdown",
        producer_script="scripts/generate_report.py",
        producer_phase="R10_FINAL_REPORT_GENERATOR",
        source_inputs=(
            "data/staging/processed/entity_master.csv",
            "data/staging/processed/pr_power_network.csv",
            "data/staging/processed/pr_prime_sub_relationships.csv",
            "data/staging/processed/pr_delivery_scorecard.csv",
            "data/staging/processed/pr_rfp_lobby_crossref.csv",
            "data/staging/processed/pr_bond_flow.csv",
            "data/staging/processed/pr_ofac_matches.csv",
            "data/staging/processed/pr_sf133_budget_execution.csv",
            "data/staging/processed/pr_act60_decrees.csv",
            "data/staging/processed/pr_lihtc_projects.csv",
            "data/staging/processed/pr_promesa_creditors.csv",
        ),
    ),
    ArtifactSpec(
        artifact_path="data/reports/pr_report_summary.json",
        artifact_type="report_summary",
        producer_script="scripts/generate_report.py",
        producer_phase="R10_FINAL_REPORT_GENERATOR",
        source_inputs=(
            "data/staging/processed/entity_master.csv",
            "data/staging/processed/pr_power_network.csv",
            "data/staging/processed/pr_prime_sub_relationships.csv",
            "data/staging/processed/pr_delivery_scorecard.csv",
            "data/staging/processed/pr_rfp_lobby_crossref.csv",
            "data/staging/processed/pr_bond_flow.csv",
            "data/staging/processed/pr_ofac_matches.csv",
            "data/staging/processed/pr_sf133_budget_execution.csv",
            "data/staging/processed/pr_act60_decrees.csv",
            "data/staging/processed/pr_lihtc_projects.csv",
            "data/staging/processed/pr_promesa_creditors.csv",
        ),
    ),
    ArtifactSpec(
        artifact_path="data/staging/processed/pr_power_network_summary.json",
        artifact_type="power_network_summary",
        producer_script="scripts/analyze_power_network.py",
        producer_phase="R8_GRAPH_REBUILD",
        source_inputs=(
            "data/staging/processed/entity_master.csv",
            "data/staging/processed/pr_fec_crossref.csv",
            "data/staging/processed/pr_lobbying_crossref.csv",
            "data/staging/processed/pr_nonprofits_master.csv",
            "data/staging/processed/pr_cms_master.csv",
            "data/staging/processed/pr_bond_flow.csv",
        ),
    ),
    ArtifactSpec(
        artifact_path="data/staging/processed/dominance_summary.json",
        artifact_type="dominance_summary",
        producer_script="scripts/dominance_analysis.py",
        producer_phase="R8_GRAPH_REBUILD",
        source_inputs=(
            "data/staging/processed/pr_contracts_master.csv",
            "data/staging/processed/pr_all_awards_master.csv",
            "data/staging/processed/enrichment/master_enriched.csv",
            "data/staging/processed/enrichment/entity_hierarchy.csv",
        ),
    ),
    ArtifactSpec(
        artifact_path="data/staging/processed/graph/network_summary.json",
        artifact_type="graph_summary",
        producer_script="scripts/network_graph.py",
        producer_phase="R8_GRAPH_REBUILD",
        source_inputs=(
            "data/staging/processed/pr_contracts_master.csv",
            "data/staging/processed/pr_all_awards_master.csv",
            "data/staging/processed/enrichment/master_enriched.csv",
            "data/staging/processed/enrichment/entity_hierarchy.csv",
        ),
    ),
    ArtifactSpec(
        artifact_path="data/staging/processed/graph/network.graphml",
        artifact_type="graphml_export",
        producer_script="scripts/network_graph.py",
        producer_phase="R8_GRAPH_REBUILD",
        source_inputs=(
            "data/staging/processed/pr_contracts_master.csv",
            "data/staging/processed/pr_all_awards_master.csv",
            "data/staging/processed/enrichment/master_enriched.csv",
            "data/staging/processed/enrichment/entity_hierarchy.csv",
        ),
    ),
    ArtifactSpec(
        artifact_path="data/staging/processed/pr_prime_sub_summary.json",
        artifact_type="prime_sub_summary",
        producer_script="scripts/analyze_prime_sub.py",
        producer_phase="R6_EXECUTION_CHAIN_REBUILD",
        source_inputs=(
            "data/staging/processed/pr_subawards_master.csv",
            "data/staging/processed/pr_subawards_summary.json",
        ),
    ),
)


LINEAGE_FIELDS: tuple[str, ...] = (
    "artifact_path",
    "artifact_type",
    "created_at",
    "modified_at",
    "source_inputs",
    "input_modified_at_min",
    "input_modified_at_max",
    "artifact_hash",
    "prior_artifact_hash",
    "was_recomputed",
    "cache_hit",
    "stale_candidate",
    "producer_script",
    "producer_phase",
    "source_row_count",
    "output_row_count",
)


def _iso_utc(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    suffix = path.suffix.lower()
    try:
        if suffix in {".csv"}:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                return max(sum(1 for _ in handle) - 1, 0)
        if suffix in {".json"}:
            import json

            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, dict):
                return len(payload)
            if isinstance(payload, list):
                return len(payload)
            return 1
        if suffix in {".md", ".txt"}:
            return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        return 0
    return 0


def _load_prior_hashes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    hashes: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                artifact_path = str(row.get("artifact_path", "")).strip()
                artifact_hash = str(row.get("artifact_hash", "")).strip()
                if artifact_path:
                    hashes[artifact_path] = artifact_hash
    except OSError:
        return {}
    return hashes


def _has_cache_guard(script_path: Path) -> bool:
    if not script_path.exists():
        return False
    text = script_path.read_text(encoding="utf-8", errors="replace")
    return (
        ("CACHED" in text)
        or ("already exists" in text and "--force" in text)
        or ("skipping" in text.lower() and "--force" in text)
    )


def build_artifact_lineage_rows(root: Path) -> list[dict[str, Any]]:
    root = Path(root)
    prior_hashes = _load_prior_hashes(root / "data/exports/artifact_lineage_audit.csv")
    rows: list[dict[str, Any]] = []

    for spec in ARTIFACT_SPECS:
        artifact = root / spec.artifact_path
        exists = artifact.exists()
        stat = artifact.stat() if exists else None
        artifact_hash = _sha256(artifact)
        prior_hash = prior_hashes.get(spec.artifact_path, "")

        input_paths = [root / rel for rel in spec.source_inputs]
        input_existing = [p for p in input_paths if p.exists()]
        input_mtimes = [p.stat().st_mtime for p in input_existing]
        input_min = min(input_mtimes) if input_mtimes else None
        input_max = max(input_mtimes) if input_mtimes else None

        source_row_count = sum(_row_count(p) for p in input_existing)
        output_row_count = _row_count(artifact)

        script_path = root / spec.producer_script
        cache_guard = _has_cache_guard(script_path)

        if exists and prior_hash:
            was_recomputed = artifact_hash != prior_hash
        elif exists and input_max is not None:
            was_recomputed = bool(stat and stat.st_mtime >= input_max)
        else:
            was_recomputed = False

        cache_hit = bool(exists and cache_guard and not was_recomputed)
        stale_candidate = bool(
            exists and input_max is not None and stat and stat.st_mtime < input_max
        )

        rows.append(
            {
                "artifact_path": spec.artifact_path,
                "artifact_type": spec.artifact_type,
                "created_at": _iso_utc(stat.st_ctime if stat else None),
                "modified_at": _iso_utc(stat.st_mtime if stat else None),
                "source_inputs": "|".join(spec.source_inputs),
                "input_modified_at_min": _iso_utc(input_min),
                "input_modified_at_max": _iso_utc(input_max),
                "artifact_hash": artifact_hash,
                "prior_artifact_hash": prior_hash,
                "was_recomputed": was_recomputed,
                "cache_hit": cache_hit,
                "stale_candidate": stale_candidate,
                "producer_script": spec.producer_script,
                "producer_phase": spec.producer_phase,
                "source_row_count": source_row_count,
                "output_row_count": output_row_count,
            }
        )

    return rows
