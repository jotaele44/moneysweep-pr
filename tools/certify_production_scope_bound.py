from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.certification_operator_lineage import verify_scope_bound_operator_corpus
from tools.certification_truth_guards import release_boundary, strict_json
from tools.certify_production import (
    DEFAULT_CONFIG,
    ROOT,
    build_report as build_base_report,
)

PASS = "PASS"
BLOCKED = "BLOCKED"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_truth_scope(truth_root: Path | None) -> dict[str, Any] | None:
    if truth_root is None:
        return None
    path = truth_root / "scope_manifest.json"
    if not path.is_file():
        return None
    try:
        payload = strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _gate_by_id(report: dict[str, Any], gate_id: str) -> dict[str, Any]:
    for gate in report.get("gates", []):
        if isinstance(gate, dict) and gate.get("id") == gate_id:
            return gate
    raise RuntimeError(f"certification gate missing: {gate_id}")


def build_report(
    *,
    root: Path = ROOT,
    config_path: Path = DEFAULT_CONFIG,
    truth_root: Path | None = None,
    operator_corpus_root: Path | None = None,
    scope_sha: str | None = None,
    implementation_sha: str | None = None,
    run_preflight: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run the base certifier, replacing only G8 with live scope-bound replay.

    This is a migration bridge. G9, G11 and G12 remain the base fail-closed
    interlocks until their own scope-bound verifiers are implemented.
    """

    root = root.resolve()
    truth_root = truth_root.resolve() if truth_root is not None else None
    operator_corpus_root = (
        operator_corpus_root.resolve() if operator_corpus_root is not None else None
    )

    report = build_base_report(
        root=root,
        config_path=config_path,
        truth_root=truth_root,
        scope_sha=scope_sha,
        implementation_sha=implementation_sha,
        run_preflight=run_preflight,
        generated_at=generated_at,
    )
    truth_scope = _load_truth_scope(truth_root)
    scope = report.get("scope", {})
    lineage = verify_scope_bound_operator_corpus(
        root=root,
        corpus_root=operator_corpus_root,
        truth_scope=truth_scope,
        current_registry_total=int(scope.get("registry_total_sources", 0)),
        current_registry_digest=str(scope.get("registry_source_ids_sha256", "")),
    )

    g0 = _gate_by_id(report, "G0_SCOPE_FREEZE")
    lineage_blockers = list(lineage.get("blockers", []))
    if g0.get("state") != PASS:
        lineage_blockers.append("scope_freeze_not_pass")
    lineage_blockers = sorted(set(lineage_blockers))
    authoritative = bool(lineage.get("authoritative")) and not lineage_blockers

    historical_g8 = _gate_by_id(report, "G8_PROVENANCE_AND_LINEAGE")
    historical_evidence = historical_g8.get("evidence", {})
    if not isinstance(historical_evidence, dict):
        historical_evidence = {}
    g8 = {
        "id": "G8_PROVENANCE_AND_LINEAGE",
        "state": PASS if authoritative else BLOCKED,
        "summary": (
            "Fresh full-snapshot corpus replay is scope-bound to current registry truth."
            if authoritative
            else "Authoritative scope-bound operator-corpus lineage proof is incomplete."
        ),
        "evidence": {
            "verification_mode": lineage.get("verification_scope", {}).get("mode")
            if isinstance(lineage.get("verification_scope"), dict)
            else None,
            "operator_snapshot_required": lineage.get("verification_scope", {}).get(
                "operator_snapshot_required"
            )
            if isinstance(lineage.get("verification_scope"), dict)
            else None,
            "operator_corpus_authoritative": authoritative,
            "operator_corpus_root": lineage.get("corpus_root"),
            "operator_corpus_id": lineage.get("corpus_id"),
            "computed_corpus_id": lineage.get("computed_corpus_id"),
            "truth_scope_id": scope.get("truth_scope_id"),
            "truth_scope_operator_corpus_id": lineage.get("scope_operator_corpus_id"),
            "current_registry_total_sources": scope.get("registry_total_sources"),
            "current_registry_source_ids_sha256": scope.get("registry_source_ids_sha256"),
            "verified_registry": lineage.get("registry"),
            "manifest_source_count": lineage.get("manifest_source_count"),
            "manifest_product_count": lineage.get("manifest_product_count"),
            "processed_file_inventory": lineage.get("processed_file_inventory"),
            "verification_errors": lineage.get("verification_errors"),
            "historical_operator_authority_claim": historical_evidence.get(
                "historical_operator_authority_claim"
            ),
            "historical_coverage_audit_total_sources": historical_evidence.get(
                "coverage_audit_total_sources"
            ),
            "historical_coverage_audit_orphan_rows": historical_evidence.get(
                "coverage_audit_orphan_rows"
            ),
        },
        "blockers": lineage_blockers,
    }
    gates = report.get("gates", [])
    report["gates"] = [g8 if gate.get("id") == "G8_PROVENANCE_AND_LINEAGE" else gate for gate in gates]

    if operator_corpus_root is not None:
        manifest_path = operator_corpus_root / "manifest.json"
        report.setdefault("input_manifest", {})["operator_corpus_manifest"] = {
            "path": str(manifest_path),
            "sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
            "identity": "LIVE_SCOPE_BOUND_CORPUS_REVERIFICATION",
        }

    g12_old = _gate_by_id(report, "G12_RELEASE_CERTIFICATION")
    g12_evidence = g12_old.get("evidence", {})
    if not isinstance(g12_evidence, dict):
        g12_evidence = {}
    upstream_nonpass = [
        gate["id"]
        for gate in report["gates"]
        if gate.get("id") != "G12_RELEASE_CERTIFICATION" and gate.get("state") != PASS
    ]
    release = release_boundary(
        upstream_nonpass,
        g12_evidence.get("historical_activation_claim"),
    )
    g12 = {
        "id": "G12_RELEASE_CERTIFICATION",
        "state": release["state"],
        "summary": "Release remains blocked pending scope-bound authenticated activation.",
        "evidence": {
            key: value for key, value in release.items() if key not in {"state", "blockers"}
        },
        "blockers": release["blockers"],
    }
    report["gates"] = [g12 if gate.get("id") == "G12_RELEASE_CERTIFICATION" else gate for gate in report["gates"]]

    all_pass = all(gate.get("state") == PASS for gate in report["gates"])
    report["certification_state"] = "CERTIFIED" if all_pass else "NON_PRODUCTION_DIAGNOSTIC"
    report["production_eligible"] = all_pass
    report["nonpass_gate_ids"] = [
        gate["id"] for gate in report["gates"] if gate.get("state") != PASS
    ]
    report["certification_bridge"] = {
        "schema_version": "moneysweep.scope_bound_certification_bridge/v1",
        "g8_live_reverification": True,
        "g9_scope_bound_replay": False,
        "g11_scope_bound_replay": False,
        "g12_scope_bound_activation": False,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scope-bound fail-closed MoneySweep production certification audit."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--truth-root", type=Path)
    parser.add_argument("--operator-corpus-root", type=Path)
    parser.add_argument("--scope-sha")
    parser.add_argument("--implementation-sha")
    parser.add_argument("--run-preflight", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--require-certified", action="store_true")
    args = parser.parse_args()

    report = build_report(
        root=args.root,
        config_path=args.config,
        truth_root=args.truth_root,
        operator_corpus_root=args.operator_corpus_root,
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
                "operator_corpus_id": _gate_by_id(
                    report, "G8_PROVENANCE_AND_LINEAGE"
                )["evidence"].get("operator_corpus_id"),
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 2 if args.require_certified and not report["production_eligible"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
