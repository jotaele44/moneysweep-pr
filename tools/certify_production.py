from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import logging
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.audit_entity_resolution_certification import (
    build as build_entity_resolution_audit,
)

from tools.certification_truth_guards import (
    derived_execution_blockers,
    digest_json,
    release_boundary,
    strict_json,
)
from tools.operator_corpus_common import load_sources, source_ids_digest
from moneysweep.runtime.source_registry import load_source_registry as load_runtime_source_registry

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "registries" / "production_certification.yaml"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
PASS, FAIL, BLOCKED, OPEN = "PASS", "FAIL", "BLOCKED", "OPEN"
TRUTH_INPUTS = {
    "materialization_readiness",
    "source_registry_status",
    "completeness_matrix",
    "source_freshness",
}


def _json(path: Path) -> dict[str, Any]:
    value = strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def _bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _gate(
    gate_id: str,
    state: str,
    summary: str,
    evidence: dict[str, Any],
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "state": state,
        "summary": summary,
        "evidence": evidence,
        "blockers": blockers or [],
    }


def _preflight(root: Path) -> dict[str, Any]:
    """Load strict preflight from the frozen evidence checkout."""
    path = root / "scripts" / "pipeline_preflight.py"
    spec = importlib.util.spec_from_file_location(
        "cert_scope_pipeline_preflight",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load strict preflight from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger = logging.getLogger("production-certification-preflight")
    logger.addHandler(logging.NullHandler())
    return module.run_pipeline_preflight(
        root,
        logger,
        strict=True,
        write_report=False,
    )


def _entity_blocker_ids(entity_audit: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for item in entity_audit.get("blocking", []):
        value = item.get("review_id") or item.get("reason")
        if value:
            blockers.append(str(value))
    return blockers


def _resolve_input_paths(
    *,
    root: Path,
    config: dict[str, Any],
    truth_root: Path | None,
) -> tuple[dict[str, Path], dict[str, str]]:
    paths: dict[str, Path] = {}
    identities: dict[str, str] = {}
    for name, configured in config["inputs"].items():
        configured_path = Path(configured)
        if truth_root is not None and name in TRUTH_INPUTS:
            path = truth_root / "reports" / configured_path.name
            identity = "DERIVED_CERTIFICATION_SCOPE_TRUTH"
        else:
            path = root / configured_path
            identity = "CERTIFICATION_SCOPE_EVIDENCE"
        paths[name] = path
        identities[name] = identity
    return paths, identities


def _validate_truth_scope(
    *,
    truth_root: Path | None,
    paths: dict[str, Path],
) -> tuple[dict[str, Any] | None, list[str]]:
    if truth_root is None:
        return None, []

    blockers: list[str] = []
    manifest_path = truth_root / "scope_manifest.json"
    if not manifest_path.is_file():
        return None, ["truth_scope_manifest_missing"]
    try:
        manifest = _json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, ["truth_scope_manifest_unreadable"]

    if manifest.get("schema_version") != "moneysweep.certification_scope/v2":
        blockers.append("truth_scope_schema_mismatch")
    scope_id = manifest.get("scope_id")
    if not isinstance(scope_id, str) or not re.fullmatch(r"[0-9a-f]{64}", scope_id):
        blockers.append("truth_scope_id_invalid")

    identity = manifest.get("scope_identity")
    if not isinstance(identity, dict):
        blockers.append("truth_scope_identity_missing")
        identity = {}
    elif digest_json(identity) != scope_id:
        blockers.append("truth_scope_id_mismatch")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        blockers.append("truth_scope_artifact_manifest_missing")

    if identity.get("artifacts_sha256") != digest_json(artifacts):
        blockers.append("truth_scope_artifact_inventory_mismatch")

    for name in sorted(TRUTH_INPUTS):
        path = paths[name]
        rel = f"reports/{path.name}"
        record = artifacts.get(rel)
        if not path.is_file():
            blockers.append(f"truth_input_missing:{name}")
            continue
        if not isinstance(record, dict):
            blockers.append(f"truth_artifact_unbound:{name}")
            continue
        if record.get("sha256") != _sha256(path):
            blockers.append(f"truth_artifact_sha256_mismatch:{name}")
        if record.get("bytes") != path.stat().st_size:
            blockers.append(f"truth_artifact_bytes_mismatch:{name}")

    truth_path = truth_root / "reports" / "certification_truth.json"
    truth_record = artifacts.get("reports/certification_truth.json")
    if not truth_path.is_file():
        blockers.append("certification_truth_missing")
    elif not isinstance(truth_record, dict):
        blockers.append("certification_truth_unbound")
    else:
        if truth_record.get("sha256") != _sha256(truth_path):
            blockers.append("certification_truth_sha256_mismatch")
        if truth_record.get("bytes") != truth_path.stat().st_size:
            blockers.append("certification_truth_bytes_mismatch")

    if isinstance(truth_record, dict) and identity.get("truth_sha256") != truth_record.get("sha256"):
        blockers.append("truth_scope_truth_identity_mismatch")
    return manifest, sorted(set(blockers))


def build_report(
    *,
    root: Path = ROOT,
    config_path: Path = DEFAULT_CONFIG,
    truth_root: Path | None = None,
    scope_sha: str | None = None,
    implementation_sha: str | None = None,
    run_preflight: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    config_path = config_path.resolve()
    truth_root = truth_root.resolve() if truth_root is not None else None
    config = _yaml(config_path)
    actual_scope_head = _head(root)
    scope_sha = scope_sha or actual_scope_head
    implementation_sha = implementation_sha or _head(ROOT)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    paths, path_identities = _resolve_input_paths(
        root=root,
        config=config,
        truth_root=truth_root,
    )
    truth_scope, truth_scope_blockers = _validate_truth_scope(
        truth_root=truth_root,
        paths=paths,
    )

    derived_truth = {}
    if truth_root is not None and not truth_scope_blockers:
        derived_truth = _json(truth_root / "reports/certification_truth.json")
    registry_sources, _ = load_sources(root)
    registry_ids = {source["source_id"] for source in registry_sources}
    registry_digest = source_ids_digest(registry_sources)

    runtime_registry_sources = list(load_runtime_source_registry(root).get("sources", []))
    runtime_registry_ids = [str(source.get("source_id", "")) for source in runtime_registry_sources]
    runtime_registry_id_counts = Counter(runtime_registry_ids)
    runtime_registry_duplicate_ids = sorted(
        source_id for source_id, count in runtime_registry_id_counts.items() if source_id and count > 1
    )
    runtime_registry_missing_ids = sum(not source_id for source_id in runtime_registry_ids)
    runtime_by_id = {
        str(source["source_id"]): source
        for source in runtime_registry_sources
        if isinstance(source.get("source_id"), str) and source["source_id"]
    }
    certification_by_id = {str(source["source_id"]): source for source in registry_sources}
    registry_profile_id_delta = sorted(set(certification_by_id) ^ set(runtime_by_id))
    registry_profile_definition_delta = sorted(
        source_id
        for source_id in set(certification_by_id) & set(runtime_by_id)
        if digest_json(certification_by_id[source_id]) != digest_json(runtime_by_id[source_id])
    )
    registry_profile_blockers: list[str] = []
    if runtime_registry_duplicate_ids:
        registry_profile_blockers.append("runtime_registry_duplicate_ids")
    if runtime_registry_missing_ids:
        registry_profile_blockers.append("runtime_registry_missing_ids")
    if registry_profile_id_delta:
        registry_profile_blockers.append("runtime_certification_source_id_divergence")
    if registry_profile_definition_delta:
        registry_profile_blockers.append("runtime_certification_definition_divergence")

    readiness = _json(paths["materialization_readiness"])
    status_rows = _csv(paths["source_registry_status"])
    recovery_rows = _csv(paths["source_recovery_matrix"])
    completeness = _json(paths["completeness_matrix"])
    freshness_rows = _csv(paths["source_freshness"])
    coverage = _json(paths["materialization_coverage_audit"])
    entity_reviews = _csv(paths["entity_review_queue"])
    historical_status = _json(paths["historical_current_status"])
    federation = _json(paths["federation_manifest"])
    canonical_graph = _json(paths["canonical_graph_summary"])
    entity_audit = build_entity_resolution_audit(root)

    ids = [row["source_id"] for row in status_rows]
    unique_ids = set(ids)
    status_counts = Counter(row["pipeline_status"] for row in status_rows)
    required = [row for row in status_rows if _bool(row["required"])]
    required_counts = Counter(row["pipeline_status"] for row in required)
    required_blockers = [row for row in required if row["pipeline_status"] != "fully_materialized"]

    recovery_ids = [row["source_id"] for row in recovery_rows]
    recovery_id_counts = Counter(recovery_ids)
    recovery_duplicate_ids = sorted(
        source_id for source_id, count in recovery_id_counts.items() if source_id and count > 1
    )
    recovery_by_id = {row["source_id"]: row for row in recovery_rows}
    automatable = {
        row["source_id"] for row in recovery_rows if _bool(row.get("automatable", "false"))
    }
    missing_recovery = sorted(unique_ids - set(recovery_by_id))
    extra_recovery = sorted(set(recovery_by_id) - unique_ids)
    automatable_unmaterialized = sorted(
        row["source_id"]
        for row in status_rows
        if row["source_id"] in automatable and row["pipeline_status"] != "fully_materialized"
    )

    freshness_targets = automatable | {row["source_id"] for row in required}
    freshness_by_id = {row["source_id"]: row for row in freshness_rows}
    freshness_missing = sorted(freshness_targets - set(freshness_by_id))
    freshness_nonfresh = sorted(
        source_id
        for source_id in freshness_targets
        if source_id in freshness_by_id
        and (
            freshness_by_id[source_id].get("receipt_valid", "").lower() != "true"
            or freshness_by_id[source_id].get("freshness_status", "")
            not in {"FRESH", "FRESHNESS_NOT_APPLICABLE"}
        )
    )
    open_reviews = [
        row
        for row in entity_reviews
        if row.get("status", "").lower() not in {"closed", "resolved", "accepted"}
    ]

    total = readiness["total_sources"]
    required_total = len(required)
    digest = readiness["source_count_provenance"]["source_ids_sha256"]
    input_manifest = {
        "certification_config": {
            "path": "registries/production_certification.yaml",
            "sha256": _sha256(config_path),
            "identity": "AUDIT_IMPLEMENTATION",
        },
        **{
            name: {
                "path": str(path),
                "sha256": _sha256(path),
                "identity": path_identities[name],
            }
            for name, path in paths.items()
        },
    }
    if truth_root is not None:
        manifest_path = truth_root / "scope_manifest.json"
        input_manifest["truth_scope_manifest"] = {
            "path": str(manifest_path),
            "sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
            "identity": "DERIVED_CERTIFICATION_SCOPE_MANIFEST",
        }

    gates: list[dict[str, Any]] = []

    truth_scope_id = truth_scope.get("scope_id") if truth_scope else None
    truth_identity = truth_scope.get("scope_identity") if truth_scope else {}
    if not isinstance(truth_identity, dict):
        truth_identity = {}
    truth_digest_match = (
        truth_root is None or truth_identity.get("registry_source_ids_sha256") == digest
    )
    if truth_scope is not None:
        if truth_identity.get("configuration_sha256") != _sha256(config_path):
            truth_scope_blockers.append("truth_scope_configuration_mismatch")
        if truth_identity.get("implementation_sha") != implementation_sha:
            truth_scope_blockers.append("truth_scope_implementation_mismatch")
        if truth_identity.get("scope_repository_sha") != scope_sha:
            truth_scope_blockers.append("truth_scope_repository_mismatch")
        if truth_identity.get("source_definitions_sha256") != digest_json({
            source["source_id"]: digest_json(source) for source in registry_sources
        }):
            truth_scope_blockers.append("truth_scope_source_definitions_mismatch")
    g0 = (
        bool(HEX40.fullmatch(scope_sha))
        and bool(HEX40.fullmatch(implementation_sha))
        and scope_sha == actual_scope_head
        and implementation_sha == _head(ROOT)
        and registry_ids == unique_ids
        and registry_digest == digest
        and required_total == config["requirements"]["required_source_count"]
        and total == len(status_rows)
        and not registry_profile_blockers
        and not truth_scope_blockers
        and truth_digest_match
    )
    g0_blockers: list[str] = []
    if not g0:
        if truth_scope_blockers:
            g0_blockers.extend(truth_scope_blockers)
        if not truth_digest_match:
            g0_blockers.append("truth_scope_registry_digest_mismatch")
        g0_blockers.extend(registry_profile_blockers)
        if not g0_blockers:
            g0_blockers.append("scope_implementation_or_denominator_mismatch")
    gates.append(
        _gate(
            "G0_SCOPE_FREEZE",
            PASS if g0 else FAIL,
            (
                "Exact scope, implementation, denominator, and truth scope are frozen."
                if g0
                else "Scope, truth, or implementation identity is not frozen."
            ),
            {
                "scope_sha": scope_sha,
                "scope_checkout_head_sha": actual_scope_head,
                "implementation_sha": implementation_sha,
                "registry_total": total,
                "status_rows": len(status_rows),
                "digest": digest,
                "truth_scope_enabled": truth_root is not None,
                "truth_scope_id": truth_scope_id,
                "truth_scope_blockers": truth_scope_blockers,
                "truth_scope_registry_digest_match": truth_digest_match,
                "runtime_registry_total": len(runtime_registry_sources),
                "runtime_registry_duplicate_ids": runtime_registry_duplicate_ids,
                "runtime_registry_missing_ids": runtime_registry_missing_ids,
                "runtime_certification_source_id_delta": registry_profile_id_delta,
                "runtime_certification_definition_delta": registry_profile_definition_delta,
                "registry_profile_blockers": registry_profile_blockers,
            },
            g0_blockers,
        )
    )

    historical_registry = historical_status.get("source_registry_current", {})
    g1 = (
        len(status_rows) == total
        and len(unique_ids) == total
        and completeness.get("total_sources") == total
        and federation.get("source_truth", {}).get("total_sources") == total
        and historical_registry.get("total_sources") == total
        and historical_registry.get("source_ids_sha256") == digest
        and readiness.get("automatable_total") == len(automatable)
        and readiness.get("automatable_total") == (
            readiness.get("automatable_ready", 0) + len(readiness.get("automatable_not_ready", []))
        )
        and readiness.get("automatable_total", 0) + readiness.get("queued_excluded_total", 0) == total
        and not recovery_duplicate_ids
        and not missing_recovery
        and not extra_recovery
    )
    gates.append(
        _gate(
            "G1_CONTROL_PLANE_RECONCILIATION",
            PASS if g1 else FAIL,
            (
                "Current source-control surfaces reconcile."
                if g1
                else "Control-plane truth is contradictory."
            ),
            {
                "source_rows": len(status_rows),
                "unique_ids": len(unique_ids),
                "required_sources": required_total,
                "automatable_total": readiness.get("automatable_total"),
                "automatable_ready": readiness.get("automatable_ready"),
                "queued_excluded_total": readiness.get("queued_excluded_total"),
                "missing_recovery_rows": missing_recovery,
                "extra_recovery_rows": extra_recovery,
                "duplicate_recovery_ids": recovery_duplicate_ids,
                "historical_status_main_sha": historical_status.get("main_sha"),
                "historical_status_is_scope_authority": False,
                "truth_scope_id": truth_scope_id,
            },
            [] if g1 else ["control_plane_reconciliation_mismatch"],
        )
    )

    if run_preflight:
        pf = _preflight(root)
        g2 = bool(pf.get("ok")) and not pf.get("structural_errors")
        gates.append(
            _gate(
                "G2_STRICT_PREFLIGHT",
                PASS if g2 else FAIL,
                ("Strict preflight passed." if g2 else "Strict preflight found structural errors."),
                {
                    "mode": "executed",
                    "checked_sources": pf.get("checked_sources"),
                    "total_sources": pf.get("total_sources"),
                    "status_counts": pf.get("status_counts"),
                    "structural_errors": pf.get("structural_errors"),
                    "missing_key_source_ids": [
                        item["source_id"] for item in pf.get("missing_keys", [])
                    ],
                },
                list(pf.get("structural_errors") or []),
            )
        )
    else:
        gates.append(
            _gate(
                "G2_STRICT_PREFLIGHT",
                OPEN,
                "Strict preflight has not been executed for this audit.",
                {"mode": "not_executed"},
                ["strict_preflight_not_executed"],
            )
        )

    g3 = (
        truth_root is not None
        and g0
        and not truth_scope_blockers
        and required_total == config["requirements"]["required_source_count"]
        and required_counts.get("fully_materialized", 0) == required_total
        and not required_blockers
    )
    gates.append(
        _gate(
            "G3_REQUIRED_SOURCE_MATERIALIZATION",
            PASS if g3 else FAIL,
            (
                "All required sources are fully materialized."
                if g3
                else "Required-source residue remains."
            ),
            {
                "required_source_count": required_total,
                "required_status_counts": dict(sorted(required_counts.items())),
                "required_blockers": [
                    {
                        "source_id": row["source_id"],
                        "pipeline_status": row["pipeline_status"],
                        "authentication": row["authentication"],
                        "producer_script": row["producer_script"],
                        "expected_outputs": [
                            item for item in row["expected_outputs"].split(";") if item
                        ],
                        "blocker_notes": row["blocker_notes"],
                    }
                    for row in required_blockers
                ],
                "truth_scope_id": truth_scope_id,
            },
            [row["source_id"] for row in required_blockers],
        )
    )

    allowed = set(config["requirements"]["allowed_pipeline_states"])
    invalid_states = sorted(
        {row["pipeline_status"] for row in status_rows if row["pipeline_status"] not in allowed}
    )
    g4 = len(status_rows) == total and len(unique_ids) == total and not invalid_states
    gates.append(
        _gate(
            "G4_FULL_SOURCE_CLASSIFICATION",
            PASS if g4 else FAIL,
            (
                "Every source has one recognized state."
                if g4
                else "Unknown or duplicate source state exists."
            ),
            {
                "pipeline_status_counts": dict(sorted(status_counts.items())),
                "invalid_states": invalid_states,
            },
            invalid_states,
        )
    )

    execution_blockers = derived_execution_blockers(derived_truth, automatable)
    g5 = (
        not automatable_unmaterialized
        and not execution_blockers
        and not truth_scope_blockers
        and len(automatable) == readiness.get("automatable_total")
    )
    gates.append(
        _gate(
            "G5_AUTOMATABLE_EXECUTION",
            PASS if g5 else FAIL,
            (
                "All automatable sources have bound execution and valid outputs."
                if g5
                else "Automatable execution is incomplete."
            ),
            {
                "automatable_total": len(automatable),
                "execution_blockers": execution_blockers,
                "unmaterialized_count": len(automatable_unmaterialized),
                "unmaterialized": automatable_unmaterialized,
                "freshness_missing": freshness_missing,
                "truth_scope_id": truth_scope_id,
            },
            automatable_unmaterialized + execution_blockers,
        )
    )

    coverage_status = completeness.get("by_coverage_status", {})
    materiality = completeness.get("by_materiality_label", {})
    excluded = readiness.get("queued_excluded_total", 0)
    coverage_by_id = {
        row["source_id"]: row for row in derived_truth.get("sources", [])
        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
    }
    contract_blockers = sorted(
        source_id for source_id in automatable
        if coverage_by_id.get(source_id, {}).get("coverage_status") != "meets_contract"
    )
    g6 = bool(automatable) and not contract_blockers and not execution_blockers and not truth_scope_blockers
    gates.append(
        _gate(
            "G6_SOURCE_VALIDATION_AND_COVERAGE_CONTRACTS",
            PASS if g6 else FAIL,
            (
                "Every in-scope source meets a coverage contract."
                if g6
                else "Coverage validation remains incomplete."
            ),
            {
                "contract_blockers": contract_blockers,
                "contracted_sources": completeness.get("contracted_sources"),
                "coverage_status": coverage_status,
                "materiality": materiality,
                "queued_excluded_total": excluded,
                "truth_scope_id": truth_scope_id,
            },
            [
                key
                for key in ("below_contract", "unverifiable", "uncontracted")
                if coverage_status.get(key, 0)
            ],
        )
    )

    entity_blockers = _entity_blocker_ids(entity_audit)
    g7 = (
        entity_audit.get("g7_candidate_state") == PASS
        and entity_audit.get("blocking_review_items") == 0
    )
    gates.append(
        _gate(
            "G7_ENTITY_RESOLUTION",
            PASS if g7 else FAIL,
            (
                "No blocking identity-resolution residue in promoted relationships."
                if g7
                else "Blocking identity-resolution residue remains."
            ),
            {
                "open_review_count": len(open_reviews),
                "open_review_ids": [row["review_id"] for row in open_reviews],
                "issue_types": dict(
                    sorted(Counter(row["issue_type"] for row in open_reviews).items())
                ),
                "advisory_low_confidence_count": entity_audit.get("advisory_low_confidence_rows"),
                "blocking_review_count": entity_audit.get("blocking_review_items"),
                "canonical_review_queue_open_rows": entity_audit.get(
                    "canonical_review_queue_open_rows"
                ),
                "canonical_graph_review_queue_open": entity_audit.get(
                    "canonical_graph_review_queue_open"
                ),
                "policy": entity_audit.get("policy"),
                "input_manifest": entity_audit.get("input_manifest"),
            },
            entity_blockers,
        )
    )

    coverage_total = coverage.get("local_truth_summary", {}).get("total_sources")
    orphan_rows = coverage.get("processed_file_inventory", {}).get("orphan_rows")
    # A historical audit Boolean is a claim, not an in-process CAS verification.
    operator_authority_claim = coverage.get("audit_scope", {}).get("operator_corpus_authoritative")
    operator_authoritative = False
    lineage_blockers: list[str] = ["scope_bound_corpus_reverification_unimplemented"]
    if coverage_total != total:
        lineage_blockers.append("lineage_denominator_mismatch")
    if not operator_authoritative:
        lineage_blockers.append("authoritative_operator_corpus_not_verified")
    if operator_authoritative and orphan_rows != 0:
        lineage_blockers.append("orphan_rows_present")
    g8 = coverage_total == total and operator_authoritative and orphan_rows == 0
    gates.append(
        _gate(
            "G8_PROVENANCE_AND_LINEAGE",
            PASS if g8 else BLOCKED,
            (
                "Authoritative current-denominator audit proves zero orphan rows."
                if g8
                else "Authoritative operator-corpus lineage proof is incomplete."
            ),
            {
                "coverage_audit_total_sources": coverage_total,
                "current_registry_total_sources": total,
                "coverage_audit_orphan_rows": orphan_rows,
                "operator_corpus_authoritative": operator_authoritative,
                "historical_operator_authority_claim": operator_authority_claim,
                "operator_corpus_id": coverage.get("audit_scope", {}).get("operator_corpus_id"),
                "registry_paths": coverage.get("audit_scope", {}).get("registry_paths"),
                "historical_unresolved_lineage_rows": historical_status.get(
                    "materialization_coverage", {}
                )
                .get("local_operator_snapshot", {})
                .get("unresolved_lineage_rows_within_derived_outputs"),
            },
            lineage_blockers,
        )
    )

    canonical_gate = canonical_graph.get("gate")
    canonical_review = canonical_graph.get("review_queue_open")
    # The historical graph summary is retained, but no replay verifier is bound yet.
    g9 = False
    gates.append(
        _gate(
            "G9_CANONICAL_MASTER_INVARIANTS",
            PASS if g9 else BLOCKED,
            (
                "Canonical master invariant receipt is certified."
                if g9
                else "Canonical master remains diagnostic."
            ),
            {
                "canonical_graph_gate": canonical_gate,
                "review_queue_open": canonical_review,
                "edge_evidence_coverage_pct": canonical_graph.get("edge_evidence_coverage_pct"),
            },
            ["scope_bound_canonical_replay_unimplemented"],
        )
    )

    g10 = bool(automatable) and not freshness_nonfresh and not freshness_missing and not truth_scope_blockers and truth_root is not None
    gates.append(
        _gate(
            "G10_FRESHNESS_AND_UNIVERSE_COMPLETENESS",
            PASS if g10 else FAIL,
            (
                "All automatable sources are explicitly fresh."
                if g10
                else "Freshness/universe evidence is incomplete."
            ),
            {
                "nonfresh_count": len(freshness_nonfresh),
                "nonfresh_automatable": freshness_nonfresh,
                "freshness_missing": freshness_missing,
                "truth_scope_id": truth_scope_id,
            },
            freshness_nonfresh + freshness_missing,
        )
    )

    fg = federation.get("federation_readiness_gate", {})
    # Do not promote production_status/ready_for_hub_live_execution report flags.
    g11 = False
    gates.append(
        _gate(
            "G11_PRODUCTION_EXPORT_AND_FEDERATION",
            PASS if g11 else BLOCKED,
            (
                "Federation production export is certified."
                if g11
                else "Federation manifest blocks production/live execution."
            ),
            {
                "production_status": federation.get("production_status"),
                "ready_for_hub_discovery": fg.get("ready_for_hub_discovery"),
                "ready_for_hub_live_execution": fg.get("ready_for_hub_live_execution"),
                "blocking_conditions": fg.get("blocking_conditions", []),
            },
            list(fg.get("blocking_conditions") or []) + ["scope_bound_federation_replay_unimplemented"],
        )
    )

    upstream_nonpass = [gate["id"] for gate in gates if gate["state"] != PASS]
    release = release_boundary(
        upstream_nonpass,
        historical_status.get("preservation", {}).get("production_activation_authorized"),
    )
    gates.append(
        _gate(
            "G12_RELEASE_CERTIFICATION", release["state"],
            "Release remains blocked pending scope-bound authenticated activation.",
            {key: value for key, value in release.items() if key not in {"state", "blockers"}},
            release["blockers"],
        )
    )

    source_ledger = []
    for row in sorted(status_rows, key=lambda item: item["source_id"]):
        source_id = row["source_id"]
        rec = recovery_by_id.get(source_id, {})
        fresh = freshness_by_id.get(source_id, {})
        source_ledger.append(
            {
                "source_id": source_id,
                "family": row["family"],
                "required": _bool(row["required"]),
                "authentication": row["authentication"],
                "producer_script": row["producer_script"],
                "expected_outputs": [item for item in row["expected_outputs"].split(";") if item],
                "update_cadence": row["update_cadence"],
                "pipeline_status": row["pipeline_status"],
                "blocker_notes": row["blocker_notes"],
                "automatable": _bool(rec.get("automatable", "false")),
                "readiness_ready": _bool(rec.get("ready", "false")),
                "path_type": rec.get("path_type", ""),
                "freshness_status": fresh.get("freshness_status", ""),
                "last_status": fresh.get("last_status", ""),
                "last_success_at": fresh.get("last_success_at", ""),
                "last_materialized_at": fresh.get("last_materialized_at", ""),
            }
        )

    all_pass = all(gate["state"] == PASS for gate in gates)
    return {
        "schema_version": config["schema_version"],
        "generated_at": generated_at,
        "claim": config["claim"],
        "audit_implementation": {
            "commit_sha": implementation_sha,
            "config_sha256": input_manifest["certification_config"]["sha256"],
        },
        "input_manifest": input_manifest,
        "scope": {
            "commit_sha": scope_sha,
            "checkout_head_sha": actual_scope_head,
            "registry_total_sources": total,
            "registry_required_sources": required_total,
            "registry_source_ids_sha256": digest,
            "truth_scope_id": truth_scope_id,
        },
        "source_universe": {
            "pipeline_status_counts": dict(sorted(status_counts.items())),
            "required_pipeline_status_counts": dict(sorted(required_counts.items())),
            "automatable_total": len(automatable),
            "queued_excluded_total": excluded,
            "queued_excluded": readiness.get("queued_excluded"),
            "completeness_matrix": completeness,
            "source_ledger": source_ledger,
        },
        "gates": gates,
        "certification_state": (
            "CERTIFIED" if all_pass else "NON_PRODUCTION_DIAGNOSTIC"
        ),
        "production_eligible": all_pass,
        "nonpass_gate_ids": [gate["id"] for gate in gates if gate["state"] != PASS],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed moneysweep-pr production certification audit."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--truth-root",
        type=Path,
        help=(
            "Use regenerated certification-scope truth for G3/G5/G6/G10; "
            "scope_manifest.json is required and hash-verified."
        ),
    )
    parser.add_argument("--scope-sha")
    parser.add_argument("--implementation-sha")
    parser.add_argument("--run-preflight", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    parser.add_argument("--require-certified", action="store_true")
    args = parser.parse_args()
    report = build_report(
        root=args.root,
        config_path=args.config,
        truth_root=args.truth_root,
        scope_sha=args.scope_sha,
        implementation_sha=args.implementation_sha,
        run_preflight=args.run_preflight,
    )
    payload = json.dumps(report, indent=2) + "\n"
    if args.output is None:
        report_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        args.output = ROOT / "build/certification-diagnostics" / report_id / "production_certificate.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    print(
        json.dumps(
            {
                "certification_state": report["certification_state"],
                "production_eligible": report["production_eligible"],
                "nonpass_gate_ids": report["nonpass_gate_ids"],
                "truth_scope_id": report["scope"].get("truth_scope_id"),
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 2 if args.require_certified and not report["production_eligible"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
