"""R2 entity universe and collapse audit.

Traces available recipient/vendor entities through:
- normalization
- entity_id assignment
- parent UEI enrichment
- graph-node inclusion

Emits collapse diagnostics and review queues to keep downstream phases blocked
until minimum R2 gates pass.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HIGH_VALUE_THRESHOLD = 1_000_000.0


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


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


_STRIP_RE = re.compile(r"[^A-Z0-9 ]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC",
    "LLC",
    "CORP",
    "CORPORATION",
    "CO",
    "LTD",
    "LP",
    "LLP",
    "THE",
    "OF",
    "AND",
}


def normalize_name(name: Any) -> str:
    text = str(name or "").upper()
    text = _STRIP_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    tokens = text.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _load_graph_vendor_norms(root: Path) -> set[str]:
    norms: set[str] = set()
    top_nodes = root / "data/staging/processed/graph/top_nodes.csv"
    if top_nodes.exists():
        with top_nodes.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("node_type", "")).strip().lower() != "vendor":
                    continue
                norm = normalize_name(row.get("node", ""))
                if norm:
                    norms.add(norm)

    edges = root / "data/staging/processed/graph/entity_edges.csv"
    if edges.exists():
        with edges.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                norm = normalize_name(row.get("source_entity", ""))
                if norm:
                    norms.add(norm)
    return norms


def _load_graph_contract_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    edges = root / "data/staging/processed/graph/entity_edges.csv"
    if not edges.exists():
        return counts

    with edges.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            norm = normalize_name(row.get("source_entity", ""))
            if not norm:
                continue
            counts[norm] = counts.get(norm, 0) + _safe_int(row.get("contract_count"))
    return counts


def _load_entity_master_rows(root: Path) -> list[dict[str, Any]]:
    path = root / "data/staging/processed/entity_master.csv"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    return rows


def _build_rows_from_entity_master(
    root: Path, graph_vendor_norms: set[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _load_entity_master_rows(root):
        raw_name = str(row.get("canonical_name") or row.get("entity_key") or "").strip()
        norm = normalize_name(raw_name or row.get("entity_key", ""))
        if not raw_name or not norm:
            continue

        entity_id = str(row.get("resolved_entity_key") or row.get("entity_key") or norm).strip()
        parent_uei = str(row.get("parent_uei") or "").strip()
        parent_name = str(row.get("parent_name") or "").strip()
        award_count = _safe_int(row.get("award_count"))
        obligation = _safe_float(row.get("total_obligated") or row.get("total_obligation"))
        source_system = str(row.get("source_datasets") or "awards_master").strip()

        high_value = obligation >= HIGH_VALUE_THRESHOLD
        graph_present = norm in graph_vendor_norms
        collapse_suspect = bool((high_value and not parent_uei) or (not graph_present))

        rows.append(
            {
                "raw_recipient_name": raw_name,
                "normalized_name": norm,
                "entity_id": entity_id,
                "parent_uei": parent_uei,
                "parent_name": parent_name,
                "resolution_method": "entity_master_parent_lineage"
                if parent_uei
                else "entity_master_unresolved",
                "resolution_confidence": 0.95 if parent_uei else 0.35,
                "source_system": source_system,
                "award_count": award_count,
                "obligation_sum": round(obligation, 2),
                "collapsed_group_size": max(award_count, 1),
                "collapse_suspect": collapse_suspect,
                "high_value_flag": high_value,
                "graph_node_present": graph_present,
            }
        )
    return rows


def _build_rows_from_summaries(root: Path, graph_vendor_norms: set[str]) -> list[dict[str, Any]]:
    report_summary = _read_json(root / "data/reports/pr_report_summary.json")
    power_summary = _read_json(root / "data/staging/processed/pr_power_network_summary.json")
    dominance_summary = _read_json(root / "data/staging/processed/dominance_summary.json")

    entities = (
        power_summary.get("top_entities")
        or report_summary.get("awards", {}).get("top_entities")
        or []
    )
    if not isinstance(entities, list):
        entities = []

    unique_entities = max(len(entities), 1)
    total_rows = _safe_int(
        dominance_summary.get("total_rows")
        or _read_json(root / "data/staging/processed/pr_all_awards_summary.json").get("total_rows")
    )
    avg_group = int(round(total_rows / unique_entities)) if total_rows else 1
    contract_counts = _load_graph_contract_counts(root)

    rows: list[dict[str, Any]] = []
    for ent in entities:
        raw_name = str(ent.get("name") or ent.get("canonical_name") or "").strip()
        norm = normalize_name(raw_name)
        if not raw_name or not norm:
            continue

        obligation = _safe_float(ent.get("awards_total") or ent.get("obligated"))
        award_count = contract_counts.get(norm, avg_group)
        high_value = obligation >= HIGH_VALUE_THRESHOLD
        graph_present = norm in graph_vendor_norms
        collapse_suspect = bool((high_value and True) or (not graph_present))
        source_system = (
            "|".join(ent.get("sources", []))
            if isinstance(ent.get("sources"), list)
            else "summary_only"
        )

        rows.append(
            {
                "raw_recipient_name": raw_name,
                "normalized_name": norm,
                "entity_id": norm,
                "parent_uei": "",
                "parent_name": "",
                "resolution_method": "summary_only_unresolved",
                "resolution_confidence": 0.2,
                "source_system": source_system or "summary_only",
                "award_count": award_count,
                "obligation_sum": round(obligation, 2),
                "collapsed_group_size": max(award_count, avg_group, 1),
                "collapse_suspect": collapse_suspect,
                "high_value_flag": high_value,
                "graph_node_present": graph_present,
            }
        )
    return rows


def _collect_entity_rows(root: Path) -> list[dict[str, Any]]:
    graph_vendor_norms = _load_graph_vendor_norms(root)
    rows = _build_rows_from_entity_master(root, graph_vendor_norms)
    if rows:
        return rows
    return _build_rows_from_summaries(root, graph_vendor_norms)


def _infer_collapse_stage(root: Path, rows: list[dict[str, Any]]) -> str:
    dominance_summary = _read_json(root / "data/staging/processed/dominance_summary.json")
    all_awards_summary = _read_json(root / "data/staging/processed/pr_all_awards_summary.json")
    network_summary = _read_json(root / "data/staging/processed/graph/network_summary.json")

    unique_in_master = _safe_int(
        all_awards_summary.get("unique_recipients") or dominance_summary.get("unique_vendors")
    )
    normalized_count = len(rows)
    parent_coverage = (
        sum(1 for row in rows if str(row.get("parent_uei", "")).strip()) / max(normalized_count, 1)
        if normalized_count
        else 0.0
    )
    graph_vendor_nodes = _safe_int(network_summary.get("vendor_nodes"))

    if unique_in_master <= 18:
        return "collapse_before_or_at_master_table"
    if normalized_count <= 18:
        return "collapse_during_normalization"
    if parent_coverage == 0:
        return "collapse_at_entity_resolution_parent_mapping"
    if graph_vendor_nodes < normalized_count:
        return "collapse_at_graph_inclusion_filter"
    return "collapse_stage_not_detected"


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
    rows = _collect_entity_rows(root)
    exports_dir = root / "data/exports"
    review_dir = root / "data/review_queue"

    unique_count = len({row["normalized_name"] for row in rows})
    parent_count = sum(1 for row in rows if str(row.get("parent_uei", "")).strip())
    parent_coverage = round(parent_count / max(len(rows), 1), 4) if rows else 0.0
    graph_exclusion_count = sum(1 for row in rows if not bool(row.get("graph_node_present")))
    high_value_unresolved = [
        row
        for row in rows
        if bool(row.get("high_value_flag")) and not str(row.get("parent_uei", "")).strip()
    ]
    collapse_suspects = [row for row in rows if bool(row.get("collapse_suspect"))]
    overcollapse_count = len(collapse_suspects)
    high_value_unresolved_count = len(high_value_unresolved)

    collapse_stage = _infer_collapse_stage(root, rows)

    # Required minimum gate from R2 ticket.
    r2_gate_passed = bool(
        unique_count >= 100
        and parent_coverage > 0.0
        and overcollapse_count == 0
        and high_value_unresolved_count == 0
    )

    prior_rebuild = _read_json(root / "data/exports/rebuild_status.json")
    prior_phase_block = bool(prior_rebuild.get("phase_7_8_blocked"))
    phase_7_8_blocked = bool(prior_phase_block or (not r2_gate_passed))

    # Required machine outputs.
    _write_csv(
        exports_dir / "entity_universe_audit.csv",
        rows,
        [
            "raw_recipient_name",
            "normalized_name",
            "entity_id",
            "parent_uei",
            "parent_name",
            "resolution_method",
            "resolution_confidence",
            "source_system",
            "award_count",
            "obligation_sum",
            "collapsed_group_size",
            "collapse_suspect",
            "high_value_flag",
            "graph_node_present",
        ],
    )

    diagnostics = [
        {
            "diagnostic": "raw_award_rows",
            "observed_value": _safe_int(
                _read_json(root / "data/staging/processed/pr_all_awards_summary.json").get(
                    "total_rows"
                )
                or _read_json(root / "data/staging/processed/dominance_summary.json").get(
                    "total_rows"
                )
            ),
            "required_value": ">= 1",
            "severity": "INFO",
            "notes": "rows entering the aggregated award universe",
        },
        {
            "diagnostic": "unique_normalized_entity_count",
            "observed_value": unique_count,
            "required_value": ">= 100",
            "severity": "BLOCKER" if unique_count < 100 else "PASS",
            "notes": "R2 minimum gate for entity universe size",
        },
        {
            "diagnostic": "parent_uei_coverage",
            "observed_value": parent_coverage,
            "required_value": "> 0",
            "severity": "BLOCKER" if parent_coverage <= 0 else "PASS",
            "notes": "R2 minimum gate for parent lineage presence",
        },
        {
            "diagnostic": "high_value_overcollapse_suspect_count",
            "observed_value": overcollapse_count,
            "required_value": "== 0",
            "severity": "BLOCKER" if overcollapse_count > 0 else "PASS",
            "notes": "entities likely collapsed too aggressively",
        },
        {
            "diagnostic": "high_value_unresolved_count",
            "observed_value": high_value_unresolved_count,
            "required_value": "== 0",
            "severity": "BLOCKER" if high_value_unresolved_count > 0 else "PASS",
            "notes": "high-value entities missing parent UEI resolution",
        },
        {
            "diagnostic": "graph_exclusion_count",
            "observed_value": graph_exclusion_count,
            "required_value": "== 0 preferred",
            "severity": "WARN" if graph_exclusion_count > 0 else "PASS",
            "notes": "normalized entities not represented as graph vendors",
        },
        {
            "diagnostic": "inferred_18_entity_collapse_stage",
            "observed_value": collapse_stage,
            "required_value": "not collapse_before_or_at_master_table",
            "severity": "BLOCKER"
            if collapse_stage == "collapse_before_or_at_master_table"
            else "INFO",
            "notes": "where the constrained universe is first observable",
        },
        {
            "diagnostic": "phase_7_8_blocked",
            "observed_value": phase_7_8_blocked,
            "required_value": "True until R2 gate passes",
            "severity": "INFO",
            "notes": "enforcement guard for downstream risk/graph phases",
        },
    ]
    _write_csv(
        exports_dir / "entity_collapse_diagnostics.csv",
        diagnostics,
        ["diagnostic", "observed_value", "required_value", "severity", "notes"],
    )

    _write_csv(
        review_dir / "suspect_entity_collapses.csv",
        collapse_suspects,
        [
            "raw_recipient_name",
            "normalized_name",
            "entity_id",
            "parent_uei",
            "parent_name",
            "resolution_method",
            "resolution_confidence",
            "source_system",
            "award_count",
            "obligation_sum",
            "collapsed_group_size",
            "collapse_suspect",
            "high_value_flag",
            "graph_node_present",
        ],
    )

    _write_csv(
        review_dir / "high_value_unresolved_entities.csv",
        high_value_unresolved,
        [
            "raw_recipient_name",
            "normalized_name",
            "entity_id",
            "parent_uei",
            "parent_name",
            "resolution_method",
            "resolution_confidence",
            "source_system",
            "award_count",
            "obligation_sum",
            "collapsed_group_size",
            "collapse_suspect",
            "high_value_flag",
            "graph_node_present",
        ],
    )

    # Persist gate status while preserving prior fields.
    rebuild_status = dict(prior_rebuild)
    rebuild_status.update(
        {
            "r2_generated_at": _utc_now(),
            "unique_normalized_entity_count": unique_count,
            "parent_uei_coverage": parent_coverage,
            "graph_exclusion_count": graph_exclusion_count,
            "high_value_overcollapse_suspect_count": overcollapse_count,
            "high_value_unresolved_count": high_value_unresolved_count,
            "inferred_18_entity_collapse_stage": collapse_stage,
            "r2_gate_passed": r2_gate_passed,
            "phase_7_8_blocked": phase_7_8_blocked,
            "phase_7_8_block_reason": (
                "R2 gate failed and/or prior phase gate still blocked"
                if phase_7_8_blocked
                else "R2 gate passed and no prior phase gate block remains"
            ),
            "r2_outputs": {
                "entity_universe_audit": "data/exports/entity_universe_audit.csv",
                "entity_collapse_diagnostics": "data/exports/entity_collapse_diagnostics.csv",
                "suspect_entity_collapses": "data/review_queue/suspect_entity_collapses.csv",
                "high_value_unresolved_entities": "data/review_queue/high_value_unresolved_entities.csv",
            },
        }
    )
    _write_json(root / "data/exports/rebuild_status.json", rebuild_status)

    return rebuild_status
